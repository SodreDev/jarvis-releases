"""A persona do Jarvis: o prompt de sistema versionado em arquivo (dono, 2026-10-18).

O texto mora em `persona.md`, ao lado deste módulo, e é lido **em execução** — mudar o jeito do
Jarvis falar é editar o arquivo e subir a `versao` do cabeçalho, sem tocar em código. Vai no
pacote (`src/jarvis/` inteiro vai no wheel), então vale instalado também.

O cabeçalho (`---` … `---`) é só metadado (`versao`, `atualizada`) e **não** vai para o modelo.
A versão entra no log do turno, para um comportamento estranho ser ligado ao texto que o causou.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

ARQUIVO: Final = Path(__file__).with_name("persona.md")
DELIMITADOR: Final = "---"


class PersonaInvalida(ValueError):
    """O arquivo da persona não tem cabeçalho legível ou está vazio."""


@dataclass(frozen=True, slots=True)
class Persona:
    versao: int
    atualizada: str
    texto: str


def ler(arquivo: Path = ARQUIVO) -> Persona:
    bruto = arquivo.read_text(encoding="utf-8")
    linhas = bruto.splitlines()
    if not linhas or linhas[0].strip() != DELIMITADOR:
        raise PersonaInvalida(f"{arquivo.name}: falta o cabeçalho `---` com a versão")
    try:
        fim = next(i for i in range(1, len(linhas)) if linhas[i].strip() == DELIMITADOR)
    except StopIteration:
        raise PersonaInvalida(f"{arquivo.name}: cabeçalho sem o `---` que o fecha") from None
    cabecalho: dict[str, str] = {}
    for linha in linhas[1:fim]:
        chave, separador, valor = linha.partition(":")
        if separador:
            cabecalho[chave.strip()] = valor.strip()
    try:
        versao = int(cabecalho["versao"])
    except (KeyError, ValueError):
        raise PersonaInvalida(f"{arquivo.name}: `versao` ausente ou não é inteiro") from None
    texto = "\n".join(linhas[fim + 1 :]).strip()
    if not texto:
        raise PersonaInvalida(f"{arquivo.name}: sem texto depois do cabeçalho")
    return Persona(versao=versao, atualizada=cabecalho.get("atualizada", ""), texto=texto)


@lru_cache(maxsize=1)
def persona_do_jarvis() -> Persona:
    """A persona do produto, lida uma vez por processo."""
    return ler()


def prompt_de_sistema() -> str:
    return persona_do_jarvis().texto
