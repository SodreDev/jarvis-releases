"""Onde estão os arquivos de dados do produto quando não há repositório em volta (ADR-0020).

**O problema, que só aparece no dia do pacote.** Metade das decisões deste projeto mora em
arquivo de dados, não em código: o registro de motores (ADR-0017), a tabela de licenças
(ADR-0011), o roteamento do barramento, os pesos do S1, o catálogo de capacidades. Cada módulo
achava o seu com `Path(__file__).parents[3] / "licenses" / ...`, o que é exato **dentro da
árvore** e errado em qualquer instalação: em `site-packages`, três níveis acima é outra coisa.
Sem isto, o aplicativo instalado subiria e morreria na primeira tela que lista motores.

A procura é declarada, nesta ordem, e quem não acha devolve o caminho da árvore — para a
mensagem de erro apontar para algum lugar que faça sentido:

1. `$JARVIS_DADOS`, que o empacotador define (`AppRun`, `.deb`, `.rpm`);
2. a raiz do repositório, quando o código roda de dentro dele (desenvolvimento, CI, teste);
3. `<prefixo>/share/jarvis`, o lugar do padrão de instalação.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

VARIAVEL: Final = "JARVIS_DADOS"
PASTA_INSTALADA: Final = "share/jarvis"


def raiz_do_repositorio() -> Path | None:
    """A raiz da árvore de código, quando o Jarvis roda de dentro dela."""
    candidato = Path(__file__).resolve().parents[2]
    return candidato if (candidato / "pyproject.toml").exists() else None


def bases() -> tuple[Path, ...]:
    """As pastas onde um arquivo de dado pode estar, na ordem em que são procuradas."""
    encontradas: list[Path] = []
    declarada = os.environ.get(VARIAVEL, "").strip()
    if declarada:
        encontradas.append(Path(declarada))
    raiz = raiz_do_repositorio()
    if raiz is not None:
        encontradas.append(raiz)
    encontradas.append(Path(sys.prefix) / PASTA_INSTALADA)
    return tuple(encontradas)


def caminho(relativo: str) -> Path:
    """O arquivo de dado `relativo` (ex.: `licenses/motores.toml`), onde quer que ele esteja."""
    for base in bases():
        candidato = base / relativo
        if candidato.exists():
            return candidato
    return bases()[0] / relativo


def pasta_de_dados() -> Path | None:
    """A base que está valendo agora — `None` quando nenhuma existe (instalação quebrada)."""
    return next((base for base in bases() if base.is_dir()), None)
