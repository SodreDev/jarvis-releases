"""Fixtures comuns a todos os testes."""

from __future__ import annotations

import pytest

from jarvis.barramento import uuid7


@pytest.fixture
def sessao() -> str:
    """Identificador de sessão válido (uuid v7, §3.1)."""
    return uuid7()
