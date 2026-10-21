"""O controle das abas e o PARAR (ADR-0027 regra 4), sem navegador: transporte e eventos falsos."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest

from jarvis.navegador.cliente import ClienteDoNavegador, NavegadorIndisponivel
from jarvis.navegador.controle import ControleDoNavegador
from jarvis.navegador.protocolo import PedidoDaPonte
from jarvis.politica.objetivo import EstadoDoObjetivo, Objetivo


class ExtensaoFalsa:
    def __init__(self) -> None:
        self.pedidos: list[tuple[str, dict[str, Any]]] = []
        self.paradas: set[str] = set()
        self.trava = threading.Lock()

    def chamar(self, pedido: PedidoDaPonte, navegador: str = "") -> dict[str, Any]:
        with self.trava:
            self.pedidos.append((pedido.method, dict(pedido.params)))
        if pedido.params.get("controle") in self.paradas:
            erro = {"codigo": "parado_pelo_dono", "mensagem": "o dono apertou parar"}
            return {"id": pedido.id, "ok": False, "error": erro}
        return {"id": pedido.id, "ok": True, "result": {}}

    def metodo(self, nome: str) -> list[dict[str, Any]]:
        with self.trava:
            return [p for m, p in self.pedidos if m == nome]


class AssinaturaFalsa:
    def __init__(self) -> None:
        self.fila: queue.Queue[dict[str, Any]] = queue.Queue()
        self.fechada = False

    def esperar(self, segundos: float) -> list[dict[str, Any]]:
        try:
            return [self.fila.get(timeout=segundos)]
        except queue.Empty:
            return []

    def fechar(self) -> None:
        self.fechada = True


def _no_controle(controle: ControleDoNavegador) -> bool:
    """Lido por função: o mypy não estreita o valor entre um passo e outro do teste."""
    return controle.no_controle


def _esperar(condicao: Callable[[], object], prazo_s: float = 3.0) -> bool:
    fim = time.monotonic() + prazo_s
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return bool(condicao())


@pytest.fixture
def extensao() -> ExtensaoFalsa:
    return ExtensaoFalsa()


@pytest.fixture
def assinatura() -> AssinaturaFalsa:
    return AssinaturaFalsa()


@pytest.fixture
def controle(extensao: ExtensaoFalsa, assinatura: AssinaturaFalsa) -> Iterator[ControleDoNavegador]:
    feito = ControleDoNavegador(
        ClienteDoNavegador(extensao),
        assinar=lambda: assinatura,
        intervalo_s=0.02,
        manter_s=0.05,
        avulsa_ociosa_s=0.15,
        ociosa_s=5.0,
    )
    yield feito
    feito.fechar()


def test_cada_objetivo_tem_a_sua_concessao_e_a_mesma_a_cada_pedido(
    controle: ControleDoNavegador,
) -> None:
    turno, tarefa = Objetivo.do_pedido("abre o youtube"), Objetivo.do_pedido("pesquisa x")

    primeira = controle.concessao(turno)

    assert controle.concessao(turno) == primeira
    assert controle.concessao(tarefa) not in (primeira, "")
    assert len(primeira) == 16 and primeira.isalnum()


def test_a_vigia_solta_quando_o_objetivo_acaba_e_a_janela_acompanha(
    controle: ControleDoNavegador, extensao: ExtensaoFalsa
) -> None:
    mudou: list[bool] = []
    controle.ao_mudar = mudou.append
    turno = Objetivo.do_pedido("abre o youtube")
    concessao = controle.concessao(turno)
    assert not _no_controle(controle) and mudou == [], "nada chegou ao navegador ainda"
    controle.confirmar(concessao)  # a extensão aceitou o primeiro pedido
    controle.confirmar(concessao)
    assert _no_controle(controle) and mudou == [True]

    turno.concluir(EstadoDoObjetivo.CONCLUIDO)

    assert _esperar(lambda: extensao.metodo("controle.soltar") == [{"controle": concessao}])
    assert _esperar(lambda: mudou == [True, False])
    assert not _no_controle(controle)


def test_o_que_fazer_no_fim_roda_com_o_estado_final(controle: ControleDoNavegador) -> None:
    vistos: list[EstadoDoObjetivo] = []
    turno = Objetivo.do_pedido("abre o youtube")
    controle.concessao(turno, ao_concluir=vistos.append)

    turno.concluir(EstadoDoObjetivo.CANCELADO)

    assert _esperar(lambda: vistos == [EstadoDoObjetivo.CANCELADO])


def test_o_parar_do_dono_pelo_evento_cancela_uma_vez_e_o_objetivo_nao_volta_a_agir(
    controle: ControleDoNavegador, assinatura: AssinaturaFalsa
) -> None:
    parados: list[Sequence[Objetivo]] = []
    controle.ao_parar = parados.append
    turno, outro = Objetivo.do_pedido("abre o youtube"), Objetivo.do_pedido("lê o g1")
    concessao = controle.concessao(turno)

    assinatura.fila.put({"evento": "parar", "concessoes": [concessao], "origem": "faixa"})
    assinatura.fila.put({"evento": "parar", "concessoes": [concessao], "origem": "barra"})

    assert _esperar(lambda: len(parados) == 1)
    time.sleep(0.1)
    assert len(parados) == 1 and parados[0][0] is turno, "uma vez por concessão"
    assert controle.revogada(concessao)
    with pytest.raises(PermissionError, match="parar"):
        controle.concessao(turno)
    assert controle.concessao(outro), "um pedido novo do dono volta a agir"


def test_o_parar_da_janela_do_jarvis_avisa_a_extensao_e_cancela_quem_estava(
    controle: ControleDoNavegador, extensao: ExtensaoFalsa
) -> None:
    parados: list[Sequence[Objetivo]] = []
    controle.ao_parar = parados.append
    turno = Objetivo.do_pedido("abre o youtube")
    controle.confirmar(controle.concessao(turno))

    devolvidos = controle.parar()

    assert devolvidos == [turno] and parados == [[turno]]
    assert extensao.metodo("controle.parar") == [{}]
    assert not controle.no_controle


def test_a_vigia_renova_e_ouve_o_parar_tambem_pela_recusa_da_extensao(
    controle: ControleDoNavegador, extensao: ExtensaoFalsa
) -> None:
    parados: list[Sequence[Objetivo]] = []
    controle.ao_parar = parados.append
    turno = Objetivo.do_pedido("abre o youtube")
    concessao = controle.concessao(turno)

    assert _esperar(lambda: len(extensao.metodo("controle.manter")) >= 2), "renova sozinha"
    extensao.paradas.add(concessao)  # o evento se perdeu, mas a extensão já recusa

    assert _esperar(lambda: parados == [[turno]])


def test_chamada_sem_objetivo_tem_concessao_avulsa_que_solta_parada(
    controle: ControleDoNavegador, extensao: ExtensaoFalsa
) -> None:
    avulsa = controle.concessao(None)

    assert controle.concessao(None) == avulsa
    assert _esperar(lambda: extensao.metodo("controle.soltar") == [{"controle": avulsa}])


def test_objetivo_que_ficou_parado_solta_as_abas_e_pega_de_novo_no_proximo_pedido(
    extensao: ExtensaoFalsa,
) -> None:
    controle = ControleDoNavegador(
        ClienteDoNavegador(extensao), intervalo_s=0.02, manter_s=5.0, ociosa_s=0.1
    )
    turno = Objetivo.do_pedido("pesquisa x")
    primeira = controle.concessao(turno)

    assert _esperar(lambda: extensao.metodo("controle.soltar") == [{"controle": primeira}])
    assert controle.concessao(turno) != primeira, "o próximo pedido pega de novo"
    controle.fechar()


def test_sem_extensao_a_vigia_nao_cai(extensao: ExtensaoFalsa) -> None:
    def assinar() -> AssinaturaFalsa:
        raise NavegadorIndisponivel("nenhum navegador")

    controle = ControleDoNavegador(ClienteDoNavegador(extensao), assinar=assinar, intervalo_s=0.02)
    turno = Objetivo.do_pedido("abre o youtube")
    controle.concessao(turno)
    turno.concluir(EstadoDoObjetivo.CONCLUIDO)

    assert _esperar(lambda: not controle.no_controle)


def test_pedido_que_nem_chegou_ao_navegador_nao_poe_nada_no_controle(
    controle: ControleDoNavegador, extensao: ExtensaoFalsa
) -> None:
    mudou: list[bool] = []
    controle.ao_mudar = mudou.append
    turno = Objetivo.do_pedido("abre o youtube")
    concessao = controle.concessao(turno)  # o navegador estava fechado: a ferramenta falhou

    turno.concluir(EstadoDoObjetivo.FALHOU)

    assert _esperar(lambda: extensao.metodo("controle.soltar") == [{"controle": concessao}])
    assert mudou == [], "a janela nunca mostrou o PARAR"
