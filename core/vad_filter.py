"""Silero-VAD wrapper para filtrar áudio antes do Whisper.

Evita que respiração/ruído ambiente seja transcrito como alucinações
('Obrigado', 'Obrigado por assistir', etc.).
"""

from __future__ import annotations

import io
import wave
from typing import Optional

import numpy as np

_MODEL = None  # lazy-loaded
_AVAILABLE: Optional[bool] = None


def _ensure_model():
    """Carrega silero-vad uma única vez. Retorna o modelo ou None se falhar."""
    global _MODEL, _AVAILABLE
    if _AVAILABLE is False:
        return None
    if _MODEL is not None:
        return _MODEL
    try:
        from silero_vad import load_silero_vad  # type: ignore
        _MODEL = load_silero_vad()
        _AVAILABLE = True
        print("[VAD] silero-vad carregado.")
        return _MODEL
    except Exception as e:
        print(f"[VAD] silero-vad indisponível ({e}); pulando filtro VAD.")
        _AVAILABLE = False
        return None


def _wav_to_float32_16k(wav_bytes: bytes) -> Optional[np.ndarray]:
    """Decodifica WAV PCM → np.float32 mono em 16kHz."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            rate = w.getframerate()
            ch = w.getnchannels()
            sw = w.getsampwidth()
            n = w.getnframes()
            raw = w.readframes(n)
        if sw == 2:
            arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif sw == 4:
            arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            return None
        if ch > 1:
            arr = arr.reshape(-1, ch).mean(axis=1)
        if rate != 16000:
            # Resample linear simples (good enough para VAD)
            new_len = int(len(arr) * 16000 / rate)
            if new_len <= 0:
                return None
            x_old = np.linspace(0.0, 1.0, len(arr), endpoint=False)
            x_new = np.linspace(0.0, 1.0, new_len, endpoint=False)
            arr = np.interp(x_new, x_old, arr).astype(np.float32)
        return arr
    except Exception:
        return None


def has_speech(wav_bytes: bytes, min_speech_ms: int = 200, threshold: float = 0.5) -> bool:
    """Retorna True se houver fala humana com confiança ≥ threshold no WAV.

    Se silero não estiver disponível, retorna True (fail-open: deixa o
    Whisper decidir).
    """
    model = _ensure_model()
    if model is None:
        return True  # fail-open: silero indisponível, não bloqueia
    audio = _wav_to_float32_16k(wav_bytes)
    if audio is None or len(audio) < 320:  # < 20ms
        return False
    try:
        from silero_vad import get_speech_timestamps  # type: ignore
        import torch  # type: ignore
        ts = get_speech_timestamps(
            torch.from_numpy(audio),
            model,
            sampling_rate=16000,
            threshold=threshold,
            min_speech_duration_ms=min_speech_ms,
            return_seconds=False,
        )
        return bool(ts)
    except Exception as e:
        print(f"[VAD] erro ao processar VAD ({e}); deixando passar.")
        return True
