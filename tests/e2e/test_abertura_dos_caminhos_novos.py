"""A abertura robusta cobre os caminhos que a ADR-0070 pôs em threads (rodada final, 2026-11-15).

O agente monitor das redes roda numa thread própria (`jarvis-agente-monitor`), cada subagente na
dele, e a delegação ao Claude Code lê o stream noutra. Uma exceção solta numa delas não pode sumir
calada: o gancho da abertura (`jarvis.gui.abertura.instalar_ganchos`) a leva ao `abertura.log`, com
o traceback e sem segredo. Aqui, num arquivo da pasta do teste (nunca o do dono).
"""

from __future__ import annotations

import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from jarvis.gui import abertura


@pytest.fixture
def log(tmp_path: Path) -> Iterator[Path]:
    original, original_da_thread = sys.excepthook, threading.excepthook
    caminho = abertura.ligar(tmp_path / "estado" / abertura.NOME_DO_LOG)
    assert caminho is not None
    abertura.instalar_ganchos()
    try:
        yield caminho
    finally:
        abertura.desligar()
        sys.excepthook, threading.excepthook = original, original_da_thread


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
@pytest.mark.parametrize(
    "nome", ["jarvis-agente-monitor", "jarvis-tarefa-t-0001", "jarvis-delegacao-leitor"]
)
def test_excecao_numa_thread_de_trabalho_vai_ao_log_da_abertura(log: Path, nome: str) -> None:
    def quebrar() -> None:
        raise RuntimeError("o modelo do agente caiu no meio")

    thread = threading.Thread(target=quebrar, name=nome, daemon=True)
    thread.start()
    thread.join(5.0)

    texto = log.read_text("utf-8")
    assert f"exceção na thread {nome}" in texto
    assert "RuntimeError: o modelo do agente caiu no meio" in texto
    assert "Traceback" in texto


def test_o_log_da_abertura_nao_leva_segredo(log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    segredo = "sk-or-v1-" + "a" * 48
    monkeypatch.setenv("OPENROUTER_API_KEY", segredo)
    abertura.registrar_na_abertura(f"o motor recusou a chave {segredo}")
    assert segredo not in log.read_text("utf-8")
