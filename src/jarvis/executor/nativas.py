"""O corpo das ferramentas nativas do assistente de voz (item 4 do pedido do dono, 2026-10-18).

Sistema (hora, estado, volume, brilho), mídia, janelas, área de transferência, notificação do
desktop, alarmes e web. Cada corpo recebe só **argumentos já validados pelo schema do manifesto** e
um `Nativas` com as portas — lançador de comandos, relógio, raiz do sistema, agenda, `obter` da web
—, **todas injetáveis**: nenhum teste toca o desktop, o relógio nem a rede.

Quem decide se roda é o PDP (tier do manifesto); aqui só se executa, e se devolve o que o modelo
pode dizer. Arquivos (criar pasta, copiar, mover) precisam do grant e moram em `organizar.py`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from jarvis.executor import desktop, sistema, web
from jarvis.executor.alarmes import AgendaDeAlarmes, quando_da_fala
from jarvis.executor.comandos import ComandoIndisponivel, Lancador, executar
from jarvis.executor.fechar import Jarvis, TabelaDeProcessos
from jarvis.executor.janelas import Janelas, focar, foco_para_o_modelo, listar_para_o_modelo
from jarvis.tela import PortaDaTela, TelaIndisponivel


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
    janelas: Janelas | None = None
    """Quem lista e foca as janelas (`kdotool` no KDE, `wmctrl` no X11; ADR-0037). `None` = o
    `wmctrl` de antes nas `window.*`, e nada de acompanhar o foco de um app aberto."""
    processos: TabelaDeProcessos | None = None
    """A tabela de processos (`/proc`) de `apps.quit` (ADR-0042). `None` = a de verdade."""
    sinalizar: Callable[[int, int], None] = os.kill
    """O sinal por PID de `apps.quit`: só aos processos que o código resolveu e conferiu."""
    relogio: Callable[[], float] = time.monotonic
    jarvis: Jarvis | None = None
    """Quem é o próprio Jarvis (nunca alvo). `None` = este processo, lido na hora."""
    anterior_da_area: str = field(default="", repr=False)
    """O texto que a área de transferência tinha antes da última escrita — é o do "desfazer"."""
    tela: PortaDaTela | None = None
    """As exibições da janela do Jarvis (ADR-0055). `None` = sem janela: as `tela.*` não existem."""


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


def _web_ler(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    """Um site (`url`) ou vários seguidos (`urls`, dono 2026-10-20) — um dos dois."""
    url, urls = a.get("url"), a.get("urls")
    if bool(url) == bool(urls):
        raise web.WebRecusada("diga um site (url) ou uma lista deles (urls), um dos dois")
    if urls:
        return web.ler_paginas([str(u) for u in urls], n.obter, n.resolver)
    return web.ler_pagina(str(url), n.obter, n.resolver)


def _janelas(n: Nativas, _a: Mapping[str, Any]) -> dict[str, Any]:
    if n.janelas is None:
        return {"janelas": desktop.listar_janelas(n.lancar)}
    return listar_para_o_modelo(n.janelas)


def _em_foco(n: Nativas, _a: Mapping[str, Any]) -> dict[str, Any]:
    """A ativa e a da frente de cada monitor (dono, 2026-10-21). Sem porta de janelas (o Wayland
    sem `kdotool`) não dá para saber — e o Jarvis diz isso em vez de chutar."""
    if n.janelas is None:
        raise ComandoIndisponivel(
            "não consigo ver as janelas nesta sessão: no Wayland do KDE, instale o kdotool"
        )
    return foco_para_o_modelo(n.janelas)


def _focar(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    """Pelo nome (o código escolhe na lista real) ou pelo `janela_id` que uma lista deu — o do
    acompanhamento de foco (ADR-0037) ou o do `window.list`."""
    janela_id = str(a.get("janela_id") or "")
    if n.janelas is not None:
        return focar(n.janelas, str(a["app"]), janela_id)
    if janela_id:
        raise ComandoIndisponivel(
            "nesta sessão não há como focar uma janela pelo id (no Wayland do KDE, instale o "
            "kdotool)"
        )
    return desktop.focar(n.lancar, str(a["app"]))


def _area_write(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    try:
        n.anterior_da_area = desktop.ler_area(n.lancar, n.ambiente)[: desktop.LIMITE_DE_ESCRITA]
    except Exception:  # sem leitura (imagem, vazia): o desfazer devolve área vazia, não falha
        n.anterior_da_area = ""
    return desktop.escrever_area(n.lancar, str(a["texto"]), n.ambiente)


def _tela(n: Nativas) -> PortaDaTela:
    if n.tela is None:
        raise TelaIndisponivel("a tela só existe com a janela do Jarvis aberta")
    return n.tela


def _tela_mostrar(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    exibicao = _tela(n).mostrar(
        str(a["html"]), titulo=str(a.get("titulo", "")), identificador=str(a.get("id", ""))
    )
    return {
        "id": exibicao.id,
        "titulo": exibicao.titulo,
        "caracteres": exibicao.caracteres,
        "removidos": list(exibicao.removidos),
        "fundo": exibicao.fundo,
    }


def _tela_ler(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    exibicao = _tela(n).ler(str(a.get("id", "")))
    return {"id": exibicao.id, "titulo": exibicao.titulo, "html": exibicao.html}


def _tela_fechar(n: Nativas, a: Mapping[str, Any]) -> dict[str, Any]:
    fechadas = _tela(n).fechar(str(a.get("id", "")), todas=bool(a.get("todas", False)))
    return {"fechadas": fechadas}


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
    "window.list": _janelas,
    "window.focused": _em_foco,
    "window.focus_app": _focar,
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
    "web.ler": _web_ler,
    "tela.mostrar": _tela_mostrar,
    "tela.ler": _tela_ler,
    "tela.fechar": _tela_fechar,
}
"""`tool_id` → corpo. O que está aqui é "ligado" no executor; `timer.*` só com agenda, `tela.*` só
com a janela."""

PRECISAM_DE_AGENDA: Final = frozenset({"timer.alarm.set", "timer.alarm.list", "timer.alarm.cancel"})
PRECISAM_DA_TELA: Final = frozenset({"tela.mostrar", "tela.ler", "tela.fechar"})
DE_ARQUIVOS: Final = frozenset({"files.create_dir", "files.copy", "files.move"})
"""Corpos que precisam do grant e do descritor da raiz: ficam no executor, via `Organizador`."""
