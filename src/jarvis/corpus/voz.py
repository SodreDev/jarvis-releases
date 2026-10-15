"""As duas vozes do corpus sintético: paramétrica e piper-ONNX (cartão F1-02).

**Cadeia de licença, verificada na origem (ADR-0012):**

- a voz é `rhasspy/piper-voices` → `pt/pt_BR/faber/medium` — repositório **MIT**, *dataset* do
  MODEL_CARD **CC0** (`https://github.com/OHF-Voice/voice-datasets`). Voz verificada **voz por
  voz**: `cadu`, `faber` e `jeff` têm dataset CC0; `edresson` é CC BY 4.0 (atribuição) e por
  isso não foi escolhida;
- a inferência é `onnxruntime` (**MIT**) lendo o `.onnx` da voz. **Não** usamos o pacote
  `piper-tts` do PyPI: ele é **GPL-3.0-or-later** (a reescrita `piper1-gpl` liga o espeak-ng), e
  copyleft forte no caminho do produto é contaminação que a porta de licença agora recusa;
- o fonemizador é o binário de sistema `espeak-ng` (**GPL-3.0**), registrado em
  `licenses/ferramentas-externas.toml` como `fora_do_produto`: ele roda **só** na geração do
  corpus, em processo separado, e nunca é ligado ao produto. O áudio gerado é dado, não obra
  derivada do programa.

**Determinismo.** A inferência VITS tem ruído interno, e `onnxruntime.set_seed` só vale na
criação da sessão — então com uma sessão compartilhada a mesma frase saía diferente. A síntese
do corpus roda com `noise_scale = 0` e `noise_w = 0`: sem ruído, sem RNG, byte a byte igual em
toda execução. A variação de prosódia que sobra é o **ritmo** (`length_scale` sorteado por item
a partir da semente), que é entrada do modelo e não RNG. Custo declarado: a voz fica menos
expressiva do que a do piper padrão — mais uma razão pela qual sintético não fecha SLO-4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from random import Random
from typing import Any, Final, Protocol

from jarvis.audio_io.quadro import TAXA_PADRAO
from jarvis.audio_io.sintese import fala_simulada

PASTA_VOZES_PADRAO: Final = Path.home() / ".cache" / "jarvis" / "vozes"
VOZ_PADRAO: Final = "pt_BR-faber-medium"
LICENCA_VOZ_PADRAO: Final = "MIT (repositório rhasspy/piper-voices) / CC0 (dataset faber)"
URL_VOZ: Final = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/"
RITMO_MINIMO: Final = 0.92
RITMO_MAXIMO: Final = 1.12


class VozIndisponivel(RuntimeError):
    """Falta o modelo da voz ou o fonemizador. A mensagem diz exatamente o que fazer."""


class Voz(Protocol):
    """Texto em pt-BR → PCM16 mono 16 kHz, determinístico por (texto, semente).

    `nome` é o gerador (vai para o campo `gerador` do rótulo), `voz` é a voz escolhida e
    `licenca` é a licença dela — os três ficam **no rótulo de cada item**, para ninguém ter
    de adivinhar depois com o que o número foi medido.
    """

    nome: str
    voz: str
    licenca: str

    def falar(self, texto: str, *, semente: int) -> bytes: ...


@dataclass(slots=True)
class VozParametrica:
    """Sem modelo e sem rede: fala **simulada** com duração estimada pelas sílabas.

    Serve para o CI provar o encanamento do gerador (determinismo, rótulos, split) sem baixar
    nada. **Não tem fonema**, então não serve para medir ASR nem detector semântico — quem
    publicar número com esta voz tem de dizer o nome dela.
    """

    nome: str = "parametrico@1"
    voz: str = "parametrico"
    licenca: str = "não se aplica (gerador do próprio repositório, Apache-2.0)"
    ms_por_silaba: float = 180.0

    def falar(self, texto: str, *, semente: int) -> bytes:
        silabas = max(1, sum(1 for letra in texto.lower() if letra in "aeiouáéíóúâêôãõà"))
        aleatorio = Random(semente)  # noqa: S311 — áudio de teste, não criptografia
        duracao = silabas * self.ms_por_silaba * aleatorio.uniform(RITMO_MINIMO, RITMO_MAXIMO)
        return fala_simulada(duracao, aleatorio=aleatorio, taxa=TAXA_PADRAO)


def reamostrar(sinal: Any, *, de: int, para: int, taps: int = 16) -> Any:
    """Reamostragem por sinc janelado (Hann), determinística e sem dependência nova.

    A voz do piper sai a 22 050 Hz e o caminho de captura do projeto é 16 000 Hz; reamostrar
    é obrigatório e não pode ser "pegar uma amostra a cada tantas" (isso traz *aliasing* para
    dentro do corpus que vai medir detector de turno).
    """
    import numpy as np

    if de == para:
        return sinal
    razao = para / de
    n_saida = math.floor(len(sinal) * razao)
    posicoes = np.arange(n_saida, dtype=np.float64) / razao
    base = np.floor(posicoes).astype(np.int64)
    deslocamentos = np.arange(-taps + 1, taps + 1, dtype=np.int64)
    indices = base[:, None] + deslocamentos[None, :]
    distancias = posicoes[:, None] - indices
    corte = min(1.0, razao)  # anti-aliasing quando a taxa cai
    janela = 0.5 * (1.0 + np.cos(np.pi * distancias / taps))
    janela[np.abs(distancias) >= taps] = 0.0
    nucleo = corte * np.sinc(corte * distancias) * janela
    soma = nucleo.sum(axis=1, keepdims=True)
    nucleo = np.divide(nucleo, soma, out=np.zeros_like(nucleo), where=soma != 0)
    amostras = sinal[np.clip(indices, 0, len(sinal) - 1)]
    return (amostras * nucleo).sum(axis=1)
