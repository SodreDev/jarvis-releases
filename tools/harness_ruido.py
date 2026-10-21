"""Harness do ruído e da dica do ASR (ADR-0043): o que vira texto, com e sem dica, e o filtro.

Uso (precisa do grupo `asr`, do peso do whisper small no cache, da voz piper e do espeak-ng):

    nice -n 19 uv run --frozen python -m tools.harness_ruido

Só áudio **sintético**: ruídos gerados com semente fixa (sala, estalo, teclado, respiração, tosse,
ventilador, chiado) e fala da voz piper com fonemas do espeak-ng — o espeak é GPL e por isso só
roda aqui, em `tools/`, fora do produto (como no corpus do F1-02). Nenhum microfone, nenhum
arquivo do dono, nenhuma rede.

Cada trecho é o que o laço manda ao ASR: 400 ms antes, o evento e o silêncio do fim. O ruído é
mandado **forçado** (como se o VAD tivesse aberto — o silero não abriu para nenhum deles: o que se
mede é o que o ASR faz quando abre). Para cada variante de dica: o texto, os sinais do whisper, o
tempo e o que o filtro de `jarvis.voz.ruido` decide. Escreve `docs/medicoes/ruido-e-dica.csv` e
imprime a tabela do resumo (`docs/medicoes/ruido-e-dica.md` a cita). O whisper volta com
temperatura (em escada) quando o logprob cai: duas rodadas podem diferir no texto inventado; o
resumo publica o que esta rodada viu.
"""

from __future__ import annotations

import argparse
import csv
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np

from jarvis.agentd.tts import MotorPiperOnnx
from jarvis.voz.dica import dica_do_asr
from jarvis.voz.interface import Sinais
from jarvis.voz.ruido import julgar_audio, julgar_texto, medir_trecho, normalizar, palavras_da_dica
from tools.harness_tts import PASTA_VOZES, VOZ_PIPER, fonemizar_com_espeak

RAIZ: Final = Path(__file__).resolve().parent.parent
SAIDA_PADRAO: Final = RAIZ / "docs" / "medicoes" / "ruido-e-dica.csv"
TAXA: Final = 16_000
SEMENTE: Final = 20261021
APPS_FICTICIOS: Final = (
    "Ark, Audacity, Bazaar, Blender, Borderlands 2, Brave Web Browser, Calculadora, Chromium, "
    "Counter-Strike 2, Discord, Dolphin, Elisa, Firefox, GIMP, Gwenview, Heroic Games Launcher, "
    "Kate, Kdenlive, Konsole, Krita, LibreOffice Calc, LibreOffice Writer, Lutris, OBS Studio, "
    "Okular, qBittorrent, Spectacle, Spotify, Steam, Telegram Desktop, Thunderbird"
)
"""A forma da dica antiga — 31 nomes, ~480 caracteres —, com apps comuns e fictícios: o catálogo
do dono não entra aqui."""
VOCABULARIO_FICTICIO: Final = ("Discord", "Spotify", "Kauã Ximenes")
FALAS: Final = (
    "Sim.",
    "Não.",
    "Para.",
    "Jarvis.",
    "Jarvis, que horas são?",
    "Abre o Discord.",
    "Abre o Spotify.",
    "Manda mensagem para o Kauã Ximenes.",
)


@dataclass(frozen=True, slots=True)
class Cena:
    nome: str
    tipo: str
    """`ruido` ou `fala`."""
    amostras: bytes
    esperado: str = ""


def _pcm(sinal: np.ndarray) -> bytes:
    return bytes(np.clip(np.rint(sinal * 32767), -32768, 32767).astype("<i2").tobytes())


def _db(valor: float) -> float:
    return float(10 ** (valor / 20))


def cenas_de_ruido(rng: np.random.Generator) -> list[Cena]:
    """Os ruídos, cada um num trecho de 2 s como o laço o mandaria (o evento a 400 ms)."""

    def sala(segundos: float, nivel: float = -62.0) -> np.ndarray:
        return rng.normal(0.0, _db(nivel), int(segundos * TAXA))

    def com(fundo: np.ndarray, evento: np.ndarray, em_s: float = 0.4) -> np.ndarray:
        saida = fundo.copy()
        i = int(em_s * TAXA)
        saida[i : i + len(evento)] += evento[: len(saida) - i]
        return saida

    def clique(nivel: float) -> np.ndarray:
        n = int(0.03 * TAXA)
        return rng.normal(0.0, 1.0, n) * np.exp(-np.arange(n) / (0.004 * TAXA)) * _db(nivel) * 4

    def teclado(segundos: float) -> np.ndarray:
        sinal = np.zeros(int(segundos * TAXA))
        t = 0.05
        while t < segundos - 0.05:
            sinal = com(sinal, clique(-28.0 + rng.uniform(-4, 2)), t)
            t += rng.uniform(0.6, 1.4) / 7.0
        return sinal

    def filtrado(segundos: float, nivel: float, baixo: float, alto: float) -> np.ndarray:
        n = int(segundos * TAXA)
        espectro = np.fft.rfft(rng.normal(0.0, 1.0, n))
        freqs = np.fft.rfftfreq(n, 1 / TAXA)
        espectro[(freqs < baixo) | (freqs > alto)] *= 0.1
        sinal: np.ndarray = np.fft.irfft(espectro, n)
        sinal /= np.sqrt(np.mean(sinal**2)) + 1e-12
        envelope = np.sin(np.pi * np.arange(n) / n) ** 2
        resultado: np.ndarray = sinal * envelope * _db(nivel)
        return resultado

    def tosse(nivel: float) -> np.ndarray:
        n = int(0.3 * TAXA)
        envelope = np.exp(-np.arange(n) / (0.08 * TAXA))
        envelope[: int(0.01 * TAXA)] *= np.linspace(0, 1, int(0.01 * TAXA))
        return rng.normal(0.0, 1.0, n) * envelope * _db(nivel) * 2

    def ventilador(segundos: float, nivel: float) -> np.ndarray:
        marrom = np.cumsum(rng.normal(0.0, 1.0, int(segundos * TAXA)))
        marrom -= np.convolve(marrom, np.ones(400) / 400, mode="same")
        marrom /= np.sqrt(np.mean(marrom**2))
        zumbido = 0.3 * np.sin(2 * np.pi * 120 * np.arange(len(marrom)) / TAXA)
        return (marrom + zumbido) * _db(nivel)

    return [
        Cena("silencio_sala", "ruido", _pcm(sala(2.0))),
        Cena("clique_do_mouse", "ruido", _pcm(com(sala(2.0), clique(-20.0)))),
        Cena("teclado", "ruido", _pcm(com(sala(2.0), teclado(1.5)))),
        Cena("respiracao", "ruido", _pcm(com(sala(2.0), filtrado(0.6, -38.0, 300, 2500)))),
        Cena("respiracao_forte", "ruido", _pcm(com(sala(2.0), filtrado(0.8, -30.0, 300, 2500)))),
        Cena("tosse", "ruido", _pcm(com(sala(2.0), tosse(-22.0)))),
        Cena("ventilador", "ruido", _pcm(ventilador(2.0, -40.0))),
        Cena("chiado", "ruido", _pcm(sala(2.0, -42.0))),
    ]


def cenas_de_fala(rng: np.random.Generator, sintetizar: Callable[[str], bytes]) -> list[Cena]:
    """A fala sintética, cada frase com 400 ms antes e 1,3 s depois, como o laço a manda."""
    cenas = []
    for texto in FALAS:
        voz = np.frombuffer(sintetizar(texto), dtype="<i2").astype(np.float64) / 32768 * 0.5
        trecho = rng.normal(0.0, _db(-62.0), int(0.4 * TAXA) + len(voz) + int(1.3 * TAXA))
        inicio = int(0.4 * TAXA)
        trecho[inicio : inicio + len(voz)] += voz
        cenas.append(Cena(f"fala:{texto}", "fala", _pcm(trecho), esperado=texto))
    return cenas


def variantes() -> dict[str, dict[str, str]]:
    """As dicas comparadas: nenhuma, a antiga (lista de apps), a `hotwords` só com o nome, e as
    duas formas da nova (só o nome, e o nome com o vocabulário do dono)."""
    return {
        "sem_dica": {},
        "lista_de_apps": {
            "hotwords": f"Jarvis, {APPS_FICTICIOS}",
            "initial_prompt": f"Abra Jarvis, {APPS_FICTICIOS}.",
        },
        "hotwords_jarvis": {"hotwords": "Jarvis"},
        "dica_so_palavra": {"initial_prompt": dica_do_asr("jarvis")},
        "dica_com_vocabulario": {"initial_prompt": dica_do_asr("jarvis", VOCABULARIO_FICTICIO)},
    }


def acertou(esperado: str, ouvido: str) -> bool:
    """Todas as palavras que importam da frase dita estão no que o ASR ouviu."""
    sem_peso = {"o", "a", "de", "da", "do", "para"}
    queria = [p for p in normalizar(esperado).split() if p not in sem_peso]
    veio = set(normalizar(ouvido).split())
    return bool(queria) and all(p in veio for p in queria)


def medir(cenas: Sequence[Cena], modelo: Any) -> list[dict[str, object]]:
    linhas: list[dict[str, object]] = []
    for cena in cenas:
        comeco = time.perf_counter()
        medida = medir_trecho(cena.amostras)
        portao = julgar_audio(medida)
        portao_us = (time.perf_counter() - comeco) * 1e6
        audio = np.frombuffer(cena.amostras, dtype="<i2").astype(np.float32) / 32768
        for nome, opcoes in variantes().items():
            comeco = time.perf_counter()
            segmentos = list(
                modelo.transcribe(
                    audio,
                    language="pt",
                    beam_size=1,
                    vad_filter=False,
                    hotwords=opcoes.get("hotwords") or None,
                    initial_prompt=opcoes.get("initial_prompt") or None,
                )[0]
            )
            asr_ms = (time.perf_counter() - comeco) * 1000
            texto = " ".join(s.text.strip() for s in segmentos).strip()
            sinais = Sinais(
                sem_fala=max((s.no_speech_prob for s in segmentos), default=None),
                logprob=(
                    sum(s.avg_logprob for s in segmentos) / len(segmentos) if segmentos else None
                ),
                compressao=max((s.compression_ratio for s in segmentos), default=None),
            )
            dica = palavras_da_dica(opcoes.get("initial_prompt") or opcoes.get("hotwords") or "")
            veredito = julgar_texto(texto, sinais, dica=dica)
            linhas.append(
                {
                    "cena": cena.nome,
                    "tipo": cena.tipo,
                    "variante": nome,
                    "texto": texto,
                    "virou_texto": int(bool(texto)),
                    "acertou": "" if cena.tipo == "ruido" else int(acertou(cena.esperado, texto)),
                    "sem_fala": "" if sinais.sem_fala is None else round(sinais.sem_fala, 3),
                    "logprob": "" if sinais.logprob is None else round(sinais.logprob, 3),
                    "compressao": "" if sinais.compressao is None else round(sinais.compressao, 2),
                    "filtro": "" if veredito.motivo is None else str(veredito.motivo),
                    "portao": "" if portao is None else str(portao),
                    "maior_fala_ms": medida.maior_fala_ms,
                    "contraste_db": round(medida.contraste_db, 1),
                    "asr_ms": round(asr_ms, 1),
                    "portao_us": round(portao_us, 1),
                }
            )
            print(f"{cena.nome:42} {nome:22} {texto[:60]!r}", flush=True)
    return linhas


def _commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "?"
    try:
        return subprocess.run(
            [git, "-C", str(RAIZ), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "?"


def _cpu() -> str:
    try:
        for linha in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("model name"):
                return linha.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "?"


def resumo(linhas: Sequence[dict[str, object]]) -> str:
    """A tabela do `.md`: por variante, quantos ruídos viraram texto, quantos o filtro segurou,
    quantas falas o ASR acertou e quantas o filtro derrubaria, e o tempo do ASR."""
    nomes = list(dict.fromkeys(str(item["variante"]) for item in linhas))
    ruidos = sorted({str(item["cena"]) for item in linhas if item["tipo"] == "ruido"})
    falas = sorted({str(item["cena"]) for item in linhas if item["tipo"] == "fala"})
    tabela = [
        "| dica | ruído que virou texto | e passou no filtro | fala acertada | fala que o filtro "
        "derrubaria | ASR p50 (ms) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for nome in nomes:
        da = [item for item in linhas if item["variante"] == nome]
        do_ruido = [item for item in da if item["tipo"] == "ruido"]
        da_fala = [item for item in da if item["tipo"] == "fala"]
        virou = sum(int(str(item["virou_texto"])) for item in do_ruido)
        passou = sum(1 for item in do_ruido if item["virou_texto"] and not item["filtro"])
        certas = sum(int(str(item["acertou"] or 0)) for item in da_fala)
        derrubadas = sum(1 for item in da_fala if item["acertou"] and item["filtro"])
        p50 = float(np.median([float(str(item["asr_ms"])) for item in da]))
        tabela.append(
            f"| {nome} | {virou}/{len(do_ruido)} | {passou}/{len(do_ruido)} | "
            f"{certas}/{len(da_fala)} | {derrubadas}/{len(da_fala)} | {p50:.0f} |"
        )
    portao = {str(item["cena"]): str(item["portao"] or "passa") for item in linhas}
    us = [float(str(item["portao_us"])) for item in linhas]
    return "\n".join(
        [
            *tabela,
            "",
            f"`n` = {len(ruidos)} ruídos e {len(falas)} falas por variante "
            f"({len(nomes)} variantes, {len(linhas)} transcrições).",
            "",
            "Portão do trecho (antes do ASR, sem depender da dica): "
            + "; ".join(f"{cena} → {veredito}" for cena, veredito in sorted(portao.items()))
            + f". Custo do portão: p50 {np.median(us):.0f} µs, máximo {max(us):.0f} µs por trecho.",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    analisa.add_argument("--threads", type=int, default=2)
    args = analisa.parse_args(argv)
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper não está instalado: `uv sync --group asr`.", file=sys.stderr)
        return 2
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
    modelo = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8",
        cpu_threads=args.threads,
        download_root=str(Path.home() / ".cache" / "jarvis"),
    )
    rng = np.random.default_rng(SEMENTE)
    cenas = [*cenas_de_ruido(rng), *cenas_de_fala(rng, voz.sintetizar)]
    linhas = medir(cenas, modelo)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with args.saida.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=list(linhas[0]))
        escritor.writeheader()
        escritor.writerows(linhas)
    cabecalho = (
        f"Commit da medição: {_commit()} · hardware: {_cpu()} (CPU, whisper small int8, "
        f"{args.threads} threads) · voz: piper {VOZ_PIPER} + espeak-ng (só em tools/)."
    )
    print(f"\n{cabecalho}\n\n{resumo(linhas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
