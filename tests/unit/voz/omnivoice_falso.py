"""Um `omnivoice` e um `torch` de mentira, para o trabalhador rodar de verdade sem 3 GB de pesos.

Nada aqui imita qualidade de voz: o "modelo" devolve uma senoide de 10 ms por caractere, a
24 kHz, como `OmniVoice.generate` devolve `list[np.ndarray]`. O que estes falsos exercitam é o
**contrato** — carregar de uma pasta, criar o prompt de voz, gerar, falhar do jeito que a
biblioteca falha (sem GPU, sem memória, erro de síntese) — e o enquadramento do protocolo.

Variáveis de ambiente que mudam o comportamento (o teste as põe no processo do trabalhador):
`FALSO_CUDA=1` (há GPU), `FALSO_CARGA=memoria|quebrada` (a carga falha), `FALSO_DORMIR=s`
(cada síntese demora), e o texto `explode` faz a síntese falhar.
"""

from __future__ import annotations

from pathlib import Path

TORCH = """
import os

__version__ = "2.8.0+cpu"
float16 = "float16"
float32 = "float32"


class _Cuda:
    @staticmethod
    def is_available():
        return os.environ.get("FALSO_CUDA") == "1"

    @staticmethod
    def get_device_name(indice):
        return "GPU de mentira"


class _Mps:
    @staticmethod
    def is_available():
        return False


class _Backends:
    mps = _Mps()


cuda = _Cuda()
backends = _Backends()
"""

OMNIVOICE = """
import os
import time

import numpy as np

print("ruído que a biblioteca imprime no stdout ao importar")

__version__ = "0.2.1"


class OmniVoice:
    sampling_rate = 24000

    @classmethod
    def from_pretrained(cls, caminho, device_map=None, dtype=None):
        falha = os.environ.get("FALSO_CARGA", "")
        if falha == "memoria":
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        if falha == "quebrada":
            raise OSError("safetensors corrompido")
        if not os.path.isdir(caminho):
            raise OSError("não há pesos nessa pasta")
        modelo = cls()
        modelo.device_map = device_map
        modelo.dtype = dtype
        return modelo

    def create_voice_clone_prompt(self, ref_audio, ref_text=None):
        if not os.path.isfile(ref_audio):
            raise FileNotFoundError("referência ausente")
        return {"audio": ref_audio, "texto": ref_text}

    def generate(self, text, language=None, voice_clone_prompt=None, **kwargs):
        if "explode" in text:
            raise RuntimeError("falha de síntese de mentira")
        time.sleep(float(os.environ.get("FALSO_DORMIR", "0")))
        n = 240 * max(1, len(text))
        t = np.arange(n, dtype=np.float32) / 24000
        return [(0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)]
"""

VERSOES = {
    "omnivoice": "0.2.1",
    "torch": "2.8.0+cpu",
    "torchaudio": "2.8.0+cpu",
    "transformers": "5.3.0",
}


def criar_bibliotecas_falsas(pasta: Path) -> Path:
    """Escreve `torch/`, `omnivoice/` e os `.dist-info` numa pasta para pôr no `PYTHONPATH`."""
    (pasta / "torch").mkdir(parents=True, exist_ok=True)
    (pasta / "torch" / "__init__.py").write_text(TORCH, encoding="utf-8")
    (pasta / "omnivoice").mkdir(exist_ok=True)
    (pasta / "omnivoice" / "__init__.py").write_text(OMNIVOICE, encoding="utf-8")
    for nome, versao in VERSOES.items():
        info = pasta / f"{nome}-{versao}.dist-info"
        info.mkdir(exist_ok=True)
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {nome}\nVersion: {versao}\n", encoding="utf-8"
        )
    return pasta
