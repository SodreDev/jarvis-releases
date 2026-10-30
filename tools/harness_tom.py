"""Mede o tom de voz (ADR-0058) sem microfone: acerto, custo e o efeito em paralelo ao ASR.

Uso: `.venv/bin/python tools/harness_tom.py [--sementes 20] [--saida docs/medicoes/tom-de-voz.md]`

1. **O banco sintético** (`tools/sinais_de_tom.py`): onze cenas com o rótulo conhecido, em N
   sementes, com e sem a linha de base do «dono» pronta; e os turnos neutros, para os falsos.
2. **O custo da análise** por duração de trecho (p50/p95).
3. **A voz piper local** (se a voz e o espeak-ng estiverem aqui): pares da mesma frase dita com
   `?` e com `.` — a entonação que um TTS de verdade produz, não a do contorno escrito à mão. O
   espeak-ng é GPL e só roda em `tools/` (licenses/motores.toml), como no harness de ruído.
4. **Em paralelo ao ASR** (se o grupo `asr` e o whisper small estiverem no cache): o tempo do ASR
   sozinho e com a análise do tom na linha ao lado, e quanto o laço esperaria depois do ASR.

Nada aqui toca microfone ou alto-falante: tudo é gerado de semente ou pela voz sintética.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

import numpy as np

RAIZ: Final = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.append(str(RAIZ))

from jarvis.voz.tom import (  # noqa: E402
    Entonacao,
    LinhaDeBase,
    medir,
    rotular,
    taxa_de_silabas,
)
from tools.sinais_de_tom import AFIRMACAO, base_do_dono, cenas, trecho, voz  # noqa: E402

SAIDA_PADRAO: Final = RAIZ / "docs" / "medicoes" / "tom-de-voz.md"
MEDIDOS: Final = ("src/jarvis/voz/tom.py", "tools/sinais_de_tom.py", "tools/harness_tom.py")
PARES: Final = (
    "vai chover amanhã de manhã",
    "você já comeu alguma coisa hoje",
    "o mercado ainda está aberto agora",
    "a reunião foi cancelada de novo",
    "você ligou para a minha mãe ontem",
    "o jogo começa às oito da noite",
    "tem café quente na cozinha",
    "o ônibus já passou por aqui",
    "a internet voltou a funcionar",
    "você salvou o arquivo da planilha",
    "o Pedro vem jantar com a gente",
    "a encomenda chegou pelo correio",
)
"""Frases que só a entonação faz pergunta: nenhuma tem palavra interrogativa."""
BASE_PIPER: Final = (
    "eu vou sair um pouco mais tarde hoje.",
    "deixa a música tocando no quarto.",
    "o relatório ficou pronto de manhã.",
    "amanhã eu preciso acordar cedo.",
    "a janela da sala está aberta.",
    "o filme começa daqui a pouco.",
)


def _p(valores: Sequence[float], q: float) -> float:
    return float(np.percentile(valores, q)) if valores else float("nan")


def _base(turnos: Sequence[tuple[bytes, str]]) -> LinhaDeBase:
    base = LinhaDeBase()
    for audio, texto in turnos:
        prosodia = medir(audio)
        base.aprender(prosodia, taxa_de_silabas(prosodia, texto))
    return base


def banco(sementes: int) -> list[str]:
    acertos: dict[str, list[int]] = {}
    falsos = 0
    neutros = 0
    for semente in range(sementes):
        base = _base(base_do_dono(1000 + 10 * semente))
        for audio, texto in base_do_dono(5000 + 10 * semente)[:3]:
            neutros += 1
            falsos += not rotular(medir(audio), base, texto=texto).neutro()
        for cena in cenas(31 * semente):
            prosodia = medir(cena.audio)
            com = rotular(prosodia, base, texto=cena.texto)
            sem = rotular(prosodia, LinhaDeBase(), texto=cena.texto)
            par = acertos.setdefault(cena.nome, [0, 0])
            par[0] += all(str(getattr(com, k)) == v for k, v in cena.esperado.items())
            par[1] += all(str(getattr(sem, k)) == v for k, v in cena.esperado.items())
    linhas = [
        f"### Banco sintético ({sementes} sementes; `sintetico`: sim)",
        "",
        "| cena | rótulo esperado | com a base pronta | sem base (1º turno) |",
        "|---|---|---|---|",
    ]
    esperados = {cena.nome: cena.esperado for cena in cenas(0)}
    for nome, (certos, certos_sem_base) in acertos.items():
        rotulo = ", ".join(f"{k}={v}" for k, v in esperados[nome].items())
        linhas.append(f"| {nome} | {rotulo} | {certos}/{sementes} | {certos_sem_base}/{sementes} |")
    linhas += [
        "",
        f"Turnos neutros (a voz «de sempre») rotulados fora do neutro: {falsos}/{neutros}.",
    ]
    return linhas


def custo() -> list[str]:
    linhas = [
        "### Custo da análise (`medir`, numpy, uma linha)",
        "",
        "| fala | n | p50 ms | p95 ms |",
        "|---|---|---|---|",
    ]
    for segundos in (1.0, 2.0, 4.0, 6.0):
        tempos = []
        for semente in range(40):
            audio = trecho(voz(AFIRMACAO, segundos, semente=semente), semente=semente)
            comeco = time.perf_counter()
            medir(audio)
            tempos.append((time.perf_counter() - comeco) * 1000)
        tempos = tempos[5:]  # aquecimento
        linhas.append(
            f"| {segundos:.0f} s | {len(tempos)} | {_p(tempos, 50):.1f} | {_p(tempos, 95):.1f} |"
        )
    return linhas


def _voz_piper() -> Callable[[str], bytes] | None:
    from tools.harness_tts import PASTA_VOZES, VOZ_PIPER, fonemizar_com_espeak

    modelo = PASTA_VOZES / VOZ_PIPER / f"{VOZ_PIPER}.onnx"
    if not modelo.exists() or shutil.which("espeak-ng") is None:
        return None
    try:
        from jarvis.agentd.tts import MotorPiperOnnx
    except ImportError:
        return None

    def fonemizar(texto: str) -> str:
        # O `--ipa` do espeak-ng tira a pontuação; a voz piper foi treinada com ela (é o `?` que
        # muda a entonação), então o sinal final volta ao fim dos fonemas.
        final = texto.rstrip()[-1:]
        return fonemizar_com_espeak(texto) + (final if final in "?.!" else "")

    motor = MotorPiperOnnx(
        caminho=modelo,
        fonemizar=fonemizar,
        voz=VOZ_PIPER,
        identificador_registrado=f"rhasspy/piper-voices:{VOZ_PIPER}",
        registrado="tts-piper-espeak",
        permitir_fora_do_produto=True,
    )
    motor.abrir()
    return motor.sintetizar


def _no_trecho(pcm: bytes, semente: int) -> bytes:
    sinal = np.frombuffer(pcm, dtype="<i2").astype(np.float64) / 32768 * 0.5
    return trecho(sinal, semente=semente)


def piper(sintetizar: Callable[[str], bytes]) -> tuple[list[str], list[tuple[bytes, str]]]:
    base = _base([(_no_trecho(sintetizar(t), i), t) for i, t in enumerate(BASE_PIPER)])
    acertos = {"?": 0, ".": 0}
    finais: dict[str, list[float]] = {"?": [], ".": []}
    audios: list[tuple[bytes, str]] = []
    for i, frase in enumerate(PARES):
        for sinal in ("?", "."):
            audio = _no_trecho(sintetizar(frase + sinal), 100 + i)
            audios.append((audio, frase))
            prosodia = medir(audio)
            tom = rotular(prosodia, base, texto=frase)  # o texto do ASR, sem a pontuação
            esperado = Entonacao.PERGUNTA if sinal == "?" else Entonacao.AFIRMACAO
            acertos[sinal] += tom.entonacao is esperado
            finais[sinal].append(prosodia.final_st)
    n = len(PARES)
    linhas = [
        "### Voz piper local, a mesma frase com `?` e com `.` (`sintetico`: sim)",
        "",
        "O texto que o rótulo recebe é o da frase **sem** pontuação (o ASR que não pôs o `?`).",
        "",
        "| dita com | n | rotulada certo | pico final − resto (st), p50 | p10 | p90 |",
        "|---|---|---|---|---|---|",
    ]
    for sinal, nome in (("?", "pergunta"), (".", "afirmação")):
        valores = finais[sinal]
        linhas.append(
            f"| {nome} | {n} | {acertos[sinal]}/{n} | {_p(valores, 50):.1f} | "
            f"{_p(valores, 10):.1f} | {_p(valores, 90):.1f} |"
        )
    return linhas, audios


def em_paralelo(audios: Sequence[tuple[bytes, str]], threads: int) -> list[str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return ["### Em paralelo ao ASR", "", "Não medido: o grupo `asr` não está instalado."]
    modelo = WhisperModel(
        "small",
        device="cpu",
        compute_type="int8",
        cpu_threads=threads,
        download_root=str(Path.home() / ".cache" / "jarvis"),
    )

    def transcrever(audio: bytes) -> None:
        sinal = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768
        segmentos, _ = modelo.transcribe(sinal, language="pt", beam_size=1)
        list(segmentos)

    transcrever(audios[0][0])
    sozinho, junto, analise, espera = [], [], [], []
    linha = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="tom")
    for audio, _ in audios:
        comeco = time.perf_counter()
        transcrever(audio)
        sozinho.append((time.perf_counter() - comeco) * 1000)
        comeco = time.perf_counter()
        futuro = linha.submit(medir, audio)
        transcrever(audio)
        fim_do_asr = time.perf_counter()
        prosodia = futuro.result()
        fim = time.perf_counter()
        junto.append((fim_do_asr - comeco) * 1000)
        espera.append((fim - fim_do_asr) * 1000)
        analise.append(prosodia.analise_ms)
    linha.shutdown()
    n = len(audios)
    return [
        f"### Em paralelo ao ASR (whisper small int8, CPU, {threads} threads; n={n})",
        "",
        "| medida | p50 ms | p95 ms |",
        "|---|---|---|",
        f"| ASR sozinho | {_p(sozinho, 50):.0f} | {_p(sozinho, 95):.0f} |",
        f"| ASR com o tom na linha ao lado | {_p(junto, 50):.0f} | {_p(junto, 95):.0f} |",
        f"| análise do tom | {_p(analise, 50):.1f} | {_p(analise, 95):.1f} |",
        f"| espera do laço depois do ASR | {_p(espera, 50):.2f} | {_p(espera, 95):.2f} |",
    ]


def _commit() -> str:
    git = shutil.which("git")
    if git is None:
        return "?"
    try:
        cabeca = subprocess.run(
            [git, "-C", str(RAIZ), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        sujo = subprocess.run(
            [git, "-C", str(RAIZ), "status", "--porcelain", "--", *MEDIDOS],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "?"
    # O código medido ainda não commitado é dito, não escondido.
    return f"{cabeca} + árvore de trabalho (tom não commitado)" if sujo else cabeca


def _cpu() -> str:
    try:
        for linha in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("model name"):
                return linha.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "?"


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--sementes", type=int, default=20)
    analisa.add_argument("--threads", type=int, default=4)
    analisa.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    args = analisa.parse_args(argv)
    partes: list[str] = [
        "# Tom de voz: acerto e custo medidos (ADR-0058)",
        "",
        f"Gerado por `tools/harness_tom.py` · commit da medição: {_commit()} · hardware: "
        f"{_cpu()} · Python {platform.python_version()} · numpy {np.__version__}. Tudo é "
        "áudio sintético: nenhum número aqui vale para a voz do dono antes de ela ser medida.",
        "",
    ]
    partes += [*banco(args.sementes), "", *custo(), ""]
    sintetizar = _voz_piper()
    audios: list[tuple[bytes, str]] = []
    if sintetizar is None:
        partes += ["### Voz piper local", "", "Não medido: falta a voz piper ou o espeak-ng.", ""]
    else:
        linhas, audios = piper(sintetizar)
        partes += [*linhas, ""]
    if audios:
        partes += [*em_paralelo(audios, args.threads), ""]
    texto = "\n".join(partes)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    args.saida.write_text(texto, encoding="utf-8")
    print(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
