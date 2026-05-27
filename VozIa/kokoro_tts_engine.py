# VozIa/kokoro_tts_engine.py
# -*- coding: utf-8 -*-

import sys
import threading
import warnings
import numpy as np

from config import (
    VOZ_NOME, VOZ_LANG, VOZ_REPO,
    VELOCIDADE_FALA, PITCH_TOM,
    REVERB_DELAY, REVERB_DECAY,
    SAMPLE_RATE,
)
from VozIa.tts_normalizer import normalizar as _tts_normalizar

# Silencia warnings do PyTorch / transformers
warnings.filterwarnings("ignore")

try:
    from kokoro import KPipeline
except ImportError:
    print("Erro: a biblioteca 'kokoro' não foi encontrada.")
    sys.exit(1)

try:
    import sounddevice as sd
except ImportError:
    print("Erro: 'sounddevice' não encontrado. Execute: pip install sounddevice")
    sys.exit(1)

try:
    from scipy.signal import resample_poly
    from math import gcd
    _SCIPY_OK = True
except ImportError:
    _SCIPY_OK = False

class TTSEngine:
    def __init__(self):
        print(f">>> [TTS] Inicializando Kokoro (Voz: {VOZ_NOME} | Speed: {VELOCIDADE_FALA} | Pitch: {PITCH_TOM})...")

        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self.voice = VOZ_NOME
        self.sample_rate = SAMPLE_RATE
        self.split_pattern = r'(?:[.!?]\s+)|(?:\n+)'

        try:
            self.pipeline = KPipeline(lang_code=VOZ_LANG, repo_id=VOZ_REPO)
        except Exception as e:
            print(f"Erro ao carregar modelo Kokoro: {e}")
            sys.exit(1)

        print(f">>> [TTS] Pronto. Reprodução via sounddevice.")

    def _preparar_texto(self, texto: str) -> str:
        if not texto:
            return ""
        texto = _tts_normalizar(texto)
        if texto and not texto[0].isupper():
            texto = texto[0].upper() + texto[1:]
        if texto and texto[-1] not in ".?!":
            texto += "."
        return texto

    def _aplicar_pitch(self, audio_np: np.ndarray) -> np.ndarray:
        """Pitch shift via resample_poly (scipy). Mantém duração original."""
        if not _SCIPY_OK or PITCH_TOM == 1.0:
            return audio_np
        # Fator de pitch: <1 = mais grave, >1 = mais agudo
        # Resample para sr/pitch -> depois resample de volta para sr original
        orig_len = len(audio_np)
        # up/down para resample_poly devem ser inteiros
        ratio = PITCH_TOM  # ex: 0.92
        up = 100
        down = int(round(100 / ratio))
        shifted = resample_poly(audio_np, up, down)
        # Corta ou padeia para manter mesmo comprimento
        if len(shifted) >= orig_len:
            return shifted[:orig_len].astype(np.float32)
        else:
            return np.pad(shifted, (0, orig_len - len(shifted))).astype(np.float32)

    def stop(self):
        """Interrompe a reprodução em curso."""
        self._stop_event.set()
        sd.stop()

    def speak(self, texto: str):
        if not texto:
            return

        with self._lock:
            self._stop_event.clear()
            texto_proc = self._preparar_texto(texto)

            try:
                generator = self.pipeline(
                    texto_proc,
                    voice=self.voice,
                    speed=VELOCIDADE_FALA,
                    split_pattern=self.split_pattern,
                )

                for _, _, audio in generator:
                    if self._stop_event.is_set():
                        break
                    if audio is None:
                        continue

                    chunk = audio.cpu().numpy().astype(np.float32)
                    chunk = self._aplicar_pitch(chunk)

                    # Toca o chunk e espera terminar antes do próximo
                    sd.play(chunk, samplerate=self.sample_rate)
                    sd.wait()

                    if self._stop_event.is_set():
                        break

            except Exception as e:
                print(f"Erro TTS: {e}")
