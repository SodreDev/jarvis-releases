"""O monitor das redes (ADR-0060, fatia B), só com ponte falsa: nenhum navegador, nenhuma conta.

A ponte falsa faz o papel do host do navegador: guarda os pedidos que o monitor fez (só podem ser
`social.abrir` e `social.estado`) e entrega os eventos que o teste põe na fila — o mesmo formato
que `extensao/social.js` manda, depois de passar por `validar_evento`."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from jarvis.navegador.cliente import (
    ExtensaoDesatualizada,
    NavegadorFalhou,
    NavegadorIndisponivel,
    SemResposta,
    VersaoDaPonte,
)
from jarvis.navegador.protocolo import (
    VERSAO_DA_PONTE,
    PedidoInvalido,
    validar_evento,
    validar_pedido,
)
from jarvis.social.config import ConfiguracaoSocial
from jarvis.social.contador import VOCABULARIO, amostra_segura
from jarvis.social.monitor import (
    REABRIR_APOS_FALHA_S,
    REABRIR_S,
    SEM_NOTICIA_S,
    EstadoDaPagina,
    EstadoDoMonitor,
    MonitorSocial,
    Notificacao,
)
from jarvis.trilha import TrilhaDeDiagnostico


class Relogio:
    def __init__(self) -> None:
        self.agora = 1_000_000.0

    def __call__(self) -> float:
        return self.agora


RAIZ = Path(__file__).resolve().parents[3]


def pagina(rede: str = "whatsapp", **campos: Any) -> EstadoDaPagina:
    evento = {
        "evento": "social",
        "rede": rede,
        "logado": True,
        "naoLidas": 0,
        "conversas": [],
        "formato": "conhecido",
        **campos,
    }
    return EstadoDaPagina.do_evento(validar_evento(evento))


def ligado(*redes: str, notificar: bool = True) -> ConfiguracaoSocial:
    configuracao = ConfiguracaoSocial()
    for rede in redes:
        configuracao = configuracao.com_rede(rede, monitorar=True, notificar=notificar)
    return configuracao


# --- a regra de avisar ------------------------------------------------------------------------
def test_avisa_quando_sobe_e_nao_quando_desce() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    primeira = estado.receber(
        pagina(naoLidas=2, conversas=[{"nome": "Ana", "naoLidas": 2}]), notificar=True
    )
    assert primeira is not None
    assert primeira.texto == "WhatsApp: 2 mensagens novas — Ana (2)"
    assert estado.receber(pagina(naoLidas=2), notificar=True) is None, "mesma contagem: nada"
    assert estado.receber(pagina(naoLidas=0), notificar=True) is None, "o dono leu: nada"
    terceira = estado.receber(
        pagina(
            naoLidas=1,
            conversas=[{"nome": "Bruno", "naoLidas": 1}],
        ),
        notificar=True,
    )
    assert terceira is not None and terceira.texto == "WhatsApp: 1 mensagem nova — Bruno (1)"
    tela = estado.para_a_tela("whatsapp")
    assert tela["estado"] == "conectada" and tela["naoLidas"] == 1
    assert [n["texto"] for n in tela["notificacoes"]] == [terceira.texto, primeira.texto]


def test_notificacoes_sao_separadas_por_rede_e_limitadas() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp", "discord"))
    for n in range(1, 9):
        estado.receber(pagina("discord", naoLidas=n), notificar=True)
    assert len(estado.para_a_tela("discord")["notificacoes"]) == 5
    assert estado.para_a_tela("whatsapp")["notificacoes"] == []


def test_sem_notificar_so_atualiza_o_estado() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("instagram", notificar=False))
    assert estado.receber(pagina("instagram", naoLidas=4), notificar=False) is None
    assert estado.para_a_tela("instagram")["naoLidas"] == 4


def test_rede_desligada_ignora_o_evento() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    assert estado.receber(pagina("tiktok", naoLidas=3), notificar=True) is None
    assert estado.para_a_tela("tiktok")["estado"] == "desligada"


def test_login_e_formato_desconhecido_viram_estado_sem_aviso() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("facebook"))
    assert estado.receber(pagina("facebook", logado=False), notificar=True) is None
    assert estado.para_a_tela("facebook")["estado"] == "esperando_login"
    assert "não digita senha" in estado.para_a_tela("facebook")["frase"]
    assert (
        estado.receber(
            pagina("facebook", logado=False, naoLidas=7, formato="desconhecido"), notificar=True
        )
        is None
    )
    assert estado.para_a_tela("facebook")["estado"] == "formato_desconhecido"


def test_muitos_nomes_viram_e_mais() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    conversas = [{"nome": f"C{i}", "naoLidas": 1} for i in range(5)]
    aviso = estado.receber(pagina(naoLidas=5, conversas=conversas), notificar=True)
    assert aviso is not None and aviso.texto.endswith("C0 (1), C1 (1), C2 (1) e mais 2")


def test_desligar_esquece_a_base_mas_guarda_as_notificacoes() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    estado.receber(pagina(naoLidas=3), notificar=True)
    estado.ajustar(ConfiguracaoSocial())
    assert estado.para_a_tela("whatsapp")["estado"] == "desligada"
    assert len(estado.para_a_tela("whatsapp")["notificacoes"]) == 1
    estado.ajustar(ligado("whatsapp"))
    assert estado.receber(pagina(naoLidas=3), notificar=True) is not None


def test_aba_sem_noticia_diz_para_recarregar_a_extensao() -> None:
    relogio = Relogio()
    estado = EstadoDoMonitor(relogio)
    estado.ajustar(ligado("whatsapp"))
    estado.pedida("whatsapp")
    estado.marcar("whatsapp", "abrindo")
    relogio.agora += SEM_NOTICIA_S + 1
    estado.conferir_noticia()
    assert estado.para_a_tela("whatsapp")["estado"] == "sem_noticia"


def test_alerta_da_pagina_sempre_avisa_uma_vez_e_some_quando_volta_ao_normal() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp", notificar=False))
    aviso = estado.receber(pagina(alerta="captcha"), notificar=False)
    assert aviso is not None and "captcha" in aviso.texto and "24 h" in aviso.texto
    assert estado.para_a_tela("whatsapp")["estado"] == "alerta"
    assert estado.receber(pagina(alerta="captcha"), notificar=False) is None, "não repete"
    estado.receber(pagina(naoLidas=0), notificar=False)
    assert estado.para_a_tela("whatsapp")["estado"] == "conectada"
    assert estado.alerta("whatsapp") == ""


def test_logout_e_elementos_sumidos_depois_de_conectada_sao_alerta() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp", "discord"))
    estado.receber(pagina(naoLidas=0), notificar=True)
    aviso = estado.receber(pagina(logado=False), notificar=True)
    assert aviso is not None and estado.alerta("whatsapp") == "logout"
    assert estado.receber(pagina(logado=False), notificar=True) is None
    estado.receber(pagina("discord", naoLidas=0), notificar=True)
    sumiu = estado.receber(pagina("discord", logado=False, formato="desconhecido"), notificar=True)
    assert sumiu is not None and estado.alerta("discord") == "elementos_sumiram"
    # sem ter conectado antes, login e formato desconhecido não são alerta
    estado.ajustar(ligado("tiktok"))
    assert estado.receber(pagina("tiktok", logado=False), notificar=True) is None
    assert estado.alerta("tiktok") == ""


# --- o contrato do evento e dos pedidos -------------------------------------------------------
@pytest.mark.parametrize(
    "evento",
    [
        {"evento": "social", "rede": "orkut", "logado": True, "naoLidas": 1},
        {"evento": "social", "rede": "whatsapp", "logado": "sim", "naoLidas": 1},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": -1},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 10_000},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": True},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "pista": "x"},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "amostra": 3},
        {
            "evento": "social",
            "rede": "whatsapp",
            "logado": True,
            "naoLidas": 1,
            "amostra": "9" * 61,
        },
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "amostra": "a\nb"},
        {
            "evento": "social",
            "rede": "whatsapp",
            "logado": True,
            "naoLidas": 1,
            "conversas": [{"nome": "x" * 81, "naoLidas": 1}],
        },
        {
            "evento": "social",
            "rede": "whatsapp",
            "logado": True,
            "naoLidas": 1,
            "conversas": [{"nome": "Ana\nlinha", "naoLidas": 1}],
        },
        {
            "evento": "social",
            "rede": "whatsapp",
            "logado": True,
            "naoLidas": 1,
            "conversas": [{"nome": "a", "naoLidas": 1}] * 21,
        },
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "texto": "oi"},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "formato": "x"},
        {"evento": "social", "rede": "whatsapp", "logado": True, "naoLidas": 1, "alerta": "y"},
    ],
)
def test_evento_social_fora_do_contrato_e_recusado(evento: dict[str, Any]) -> None:
    with pytest.raises(PedidoInvalido):
        validar_evento(evento)


def test_pedidos_do_monitor_so_aceitam_rede_conhecida() -> None:
    pedido = validar_pedido({"id": "a1", "method": "social.abrir", "params": {"rede": "discord"}})
    assert pedido.params == {"rede": "discord"}
    for params in ({}, {"rede": "orkut"}, {"rede": "whatsapp", "url": "https://x.example/"}):
        with pytest.raises(PedidoInvalido):
            validar_pedido({"id": "a1", "method": "social.abrir", "params": params})


# --- o fio ------------------------------------------------------------------------------------
class AssinaturaFalsa:
    def __init__(self, fila: list[dict[str, Any]]) -> None:
        self.fila = fila
        self.fechada = False

    def esperar(self, segundos: float) -> list[dict[str, Any]]:
        time.sleep(min(segundos, 0.01))
        saida, self.fila[:] = list(self.fila), []
        return [validar_evento(e) for e in saida]

    def fechar(self) -> None:
        self.fechada = True


class PonteFalsa:
    def __init__(self, *, aberta: bool = True) -> None:
        self.aberta = aberta
        self.fila: list[dict[str, Any]] = []
        self.pedidos: list[tuple[str, str, dict[str, Any]]] = []
        self.assinaturas: list[AssinaturaFalsa] = []
        self.tentativas = 0
        """Quantas vezes o monitor tentou assinar (com ou sem host)."""
        self.falha_ao_abrir: Exception | None = None
        self.versao_da_ponte: VersaoDaPonte | None = None

    def assinar(self, navegador: str = "") -> AssinaturaFalsa:
        self.tentativas += 1
        if not self.aberta:
            raise NavegadorIndisponivel("nenhum navegador com a extensão do Jarvis está aberto")
        assinatura = AssinaturaFalsa(self.fila)
        self.assinaturas.append(assinatura)
        return assinatura

    def versao(self, navegador: str) -> VersaoDaPonte:
        if self.versao_da_ponte is None:
            return VersaoDaPonte(host=VERSAO_DA_PONTE, extensao=VERSAO_DA_PONTE)
        return self.versao_da_ponte

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]:
        validar_pedido({"id": "t1", "method": metodo, "params": params})
        self.pedidos.append((metodo, navegador, params))
        if metodo == "social.abrir" and self.falha_ao_abrir is not None:
            raise self.falha_ao_abrir
        if metodo == "social.estado":
            return {"logado": False, "naoLidas": 0, "conversas": [], "formato": "conhecido"}
        return {"tabId": 7, "reutilizada": False}


def _esperar(condicao: Callable[[], bool], segundos: float = 3.0) -> bool:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        if condicao():
            return True
        time.sleep(0.01)
    return condicao()


def _monitor(
    ponte: PonteFalsa,
    configuracao: list[ConfiguracaoSocial],
    *,
    prazo_de_conexao_s: float = 0.0,
    navegador_aberto: Callable[[], bool | None] | None = None,
    diagnosticos: list[dict[str, str]] | None = None,
) -> tuple[MonitorSocial, list[Notificacao], threading.Event]:
    avisos: list[Notificacao] = []
    mudou = threading.Event()
    monitor = MonitorSocial(
        ponte,
        configuracao=lambda: configuracao[0],
        familia=lambda: "chromium",
        ao_notificar=avisos.append,
        ao_mudar=mudou.set,
        intervalo_s=0.02,
        prazo_de_conexao_s=prazo_de_conexao_s,
        navegador_aberto=navegador_aberto,
        ao_diagnostico=None if diagnosticos is None else (lambda d: diagnosticos.append(dict(d))),
    )
    return monitor, avisos, mudou


def test_sem_rede_ligada_o_monitor_nao_assina_nem_abre_nada() -> None:
    ponte = PonteFalsa()
    monitor, _, _ = _monitor(ponte, [ConfiguracaoSocial()])
    monitor.iniciar()
    time.sleep(0.15)
    monitor.parar()
    assert ponte.pedidos == [] and ponte.assinaturas == []


def test_rede_ligada_abre_a_aba_de_fundo_e_avisa_pelo_evento() -> None:
    ponte = PonteFalsa()
    configuracao = [ligado("whatsapp")]
    monitor, avisos, _ = _monitor(ponte, configuracao)
    monitor.iniciar()
    try:
        assert _esperar(lambda: any(p[0] == "social.abrir" for p in ponte.pedidos))
        assert ponte.pedidos[0] == ("social.abrir", "chromium", {"rede": "whatsapp"})
        assert {p[0] for p in ponte.pedidos} <= {"social.abrir", "social.estado"}
        assert _esperar(
            lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == "esperando_login"
        )
        ponte.fila.append(
            {
                "evento": "social",
                "rede": "whatsapp",
                "logado": True,
                "naoLidas": 1,
                "conversas": [{"nome": "Ana", "naoLidas": 1}],
                "formato": "conhecido",
            }
        )
        assert _esperar(lambda: len(avisos) == 1)
        assert avisos[0].texto == "WhatsApp: 1 mensagem nova — Ana (1)"
        # evento de rede não ligada e evento que não é social: ignorados
        ponte.fila.append({"evento": "social", "rede": "tiktok", "logado": True, "naoLidas": 9})
        ponte.fila.append({"evento": "parar", "concessoes": [], "origem": "barra"})
        time.sleep(0.1)
        assert len(avisos) == 1
        # o dono desliga: o fio fecha a assinatura e não pede mais nada
        configuracao[0] = ConfiguracaoSocial()
        monitor.atualizar()
        assert _esperar(lambda: all(a.fechada for a in ponte.assinaturas))
        antes = len(ponte.pedidos)
        time.sleep(0.1)
        assert len(ponte.pedidos) == antes
    finally:
        monitor.parar()


def test_sem_navegador_aberto_diz_isso_e_nao_abre_nada() -> None:
    ponte = PonteFalsa(aberta=False)
    monitor, _, mudou = _monitor(ponte, [ligado("discord")])
    monitor.iniciar()
    try:
        assert _esperar(mudou.is_set)
        assert _esperar(lambda: monitor.estado.para_a_tela("discord")["estado"] == "sem_extensao")
        assert "Recarregar" in monitor.estado.para_a_tela("discord")["frase"]
        assert ponte.pedidos == []
    finally:
        monitor.parar()


# --- fatia E: Instagram, Facebook, TikTok e Discord, só leitura -------------------------------
def test_quatro_redes_ao_mesmo_tempo_com_notificacoes_e_alertas_separados() -> None:
    ponte = PonteFalsa()
    redes = ("instagram", "facebook", "tiktok", "discord")
    configuracao = [ligado(*redes)]
    avisos: list[Notificacao] = []
    alertas: list[tuple[str, str]] = []
    monitor = MonitorSocial(
        ponte,
        configuracao=lambda: configuracao[0],
        familia=lambda: "chromium",
        ao_notificar=avisos.append,
        ao_mudar=lambda: None,
        ao_alerta=lambda rede, alerta: alertas.append((rede, alerta)),
        intervalo_s=0.02,
    )
    monitor.iniciar()
    try:
        assert _esperar(
            lambda: {p[2]["rede"] for p in ponte.pedidos if p[0] == "social.abrir"} == set(redes)
        )
        for numero, rede in enumerate(redes, start=1):
            ponte.fila.append(
                {
                    "evento": "social",
                    "rede": rede,
                    "logado": True,
                    "naoLidas": numero,
                    "conversas": [{"nome": f"pessoa-{rede}", "naoLidas": numero}],
                    "formato": "conhecido",
                    "alerta": "",
                }
            )
        assert _esperar(lambda: len(avisos) == 4)
        assert sorted(a.rede for a in avisos) == sorted(redes)
        for rede in redes:
            cartao = monitor.estado.para_a_tela(rede)
            assert len(cartao["notificacoes"]) == 1
            assert f"pessoa-{rede}" in cartao["notificacoes"][0]["texto"]
        ponte.fila.append(
            {
                "evento": "social",
                "rede": "discord",
                "logado": True,
                "naoLidas": 0,
                "conversas": [],
                "formato": "conhecido",
                "alerta": "verificacao",
            }
        )
        assert _esperar(lambda: alertas == [("discord", "verificacao")])
        assert monitor.estado.para_a_tela("instagram")["estado"] == "conectada"
        assert {p[0] for p in ponte.pedidos} <= {"social.abrir", "social.estado"}, "só leitura"
    finally:
        monitor.parar()


def test_nenhuma_rede_alem_do_whatsapp_tem_caminho_de_envio() -> None:
    from jarvis.social.envio import REDES_COM_ENVIO
    from jarvis.social.redes import REDES

    assert {"whatsapp"} == REDES_COM_ENVIO
    assert [r.id for r in REDES if r.responde] == ["whatsapp"]
    for rede in ("instagram", "facebook", "tiktok", "discord"):
        for metodo in ("social.cabecalho", "social.abrirConversa", "social.enviar"):
            params: dict[str, Any] = {"rede": rede}
            if metodo == "social.abrirConversa":
                params["nome"] = "alguém"
            with pytest.raises(PedidoInvalido):
                validar_pedido({"id": "z1", "method": metodo, "params": params})


# --- a conexão com a extensão (bug do dono, 2026-11-13: «não há navegador com a extensão») ------
def test_sem_host_dentro_do_prazo_e_conectando_e_pega_o_host_que_aparece_depois() -> None:
    """A corrida da partida: o monitor pede antes de o fundo da extensão chamar o host. Dentro do
    prazo de conexão ele diz «conectando», tenta de novo logo e abre a aba quando o host chega."""
    ponte = PonteFalsa(aberta=False)
    monitor, _, _ = _monitor(ponte, [ligado("whatsapp")], prazo_de_conexao_s=60.0)
    monitor.iniciar()
    try:
        assert _esperar(lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == "conectando")
        assert _esperar(lambda: ponte.tentativas >= 3), "tenta de novo a cada intervalo"
        assert ponte.pedidos == []
        ponte.aberta = True
        assert _esperar(lambda: any(p[0] == "social.abrir" for p in ponte.pedidos))
        assert _esperar(
            lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == "esperando_login"
        )
    finally:
        monitor.parar()


@pytest.mark.parametrize(
    ("aberto", "esperado"),
    [(False, "sem_navegador"), (True, "sem_extensao"), (None, "sem_extensao")],
)
def test_fora_do_prazo_diz_o_que_faltou(aberto: bool | None, esperado: str) -> None:
    ponte = PonteFalsa(aberta=False)
    diagnosticos: list[dict[str, str]] = []
    monitor, _, _ = _monitor(
        ponte, [ligado("whatsapp")], navegador_aberto=lambda: aberto, diagnosticos=diagnosticos
    )
    monitor.iniciar()
    try:
        assert _esperar(lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == esperado)
        frase = monitor.estado.para_a_tela("whatsapp")["frase"]
        assert ("abra-o" in frase) is (esperado == "sem_navegador")
        assert ("Recarregar" in frase) is (esperado == "sem_extensao")
        assert _esperar(lambda: bool(diagnosticos))
        assert diagnosticos[-1]["estado"] == esperado
        assert diagnosticos[-1]["codigo"] in {"navegador_fechado", "sem_host"}
        quantos = len(diagnosticos)
        time.sleep(0.2)
        assert len(diagnosticos) == quantos, "a trilha só recebe a mudança, não cada tique"
    finally:
        monitor.parar()


@pytest.mark.parametrize(
    ("falha", "estado", "codigo"),
    [
        (ExtensaoDesatualizada("social.abrir"), "extensao_antiga", "extensao_desatualizada"),
        (
            SemResposta("a extensão não respondeu a social.abrir em 8 s"),
            "sem_resposta",
            "sem_resposta",
        ),
        (NavegadorFalhou("falha", "tabs.create recusou"), "sem_resposta", "falha"),
        (NavegadorIndisponivel("o host fechou sem responder"), "conectando", "sem_host"),
    ],
)
def test_falha_ao_abrir_a_aba_nao_vira_sem_extensao(
    falha: Exception, estado: str, codigo: str
) -> None:
    """Antes, QUALQUER falha do `social.abrir` dizia «sem navegador com a extensão» e só tentava de
    novo em 120 s — mesmo com a extensão conectada e a aba abrindo devagar."""
    ponte = PonteFalsa()
    ponte.falha_ao_abrir = falha
    diagnosticos: list[dict[str, str]] = []
    monitor, _, _ = _monitor(ponte, [ligado("whatsapp")], diagnosticos=diagnosticos)
    monitor.iniciar()
    try:
        assert _esperar(lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == estado)
        assert _esperar(lambda: any(d["codigo"] == codigo for d in diagnosticos))
    finally:
        monitor.parar()


def test_falha_ao_abrir_tenta_de_novo_logo_e_noticia_espera_o_normal() -> None:
    relogio = Relogio()
    estado = EstadoDoMonitor(relogio)
    estado.ajustar(ligado("whatsapp"))
    assert estado.precisa_abrir("whatsapp")
    estado.pedida("whatsapp")
    estado.falhou("whatsapp", "sem_resposta", "sem_resposta")
    relogio.agora += REABRIR_APOS_FALHA_S - 1
    assert not estado.precisa_abrir("whatsapp")
    relogio.agora += 1
    assert estado.precisa_abrir("whatsapp")
    estado.pedida("whatsapp")  # deu certo desta vez: volta ao prazo de quem só ficou sem notícia
    relogio.agora += REABRIR_APOS_FALHA_S
    assert not estado.precisa_abrir("whatsapp")
    relogio.agora += REABRIR_S
    assert estado.precisa_abrir("whatsapp")
    estado.reconectou(["whatsapp"])  # host novo: pede a aba de novo na hora
    estado.pedida("whatsapp")
    estado.reconectou(["whatsapp"])
    assert estado.precisa_abrir("whatsapp")


def test_extensao_de_antes_avisa_recarregar_mesmo_com_a_rede_conectada() -> None:
    ponte = PonteFalsa()
    ponte.versao_da_ponte = VersaoDaPonte(host=VERSAO_DA_PONTE, extensao=VERSAO_DA_PONTE - 1)
    diagnosticos: list[dict[str, str]] = []
    monitor, _, _ = _monitor(ponte, [ligado("whatsapp")], diagnosticos=diagnosticos)
    monitor.iniciar()
    try:
        assert _esperar(
            lambda: monitor.estado.para_a_tela("whatsapp")["estado"] == "esperando_login"
        )
        assert "Recarregar" in monitor.estado.para_a_tela("whatsapp")["frase"]
        assert _esperar(
            lambda: any(d["codigo"] == f"extensao_v{VERSAO_DA_PONTE - 1}" for d in diagnosticos)
        )
    finally:
        monitor.parar()


# --- o contador (bug do dono, 2026-11-13: «formato não reconhecido do contador») ---------------
def test_tela_de_carga_e_carregando_e_nao_vira_alerta_depois_de_conectada() -> None:
    """O WhatsApp Web mostra a tela de carga ao abrir e ao reconectar: não é «a página mudou» nem
    «a sessão caiu» — antes, isso pausava o envio por 24 h com «elementos sumiram»."""
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    carga: dict[str, Any] = {"logado": False, "formato": "desconhecido", "pista": "carregando"}
    assert estado.receber(pagina(**carga), notificar=True) is None
    tela = estado.para_a_tela("whatsapp")
    assert tela["estado"] == "carregando" and "carregando" in tela["frase"]
    estado.receber(pagina(naoLidas=2, conversas=[{"nome": "Ana", "naoLidas": 2}]), notificar=True)
    assert estado.receber(pagina(**carga), notificar=True) is None
    assert (
        estado.alerta("whatsapp") == "" and estado.para_a_tela("whatsapp")["estado"] == "carregando"
    )
    # voltou com as mesmas não lidas: nada de aviso repetido
    assert estado.receber(pagina(naoLidas=2), notificar=True) is None
    assert estado.para_a_tela("whatsapp")["estado"] == "conectada"


def test_cada_falta_tem_a_sua_frase() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp", "discord"))
    estado.receber(pagina(logado=False), notificar=True)
    assert "QR" in estado.para_a_tela("whatsapp")["frase"]
    estado.receber(
        pagina(
            "discord",
            logado=False,
            formato="desconhecido",
            pista="sem_lista",
            amostra="(3) Ana Souza | Discord",
        ),
        notificar=True,
    )
    tela = estado.para_a_tela("discord")
    assert tela["estado"] == "formato_desconhecido"
    assert "lista de conversas" in tela["frase"] and "diagnóstico" in tela["frase"]
    assert "«(3) x x | discord»" in tela["frase"], "a amostra chega sanitizada de novo"
    assert "Ana" not in tela["frase"]


def test_contador_ilegivel_conta_e_avisa_sem_derrubar_nada() -> None:
    estado = EstadoDoMonitor(Relogio())
    estado.ajustar(ligado("whatsapp"))
    aviso = estado.receber(
        pagina(
            naoLidas=1,
            conversas=[{"nome": "Zé", "naoLidas": 1}],
            pista="contador_ilegivel",
            amostra="1,5 mil",
        ),
        notificar=True,
    )
    assert aviso is not None and aviso.texto == "WhatsApp: 1 mensagem nova — Zé (1)"
    tela = estado.para_a_tela("whatsapp")
    assert tela["estado"] == "conectada" and "formato que o Jarvis não reconhece" in tela["frase"]
    assert estado.diagnostico("whatsapp") == {
        "rede": "whatsapp",
        "estado": "conectada",
        "codigo": "",
        "pista": "contador_ilegivel",
        "amostra": "1,5 mil",
    }


def test_a_trilha_guarda_a_pista_e_a_amostra_sanitizada(tmp_path: Path) -> None:
    trilha = TrilhaDeDiagnostico(tmp_path)
    trilha.evento(
        "rede.estado",
        rede="whatsapp",
        estado="formato_desconhecido",
        codigo="",
        pista="sem_lista",
        amostra="(2) Maria +55 11 98765-4321",
        nome="Maria",
    )
    linha = json.loads((tmp_path / "turnos.jsonl").read_text("utf-8"))
    assert linha["pista"] == "sem_lista"
    assert linha["amostra"] == "(2) x ###"
    assert linha["campos_fora"] == ["nome"]


def test_o_vocabulario_da_amostra_e_o_mesmo_na_extensao() -> None:
    dados = (RAIZ / "extensao" / "social-seletores.js").read_text("utf-8")
    corpo = "\n".join(linha for linha in dados.splitlines() if not linha.startswith("//"))
    prefixo = "globalThis.__jarvisSeletoresSociais = "
    seletores = json.loads(corpo.strip().removeprefix(prefixo).removesuffix(";"))
    assert frozenset(seletores["vocabularioDaAmostra"]) == VOCABULARIO
    assert amostra_segura("(\u0663) WhatsApp") == "(3) whatsapp"
    assert amostra_segura("Marcada como não lida") == "marcada como nao lida"
