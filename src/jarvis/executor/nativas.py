"""O corpo das ferramentas nativas do assistente de voz (item 4 do pedido do dono, 2026-10-18).

Sistema (hora, estado, volume, brilho), mídia, janelas, área de transferência, notificação do
desktop, alarmes e web. Cada corpo recebe só **argumentos já validados pelo schema do manifesto** e
um `Nativas` com as portas — lançador de comandos, relógio, raiz do sistema, agenda, `obter` da web
—, **todas injetáveis**: nenhum teste toca o desktop, o relógio nem a rede.

Quem decide se roda é o PDP (tier do manifesto); aqui só se executa, e se devolve o que o modelo
pode dizer. Arquivos (criar pasta, copiar, mover) precisam do grant e moram em `organizar.py`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from jarvis.executor import desktop, sistema, web
from jarvis.executor.alarmes import AgendaDeAlarmes, quando_da_fala
from jarvis.executor.comandos import Lancador, executar


@dataclass(slots=True)
class Nativas:
    lar: Path
    lancar: Lancador = executar
    agora: Callable[[], datetime] = datetime.now
    raiz_do_sistema: Path = Path("/")
    ambiente: Mapping[str, str] | None = None
    agenda: AgendaDeAlarmes | None = None
    obter: web.Obter = web.obter_publico
    resolver: web.Resolver = web._resolver_dns
    dormir: Callable[[float], None] = time.sleep
    anterior_da_area: str = field(default="", repr=False)
    """O texto que a área de transferência tinha antes da última escrita — é o do "desfazer"."""


Corpo = Callable[[Nativas, Mapping[str, Any]], dict[str, Any]]


def _agenda(n: Nativas) -> AgendaDeAlarmes:
    if n.agenda is None:
        raise ValueError("a agenda de alarmes não está ligada nesta sessão")
    return n.agenda


def _quando_humano(quando: float, agora: datetime) -> str:
    alvo = datetime.fromtimestamp(quando).astimezone()
    falta = max(0, round(quando - agora.timestamp()))
    if falta < 90:
        return f"daqui a {falta} segundos"
    if falta < 5400:
        return f"daqui a {round(falta / 60)} minutos, às {alvo:%H:%M}"
    dia = "hoje" if alvo.date() == agora.astimezone().date() else f"{alvo:%d/%m}"
    return f"{dia}, às {alvo:%H:%M}"


def _alarme_set(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    agora = n.agora().astimezone()
    quando = quando_da_fala(em_segundos=a.get("em_segundos"), as_=a.get("quando"), agora=agora)
    alarme = _agenda(n).agendar(str(a["mensagem"]), quando)
    return {
        "alarme_id": alarme.id,
        "mensagem": alarme.mensagem,
        "quando_humano": _quando_humano(quando, agora),
        "em_segundos": alarme.em_segundos(agora.timestamp()),
    }


def _alarme_list(n: Nativas, _a: Mapping[str, Any]) -> dict[str, Any]:
    agora = n.agora().astimezone().timestamp()
    return {
        "alarmes": [
            {"alarme_id": x.id, "mensagem": x.mensagem, "falta_segundos": x.em_segundos(agora)}
            for x in _agenda(n).listar()
        ]
    }


def _alarme_cancel(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    cancelado = _agenda(n).cancelar(str(a["alarme_id"]))
    return {"alarme_id": cancelado.id, "mensagem": cancelado.mensagem}


def _area_write(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    try:
        n.anterior_da_area = desktop.ler_area(n.lancar, n.ambiente)[: desktop.LIMITE_DE_ESCRITA]
    except Exception:  # sem leitura (imagem, vazia): o desfazer devolve área vazia, não falha
        n.anterior_da_area = ""
    return desktop.escrever_area(n.lancar, str(a["texto"]), n.ambiente)


CORPOS: Final[dict[str, Corpo]] = {
    "system.clock.now": lambda n, a: sistema.hora_agora(n.agora),
    "system.machine.status": lambda n, a: sistema.estado_da_maquina(
        raiz=n.raiz_do_sistema, lar=n.lar, dormir=n.dormir
    ),
    "system.volume.get": lambda n, a: sistema.volume_atual(n.lancar),
    "system.volume.set": lambda n, a: sistema.definir_volume(
        n.lancar, nivel=a.get("nivel"), delta=a.get("delta"), mudo=a.get("mudo")
    ),
    "system.brightness.set": lambda n, a: sistema.definir_brilho(
        n.lancar, nivel=a.get("nivel"), delta=a.get("delta")
    ),
    "media.player.control": lambda n, a: desktop.controlar_midia(
        n.lancar, str(a["acao"]), str(a.get("player", ""))
    ),
    "media.player.status": lambda n, a: desktop.estado_da_midia(n.lancar),
    "window.list": lambda n, a: {"janelas": desktop.listar_janelas(n.lancar)},
    "window.focus_app": lambda n, a: desktop.focar(n.lancar, str(a["app"])),
    "window.close_app": lambda n, a: desktop.fechar(n.lancar, str(a["app"])),
    "clipboard.text.read": lambda n, a: desktop.texto_da_area(n.lancar, n.ambiente),
    "clipboard.text.write": _area_write,
    "notify.desktop.send": lambda n, a: desktop.notificar(
        n.lancar, str(a["titulo"]), str(a["texto"])
    ),
    "timer.alarm.set": _alarme_set,
    "timer.alarm.list": _alarme_list,
    "timer.alarm.cancel": _alarme_cancel,
    "web.buscar": lambda n, a: web.buscar(str(a["consulta"]), n.obter, n.ambiente, n.resolver),
    "web.canal_videos": lambda n, a: web.canal_videos(str(a["canal"]), n.obter, n.resolver),
    "web.ler": lambda n, a: web.ler_pagina(str(a["url"]), n.obter, n.resolver),
}
"""`tool_id` → corpo. O que está aqui é "ligado" no executor; `timer.*` só com agenda."""

PRECISAM_DE_AGENDA: Final = frozenset({"timer.alarm.set", "timer.alarm.list", "timer.alarm.cancel"})
DE_ARQUIVOS: Final = frozenset({"files.create_dir", "files.copy", "files.move"})
"""Corpos que precisam do grant e do descritor da raiz: ficam no executor, via `Organizador`."""
