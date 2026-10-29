"""Delegar ao Claude Code do dono o que o Jarvis não deu conta no navegador (ADR-0054).

Fora de `executor`/`policy` de propósito: abre processo filho (o `claude`), e o executor mantém a
invariante de não ter caminho para shell (`test_sem_shell`, F0-03)."""

from jarvis.delegacao.claude_code import Codigo, DelegadorClaudeCode, Resultado
from jarvis.delegacao.config import (
    ConfiguracaoDaDelegacao,
    ConfiguracaoDaDelegacaoInvalida,
    carregar_delegacao,
)

__all__ = [
    "Codigo",
    "ConfiguracaoDaDelegacao",
    "ConfiguracaoDaDelegacaoInvalida",
    "DelegadorClaudeCode",
    "Resultado",
    "carregar_delegacao",
]
