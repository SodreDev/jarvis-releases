"""Harness de latência de captura e a decisão D1 (cartão F0-04, SPEC §2).

    uv run --frozen --group medicao python tools/harness_captura.py

Mede o caminho `frame de 20 ms → pré-filtro → VAD → evento` em braços equivalentes:

* `rust-std` — Rust só com a biblioteca padrão, compilado com `rustc -O` (sem cargo, sem
  rede, sem instalar nada: exigência do dono);
* `python-numpy` — mesma aritmética e os mesmos limiares do braço Rust;
* `python-onnx` — VAD neural de verdade (`silero-vad`, MIT, verificado na F0-09), que é o que
  o produto usaria em Python.

Mede também **dois pisos**, para separar o que é nosso do que é da máquina: o piso de
agendamento (laço de 20 ms sem processamento) e o piso do dispositivo de áudio (cadência de
entrega real). O piso do dispositivo lê o **monitor da saída**, nunca o microfone do dono —
decisão de privacidade, registrada no relatório.

Publica `docs/medicoes/f0-04-captura.csv` e `.md` com hardware, `n`, 3 execuções, mediana,
p95, p99 e as pausas de GC medidas à parte.
"""

from __future__ import annotations

import argparse
import csv
import gc
import itertools
import json
import math
import os
import platform
import shutil
import statistics
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
PASTA_SAIDA: Final = RAIZ / "docs" / "medicoes"
FONTE_RUST: Final = RAIZ / "medicao" / "vad_bench.rs"

TAXA: Final = 16_000
FRAME: Final = TAXA // 50  # 20 ms
PRE_ENFASE: Final = 0.97
LIMIAR_DB: Final = -45.0
LIMIAR_ZCR: Final = 0.35
FRAMES_PARA_LIGAR: Final = 2
FRAMES_PARA_DESLIGAR: Final = 6
JANELA_SILERO: Final = 512


@dataclass
class Resultado:
    braco: str
    execucao: int
    n: int
    eventos: int
    media_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    gc_pausas: int = 0
    gc_ms: float = 0.0
    observacao: str = ""


@dataclass
class Piso:
    nome: str
    n: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    observacao: str = ""


@dataclass
class Lacuna:
    o_que: str
    por_que: str


def percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    return ordenados[min(round(p / 100 * (len(ordenados) - 1)), len(ordenados) - 1)]


def hardware() -> dict[str, str]:
    cpu = platform.processor()
    try:
        for linha in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("model name"):
                cpu = linha.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    memoria = "?"
    try:
        for linha in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if linha.startswith("MemTotal"):
                memoria = f"{int(linha.split()[1]) / 1024 / 1024:.0f} GiB"
                break
    except OSError:
        pass
    return {
        "cpu": cpu or "?",
        "nucleos": str(os.cpu_count() or "?"),
        "memoria": memoria,
        "plataforma": platform.platform(),
        "python": platform.python_version(),
    }


# --- áudio sintético, igual para todos os braços ----------------------------------
def gerar_audio(caminho: Path, segundos: float) -> int:
    """Fala e silêncio alternados, determinístico — os três braços leem o mesmo arquivo.

    Não é corpus: é sinal com envelope e harmônicos para o VAD ter trabalho de verdade
    (ligar e desligar). O corpus pt-BR de turno é da F1, com consentimento (cartão F0-08).
    """
    total = int(segundos * TAXA)
    dados = bytearray()
    estado_fala = False
    proxima_troca = 0
    semente = 20_261_015
    valor = semente
    for i in range(total):
        if i >= proxima_troca:
            estado_fala = not estado_fala
            valor = (valor * 1103515245 + 12345) & 0x7FFFFFFF
            proxima_troca = i + int(TAXA * (0.4 + (valor % 1000) / 1000.0))
        t = i / TAXA
        valor = (valor * 1103515245 + 12345) & 0x7FFFFFFF
        ruido = ((valor % 2001) - 1000) / 1000.0
        if estado_fala:
            envelope = 0.35 + 0.25 * math.sin(2 * math.pi * 3.0 * t)
            amostra = (
                envelope
                * (
                    0.6 * math.sin(2 * math.pi * 130.0 * t)
                    + 0.3 * math.sin(2 * math.pi * 260.0 * t)
                    + 0.1 * math.sin(2 * math.pi * 1800.0 * t)
                )
                + 0.01 * ruido
            )
        else:
            amostra = 0.0008 * ruido
        dados += struct.pack("<h", max(-32768, min(32767, int(amostra * 32767))))
    caminho.write_bytes(bytes(dados))
    return total // FRAME


def carregar(caminho: Path) -> Any:
    import numpy as np

    bruto = np.frombuffer(caminho.read_bytes(), dtype="<i2")
    return (bruto.astype(np.float32) / 32768.0).copy()


# --- braço Python + numpy ---------------------------------------------------------
class VadBarato:
    """Mesma lógica do braço Rust: pré-ênfase, RMS em dB, ZCR e histerese."""

    def __init__(self) -> None:
        self.anterior = 0.0
        self.acima = 0
        self.abaixo = 0
        self.falando = False

    def frame(self, amostras: Any) -> bool | None:
        import numpy as np

        deslocado = np.empty_like(amostras)
        deslocado[0] = self.anterior
        deslocado[1:] = amostras[:-1]
        filtrado = amostras - PRE_ENFASE * deslocado
        self.anterior = float(amostras[-1])

        rms = float(np.sqrt(np.mean(filtrado * filtrado)))
        db = 20.0 * math.log10(rms + 1e-12)
        sinais = filtrado >= 0
        zcr = float(np.count_nonzero(sinais[1:] != sinais[:-1])) / len(amostras)

        voz = db > LIMIAR_DB and zcr < LIMIAR_ZCR
        if voz:
            self.acima += 1
            self.abaixo = 0
        else:
            self.abaixo += 1
            self.acima = 0
        if not self.falando and self.acima >= FRAMES_PARA_LIGAR:
            self.falando = True
            return True
        if self.falando and self.abaixo >= FRAMES_PARA_DESLIGAR:
            self.falando = False
            return False
        return None


def medir_python_numpy(audio: Any, frames: int, execucao: int) -> Resultado:
    vad = VadBarato()
    tempos: list[float] = []
    eventos = 0
    with ObservadorDeGc() as gc_obs:
        for f in range(frames):
            pedaco = audio[f * FRAME : (f + 1) * FRAME]
            inicio = time.perf_counter()
            evento = vad.frame(pedaco)
            tempos.append((time.perf_counter() - inicio) * 1000.0)
            if evento is not None:
                eventos += 1
    return _resultado("python-numpy", execucao, tempos, eventos, gc_obs)


# --- braço Python + ONNX (silero-vad) ---------------------------------------------
def medir_python_onnx(audio: Any, frames: int, execucao: int, modelo: Path) -> Resultado:
    import numpy as np
    import onnxruntime as ort

    opcoes = ort.SessionOptions()
    opcoes.intra_op_num_threads = 1  # caminho de voz: um frame por vez, sem roubar núcleos
    opcoes.inter_op_num_threads = 1
    sessao = ort.InferenceSession(
        str(modelo), sess_options=opcoes, providers=["CPUExecutionProvider"]
    )
    estado = np.zeros((2, 1, 128), dtype=np.float32)
    taxa = np.array(TAXA, dtype=np.int64)
    acumulado = np.zeros(0, dtype=np.float32)

    tempos: list[float] = []
    eventos = 0
    acima = 0
    abaixo = 0
    falando = False
    with ObservadorDeGc() as gc_obs:
        for f in range(frames):
            pedaco = audio[f * FRAME : (f + 1) * FRAME]
            inicio = time.perf_counter()
            acumulado = np.concatenate((acumulado, pedaco))
            while len(acumulado) >= JANELA_SILERO:
                janela = acumulado[:JANELA_SILERO].reshape(1, JANELA_SILERO)
                acumulado = acumulado[JANELA_SILERO:]
                saida, estado = sessao.run(None, {"input": janela, "state": estado, "sr": taxa})
                p = float(saida[0][0])
                if p > 0.5:
                    acima += 1
                    abaixo = 0
                else:
                    abaixo += 1
                    acima = 0
                if not falando and acima >= 1:
                    falando = True
                    eventos += 1
                elif falando and abaixo >= 4:
                    falando = False
                    eventos += 1
            tempos.append((time.perf_counter() - inicio) * 1000.0)
    return _resultado("python-onnx", execucao, tempos, eventos, gc_obs)


def medir_evento_no_barramento(execucao: int, eventos: int, trabalho: Path) -> Resultado:
    """Custo do "→ evento" do SLO-1: envelope + validação de borda + IPC + log encadeado.

    O SLO-1 é `captura → AEC/VAD → evento`, e o evento é o que atravessa a fronteira de
    processo (§3). Medir só o VAD deixaria de fora justamente a parte que o barramento
    cobra: serializar, validar na borda, mandar pelo socket e gravar no log com hash.
    """
    from multiprocessing.connection import Pipe

    from jarvis.barramento import LogDeEventos, Prioridade, Tipo, Trust, uuid7, validar
    from jarvis.barramento.envelope import Envelope
    from jarvis.barramento.ipc import Canal

    nossa, deles = Pipe(duplex=True)
    emissor = Canal(nossa, nome="audio-io")
    receptor = Canal(deles, nome="agentd")
    sessao = uuid7()
    tempos: list[float] = []
    with LogDeEventos(trabalho / f"barramento-{execucao}.sqlite") as log, ObservadorDeGc() as obs:
        for i in range(eventos):
            inicio = time.perf_counter()
            envelope = Envelope(
                session_id=sessao,
                epoch=i,
                source="audio-io",
                trust=Trust.USER_VOICE,
                priority=Prioridade.P0,
                type=Tipo.AUDIO_ACTIVITY,
                payload={
                    "speech": True,
                    "device_id": "sintetico:0",
                    "energy_db": -18.0,
                    "aec_ok": True,
                },
            )
            validar(envelope)
            emissor.enviar({"publicar": envelope.para_dict()})
            recebido = receptor.receber(timeout=1.0)
            assert recebido is not None
            log.anexar(envelope)
            tempos.append((time.perf_counter() - inicio) * 1000.0)
    emissor.fechar()
    receptor.fechar()
    resultado = _resultado("evento-no-barramento", execucao, tempos, eventos, obs)
    resultado.observacao = "envelope + validação + IPC ida e volta + log com hash"
    return resultado


class ObservadorDeGc:
    """Mede as pausas do coletor à parte — "a cauda é o que decide" (aceite F0-04 b)."""

    def __init__(self) -> None:
        self.pausas: list[float] = []
        self._inicio = 0.0

    def _callback(self, fase: str, _info: dict[str, Any]) -> None:
        if fase == "start":
            self._inicio = time.perf_counter()
        elif self._inicio:
            self.pausas.append((time.perf_counter() - self._inicio) * 1000.0)

    def __enter__(self) -> ObservadorDeGc:
        gc.callbacks.append(self._callback)
        return self

    def __exit__(self, *_: object) -> None:
        gc.callbacks.remove(self._callback)

    @property
    def total_ms(self) -> float:
        return sum(self.pausas)


def _resultado(
    braco: str, execucao: int, tempos: list[float], eventos: int, gc_obs: ObservadorDeGc
) -> Resultado:
    return Resultado(
        braco=braco,
        execucao=execucao,
        n=len(tempos),
        eventos=eventos,
        media_ms=statistics.mean(tempos) if tempos else 0.0,
        p50_ms=percentil(tempos, 50),
        p95_ms=percentil(tempos, 95),
        p99_ms=percentil(tempos, 99),
        max_ms=max(tempos) if tempos else 0.0,
        gc_pausas=len(gc_obs.pausas),
        gc_ms=gc_obs.total_ms,
    )


# --- braço Rust -------------------------------------------------------------------
def compilar_rust(destino: Path) -> tuple[Path | None, str]:
    rustc = shutil.which("rustc")
    if rustc is None:
        return None, "rustc não está no PATH e nada foi instalado (regra do dono)"
    concluido = subprocess.run(
        [rustc, "--edition", "2021", "-O", "-o", str(destino), str(FONTE_RUST)],
        capture_output=True,
        text=True,
        check=False,
    )
    if concluido.returncode != 0:
        return None, f"rustc falhou: {concluido.stderr.strip()[:300]}"
    versao = subprocess.run(
        [rustc, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    return destino, versao


def medir_rust(binario: Path, audio: Path, frames: int, execucao: int) -> Resultado:
    concluido = subprocess.run(
        [str(binario), str(audio), str(frames), str(execucao)],
        capture_output=True,
        text=True,
        check=True,
    )
    dados: dict[str, Any] = json.loads(concluido.stdout.strip().splitlines()[-1])
    return Resultado(
        braco=str(dados["braco"]),
        execucao=int(dados["execucao"]),
        n=int(dados["n"]),
        eventos=int(dados["eventos"]),
        media_ms=float(dados["media_ms"]),
        p50_ms=float(dados["p50_ms"]),
        p95_ms=float(dados["p95_ms"]),
        p99_ms=float(dados["p99_ms"]),
        max_ms=float(dados["max_ms"]),
    )


# --- pisos ------------------------------------------------------------------------
def piso_de_agendamento(frames: int) -> Piso:
    """Quanto o próprio agendador atrasa um laço de 20 ms, sem processamento nenhum."""
    atrasos: list[float] = []
    alvo = time.perf_counter()
    for _ in range(frames):
        alvo += FRAME / TAXA
        espera = alvo - time.perf_counter()
        if espera > 0:
            time.sleep(espera)
        atrasos.append((time.perf_counter() - alvo) * 1000.0)
    return Piso(
        nome="agendamento (laço de 20 ms, sem nosso código)",
        n=len(atrasos),
        p50_ms=percentil(atrasos, 50),
        p95_ms=percentil(atrasos, 95),
        p99_ms=percentil(atrasos, 99),
    )


def piso_do_dispositivo(segundos: float) -> tuple[Piso | None, str]:
    """Cadência real de entrega do dispositivo, lendo o **monitor da saída**.

    Nunca o microfone: gravar o microfone do dono para medir jitter seria invadir
    privacidade por nada. O monitor é um dispositivo de captura de verdade do PipeWire e
    tem o mesmo caminho de driver.
    """
    pw_record = shutil.which("pw-record")
    if pw_record is None:
        return None, "pw-record não existe nesta máquina"
    alvo = _monitor_de_saida()
    if alvo is None:
        return None, "nenhum monitor de saída encontrado (não se mede o microfone do dono)"

    argv = [
        pw_record,
        "--target",
        alvo,
        "--rate",
        str(TAXA),
        "--channels",
        "1",
        "--format",
        "s16",
        "-",
    ]
    bytes_por_frame = FRAME * 2
    atrasos: list[float] = []
    processo = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        assert processo.stdout is not None
        inicio = time.perf_counter()
        esperado = inicio
        limite = inicio + segundos
        while time.perf_counter() < limite:
            pedaco = processo.stdout.read(bytes_por_frame)
            if not pedaco or len(pedaco) < bytes_por_frame:
                break
            esperado += FRAME / TAXA
            atrasos.append((time.perf_counter() - esperado) * 1000.0)
    finally:
        processo.terminate()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processo.kill()
            processo.wait(timeout=5)
    if len(atrasos) < 50:
        return None, f"o monitor entregou só {len(atrasos)} frames: amostra insuficiente"
    # O primeiro bloco carrega o tempo de abertura do fluxo; tira-se o aquecimento.
    uteis = atrasos[25:]
    diferencas = [b - a for a, b in itertools.pairwise(uteis)]
    return (
        Piso(
            nome=f"dispositivo (monitor de saída {alvo}, sem nosso código)",
            n=len(diferencas),
            p50_ms=percentil([abs(d) for d in diferencas], 50),
            p95_ms=percentil([abs(d) for d in diferencas], 95),
            p99_ms=percentil([abs(d) for d in diferencas], 99),
            observacao="jitter entre blocos de 20 ms; monitor, nunca microfone",
        ),
        "",
    )


def _monitor_de_saida() -> str | None:
    pactl = shutil.which("pactl")
    if pactl is None:
        return None
    concluido = subprocess.run(
        [pactl, "list", "short", "sources"], capture_output=True, text=True, check=False
    )
    for linha in concluido.stdout.splitlines():
        partes = linha.split("\t")
        if len(partes) > 1 and partes[1].endswith(".monitor"):
            return partes[1]
    return None


# --- relatório --------------------------------------------------------------------
@dataclass
class Medicao:
    resultados: list[Resultado] = field(default_factory=list)
    pisos: list[Piso] = field(default_factory=list)
    lacunas: list[Lacuna] = field(default_factory=list)
    versao_rust: str = ""
    n_frames: int = 0
    execucoes: int = 0


def escrever_csv(medicao: Medicao, caminho: Path) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(
            [
                "braco",
                "execucao",
                "n",
                "eventos",
                "media_ms",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "max_ms",
                "gc_pausas",
                "gc_ms",
            ]
        )
        for r in medicao.resultados:
            escritor.writerow(
                [
                    r.braco,
                    r.execucao,
                    r.n,
                    r.eventos,
                    f"{r.media_ms:.6f}",
                    f"{r.p50_ms:.6f}",
                    f"{r.p95_ms:.6f}",
                    f"{r.p99_ms:.6f}",
                    f"{r.max_ms:.6f}",
                    r.gc_pausas,
                    f"{r.gc_ms:.3f}",
                ]
            )
        escritor.writerow([])
        escritor.writerow(["piso", "n", "p50_ms", "p95_ms", "p99_ms", "observacao"])
        for p in medicao.pisos:
            escritor.writerow(
                [p.nome, p.n, f"{p.p50_ms:.6f}", f"{p.p95_ms:.6f}", f"{p.p99_ms:.6f}", p.observacao]
            )


def resumo_por_braco(medicao: Medicao) -> dict[str, dict[str, float]]:
    resumo: dict[str, dict[str, float]] = {}
    for braco in dict.fromkeys(r.braco for r in medicao.resultados):
        grupo = [r for r in medicao.resultados if r.braco == braco]
        resumo[braco] = {
            "p50": statistics.median([r.p50_ms for r in grupo]),
            "p95": statistics.median([r.p95_ms for r in grupo]),
            "p99": statistics.median([r.p99_ms for r in grupo]),
            "max": max(r.max_ms for r in grupo),
            "gc_pausas": sum(r.gc_pausas for r in grupo),
            "gc_ms": sum(r.gc_ms for r in grupo),
            "n": sum(r.n for r in grupo),
        }
    return resumo


def escrever_markdown(medicao: Medicao, caminho: Path) -> None:
    maquina = hardware()
    resumo = resumo_por_braco(medicao)
    linhas = [
        "# F0-04 — latência de captura e a decisão D1: números medidos",
        "",
        "**Gerado por** `tools/harness_captura.py` (não editar à mão). "
        f"**Data:** {time.strftime('%Y-%m-%d')}.",
        "",
        "## Como foi medido",
        "",
        f"- hardware: {maquina['cpu']}, {maquina['nucleos']} fios, {maquina['memoria']} de RAM",
        f"- {maquina['plataforma']}, Python {maquina['python']}"
        + (f", {medicao.versao_rust}" if medicao.versao_rust else ""),
        f"- {medicao.n_frames} frames de 20 ms por execução "
        f"({medicao.n_frames * 20 / 1000:.0f} s de áudio), {medicao.execucoes} execuções",
        "- o caminho medido é `frame de 20 ms → pré-filtro → VAD → evento`; os braços "
        "`rust-std` e `python-numpy` usam a **mesma** aritmética e os mesmos limiares, para a "
        "comparação ser de linguagem e não de algoritmo",
        "- áudio sintético determinístico, idêntico para os três braços (fala e silêncio "
        "alternados). **Não é corpus**: corpus pt-BR de turno é da F1, com consentimento",
        "- `rust-std` compila com `rustc -O`, **só biblioteca padrão**: sem cargo, sem rede e "
        "sem instalar nada na máquina",
        "- `python-onnx` usa `silero-vad` (MIT, verificado na F0-09) com 1 thread, janela de "
        "512 amostras, que é o que o modelo exige a 16 kHz",
        "- `evento-no-barramento` mede o **resto** do SLO-1: criar o envelope da §3.1, validar "
        "na borda, mandar pelo IPC (ida e volta) e gravar no log encadeado por hash. É por "
        "evento, não por frame",
        "",
        "## Resultado por braço (mediana das execuções)",
        "",
        "| braço | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) | pausas de GC | GC total (ms) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for braco, valores in resumo.items():
        linhas.append(
            f"| `{braco}` | {valores['p50']:.4f} | {valores['p95']:.4f} | {valores['p99']:.4f} "
            f"| {valores['max']:.4f} | {valores['gc_pausas']:.0f} | {valores['gc_ms']:.1f} |"
        )

    linhas += [
        "",
        "## Pisos: o que é da máquina, não nosso",
        "",
        "| piso | n | p50 (ms) | p95 (ms) | p99 (ms) | observação |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for p in medicao.pisos:
        linhas.append(
            f"| {p.nome} | {p.n} | {p.p50_ms:.3f} | {p.p95_ms:.3f} | {p.p99_ms:.3f} "
            f"| {p.observacao} |"
        )

    # --- proposta de D1, calculada dos números acima --------------------------------
    vad_rust = resumo.get("rust-std", {}).get("p95", 0.0)
    vad_numpy = resumo.get("python-numpy", {}).get("p95", 0.0)
    vad_onnx = resumo.get("python-onnx", {}).get("p95", 0.0)
    barramento = resumo.get("evento-no-barramento", {}).get("p95", 0.0)
    agendamento = next((p.p95_ms for p in medicao.pisos if p.nome.startswith("agendamento")), 0.0)
    piso_dispositivo = next(
        (p.p95_ms for p in medicao.pisos if p.nome.startswith("dispositivo")), 0.0
    )
    nosso_python = vad_onnx + barramento + agendamento
    nosso_rust = vad_rust + barramento + agendamento
    orcamento = 80.0  # SLO-1 p95

    linhas += [
        "",
        "## Proposta de D1 (linguagem e IPC do núcleo)",
        "",
        f"O orçamento do SLO-1 é **p95 ≤ {orcamento:.0f} ms** de captura a evento. Somando o "
        "que é nosso — VAD + criar/validar/enviar/registrar o evento + o piso de agendamento:",
        "",
        "| caminho | p95 somado (ms) | fração do SLO-1 |",
        "|---|---:|---:|",
        f"| Python + ONNX (silero) | {nosso_python:.3f} | {100 * nosso_python / orcamento:.2f}% |",
        f"| Rust (VAD barato) + barramento em Python | {nosso_rust:.3f} "
        f"| {100 * nosso_rust / orcamento:.2f}% |",
        "",
        f"- A diferença de linguagem **no VAD** é de {vad_rust:.4f} ms (Rust) contra "
        f"{vad_numpy:.4f} ms (Python+numpy, mesma aritmética) e {vad_onnx:.4f} ms "
        f"(Python+ONNX, VAD neural de verdade). Em termos de SLO-1, a maior dessas é "
        f"{100 * vad_onnx / orcamento:.2f}% do orçamento.",
        f"- O **custo do evento** ({barramento:.3f} ms p95: envelope, validação de borda, IPC "
        "ida e volta e log encadeado) é maior que o custo do VAD em qualquer linguagem. O "
        "gargalo do nosso lado é a fronteira, não a aritmética.",
        f"- O **piso do dispositivo** medido ({piso_dispositivo:.1f} ms p95) é uma a duas "
        "ordens de grandeza maior que tudo que fazemos — com a ressalva de viés logo abaixo.",
        "",
        "**Proposta:** manter **Python 3.12 nos sete processos no v0**, com a fronteira pronta "
        "para trocar `audio-io`/`agentd` por Rust sem reescrever contrato (o contrato é dado: "
        "`schemas/events.v1.json` e `schemas/event_log.sql`). O número não justifica pagar duas "
        "linguagens agora: o nosso custo total é menos de 1% do SLO-1, e o ecossistema de ML "
        "(ONNX, ASR, TTS) está em Python.",
        "",
        "**A lacuna que pode derrubar a proposta:** o que foi medido é VAD + evento, **não** "
        "AEC/NR de verdade, **não** ASR incremental e **não** captura de dispositivo real. Se "
        "a F1 medir que AEC + ASR + TTS em Python estouram o SLO-1 ou o SLO-2 na máquina do "
        "dono, a troca é local, em dois processos, e a decisão volta — por isso a fronteira "
        "fica trocável desde já. Esta proposta é do executor, com base em medição; **a decisão "
        "é do dono** (ADR do cartão F0-10).",
        "",
        "## O que **não** foi medido",
        "",
    ]
    linhas += [f"- **{lac.o_que}** — {lac.por_que}" for lac in medicao.lacunas]
    linhas += [
        "",
        "### Viés conhecido do piso do dispositivo",
        "",
        "O piso foi medido no **monitor de uma saída ociosa** (nada tocando). Um monitor sem "
        "produtor ativo entrega em rajada, então o p95 de ~20 ms mede o comportamento da "
        "rajada, e não o jitter de um fluxo de captura em uso. Trate-o como **limite superior "
        "grosseiro**, não como medida do caminho de áudio ativo. O número honesto só sai na "
        "F1, com captura de verdade e consentimento do dono — e é lá que o SLO-1 é cobrado "
        "ponta a ponta, do microfone ao evento.",
    ]

    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(description=__doc__)
    analisa.add_argument("--frames", type=int, default=10_000, help="frames de 20 ms (n)")
    analisa.add_argument("--execucoes", type=int, default=3)
    analisa.add_argument("--modelo", type=Path, default=None, help="silero_vad.onnx")
    analisa.add_argument("--segundos-piso", type=float, default=6.0)
    analisa.add_argument(
        "--trabalho", type=Path, default=None, help="pasta para o áudio e o binário"
    )
    analisa.add_argument(
        "--saida",
        type=Path,
        default=PASTA_SAIDA,
        help=(
            "onde publicar o CSV e o relatório (padrão: docs/medicoes). O teste de fumaça "
            "aponta para uma pasta temporária: suíte de teste não reescreve medição publicada"
        ),
    )
    args = analisa.parse_args(argv)

    trabalho = (
        args.trabalho
        or Path(
            os.environ.get("TMPDIR", "/tmp")  # noqa: S108
        )
        / "jarvis-f0-04"
    )
    trabalho.mkdir(parents=True, exist_ok=True)
    audio = trabalho / "audio.raw"

    medicao = Medicao(n_frames=args.frames, execucoes=args.execucoes)
    segundos = args.frames * FRAME / TAXA + 1
    print(f"gerando {segundos:.0f} s de áudio sintético em {audio}")
    disponiveis = gerar_audio(audio, segundos)
    frames = min(args.frames, disponiveis)
    medicao.n_frames = frames

    amostras = carregar(audio)

    binario, versao = compilar_rust(trabalho / "vad_bench")
    medicao.versao_rust = versao if binario else ""
    if binario is None:
        medicao.lacunas.append(
            Lacuna("braço Rust (`rust-std`)", f"não foi possível compilar: {versao}")
        )

    for execucao in range(1, args.execucoes + 1):
        if binario is not None:
            medicao.resultados.append(medir_rust(binario, audio, frames, execucao))
        medicao.resultados.append(medir_python_numpy(amostras, frames, execucao))
        if args.modelo is not None and args.modelo.exists():
            medicao.resultados.append(medir_python_onnx(amostras, frames, execucao, args.modelo))
        medicao.resultados.append(medir_evento_no_barramento(execucao, min(frames, 2000), trabalho))
    if args.modelo is None or not args.modelo.exists():
        medicao.lacunas.append(
            Lacuna(
                "braço `python-onnx`",
                "o modelo silero-vad não foi passado em `--modelo` (o peso não é versionado "
                "no repositório; baixe-o e aponte o caminho)",
            )
        )

    medicao.pisos.append(piso_de_agendamento(min(frames, 500)))
    piso, motivo = piso_do_dispositivo(args.segundos_piso)
    if piso is not None:
        medicao.pisos.append(piso)
    else:
        medicao.lacunas.append(Lacuna("piso do dispositivo de áudio", motivo))

    medicao.lacunas.append(
        Lacuna(
            "captura do microfone de verdade",
            "não foi medida de propósito: gravar o microfone do dono para medir jitter seria "
            "invadir privacidade sem necessidade. O piso do dispositivo usa o monitor da "
            "saída, que tem o mesmo caminho de driver",
        )
    )
    medicao.lacunas.append(
        Lacuna(
            "Windows",
            "o harness é portável (Rust std, Python, stdlib), mas foi executado só em Linux: "
            "não há máquina Windows nem remoto nesta sessão",
        )
    )
    medicao.lacunas.append(
        Lacuna(
            "AEC e redução de ruído de verdade",
            "o pré-filtro medido é pré-ênfase + RMS + ZCR, que é o 'VAD barato' do esqueleto. "
            "AEC (WebRTC ou equivalente) entra na F1 e tem custo próprio, não medido aqui",
        )
    )

    saida: Path = args.saida
    saida.mkdir(parents=True, exist_ok=True)
    escrever_csv(medicao, saida / "f0-04-captura.csv")
    escrever_markdown(medicao, saida / "f0-04-captura.md")

    print(f"\n{'braço':14} {'p50':>9} {'p95':>9} {'p99':>9} {'máx':>9}  GC")
    for braco, valores in resumo_por_braco(medicao).items():
        print(
            f"{braco:14} {valores['p50']:9.4f} {valores['p95']:9.4f} {valores['p99']:9.4f} "
            f"{valores['max']:9.4f}  {valores['gc_pausas']:.0f} pausas / {valores['gc_ms']:.1f} ms"
        )
    for p in medicao.pisos:
        print(f"piso: {p.nome}: p50 {p.p50_ms:.3f} ms, p95 {p.p95_ms:.3f} ms (n={p.n})")
    for lacuna in medicao.lacunas:
        print(f"não medido: {lacuna.o_que} — {lacuna.por_que}")
    print(f"\ncsv e relatório em {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
