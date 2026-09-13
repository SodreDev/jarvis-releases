"""
Voice control — integra os comandos de voz do Jarvis com o sistema de gestos.

Mapeia frases de voz para modos de interação e ações do workspace 3D.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable

from gesture_interface.config import VOICE_PHRASES
from gesture_interface.interaction.mode_classifier import ModeClassifier


def _normalize(text: str) -> str:
    """Remove acentos e converte para minúsculas."""
    nfkd = unicodedata.normalize("NFKD", text.lower().strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# ── Regex para detecção de comandos do gesture interface ─────────────────
_RE_GESTURE_MODE = re.compile(
    r"\b(?:modo\s+completo|interface\s+total|ativar\s+interface\s+total"
    r"|modo\s+controle|controlar\s+tela"
    r"|modo\s+desenho|controle\s+com\s+desenho"
    r"|modo\s+design|abrir\s+est[uú]dio\s+3d)\b",
    re.I,
)

_RE_GESTURE_ON = re.compile(
    r"\b(?:ativar?|iniciar?|ligar?)\s+(?:gestos?|interface\s+gestual|controle\s+gestual)\b",
    re.I,
)

_RE_GESTURE_OFF = re.compile(
    r"\b(?:desativar?|parar?|desligar?|fechar?)\s+(?:gestos?|interface\s+gestual|controle\s+gestual)\b",
    re.I,
)

_RE_CREATE_OBJECT = re.compile(
    r"\b(?:cri[ae]r?|criar?|gerar?)\s+(?:um\s+)?(\w+)\b",
    re.I,
)

_RE_SCALE_OBJECT = re.compile(
    r"\b(?:escalar?|redimensionar?|aumentar?|diminuir?)\s+(?:o\s+)?objeto\b",
    re.I,
)

_RE_RECORD_GESTURE = re.compile(
    r"\b(?:gravar?|registrar?|salvar?)\s+(?:novo\s+)?gesto\b",
    re.I,
)


class VoiceCommands:
    """
    Processa comandos de voz relacionados ao sistema de gestos.
    Integra-se com o fluxo de _detectar_comando_sistema do main.py.
    """

    def __init__(self, classifier: ModeClassifier) -> None:
        self._classifier = classifier
        self._gesture_system_active = False

    def detect(self, text: str) -> tuple[str, str] | None:
        """
        Tenta detectar um comando do gesture interface no texto.
        Retorna (action, arg) ou None se não reconhecido.

        Actions possíveis:
            "gesture_mode"    — muda o modo (arg = nome do modo)
            "gesture_on"      — ativa o sistema de gestos
            "gesture_off"     — desativa o sistema de gestos
            "gesture_create"  — cria objeto 3D (arg = shape)
            "gesture_scale"   — escala objeto selecionado
            "gesture_record"  — inicia gravação de gesto
        """
        tl = _normalize(text)

        # ── On / Off ────────────────────────────────────────────────────
        if _RE_GESTURE_ON.search(tl):
            return ("gesture_on", "")

        if _RE_GESTURE_OFF.search(tl):
            return ("gesture_off", "")

        # ── Mode switch ─────────────────────────────────────────────────
        if _RE_GESTURE_MODE.search(tl):
            mode = self._match_mode(tl)
            if mode:
                return ("gesture_mode", mode)

        # ── 3D commands ─────────────────────────────────────────────────
        m = _RE_CREATE_OBJECT.search(tl)
        if m:
            shape = m.group(1).lower()
            # Mapear comandos em português para shapes
            shape_map = {
                "cubo": "cube", "esfera": "sphere", "cilindro": "cylinder",
                "cube": "cube", "sphere": "sphere", "cylinder": "cylinder",
            }
            mapped = shape_map.get(shape)
            if mapped:
                return ("gesture_create", mapped)

        if _RE_SCALE_OBJECT.search(tl):
            return ("gesture_scale", "")

        if _RE_RECORD_GESTURE.search(tl):
            return ("gesture_record", "")

        return None

    def _match_mode(self, text_normalized: str) -> str | None:
        """Identifica qual modo corresponde ao texto."""
        for mode, phrases in VOICE_PHRASES.items():
            for phrase in phrases:
                if _normalize(phrase) in text_normalized:
                    return mode
        return None

    def execute(self, action: str, arg: str) -> str:
        """
        Executa a ação identificada. Retorna mensagem de resposta.
        """
        if action == "gesture_on":
            self._gesture_system_active = True
            return "Interface gestual ativada, Senhor."

        if action == "gesture_off":
            self._gesture_system_active = False
            return "Interface gestual desativada, Senhor."

        if action == "gesture_mode":
            try:
                state = self._classifier.set_mode(arg)
                modules = []
                if state.desktop:
                    modules.append("desktop")
                if state.canvas2d:
                    modules.append("canvas 2D")
                if state.workspace3d:
                    modules.append("workspace 3D")
                active = ", ".join(modules) if modules else "nenhum"
                return f"Modo {arg} ativado. Módulos: {active}."
            except ValueError:
                return f"Modo '{arg}' não reconhecido, Senhor."

        if action == "gesture_create":
            return f"create_object:{arg}"  # sinaliza ao main para chamar workspace3d

        if action == "gesture_scale":
            return "scale_object"

        if action == "gesture_record":
            return "record_gesture_start"

        return "Comando gestual não reconhecido."

    @property
    def is_active(self) -> bool:
        return self._gesture_system_active
