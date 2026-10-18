"""Corpus textual sintético de regressão para pronúncia aproximada de aplicativos.

As linhas são transcrições previstas/observadas, não áudio: por isso são rápidas, determinísticas
e rodam sem microfone, rede ou o peso do Whisper. O roteiro de medição em
``docs/medicoes/f1-17-pronuncia-apps.md`` descreve como substituí-las por áudio TTS + ASR local.
"""

from __future__ import annotations

from jarvis.apps.medicao import CasoDePronuncia

CASOS_SINTETICOS: tuple[CasoDePronuncia, ...] = (
    CasoDePronuncia("discórdi", "discord"),
    CasoDePronuncia("discorde", "discord"),
    CasoDePronuncia("abre o discórdi", "discord"),
    CasoDePronuncia("espótifai", "spotify"),
    CasoDePronuncia("spotifai", "spotify"),
    CasoDePronuncia("abre o spotify", "spotify"),
    CasoDePronuncia("vi esse côdi", "vscode"),
    CasoDePronuncia("visual studio code", "vscode"),
    CasoDePronuncia("abre o vs code", "vscode"),
    CasoDePronuncia("cróme", "chrome"),
    CasoDePronuncia("google crômi", "chrome"),
    CasoDePronuncia("abre o chrome", "chrome"),
    CasoDePronuncia("brêive", "brave"),
    CasoDePronuncia("brave browser", "brave"),
    CasoDePronuncia("obisídian", "obsidian"),
    CasoDePronuncia("abre o obsidian", "obsidian"),
    CasoDePronuncia("tim speak", "teamspeak"),
    CasoDePronuncia("team speak", "teamspeak"),
    # Negativos: não podem abrir um app só porque há alguma consonante em comum.
    CasoDePronuncia("planilha galáctica", None),
    CasoDePronuncia("abre a calculadora", None),
    CasoDePronuncia("mensagem para a Bia", None),
)
