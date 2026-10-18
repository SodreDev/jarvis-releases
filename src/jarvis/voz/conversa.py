"""A conversa que sobrevive ao reinício, vista da janela (ADR-0019, ADR-0026).

A janela não importa `jarvis.memoryd` (a fronteira da ADR-0019 é verificada por `import`): ela
chega ao histórico **pelo laço**. Este módulo é essa porta — os mesmos nomes de
`jarvis.memoryd.conversa`, que é onde a lógica mora.
"""

from __future__ import annotations

from jarvis.memoryd.conversa import ConversaPersistente as ConversaPersistente
from jarvis.memoryd.conversa import abrir_conversa as abrir_conversa

__all__ = ["ConversaPersistente", "abrir_conversa"]
