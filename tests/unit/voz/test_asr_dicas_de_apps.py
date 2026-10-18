"""O resolvedor de apps chega à voz (dono, 2026-10-18): os nomes dos apps instalados vão ao ASR
local como dicas (`hotwords`/`initial_prompt`), para o nome em inglês não virar outra palavra.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.voz import app as modulo_app
from jarvis.voz.config import Configuracao


class WhisperGravador:
    """Guarda como o laço o montou, sem carregar modelo nenhum."""

    ultimo: WhisperGravador | None = None

    def __init__(self, **campos: Any) -> None:
        self.campos = campos
        WhisperGravador.ultimo = self

    def abrir(self) -> None:
        return None


def test_o_asr_local_recebe_a_palavra_de_ativacao_e_os_nomes_dos_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo_app, "MotorWhisper", WhisperGravador)
    monkeypatch.setattr(modulo_app, "o_que_falta", lambda *a, **k: "")

    modulo_app.motor_de_asr(
        Configuracao(asr="asr-whisper-local", palavra="jarvis"),
        raiz=tmp_path,
        cancelado=lambda: False,
        dicas_apps=["Discord", "Brave Web Browser", "discord"],
    )

    gravado = WhisperGravador.ultimo
    assert gravado is not None
    dicas = gravado.campos["dicas"]
    assert dicas.split(", ")[0] == "jarvis", "a palavra de ativação continua primeiro"
    assert "Discord" in dicas and "Brave Web Browser" in dicas
    assert dicas.count("iscord") == 1, "sem repetir o que só difere na caixa"


def test_o_laco_junta_os_apps_instalados_para_a_dica(tmp_path: Path) -> None:
    laco = modulo_app.Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        raiz=tmp_path,
    )

    nomes = laco._nomes_dos_apps()

    assert all(isinstance(n, str) for n in nomes)
