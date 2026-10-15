"""Política de licença do projeto, em um lugar só (ADR-0011, cartões F0-09 e F1-09).

Mora em `src/` porque deixou de ser assunto só de CI: o carregador de voz do TTS (F1-09)
**recusa em tempo de execução** uma voz cuja licença não seja permissiva, e recusar no produto
exige a política no produto. A porta de licença (`tools/license_gate.py`) usa exatamente estas
mesmas listas — uma classificação só, para o CI e o produto nunca discordarem sobre o que é
permissivo.
"""

from __future__ import annotations

import re
import tomllib
from enum import StrEnum, auto
from pathlib import Path
from typing import Final

ARQUIVO_MODELOS: Final = Path(__file__).resolve().parents[2] / "licenses" / "modelos.toml"


class Categoria(StrEnum):
    PERMISSIVA = auto()
    ATRIBUICAO = auto()
    """Uso comercial permitido, com atribuição obrigatória no produto (CC-BY, BSD-4)."""

    COPYLEFT_FORTE = auto()
    """Comercial é permitido, mas obriga abrir o derivado: aviso, não bloqueio."""

    NAO_COMERCIAL = auto()
    """Bloqueio: é o que a ADR-0011 proíbe."""

    DESCONHECIDA = auto()


PERMISSIVAS: Final[frozenset[str]] = frozenset(
    {
        "apache-2.0",
        "apache 2.0",
        "apache software license",
        "mit",
        "mit license",
        "mit-0",
        "bsd",
        "bsd-2-clause",
        "bsd-3-clause",
        "bsd license",
        "isc",
        "0bsd",
        "unlicense",
        "cc0-1.0",
        "psf-2.0",
        "python-2.0",
        "python software foundation license",
        "zlib",
        "mpl-2.0",
        "apache-2.0 or mit",
        "mit or apache-2.0",
        "bsl-1.0",
        "lgpl-2.1-or-later",
        "lgpl-3.0-or-later",
    }
)
ATRIBUICAO_OBRIGATORIA: Final[frozenset[str]] = frozenset(
    {"cc-by-4.0", "cc-by-3.0", "cc-by-sa-4.0", "bsd-4-clause", "openrail", "cdla-permissive-2.0"}
)
COPYLEFT_FORTE: Final[frozenset[str]] = frozenset(
    {"gpl-2.0", "gpl-3.0", "gpl-3.0-only", "gpl-3.0-or-later", "agpl-3.0", "sspl-1.0"}
)
PADROES_NAO_COMERCIAIS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bnon-?commercial\b"),
    re.compile(r"\bnc\b"),
    re.compile(r"cc-by-nc"),
    re.compile(r"\bresearch[\s-]*(only|purposes)\b"),
    re.compile(r"polyform[\s-]*(noncommercial|non-commercial)"),
    re.compile(r"coqui[\s-]*public[\s-]*model[\s-]*license|\bcpml\b"),
    re.compile(r"creativeml[\s-]*openrail[\s-]*m-nc"),
)


PADROES_POR_NOME: Final[tuple[tuple[re.Pattern[str], Categoria], ...]] = (
    # Nome livre em vez de SPDX: muito pacote ainda escreve a licença em prosa.
    # A ordem importa: "lesser general public" tem de ser vista antes de "gpl".
    (re.compile(r"lesser general public|\blgpl\b"), Categoria.PERMISSIVA),
    (re.compile(r"mozilla public license|\bmpl[\s-]*2"), Categoria.PERMISSIVA),
    (re.compile(r"\bapache\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bmit\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bbsd\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bisc\b"), Categoria.PERMISSIVA),
    (re.compile(r"python software foundation|\bpsf\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bzlib\b|\bunlicense\b|public domain|\bcc0\b"), Categoria.PERMISSIVA),
    (re.compile(r"\bboost software license\b"), Categoria.PERMISSIVA),
    (re.compile(r"creative commons attribution(?!.*non)|\bcc[\s-]*by\b"), Categoria.ATRIBUICAO),
    (re.compile(r"affero|\bagpl\b|\bsspl\b|gnu general public|\bgpl\b"), Categoria.COPYLEFT_FORTE),
)


def classificar(licenca: str | None) -> Categoria:
    """Categoria de uma licença a partir do texto declarado (SPDX ou nome)."""
    if licenca is None:
        return Categoria.DESCONHECIDA
    texto = licenca.strip().lower()
    if not texto or texto in {"unknown", "other", "none", "proprietary"}:
        return Categoria.DESCONHECIDA
    if any(padrao.search(texto) for padrao in PADROES_NAO_COMERCIAIS):
        return Categoria.NAO_COMERCIAL
    if texto in PERMISSIVAS:
        return Categoria.PERMISSIVA
    if texto in ATRIBUICAO_OBRIGATORIA:
        return Categoria.ATRIBUICAO
    if texto in COPYLEFT_FORTE:
        return Categoria.COPYLEFT_FORTE
    for padrao, categoria in PADROES_POR_NOME:
        if padrao.search(texto):
            return categoria
    return Categoria.DESCONHECIDA


def licenca_registrada(identificador: str, *, arquivo: Path = ARQUIVO_MODELOS) -> str | None:
    """Licença de um modelo **pelo registro**, não pelo que o chamador afirma.

    Devolve `None` quando o modelo não está registrado — e quem carrega modelo não registrado
    tem de recusar: licença que ninguém verificou não é licença permissiva por otimismo.
    """
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    for modelo in dados.get("modelo", []):
        if str(modelo["id"]) == identificador:
            return str(modelo["licenca"])
    return None


def estado_registrado(identificador: str, *, arquivo: Path = ARQUIVO_MODELOS) -> str | None:
    """Estado do registro (`candidato`, `em_uso`, `barrado`), ou `None` se não registrado."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    for modelo in dados.get("modelo", []):
        if str(modelo["id"]) == identificador:
            return str(modelo.get("estado", "candidato"))
    return None
