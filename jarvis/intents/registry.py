"""Registry de intents.

Cada domínio (spotify, sistema, mensageria, etc.) registra detectores aqui.
Um detector é uma função `(texto) -> IntentMatch | None`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass
class IntentMatch:
    name: str                # ex.: "spotify.pause"
    domain: str              # ex.: "spotify"
    confidence: float = 1.0  # 1.0 p/ regex; 0–1 p/ classificadores
    payload: dict[str, Any] = field(default_factory=dict)


Detector = Callable[[str], IntentMatch | None]


class IntentRegistry:
    def __init__(self) -> None:
        self._detectors: list[tuple[str, Detector]] = []

    def register(self, domain: str, detector: Detector) -> None:
        self._detectors.append((domain, detector))

    def detect(self, text: str) -> IntentMatch | None:
        for _domain, det in self._detectors:
            try:
                m = det(text)
            except Exception:
                continue
            if m is not None:
                return m
        return None

    def detect_all(self, text: str) -> list[IntentMatch]:
        out: list[IntentMatch] = []
        for _domain, det in self._detectors:
            try:
                m = det(text)
            except Exception:
                continue
            if m is not None:
                out.append(m)
        return out

    def domains(self) -> Iterable[str]:
        return sorted({d for d, _ in self._detectors})


_registry: IntentRegistry | None = None


def get_registry() -> IntentRegistry:
    global _registry
    if _registry is None:
        _registry = IntentRegistry()
        _bootstrap(_registry)
    return _registry


def _bootstrap(reg: IntentRegistry) -> None:
    # importãoes tardias p/ evitar ciclos.
    # ORDEM IMPORTA: detectores mais específicos primeiro.
    from . import mensageria, sistema, spotify

    mensageria.register_into(reg)   # tem palavra de plataforma → mais específico
    sistema.register_into(reg)      # comandos do SO
    spotify.register_into(reg)      # música (fallback amplo)


__all__ = ["IntentMatch", "IntentRegistry", "Detector", "get_registry"]
