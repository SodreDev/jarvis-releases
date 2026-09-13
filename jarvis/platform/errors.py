"""Erros da camada jarvis.platform."""
from __future__ import annotations

from typing import List, Tuple


class CapabilityUnavailable(Exception):
    """Nenhuma implementação de uma capacidade pôde ser resolvida no contexto atual.

    Atributos:
        cap: a capacidade pedida (jarvis.platform.capabilities.Cap).
        tried: lista de (caminho, motivo) das tentativas que falharam.
    """

    def __init__(self, cap, tried: List[Tuple[str, str]] | None = None):
        self.cap = cap
        self.tried: List[Tuple[str, str]] = list(tried or [])
        cap_name = getattr(cap, "value", cap)
        detalhe = "; ".join(f"{caminho} ({motivo})" for caminho, motivo in self.tried)
        msg = f"capacidade '{cap_name}' indisponível neste contexto"
        if detalhe:
            msg += f"; tentativas: {detalhe}"
        super().__init__(msg)
