"""O monitor das redes (ADR-0060, fatia B), só com ponte falsa: nenhum navegador, nenhuma conta.

A ponte falsa faz o papel do host do navegador: guarda os pedidos que o monitor fez (só podem ser
`social.abrir` e `social.estado`) e entrega os eventos que o teste põe na fila — o mesmo formato
que `extensao/social.js` manda, depois de passar por `validar_evento`."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest

from jarvis.navegador.protocolo import PedidoInvalido, validar_evento, validar_pedido
from jarvis.social.config import ConfiguracaoSocial
from jarvis.social.monitor import (
    SEM_NOTICIA_S,
    EstadoDaPagina,
    EstadoDoMonitor,
    MonitorSocial,
    Notificacao,
)


class Relogio:
    def __init__(self) -> None:
        self.agora = 1_000_000.0

    def __call__(self) -> float:
        return self.agora


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

    def assinar(self, navegador: str = "") -> AssinaturaFalsa:
        if not self.aberta:
            raise OSError("sem host")
        assinatura = AssinaturaFalsa(self.fila)
        self.assinaturas.append(assinatura)
        return assinatura

    def pedir(self, metodo: str, navegador: str, **params: Any) -> dict[str, Any]:
        validar_pedido({"id": "t1", "method": metodo, "params": params})
        self.pedidos.append((metodo, navegador, params))
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
    ponte: PonteFalsa, configuracao: list[ConfiguracaoSocial]
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
        assert ponte.pedidos == []
    finally:
        monitor.parar()
