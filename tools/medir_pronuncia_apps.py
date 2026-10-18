"""Mede o corpus textual de pronúncia aproximada, sem ASR, TTS, rede ou microfone.

Uso: ``uv run --frozen python tools/medir_pronuncia_apps.py``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from jarvis.apps.corpus import CASOS_SINTETICOS
from jarvis.apps.medicao import MetricasDePronuncia, medir
from jarvis.apps.resolvedor import ResolvedorDeApps
from jarvis.executor.lancador import App


def _app(identificador: str, nome: str) -> App:
    return App(
        id=identificador,
        nome=nome,
        nomes=(nome, identificador),
        argv=(identificador,),
        arquivo=Path(),
        exec_nome=identificador,
    )


def catalogo_de_referencia() -> tuple[App, ...]:
    """Os nomes instalados fictícios usados no corpus; o produto usa o catálogo real."""
    return (
        _app("discord", "Discord"),
        _app("spotify", "Spotify"),
        _app("vscode", "Visual Studio Code"),
        _app("chrome", "Google Chrome"),
        _app("brave", "Brave Web Browser"),
        _app("obsidian", "Obsidian"),
        _app("teamspeak", "TeamSpeak"),
    )


def medir_corpus() -> MetricasDePronuncia:
    return medir(CASOS_SINTETICOS, ResolvedorDeApps(catalogo_de_referencia()))


def main(argv: Sequence[str] | None = None) -> int:
    if argv:
        raise ValueError("esta medição não recebe argumentos")
    metricas = medir_corpus()
    print(
        json.dumps(
            {
                "total": metricas.total,
                "com_referencia": metricas.com_referencia,
                "top_1": metricas.top_1,
                "top_3": metricas.top_3,
                "falso_aceite": metricas.falso_aceite,
                "taxa_top_1": metricas.taxa_top_1,
                "taxa_top_3": metricas.taxa_top_3,
                "taxa_falso_aceite": metricas.taxa_falso_aceite,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
