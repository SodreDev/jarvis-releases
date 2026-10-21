"""O trabalhador do OmniVoice, rodando de verdade, contra uma biblioteca de mentira (ADR-0039).

Nenhum PyTorch, nenhum peso: `omnivoice_falso` põe um `torch` e um `omnivoice` falsos no
`PYTHONPATH` do processo. O que se prova é o contrato que o motor do Jarvis usa — o
enquadramento, a ordem `ola → pronto → voz → áudio`, os erros que chegam como mensagem (sem GPU,
sem memória, síntese que falha) e o stdout que só leva protocolo.
"""

from __future__ import annotations

import io
import json
import os
import struct
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tools import omnivoice_trabalhador as trabalhador

from tests.unit.voz.omnivoice_falso import criar_bibliotecas_falsas

TRABALHADOR = Path(trabalhador.__file__)


@pytest.fixture
def falsos(tmp_path: Path) -> Path:
    return criar_bibliotecas_falsas(tmp_path / "falsos")


@pytest.fixture
def pesos(tmp_path: Path) -> Path:
    pasta = tmp_path / "pesos" / "c5fdb5ccb189"
    pasta.mkdir(parents=True)
    return pasta


def processo(falsos: Path, *argv: str, **extra: str) -> subprocess.Popen[bytes]:
    """O trabalhador de verdade, com as bibliotecas falsas na frente do `sys.path`."""
    limpo = {k: v for k, v in os.environ.items() if not k.startswith("FALSO_")}
    ambiente = {**limpo, "PYTHONPATH": str(falsos), **extra}
    return subprocess.Popen(
        [sys.executable, str(TRABALHADOR), *argv],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=ambiente,
    )


def enviar(proc: subprocess.Popen[bytes], pedido: dict[str, Any]) -> None:
    assert proc.stdin is not None
    trabalhador.escrever(proc.stdin, pedido)  # type: ignore[arg-type]


def receber(proc: subprocess.Popen[bytes]) -> tuple[dict[str, Any], bytes]:
    assert proc.stdout is not None
    cabecalho = trabalhador.ler(proc.stdout)  # type: ignore[arg-type]
    assert cabecalho is not None, "o trabalhador fechou o canal"
    corpo = proc.stdout.read(int(cabecalho.get("bytes", 0))) if cabecalho.get("bytes") else b""
    return cabecalho, corpo


@pytest.fixture
def servindo(falsos: Path, pesos: Path) -> Iterator[subprocess.Popen[bytes]]:
    proc = processo(falsos, "--pesos", str(pesos), "--dispositivo", "cpu")
    yield proc
    if proc.poll() is None:
        proc.kill()
    proc.wait(timeout=10)
    for canal in (proc.stdin, proc.stdout, proc.stderr):
        if canal is not None:
            canal.close()


def referencia(tmp_path: Path) -> Path:
    arquivo = tmp_path / "ref.wav"
    arquivo.write_bytes(b"RIFF de mentira")
    return arquivo


# --- verificar ------------------------------------------------------------------------------


def test_verificar_diz_versoes_e_dispositivo_sem_carregar_modelo(falsos: Path) -> None:
    proc = processo(falsos, "--verificar", "--dispositivo", "cpu")
    saida, erro = proc.communicate(timeout=30)
    assert proc.returncode == 0
    relatorio = json.loads(saida)  # o stdout tem SÓ o JSON: o ruído da biblioteca foi para o stderr
    assert relatorio["protocolo"] == trabalhador.PROTOCOLO
    assert relatorio["versoes"]["omnivoice"] == "0.2.1"
    assert relatorio["versoes"]["torch"] == "2.8.0+cpu"
    assert relatorio["dispositivo_ok"] is True
    assert "ruído que a biblioteca imprime" in erro.decode("utf-8")


def test_verificar_cuda_sem_gpu_responde_que_nao_ve(falsos: Path) -> None:
    proc = processo(falsos, "--verificar", "--dispositivo", "cuda")
    saida, _ = proc.communicate(timeout=30)
    relatorio = json.loads(saida)
    assert relatorio["cuda"] is False and relatorio["dispositivo_ok"] is False


def test_verificar_cuda_com_gpu(falsos: Path) -> None:
    proc = processo(falsos, "--verificar", "--dispositivo", "cuda", FALSO_CUDA="1")
    saida, _ = proc.communicate(timeout=30)
    relatorio = json.loads(saida)
    assert relatorio["dispositivo_ok"] is True and relatorio["gpu"] == "GPU de mentira"


# --- servir ---------------------------------------------------------------------------------


def test_ola_pronto_voz_audio_e_sair(servindo: subprocess.Popen[bytes], tmp_path: Path) -> None:
    ola, _ = receber(servindo)
    assert ola == {"tipo": "ola", "protocolo": trabalhador.PROTOCOLO}
    pronto, _ = receber(servindo)
    assert pronto["tipo"] == "pronto" and pronto["taxa"] == 24_000
    assert pronto["dispositivo"] == "cpu"

    enviar(servindo, {"op": "voz", "id": 1, "audio": str(referencia(tmp_path)), "texto": "oi"})
    assert receber(servindo)[0] == {"tipo": "voz", "id": 1}

    texto = "Bom dia, tudo certo por aqui."
    enviar(servindo, {"op": "sintetizar", "id": 2, "texto": texto, "idioma": "pt"})
    cabecalho, corpo = receber(servindo)
    assert cabecalho["tipo"] == "audio" and cabecalho["id"] == 2
    assert cabecalho["amostras"] == 240 * len(texto)
    audio = np.frombuffer(corpo, dtype="<f4")
    assert audio.size == cabecalho["amostras"] and float(np.abs(audio).max()) > 0.1

    enviar(servindo, {"op": "sair"})
    assert servindo.wait(timeout=10) == 0


def test_o_texto_falado_nao_vai_para_o_stderr(
    servindo: subprocess.Popen[bytes], tmp_path: Path
) -> None:
    receber(servindo)
    receber(servindo)
    enviar(servindo, {"op": "voz", "id": 1, "audio": str(referencia(tmp_path)), "texto": "oi"})
    receber(servindo)
    segredo = "a senha do cofre é tucano azul 4471"
    enviar(servindo, {"op": "sintetizar", "id": 2, "texto": segredo})
    receber(servindo)
    enviar(servindo, {"op": "sair"})
    servindo.wait(timeout=10)
    assert servindo.stderr is not None
    assert "tucano" not in servindo.stderr.read().decode("utf-8")


def test_erro_de_sintese_vira_mensagem_e_o_trabalhador_segue(
    servindo: subprocess.Popen[bytes], tmp_path: Path
) -> None:
    receber(servindo)
    receber(servindo)
    enviar(servindo, {"op": "voz", "id": 1, "audio": str(referencia(tmp_path)), "texto": "oi"})
    receber(servindo)
    enviar(servindo, {"op": "sintetizar", "id": 2, "texto": "isto explode"})
    erro, _ = receber(servindo)
    assert erro["tipo"] == "erro" and erro["motivo"] == "sintese" and erro["id"] == 2
    enviar(servindo, {"op": "sintetizar", "id": 3, "texto": "e isto não"})
    assert receber(servindo)[0]["tipo"] == "audio"


def test_sintetizar_sem_voz_e_voz_ausente_sao_recusados(
    servindo: subprocess.Popen[bytes], tmp_path: Path
) -> None:
    receber(servindo)
    receber(servindo)
    enviar(servindo, {"op": "sintetizar", "id": 1, "texto": "sem voz ainda"})
    assert receber(servindo)[0]["motivo"] == "pedido"
    enviar(servindo, {"op": "voz", "id": 2, "audio": str(tmp_path / "nao.wav"), "texto": "x"})
    erro, _ = receber(servindo)
    assert erro["motivo"] == "voz" and erro["id"] == 2


def test_fim_da_entrada_encerra_limpo(servindo: subprocess.Popen[bytes]) -> None:
    receber(servindo)
    receber(servindo)
    assert servindo.stdin is not None
    servindo.stdin.close()
    assert servindo.wait(timeout=10) == 0


def test_enquadramento_quebrado_encerra_dizendo_por_que(servindo: subprocess.Popen[bytes]) -> None:
    receber(servindo)
    receber(servindo)
    assert servindo.stdin is not None
    servindo.stdin.write(struct.pack(">I", trabalhador.LIMITE_DO_PEDIDO + 1))
    servindo.stdin.flush()
    erro, _ = receber(servindo)
    assert erro["tipo"] == "erro" and erro["motivo"] == "pedido"
    assert servindo.wait(timeout=10) == 5


@pytest.mark.parametrize(
    ("ambiente", "dispositivo", "motivo", "codigo"),
    [
        ({}, "cuda", "sem_gpu", 3),
        ({"FALSO_CARGA": "memoria", "FALSO_CUDA": "1"}, "cuda", "sem_gpu", 4),
        ({"FALSO_CARGA": "quebrada"}, "cpu", "carga", 4),
    ],
)
def test_sem_gpu_ou_carga_que_falha_chegam_como_mensagem(
    falsos: Path, pesos: Path, ambiente: dict[str, str], dispositivo: str, motivo: str, codigo: int
) -> None:
    proc = processo(falsos, "--pesos", str(pesos), "--dispositivo", dispositivo, **ambiente)
    saida, _ = proc.communicate(timeout=30)
    canal = io.BytesIO(saida)
    assert trabalhador.ler(canal) == {"tipo": "ola", "protocolo": trabalhador.PROTOCOLO}
    erro = trabalhador.ler(canal)
    assert erro is not None and erro["tipo"] == "erro" and erro["motivo"] == motivo
    assert proc.returncode == codigo


def test_sem_a_biblioteca_a_carga_falha_com_frase(tmp_path: Path, pesos: Path) -> None:
    """O venv quebrado (sem `omnivoice`) não vira silêncio: vira `erro/carga`."""
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    proc = processo(vazio, "--pesos", str(pesos), "--dispositivo", "cpu")
    saida, _ = proc.communicate(timeout=30)
    canal = io.BytesIO(saida)
    trabalhador.ler(canal)
    erro = trabalhador.ler(canal)
    assert erro is not None and erro["motivo"] == "carga"
    assert erro["detalhe"].startswith("ModuleNotFoundError")
    assert proc.returncode == 4
