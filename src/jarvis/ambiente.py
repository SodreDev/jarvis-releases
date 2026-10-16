"""Variáveis de ambiente que mais de um pacote precisa, num lugar só.

Nasceu com o `CI`: a proibição de abrir dispositivo real sob CI (cartão F1-01) e a de abrir
**rede** (cartão F1-14) são a mesma ideia — a recusa mora no código de produção, não numa
fixture —, e as duas precisavam do mesmo `em_ci`. Deixar a função dentro de `audio_io` obrigaria
`jarvis.rede` a importar o pacote de áudio para saber se está em CI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

VARIAVEL_CI: Final = "CI"
VALORES_VERDADEIROS: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on", "sim"})


def ambiente_ou_os(ambiente: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if ambiente is None else ambiente


def verdadeiro(valor: str | None) -> bool:
    return (valor or "").strip().lower() in VALORES_VERDADEIROS


def em_ci(ambiente: Mapping[str, str] | None = None) -> bool:
    return verdadeiro(ambiente_ou_os(ambiente).get(VARIAVEL_CI))
