"""Diagnóstico do STT na SUA máquina e na SUA voz (ADR-0067) — para o dono rodar, não a suíte.

O `tools/harness_stt.py` mede com voz sintética; o que só você pode medir é a sua voz, o seu
microfone e a sua placa de vídeo. Grave três ou quatro frases curtas (o áudio fica com você; este
script não grava nada sozinho, não manda nada para a rede e não guarda texto):

    arecord -f S16_LE -r 16000 -c 1 -d 3 ~/mae.wav        # diga: «abre o contato da minha mãe»
    arecord -f S16_LE -r 16000 -c 1 -d 3 ~/zap.wav        # diga: «manda mensagem no WhatsApp»
    nice -n 19 uv run --frozen python -m tools.diagnostico_stt ~/mae.wav ~/zap.wav

Ele diz: (1) se a placa de vídeo pode rodar o whisper (CUDA + cuBLAS) e o que falta se não pode;
(2) para cada configuração (modelo, beam, dica), o que cada arquivo virou e quanto demorou; (3) a
mesma frase depois da reconciliação por som (`jarvis.voz.reconciliar`). Mande a saída para quem
estiver cuidando do STT — ela tem o que você disse, então só se quiser.
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from jarvis.voz.dica import dica_do_asr
from jarvis.voz.reconciliar import Reconciliador

CONFIGS = (
    # (modelo, beam, dica)
    ("small", 1, "lista"),
    ("small", 5, "lista"),
    ("medium", 5, "lista"),
    ("large-v3-turbo", 5, "lista"),
)


def ler_wav(caminho: Path) -> np.ndarray:
    with wave.open(str(caminho), "rb") as arquivo:
        if arquivo.getsampwidth() != 2:
            raise SystemExit(f"{caminho}: precisa ser PCM de 16 bits (arecord -f S16_LE)")
        quadros = arquivo.readframes(arquivo.getnframes())
        canais, taxa = arquivo.getnchannels(), arquivo.getframerate()
    audio = np.frombuffer(quadros, dtype="<i2").astype(np.float32) / 32768.0
    if canais > 1:
        audio = audio.reshape(-1, canais).mean(axis=1)
    if taxa != 16000:
        n = int(len(audio) * 16000 / taxa)
        audio = np.interp(np.arange(n) * taxa / 16000, np.arange(len(audio)), audio).astype(
            np.float32
        )
    return audio


def placa_de_video() -> str:
    """CUDA pronta para o CTranslate2? Diz o que falta, sem instalar nada."""
    try:
        import ctranslate2  # type: ignore[import-untyped]
    except ImportError:
        return "faster-whisper não instalado (uv sync --group asr)"
    if ctranslate2.get_cuda_device_count() == 0:
        return "nenhuma GPU CUDA visível: o whisper roda na CPU"
    try:
        from faster_whisper import WhisperModel

        modelo = WhisperModel("tiny", device="cuda", compute_type="float16")
        list(modelo.transcribe(np.zeros(16000, dtype=np.float32), language="pt")[0])
    except Exception as erro:  # a mensagem do runtime é o diagnóstico
        return (
            f"GPU visível, mas o whisper não roda nela: {type(erro).__name__}: {erro}. "
            "Falta a cuBLAS 12 (libcublas.so.12) — `uv pip install nvidia-cublas-cu12` no venv "
            "ou o pacote cuda-cublas-12 do sistema."
        )
    return "GPU pronta: o whisper pode rodar em CUDA (float16)"


def main(argv: Sequence[str] | None = None) -> int:
    analisa = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    analisa.add_argument("wavs", nargs="+", type=Path)
    analisa.add_argument("--palavra", default="jarvis")
    analisa.add_argument("--termo", action="append", default=[], help="termo do seu vocabulário")
    analisa.add_argument("--threads", type=int, default=4)
    analisa.add_argument("--so-small", action="store_true", help="pula medium e turbo (rápido)")
    args = analisa.parse_args(argv)
    from faster_whisper import WhisperModel

    print(f"placa de vídeo: {placa_de_video()}\n")
    audios = {caminho.name: ler_wav(caminho) for caminho in args.wavs}
    dicas = {"lista": dica_do_asr(args.palavra, args.termo)}
    reconciliador = Reconciliador.do_contexto()
    for modelo_nome, beam, dica in CONFIGS:
        if args.so_small and modelo_nome != "small":
            continue
        comeco = time.perf_counter()
        modelo = WhisperModel(
            modelo_nome, device="cpu", compute_type="int8", cpu_threads=args.threads
        )
        carga = time.perf_counter() - comeco
        print(f"== {modelo_nome}, beam {beam}, dica {dica} (carregou em {carga:.1f} s)")
        for nome, audio in audios.items():
            comeco = time.perf_counter()
            trechos, _ = modelo.transcribe(
                audio,
                language="pt",
                beam_size=beam,
                vad_filter=False,
                initial_prompt=dicas[dica] or None,
            )
            texto = " ".join(t.text for t in trechos).strip()
            ms = (time.perf_counter() - comeco) * 1000
            corrigido = reconciliador.reconciliar(texto).texto
            depois = f"  → reconciliado: {corrigido!r}" if corrigido != texto else ""
            print(f"  {nome}: {texto!r} ({ms:.0f} ms){depois}")
        del modelo
    return 0


if __name__ == "__main__":
    sys.exit(main())
