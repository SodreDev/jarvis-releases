"""O host nativo de ponta a ponta, sem navegador: pipes no lugar do `stdio` do navegador, uma
"extensão" falsa numa thread, e o socket Unix numa pasta temporária do teste."""

from __future__ import annotations

import io
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

import pytest

from jarvis.navegador import host
from jarvis.navegador.cliente import (
    ClienteDoNavegador,
    NavegadorFalhou,
    NavegadorIndisponivel,
    TransporteUnix,
)
from jarvis.navegador.protocolo import ORIGEM_CHROMIUM, PedidoDaPonte
from jarvis.navegador.quadro import codificar, escrever_quadro, ler_quadro

Extensao = Callable[[dict[str, Any]], dict[str, Any] | None]

PRAZO_DO_TESTE_S: Final = 30.0
"""Teto das esperas por condição. Generoso de propósito: com o `verificar.py` em `nice -n 19` e a
máquina ocupada, o host e a "extensão" podem levar segundos para rodar — e uma espera por
condição sai assim que ela vale, então o teto não atrasa o teste que passa."""


class Navegador:
    """O outro lado do `stdio`: a "extensão" lê pedidos do host e responde como o roteiro manda."""

    def __init__(self, tmp: Path, roteiro: Extensao, prazo_s: float = 5.0) -> None:
        pedidos_r, pedidos_w = os.pipe()  # host → extensão
        respostas_r, respostas_w = os.pipe()  # extensão → host
        self._do_host = os.fdopen(pedidos_r, "rb")
        self._para_o_host = os.fdopen(respostas_w, "wb")
        self.recebidos: list[dict[str, Any]] = []
        self.chegou = threading.Event()
        """Um pedido chegou à extensão — e, portanto, já está em voo no host."""
        self._roteiro = roteiro
        ambiente = {"XDG_RUNTIME_DIR": str(tmp)}
        self.codigo: list[int] = []
        saida = os.fdopen(pedidos_w, "wb")
        entrada = os.fdopen(respostas_r, "rb")

        def rodar() -> None:
            self.codigo.append(
                host.principal([ORIGEM_CHROMIUM], entrada, saida, ambiente, prazo_s=prazo_s)
            )
            saida.close()
            entrada.close()

        self._host = threading.Thread(target=rodar, daemon=True)
        self._extensao = threading.Thread(target=self._servir, daemon=True)
        self.pasta = host.pasta_dos_sockets(ambiente, os.getuid())

    def abrir(self) -> None:
        self._host.start()
        self._extensao.start()
        fim = time.monotonic() + PRAZO_DO_TESTE_S
        while time.monotonic() < fim:  # espera o socket nascer
            if list(self.pasta.glob("*.sock")):
                return
            threading.Event().wait(0.01)
        raise AssertionError(f"o host não abriu o socket em {PRAZO_DO_TESTE_S:.0f} s")

    def fechar(self) -> None:
        if self._para_o_host.closed:
            return
        self._para_o_host.close()  # o navegador fechou o stdin do host
        self._host.join(PRAZO_DO_TESTE_S)
        self._extensao.join(PRAZO_DO_TESTE_S)
        assert not self._host.is_alive(), "o host não saiu depois de o navegador fechar o stdin"

    def evento(self, dados: dict[str, Any]) -> None:
        """A extensão falando por conta própria (o PARAR do dono), sem pedido nenhum."""
        escrever_quadro(self._para_o_host, dados, 1_000_000)

    def _servir(self) -> None:
        while True:
            try:
                pedido = ler_quadro(self._do_host, 1_000_000)
            except Exception:
                return
            if pedido is None:
                return
            self.recebidos.append(pedido)
            self.chegou.set()
            resposta = self._roteiro(pedido)
            if resposta is not None:
                escrever_quadro(self._para_o_host, resposta, 1_000_000)


@pytest.fixture
def curto(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("n")  # caminho de socket Unix tem teto de ~100 caracteres


@pytest.fixture
def navegador(curto: Path) -> Iterator[Callable[[Extensao, float], Navegador]]:
    abertos: list[Navegador] = []

    def abrir(roteiro: Extensao, prazo_s: float = 5.0) -> Navegador:
        nav = Navegador(curto, roteiro, prazo_s)
        nav.abrir()
        abertos.append(nav)
        return nav

    yield abrir
    for nav in abertos:
        nav.fechar()


def _ecoa(pedido: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pedido["id"],
        "ok": True,
        "result": {"metodo": pedido["method"], "p": pedido["params"]},
    }


def test_o_pedido_do_jarvis_chega_na_extensao_e_a_resposta_volta(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    cliente = ClienteDoNavegador(TransporteUnix(nav.pasta))

    assert cliente.chamar("page.click", tabId=3, alvo="Próxima") == {
        "metodo": "page.click",
        "p": {"tabId": 3, "alvo": "Próxima"},
    }
    assert nav.recebidos[0]["method"] == "page.click"
    modo_pasta = nav.pasta.stat().st_mode & 0o777
    modo_socket = next(nav.pasta.glob("*.sock")).stat().st_mode & 0o777
    assert (modo_pasta, modo_socket) == (0o700, 0o600)


def test_erro_da_extensao_vira_navegador_falhou_com_o_codigo_dela(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    def roteiro(pedido: dict[str, Any]) -> dict[str, Any]:
        erro = {"codigo": "alvo_ausente", "mensagem": "não achei"}
        return {"id": pedido["id"], "ok": False, "error": erro}

    cliente = ClienteDoNavegador(TransporteUnix(navegador(roteiro, 5.0).pasta))
    with pytest.raises(NavegadorFalhou) as erro:
        cliente.clicar(1, "Nada")
    assert erro.value.codigo == "alvo_ausente"


def test_resposta_com_id_trocado_e_descartada_e_o_pedido_estoura_o_prazo(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    def roteiro(_pedido: dict[str, Any]) -> dict[str, Any]:
        return {"id": "outro", "ok": True, "result": {}}

    cliente = ClienteDoNavegador(TransporteUnix(navegador(roteiro, 0.3).pasta))
    with pytest.raises(NavegadorFalhou) as erro:
        cliente.abas()
    assert erro.value.codigo == "tempo_esgotado"


def test_navegador_que_fecha_no_meio_avisa_quem_espera(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(lambda _p: None, 20.0)  # nunca responde
    cliente = ClienteDoNavegador(TransporteUnix(nav.pasta))
    resultado: list[BaseException] = []

    def chamar() -> None:
        try:
            cliente.abas()
        except BaseException as erro:
            resultado.append(erro)

    fio = threading.Thread(target=chamar)
    fio.start()
    # O pedido tem de estar em voo antes de o navegador fechar: é isso que o teste exercita. Antes
    # a espera era de 3 s contados em voltas, e sob carga o navegador fechava antes de o pedido
    # chegar.
    assert nav.chegou.wait(PRAZO_DO_TESTE_S), (
        f"o pedido do cliente não chegou à extensão em {PRAZO_DO_TESTE_S:.0f} s"
    )
    nav.fechar()
    fio.join(PRAZO_DO_TESTE_S)
    assert not fio.is_alive(), "o cliente ficou esperando depois de o navegador fechar"
    assert isinstance(resultado[0], NavegadorFalhou)
    assert resultado[0].codigo == "navegador_fechado"
    assert nav.codigo == [0]
    assert not list(nav.pasta.glob("*.sock"))  # o host apaga o socket ao sair


def test_quem_espera_resposta_recebe_o_motivo_mesmo_com_o_fio_atrasado(
    navegador: Callable[[Extensao, float], Navegador], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrida por trás da intermitência: o fio que atende é acordado pelo `encerrar` da ponte,
    mas o host fechava as conexões antes de ele escrever o "navegador_fechado" — e o Jarvis lia
    "o host fechou sem responder". Aqui o atraso do escalonador é forçado (200 ms)."""
    original = host.Ponte.pedir

    def pedir_atrasado(ponte: host.Ponte, pedido: PedidoDaPonte) -> dict[str, Any]:
        resposta = original(ponte, pedido)
        time.sleep(0.2)
        return resposta

    monkeypatch.setattr(host.Ponte, "pedir", pedir_atrasado)
    nav = navegador(lambda _p: None, 20.0)
    resultado: list[BaseException] = []

    def chamar() -> None:
        try:
            ClienteDoNavegador(TransporteUnix(nav.pasta)).abas()
        except BaseException as erro:
            resultado.append(erro)

    fio = threading.Thread(target=chamar)
    fio.start()
    assert nav.chegou.wait(PRAZO_DO_TESTE_S), "o pedido do cliente não chegou à extensão"
    nav.fechar()
    fio.join(PRAZO_DO_TESTE_S)
    assert not fio.is_alive(), "o cliente ficou esperando depois de o navegador fechar"
    assert isinstance(resultado[0], NavegadorFalhou), resultado
    assert resultado[0].codigo == "navegador_fechado"


def test_o_host_revalida_o_vocabulario_mesmo_que_o_cliente_tenha_sido_burlado(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    transporte = TransporteUnix(nav.pasta)
    torto = PedidoDaPonte("x1", "page.exec", {"codigo": "1"})  # método fora do vocabulário
    resposta = transporte.chamar(torto)
    assert resposta["ok"] is False
    assert resposta["error"]["codigo"] == "pedido_invalido"
    assert nav.recebidos == []  # nada chegou à extensão


def test_sem_host_o_cliente_diz_que_nao_ha_navegador(tmp_path: Path) -> None:
    cliente = ClienteDoNavegador(TransporteUnix(tmp_path / "nao-existe"))
    with pytest.raises(NavegadorIndisponivel, match="nenhum navegador"):
        cliente.abas()


def test_pasta_dos_sockets_que_nao_e_so_do_dono_nao_e_usada(tmp_path: Path) -> None:
    pasta = tmp_path / "aberta"
    pasta.mkdir(mode=0o777)
    pasta.chmod(0o777)
    with pytest.raises(NavegadorIndisponivel):
        ClienteDoNavegador(TransporteUnix(pasta)).abas()


def test_origem_que_nao_e_a_extensao_do_jarvis_nao_abre_socket(curto: Path) -> None:
    saida = io.BytesIO()
    codigo = host.principal(
        ["chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/"],
        io.BytesIO(),
        saida,
        {"XDG_RUNTIME_DIR": str(curto)},
    )
    assert codigo == 2
    assert saida.getvalue() == b""  # nada no stdout: ele é só dos quadros
    assert not (curto / "jarvis").exists()


def test_host_responde_so_a_pedidos_e_o_stdout_so_leva_quadros(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    ClienteDoNavegador(TransporteUnix(nav.pasta)).abas()
    assert nav.recebidos[0].keys() == {"id", "method", "params"}
    assert codificar(nav.recebidos[0], 1_000_000)  # voltou como quadro válido, não como texto solto


def test_host_nao_tem_porta_de_rede() -> None:
    """O código do host e do cliente não cria soquete de rede nem fala HTTP."""
    raiz = Path(host.__file__).parent
    proibidos = (
        "AF_INET",
        "AF_INET6",
        "http.server",
        "http.client",
        "urllib.request",
        "socketserver",
        "requests",
        "websocket",
        "httpx",
    )
    for arquivo in raiz.glob("*.py"):
        texto = arquivo.read_text(encoding="utf-8")
        for palavra in proibidos:
            assert palavra not in texto, f"{arquivo.name} usa {palavra}"


# --- o PARAR do dono: evento da extensão para quem assinou (ADR-0027 regra 4) ---------------------
PARAR = {"evento": "parar", "concessoes": ["a1b2c3d4e5f60708"], "origem": "faixa"}


def test_o_parar_da_extensao_chega_a_quem_assinou(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    assinatura = TransporteUnix(nav.pasta).assinar()
    try:
        nav.evento(PARAR)
        recebidos = assinatura.esperar(3.0)
    finally:
        assinatura.fechar()

    assert recebidos == [PARAR]
    assert all(p["method"] != "eventos.assinar" for p in nav.recebidos), "o host atende sozinho"


def test_evento_fora_do_vocabulario_nao_chega_a_ninguem(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    assinatura = TransporteUnix(nav.pasta).assinar()
    try:
        nav.evento({"evento": "abrir", "concessoes": [], "origem": "faixa"})
        nav.evento({"evento": "parar", "concessoes": ["NÃO É"], "origem": "faixa"})
        nav.evento({"evento": "parar", "concessoes": [], "origem": "página"})
        nav.evento(PARAR)  # o único válido
        recebidos = assinatura.esperar(3.0)
    finally:
        assinatura.fechar()

    assert recebidos == [PARAR]


def test_os_pedidos_continuam_com_alguem_assinado(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    transporte = TransporteUnix(nav.pasta)
    assinatura = transporte.assinar()
    try:
        resposta = ClienteDoNavegador(transporte).chamar("page.read", tabId=3)
    finally:
        assinatura.fechar()

    assert resposta == {"metodo": "page.read", "p": {"tabId": 3}}


def test_assinantes_demais_sao_recusados(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    transporte = TransporteUnix(nav.pasta)
    abertas = [transporte.assinar() for _ in range(host.MAXIMO_DE_ASSINANTES)]
    try:
        with pytest.raises(NavegadorIndisponivel, match="recusou"):
            transporte.assinar()
    finally:
        for assinatura in abertas:
            assinatura.fechar()


def test_o_navegador_que_fecha_acorda_quem_espera_eventos(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_ecoa, 5.0)
    assinatura = TransporteUnix(nav.pasta).assinar()
    try:
        nav.fechar()
        with pytest.raises(NavegadorIndisponivel):
            for _ in range(20):
                assinatura.esperar(0.5)
    finally:
        assinatura.fechar()
