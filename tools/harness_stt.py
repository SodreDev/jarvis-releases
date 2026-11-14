"""Harness do STT em pt-BR (ADR-0067): qual configuração do whisper local ouve «mãe», «WhatsApp».

Uso (precisa do grupo `asr`, dos pesos no cache do Hugging Face, da voz piper e do espeak-ng):

    nice -n 19 uv run --frozen python -m tools.harness_stt                    # todas as configs
    nice -n 19 uv run --frozen python -m tools.harness_stt --configs small-b1-atual,small-b5-frase

Só áudio **sintético**: a voz piper com fonemas do espeak-ng (GPL, só em `tools/`), em três
variações de ritmo, altura e fundo por frase, e os ruídos forçados do `harness_ruido` (o que vira
texto quando o trecho não tem fala). Nenhum microfone, nenhum áudio do dono, nenhuma rede, nenhuma
chave — a Groq não é medida aqui (ela recebe o mesmo `language` e a mesma dica que o local).

O texto que a voz sintetiza é a **pronúncia** brasileira ("uótsápi", "gê pê tê"); o esperado é a
grafia ("WhatsApp", "GPT"). Para cada configuração: WER médio, acerto do termo-chave (sem caixa e
sem acento: «mae» conta como «mãe», «Whats App» não conta como «WhatsApp»), quantos ruídos viraram
texto que passa no filtro de `jarvis.voz.ruido`, e o tempo do ASR. Escreve
`docs/medicoes/stt-pt-br.csv` e imprime o resumo que `docs/medicoes/stt-pt-br.md` cita.

**Ressalva:** voz sintética é material fácil (sem sotaque, sem sala). O número aqui ordena as
configurações; não é o WER na voz do dono.
"""

from __future__ import annotations

import argparse
import csv
import gc
import statistics
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from jarvis.agentd.asr import _cuda_visivel
from jarvis.agentd.tts import MotorPiperOnnx
from jarvis.corpus.metricas import wer
from jarvis.voz.dica import dica_do_asr
from jarvis.voz.interface import Sinais
from jarvis.voz.ruido import julgar_texto, palavras_da_dica
from jarvis.voz.vocabulario import dobrar
from tools.harness_ruido import SEMENTE, TAXA, cenas_de_ruido
from tools.harness_tts import PASTA_VOZES, VOZ_PIPER, fonemizar_com_espeak

RAIZ: Final = Path(__file__).resolve().parent.parent
SAIDA_PADRAO: Final = RAIZ / "docs" / "medicoes" / "stt-pt-br.csv"
TERMOS_FICTICIOS: Final = ("WhatsApp", "Discord", "Spotify", "Gemini", "GPT")
"""O vocabulário de exemplo que entra na dica — termos comuns, não os do dono."""


@dataclass(frozen=True, slots=True)
class Frase:
    esperado: str
    fala: str
    """O que a voz sintetiza: a pronúncia brasileira, não a grafia."""
    chave: str
    """O termo que tem de sair escrito (a comparação é sem caixa e sem acento)."""


FRASES: Final = (
    Frase("Mãe.", "Mãe.", "mãe"),
    Frase("Minha mãe.", "Minha mãe.", "mãe"),
    Frase("Abre o contato da minha mãe.", "Abre o contato da minha mãe.", "mãe"),
    Frase("Liga pra minha mãe.", "Liga pra minha mãe.", "mãe"),
    Frase("WhatsApp.", "Uótsápi.", "whatsapp"),
    Frase("Abre o WhatsApp.", "Abre o uótsápi.", "whatsapp"),
    Frase(
        "Manda mensagem no WhatsApp pra minha mãe.",
        "Manda mensagem no uótsápi pra minha mãe.",
        "whatsapp",
    ),
    Frase("Pergunta pro GPT.", "Pergunta pro gê pê tê.", "gpt"),
    Frase("Abre o ChatGPT.", "Abre o tchét gê pê tê.", "chatgpt"),
    Frase("Abre o Gemini.", "Abre o djêmini.", "gemini"),
    Frase("Abre o Discord.", "Abre o díscórd.", "discord"),
    Frase("Abre o Spotify.", "Abre o spótifai.", "spotify"),
    Frase("Jarvis, que horas são?", "Jarvis, que horas são?", "jarvis"),
    Frase("Fecha o Steam.", "Fecha o stím.", "steam"),
    Frase("Sim.", "Sim.", "sim"),
    Frase("Não.", "Não.", "não"),
)
VARIACOES: Final = (
    # (ritmo do piper, fator de altura, fundo em dB)
    (1.0, 1.0, -62.0),
    (0.85, 0.93, -50.0),
    (1.2, 1.07, -45.0),
)


@dataclass(frozen=True, slots=True)
class Config:
    nome: str
    modelo: str
    compute: str
    beam: int
    dica: str
    """`nenhuma`, `atual` (a lista de termos de hoje) ou `frase` (frase em pt-BR com os termos)."""
    opcoes: tuple[tuple[str, Any], ...] = ()


CONFIGS: Final = {
    c.nome: c
    for c in (
        Config("small-b1-atual", "small", "int8", 1, "atual"),
        Config("small-b1-nenhuma", "small", "int8", 1, "nenhuma"),
        Config("small-b5-atual", "small", "int8", 5, "atual"),
        Config("small-b5-frase", "small", "int8", 5, "frase"),
        Config("medium-b5-frase", "medium", "int8", 5, "frase"),
        Config("medium-b5-atual", "medium", "int8", 5, "atual"),
        Config("large-v3-b5-frase", "large-v3", "int8", 5, "frase"),
        Config("turbo-b5-frase", "large-v3-turbo", "int8", 5, "frase"),
        Config("turbo-b5-atual", "large-v3-turbo", "int8", 5, "atual"),
        Config("turbo-b1-frase", "large-v3-turbo", "int8", 1, "frase"),
        Config("turbo-b1-atual", "large-v3-turbo", "int8", 1, "atual"),
    )
}


def _pcm(sinal: np.ndarray) -> bytes:
    return bytes(np.clip(np.rint(sinal * 32767), -32768, 32767).astype("<i2").tobytes())


def _altura(voz: np.ndarray, fator: float) -> np.ndarray:
    """Reamostra (altura e duração juntas): uma voz mais grave ou mais aguda, sem dependência."""
    if fator == 1.0:
        return voz
    n = int(len(voz) / fator)
    resultado: np.ndarray = np.interp(np.arange(n) * fator, np.arange(len(voz)), voz)
    return resultado


def cenas_de_fala(
    rng: np.random.Generator, sintetizar: Callable[[str, float], bytes]
) -> list[tuple[str, Frase, bytes]]:
    """Cada frase nas três variações, com 400 ms antes e 1,3 s depois, como o laço a manda."""
    cenas = []
    for frase in FRASES:
        for i, (ritmo, fator, fundo) in enumerate(VARIACOES):
            voz = np.frombuffer(sintetizar(frase.fala, ritmo), dtype="<i2").astype(np.float64)
            voz = _altura(voz / 32768 * 0.5, fator)
            trecho = rng.normal(
                0.0, 10 ** (fundo / 20), int(0.4 * TAXA) + len(voz) + int(1.3 * TAXA)
            )
            inicio = int(0.4 * TAXA)
            trecho[inicio : inicio + len(voz)] += voz
            cenas.append((f"{frase.esperado}#{i}", frase, _pcm(trecho)))
    return cenas


def dica_em_frase(palavra: str, termos: Sequence[str]) -> str:
    """A candidata medida e descartada (ADR-0067): os termos depois de uma frase em pt-BR. No
    small ela não ajudou nada e tirou o «Jarvis» do começo — a palavra de ativação se perdeu."""
    lista = dica_do_asr(palavra, termos)
    primeiro, _, resto = lista.partition(", ")
    abertura = "Conversa em português do Brasil com o"
    return f"{abertura} {primeiro}: {resto}" if resto else f"{abertura} {primeiro}"


def dica_de(tipo: str) -> str:
    if tipo == "atual":
        return dica_do_asr("jarvis", TERMOS_FICTICIOS)
    if tipo == "frase":
        return dica_em_frase("jarvis", TERMOS_FICTICIOS)
    return ""


def acertou_a_chave(chave: str, ouvido: str) -> bool:
    return (
        f" {dobrar(chave)} "
        in f" {' '.join(dobrar(ouvido).replace('-', ' ').split())} ".replace(".", " ")
        .replace(",", " ")
        .replace("?", " ")
        .replace("!", " ")
    )


def transcrever(
    modelo: Any, config: Config, dica: str, amostras: bytes
) -> tuple[str, Sinais, float]:
    audio = np.frombuffer(amostras, dtype="<i2").astype(np.float32) / 32768.0
    comeco = time.perf_counter()
    trechos, _ = modelo.transcribe(
        audio,
        language="pt",
        beam_size=config.beam,
        vad_filter=False,
        initial_prompt=dica or None,
        **dict(config.opcoes),
    )
    partes = list(trechos)
    ms = (time.perf_counter() - comeco) * 1000.0
    texto = " ".join(t.text for t in partes).strip()
    if not partes:
        return texto, Sinais(), ms
    media = sum(float(t.avg_logprob) for t in partes) / len(partes)
    return (
        texto,
        Sinais(
            sem_fala=max(float(t.no_speech_prob) for t in partes),
            logprob=media,
            compressao=max(float(t.compression_ratio) for t in partes),
        ),
        ms,
    )


def medir(
    config: Config,
    fala: Sequence[tuple[str, Frase, bytes]],
    ruido: Sequence[Any],
    threads: int,
    dispositivo: str = "cpu",
) -> list[dict[str, object]]:
    from faster_whisper import WhisperModel

    if dispositivo == "cuda":
        _cuda_visivel()  # abre a cuBLAS do pacote nvidia-cublas-cu12, se houver
        modelo = WhisperModel(config.modelo, device="cuda", compute_type="float16")
    else:
        modelo = WhisperModel(
            config.modelo, device="cpu", compute_type=config.compute, cpu_threads=threads
        )
    nome_da_config = f"{config.nome}@cuda" if dispositivo == "cuda" else config.nome
    dica = dica_de(config.dica)
    palavras = palavras_da_dica(dica)
    linhas: list[dict[str, object]] = []
    transcrever(modelo, config, dica, fala[0][2])  # aquece (o primeiro paga a alocação)
    for nome, frase, amostras in fala:
        texto, sinais, ms = transcrever(modelo, config, dica, amostras)
        veredito = julgar_texto(texto, sinais, dica=palavras)
        linhas.append(
            {
                "config": nome_da_config,
                "cena": nome,
                "tipo": "fala",
                "esperado": frase.esperado,
                "ouvido": texto,
                "wer": round(wer(frase.esperado, texto).taxa, 3),
                "chave": int(acertou_a_chave(frase.chave, texto)),
                "descartado": int(veredito.descartado),
                "asr_ms": round(ms),
            }
        )
    for cena in ruido:
        texto, sinais, ms = transcrever(modelo, config, dica, cena.amostras)
        veredito = julgar_texto(texto, sinais, dica=palavras)
        linhas.append(
            {
                "config": nome_da_config,
                "cena": cena.nome,
                "tipo": "ruido",
                "esperado": "",
                "ouvido": texto,
                "wer": "",
                "chave": "",
                "descartado": int(veredito.descartado or not texto.strip()),
                "asr_ms": round(ms),
            }
        )
    del modelo
    gc.collect()
    return linhas


def resumo(linhas: Sequence[dict[str, object]]) -> str:
    saida = [
        "| configuração | WER médio | termo-chave | «mãe» | «WhatsApp» | fala descartada | "
        "ruído que vira texto | ASR p50 (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for nome in dict.fromkeys(str(linha["config"]) for linha in linhas):
        fala = [x for x in linhas if x["config"] == nome and x["tipo"] == "fala"]
        ruido = [x for x in linhas if x["config"] == nome and x["tipo"] == "ruido"]
        mae = [
            x
            for x in fala
            if "mãe" in str(x["esperado"]).lower() and "WhatsApp" not in str(x["esperado"])
        ]
        zap = [x for x in fala if "WhatsApp" in str(x["esperado"])]

        def taxa(grupo: Sequence[dict[str, object]]) -> str:
            return f"{sum(int(str(x['chave'])) for x in grupo)}/{len(grupo)}"

        saida.append(
            f"| {nome} | {statistics.mean(float(str(x['wer'])) for x in fala):.3f} | "
            f"{taxa(fala)} | "
            f"{taxa(mae)} | {taxa(zap)} | {sum(int(str(x['descartado'])) for x in fala)} | "
            f"{sum(1 - int(str(x['descartado'])) for x in ruido)}/{len(ruido)} | "
            f"{statistics.median(float(str(x['asr_ms'])) for x in fala):.0f} |"
        )
    return "\n".join(saida)


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--configs", default=",".join(CONFIGS))
    analisa.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    analisa.add_argument("--threads", type=int, default=4)
    analisa.add_argument("--dispositivo", choices=("cpu", "cuda"), default="cpu")
    args = analisa.parse_args(argv)
    escolhidas = [CONFIGS[n.strip()] for n in args.configs.split(",") if n.strip()]
    voz = MotorPiperOnnx(
        caminho=PASTA_VOZES / VOZ_PIPER / f"{VOZ_PIPER}.onnx",
        fonemizar=fonemizar_com_espeak,
        voz=VOZ_PIPER,
        identificador_registrado=f"rhasspy/piper-voices:{VOZ_PIPER}",
        # Medição, não produto: o espeak-ng (GPL) só roda em tools/ (licenses/motores.toml).
        registrado="tts-piper-espeak",
        permitir_fora_do_produto=True,
    )
    voz.abrir()

    def sintetizar(texto: str, ritmo: float) -> bytes:
        voz.ritmo = ritmo
        return voz.sintetizar(texto)

    rng = np.random.default_rng(SEMENTE)
    fala = cenas_de_fala(rng, sintetizar)
    ruido = cenas_de_ruido(rng)
    linhas: list[dict[str, object]] = []
    for config in escolhidas:
        print(f"… {config.nome}", file=sys.stderr, flush=True)
        linhas.extend(medir(config, fala, ruido, args.threads, args.dispositivo))
        print(resumo(linhas).splitlines()[-1], file=sys.stderr)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    print(
        f"\n{args.dispositivo}, {args.threads} threads · voz piper {VOZ_PIPER} + espeak-ng"
        f"\n\n{resumo(linhas)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
