"""O whisper local escolhe a placa de vídeo e volta à CPU sozinho (ADR-0067).

Com runtime falso (`faster_whisper` e `ctranslate2` de mentira): nenhum modelo carrega, nenhuma
placa é tocada. O caso desta máquina é o do meio — a GPU aparece, mas falta a libcublas.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from jarvis.agentd.asr import MODELO_NA_CPU, MODELO_NA_PLACA, TAMANHO_AUTOMATICO, MotorWhisper


class _Modelo:
    def __init__(self, dispositivo: str, falha: bool) -> None:
        self.dispositivo = dispositivo
        self.falha = falha

    def transcribe(self, _audio: object, **_opcoes: object) -> tuple[list[object], None]:
        if self.falha:
            raise RuntimeError("Library libcublas.so.12 is not found or cannot be loaded")
        return [], None


def _runtime_falso(
    monkeypatch: pytest.MonkeyPatch, *, placas: int, cuda_quebra: bool
) -> list[dict[str, Any]]:
    criados: list[dict[str, Any]] = []

    def whisper_model(tamanho: str, **opcoes: Any) -> _Modelo:
        criados.append({"tamanho": tamanho, **opcoes})
        return _Modelo(opcoes["device"], opcoes["device"] == "cuda" and cuda_quebra)

    faster = types.ModuleType("faster_whisper")
    faster.WhisperModel = whisper_model  # type: ignore[attr-defined]
    ct2 = types.ModuleType("ctranslate2")
    ct2.get_cuda_device_count = lambda: placas  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", faster)
    monkeypatch.setitem(sys.modules, "ctranslate2", ct2)
    return criados


def test_com_a_placa_pronta_o_whisper_roda_nela_em_float16(monkeypatch: pytest.MonkeyPatch) -> None:
    criados = _runtime_falso(monkeypatch, placas=1, cuda_quebra=False)
    motor = MotorWhisper(tamanho="large-v3-turbo")
    motor.abrir()
    assert motor.em_uso == "cuda/float16"
    assert [(c["device"], c["compute_type"]) for c in criados] == [("cuda", "float16")]


def test_sem_a_cublas_a_placa_falha_na_conta_de_teste_e_volta_a_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A falta da libcublas só aparece na primeira conta, não ao carregar — caso desta máquina."""
    criados = _runtime_falso(monkeypatch, placas=1, cuda_quebra=True)
    motor = MotorWhisper()
    motor.abrir()
    assert motor.em_uso == "cpu/int8"
    assert [c["device"] for c in criados] == ["cuda", "cpu"]


def test_sem_placa_vai_direto_a_cpu_e_cuda_forcado_nao_esconde_o_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    criados = _runtime_falso(monkeypatch, placas=0, cuda_quebra=False)
    motor = MotorWhisper()
    motor.abrir()
    assert motor.em_uso == "cpu/int8"
    assert [c["device"] for c in criados] == ["cpu"]

    _runtime_falso(monkeypatch, placas=1, cuda_quebra=True)
    with pytest.raises(RuntimeError, match="libcublas"):
        MotorWhisper(dispositivo="cuda").abrir()


def test_auto_e_o_turbo_na_placa_e_o_modelo_da_cpu_sem_ela(monkeypatch: pytest.MonkeyPatch) -> None:
    """`modelo_do_asr = "auto"`: o relatório diz o tamanho que carregou, não «auto»."""
    criados = _runtime_falso(monkeypatch, placas=1, cuda_quebra=False)
    na_placa = MotorWhisper(tamanho=TAMANHO_AUTOMATICO)
    na_placa.abrir()
    assert (criados[-1]["tamanho"], na_placa.tamanho) == (MODELO_NA_PLACA, MODELO_NA_PLACA)
    assert na_placa.nome == f"faster-whisper@{MODELO_NA_PLACA}"

    criados = _runtime_falso(monkeypatch, placas=1, cuda_quebra=True)
    na_cpu = MotorWhisper(tamanho=TAMANHO_AUTOMATICO)
    na_cpu.abrir()
    assert [c["tamanho"] for c in criados] == [MODELO_NA_PLACA, MODELO_NA_CPU]
    assert (na_cpu.tamanho, na_cpu.em_uso) == (MODELO_NA_CPU, "cpu/int8")


def test_tamanho_escolhido_a_mao_vale_nos_dois(monkeypatch: pytest.MonkeyPatch) -> None:
    criados = _runtime_falso(monkeypatch, placas=1, cuda_quebra=True)
    motor = MotorWhisper(tamanho="medium")
    motor.abrir()
    assert [c["tamanho"] for c in criados] == ["medium", "medium"]
    assert motor.nome == "faster-whisper@medium"
