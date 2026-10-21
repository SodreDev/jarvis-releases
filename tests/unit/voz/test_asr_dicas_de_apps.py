"""A dica do ASR é curta (ADR-0043): a palavra de ativação e os termos do dono, nos dois motores.

Antes, os nomes de todos os apps instalados iam ao ASR local como `hotwords` e `initial_prompt`
(pedido do dono, 2026-10-18: "abre o Discord" virava "abre o disco"). Medido com áudio sintético,
essa lista fazia todo ruído forçado no whisper virar nome de app; ela saiu. Quem casa a fala com
o app continua sendo o resolvedor de `jarvis.apps`, contra o catálogo, depois do ASR.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.voz import app as modulo_app
from jarvis.voz.config import Configuracao
from jarvis.voz.dica import LIMITE_DE_CARACTERES, LIMITE_DE_TERMOS, dica_do_asr


class WhisperGravador:
    """Guarda como o laço o montou, sem carregar modelo nenhum."""

    ultimo: WhisperGravador | None = None

    def __init__(self, **campos: Any) -> None:
        self.campos = campos
        WhisperGravador.ultimo = self

    def abrir(self) -> None:
        return None


def test_o_asr_local_recebe_a_dica_curta_e_nao_a_lista_de_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(modulo_app, "MotorWhisper", WhisperGravador)
    monkeypatch.setattr(modulo_app, "o_que_falta", lambda *a, **k: "")

    modulo_app.motor_de_asr(
        Configuracao(asr="asr-whisper-local", palavra="jarvis"),
        raiz=tmp_path,
        cancelado=lambda: False,
        dica="Jarvis, Thiago Nigro.",
    )

    gravado = WhisperGravador.ultimo
    assert gravado is not None
    assert gravado.campos["dica"] == "Jarvis, Thiago Nigro."
    assert "dicas" not in gravado.campos


def test_o_laco_monta_a_dica_pela_palavra_de_ativacao(tmp_path: Path) -> None:
    laco = modulo_app.Aplicativo(
        configuracao=Configuracao(asr="asr-whisper-local", tts="tts-parametrico", s2="eco"),
        raiz=tmp_path,
    )
    assert laco._dica_do_asr() == "Jarvis."


def test_a_dica_poe_a_palavra_primeiro_com_inicial_e_sem_repetir() -> None:
    dica = dica_do_asr("jarvis", ["Thiago Nigro", "teamspeak", "TeamSpeak", "JARVIS", "OBS Studio"])
    assert dica == "Jarvis, Thiago Nigro, Teamspeak, OBS Studio."


def test_a_dica_respeita_o_orcamento() -> None:
    muitos = [f"termo{i}" for i in range(50)]
    dica = dica_do_asr("jarvis", muitos)
    assert dica.count(",") + 1 <= LIMITE_DE_TERMOS
    assert len(dica) <= LIMITE_DE_CARACTERES
    longos = ["x" * 90, "y" * 90, "z" * 90]
    assert len(dica_do_asr("jarvis", longos)) <= LIMITE_DE_CARACTERES


def test_sem_palavra_nem_termo_nao_ha_dica() -> None:
    assert dica_do_asr("", ["", "  "]) == ""
