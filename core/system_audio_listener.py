"""
System Audio Listener — captura o áudio do computador (loopback WASAPI) e
transcreve via Groq Whisper para que o JARVIS tenha contexto sobre o que está
sendo ouvido: vídeos, músicas, chamadas, etc.

Fluxo:
    WASAPI loopback → chunks de CHUNK_S segundos
    → filtro de energia (descarta silêncio)
    → transcribe_cb(wav_bytes) → texto
    → ambient_listener.feed_utterance(texto, speaker_id="system")
    → ProactiveEngine pode reagir (vide SYSTEM_AUDIO_REACT_CHANCE)

Uso no main.py:
    from core import system_audio_listener as _sal
    _sal.start(transcribe_cb=self._quick_transcribe)

Dependência: pip install pyaudiowpatch
"""
from __future__ import annotations

import io
import struct
import threading
import time
import wave
from typing import Callable, Optional

import config as _cfg

# ── Estado ─────────────────────────────────────────────────────────────────

_RUNNING = False
_THREAD: Optional[threading.Thread] = None
_LOCK = threading.RLock()
_TRANSCRIBE_CB: Optional[Callable[[bytes], str]] = None

DEPS_OK = False
_ERR_MSG = ""

try:
    import pyaudiowpatch as _pa
    import numpy as _np
    DEPS_OK = True
except ImportError as _e:
    _ERR_MSG = str(_e)

print(f"[SysAudio] Módulo carregado (DEPS_OK={DEPS_OK}"
      + (f" err={_ERR_MSG}" if not DEPS_OK else "") + ")")


# ── API pública ────────────────────────────────────────────────────────────


def start(transcribe_cb: Callable[[bytes], str]) -> str:
    """
    Inicia captura de loopback.

    Args:
        transcribe_cb: callable que recebe bytes WAV e devolve texto.
                       Use `jarvis._quick_transcribe` — já tem VAD + prompt.

    Retorna string de status para exibir no chat.
    """
    global _RUNNING, _THREAD, _TRANSCRIBE_CB
    print(f"[SysAudio] start() chamado. DEPS_OK={DEPS_OK}")
    if not DEPS_OK:
        return f"Áudio do sistema indisponível: {_ERR_MSG}"
    with _LOCK:
        if _RUNNING:
            return "Já estou ouvindo o áudio do sistema, Senhor."
        _TRANSCRIBE_CB = transcribe_cb
        _RUNNING = True
        _THREAD = threading.Thread(
            target=_loop, daemon=True, name="sys-audio-listener"
        )
        _THREAD.start()
    return "Ouço o áudio do sistema agora, Senhor."


def stop() -> str:
    global _RUNNING
    with _LOCK:
        _RUNNING = False
    return "Parei de ouvir o áudio do sistema."


def is_running() -> bool:
    return _RUNNING


# ── Loop de captura ────────────────────────────────────────────────────────


def _loop() -> None:
    """Roda em thread daemon. Captura loopback, transcreve e publica."""
    global _RUNNING

    chunk_s: float = float(getattr(_cfg, "SYSTEM_AUDIO_CHUNK_S", 6))
    min_rms: float = float(getattr(_cfg, "SYSTEM_AUDIO_MIN_RMS", 300))

    p = _pa.PyAudio()
    stream = None
    device_info = None

    try:
        # ── Encontra dispositivo de loopback padrão ─────────────────────────
        wasapi_info = p.get_host_api_info_by_type(_pa.paWASAPI)
        default_out_idx = wasapi_info["defaultOutputDevice"]
        default_speakers = p.get_device_info_by_index(default_out_idx)

        # pyaudiowpatch marca dispositivos de loopback com "isLoopbackDevice"
        if not default_speakers.get("isLoopbackDevice", False):
            found = None
            for loopback in p.get_loopback_device_info_generator():
                if default_speakers["name"] in loopback["name"]:
                    found = loopback
                    break
            if found is None:
                # Fallback: primeiro loopback disponível
                for loopback in p.get_loopback_device_info_generator():
                    found = loopback
                    break
            if found is None:
                print("[SysAudio] Nenhum dispositivo de loopback encontrado.")
                _RUNNING = False
                return
            device_info = found
        else:
            device_info = default_speakers

        channels = int(device_info.get("maxInputChannels", 2)) or 2
        sample_rate = int(device_info.get("defaultSampleRate", 44100))
        frames_per_buffer = 512

        print(
            f"[SysAudio] Loop iniciado. Dispositivo: '{device_info['name']}' "
            f"{channels}ch @ {sample_rate}Hz  chunk={chunk_s}s  min_rms={min_rms}"
        )

        stream = p.open(
            format=_pa.paInt16,
            channels=channels,
            rate=sample_rate,
            frames_per_buffer=frames_per_buffer,
            input=True,
            input_device_index=device_info["index"],
        )

        frames_per_chunk = int(sample_rate * chunk_s)

        while _RUNNING:
            # ── Coleta um chunk ────────────────────────────────────────────
            frames = []
            collected = 0
            while collected < frames_per_chunk and _RUNNING:
                to_read = min(frames_per_buffer, frames_per_chunk - collected)
                try:
                    data = stream.read(to_read, exception_on_overflow=False)
                    frames.append(data)
                    collected += to_read
                except Exception as e:
                    print(f"[SysAudio] Erro na leitura: {e}")
                    time.sleep(0.1)

            if not _RUNNING:
                break

            raw = b"".join(frames)

            # ── Filtro de energia ─────────────────────────────────────────
            rms = _compute_rms_int16(raw)
            if rms < min_rms:
                continue  # silêncio / música muito baixa — ignora

            # ── Converte para WAV mono 16kHz para Whisper ─────────────────
            wav_bytes = _to_wav_mono(raw, sample_rate, channels)
            if not wav_bytes:
                continue

            # ── Transcreve ────────────────────────────────────────────────
            cb = _TRANSCRIBE_CB
            if cb is None:
                continue
            try:
                texto = cb(wav_bytes)
            except Exception as e:
                print(f"[SysAudio] transcribe_cb falhou: {e}")
                continue

            if not texto or not texto.strip():
                continue

            # ── Publica no ambient listener ───────────────────────────────
            try:
                from core import ambient_listener as _al
                _al.feed_utterance(texto.strip(), speaker_id="system")
                print(f"[SysAudio] → '{texto.strip()[:80]}'")
            except Exception as e:
                print(f"[SysAudio] feed_utterance falhou: {e}")

    except Exception as e:
        print(f"[SysAudio] Erro fatal no loop: {e}")
    finally:
        _RUNNING = False
        try:
            if stream:
                stream.stop_stream()
                stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass
        print("[SysAudio] Loop encerrado.")


# ── Helpers de áudio ───────────────────────────────────────────────────────


def _compute_rms_int16(raw: bytes) -> float:
    """RMS de PCM int16 bruto (multi-channel OK — usa todos os samples)."""
    n = len(raw) // 2
    if n == 0:
        return 0.0
    try:
        samples = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32)
        return float(_np.sqrt(_np.mean(samples ** 2)))
    except Exception:
        return 0.0


def _to_wav_mono(raw: bytes, sample_rate: int, channels: int) -> bytes:
    """
    Converte PCM int16 multi-channel → WAV mono 16kHz.
    Usa numpy para mix-down e scipy/resampy se disponível, senão decimação
    simples (suficiente para Whisper que é robusto a sample rates).
    """
    try:
        samples = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32)

        # Mix-down para mono (média dos canais)
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)

        # Resample para 16 kHz se necessário
        target_rate = 16000
        if sample_rate != target_rate:
            ratio = target_rate / sample_rate
            new_len = int(len(samples) * ratio)
            # Resample simples por interpolação linear (audioop foi removido em 3.13)
            old_indices = _np.linspace(0, len(samples) - 1, new_len)
            samples = _np.interp(old_indices, _np.arange(len(samples)), samples)

        # Clip e converte de volta para int16
        samples = _np.clip(samples, -32768, 32767).astype(_np.int16)

        # Serializa como WAV
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(target_rate)
            wf.writeframes(samples.tobytes())
        return buf.getvalue()
    except Exception as e:
        print(f"[SysAudio] _to_wav_mono falhou: {e}")
        return b""
