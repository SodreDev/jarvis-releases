"""Ferramental de manifesto de capacidade (SPEC §4; cartão F0-07).

O manifesto é verificado por máquina, não por boa vontade: `validador` recusa manifesto
incompleto, `lint` recusa catálogo que viole as regras da §4 e da ADR-0010, e `codegen` gera
o stub tipado a partir do contrato — para o executor não inventar assinatura.
"""

from jarvis.manifesto.codegen import gerar_stub
from jarvis.manifesto.lint import Achado, lintar_catalogo
from jarvis.manifesto.validador import (
    ARQUIVO_SCHEMA,
    ManifestoInvalido,
    carregar_manifesto,
    validar_manifesto,
)

__all__ = [
    "ARQUIVO_SCHEMA",
    "Achado",
    "ManifestoInvalido",
    "carregar_manifesto",
    "gerar_stub",
    "lintar_catalogo",
    "validar_manifesto",
]
