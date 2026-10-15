"""Canonicalização de caminho antes de qualquer comparação (SPEC §5.5).

Duas grafias do mesmo caminho **não podem** produzir decisões diferentes — é assim que
lista de negação é burlada na prática. As regras de forma são puramente lexicais, então
valem e são testáveis nos dois sistemas: a análise de um caminho do Windows roda em Linux
igual, e é isso que permite provar o aceite (f) do cartão F0-06 sem máquina Windows.

O que **não** é lexical (abrir por descritor, identidade do arquivo, nome 8.3 de verdade)
está em `descritor.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final


class Sistema(StrEnum):
    POSIX = "posix"
    WINDOWS = "windows"


class CaminhoRecusado(ValueError):
    """Forma de caminho que a política recusa antes de olhar raiz ou permissão."""


DISPOSITIVOS_RESERVADOS: Final[frozenset[str]] = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        "clock$",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)
NOME_8_3: Final = re.compile(r"^[^.]{1,6}~[0-9]+(\.[^.]{1,3})?$", re.IGNORECASE)
CARACTERES_INVALIDOS_WINDOWS: Final = '<>"|?*'
CONTROLE: Final = re.compile(r"[\x00-\x1f]")


@dataclass(frozen=True, slots=True)
class CaminhoCanonico:
    """Resultado da canonicalização: o que a política compara."""

    texto: str
    """Forma canônica, já normalizada em unicode (e em caixa, no Windows)."""

    partes: tuple[str, ...]
    """Componentes, do mais externo ao mais interno, sem `.` nem `..`."""

    absoluto: bool
    sistema: Sistema

    def dentro_de(self, raiz: CaminhoCanonico) -> bool:
        return self.partes[: len(raiz.partes)] == raiz.partes

    def relativo_a(self, raiz: CaminhoCanonico) -> tuple[str, ...]:
        if not self.dentro_de(raiz):
            raise CaminhoRecusado(f"{self.texto} está fora de {raiz.texto}")
        return self.partes[len(raiz.partes) :]


def normalizar_unicode(texto: str) -> str:
    """NFC — forma única para o mesmo texto (§5.5 "normalização unicode").

    Sem isso, `café` em NFD e em NFC são strings diferentes para a lista de negação e iguais
    para o olho de quem lê o log.
    """
    return unicodedata.normalize("NFC", texto)


def canonicalizar(caminho: str, sistema: Sistema) -> CaminhoCanonico:
    if sistema is Sistema.WINDOWS:
        return _canonicalizar_windows(caminho)
    return _canonicalizar_posix(caminho)


def _comum(caminho: str) -> str:
    if not caminho:
        raise CaminhoRecusado("caminho vazio")
    texto = normalizar_unicode(caminho)
    if "\x00" in texto:
        raise CaminhoRecusado("caminho com byte nulo")
    if CONTROLE.search(texto):
        raise CaminhoRecusado("caminho com caractere de controle")
    return texto


def _resolver_partes(partes: tuple[str, ...], *, absoluto: bool) -> tuple[str, ...]:
    """Resolve `.` e `..` lexicalmente; subir acima da raiz é recusa, não clamp silencioso."""
    resolvidas: list[str] = []
    for parte in partes:
        if parte in ("", "."):
            continue
        if parte == "..":
            if not resolvidas:
                raise CaminhoRecusado("caminho sobe acima da raiz com '..'")
            resolvidas.pop()
            continue
        resolvidas.append(parte)
    if not absoluto and not resolvidas:
        raise CaminhoRecusado("caminho relativo vazio depois de resolver '.' e '..'")
    return tuple(resolvidas)


def _canonicalizar_posix(caminho: str) -> CaminhoCanonico:
    texto = _comum(caminho)
    puro = PurePosixPath(texto)
    absoluto = puro.is_absolute()
    partes = _resolver_partes(
        tuple(p for p in puro.parts if p != "/"),
        absoluto=absoluto,
    )
    prefixo = "/" if absoluto else ""
    return CaminhoCanonico(
        texto=prefixo + "/".join(partes),
        partes=partes,
        absoluto=absoluto,
        sistema=Sistema.POSIX,
    )


def _canonicalizar_windows(caminho: str) -> CaminhoCanonico:
    texto = _comum(caminho)

    if texto.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./")):
        raise CaminhoRecusado("caminho de dispositivo (\\\\?\\ ou \\\\.\\) não é expressável")
    if texto.startswith(("\\\\", "//")):
        raise CaminhoRecusado("caminho UNC (\\\\servidor\\compartilhamento) não é expressável")

    puro = PureWindowsPath(texto)
    unidade = puro.drive
    if unidade and not texto[len(unidade) :].startswith(("\\", "/")):
        # `C:foo` é relativo ao diretório corrente *daquela unidade* — ambíguo por projeto.
        raise CaminhoRecusado("caminho relativo a unidade (C:foo) não é expressável")

    partes = tuple(p for p in puro.parts if p not in (unidade, unidade + "\\", "\\", "/"))
    for parte in partes:
        _conferir_componente_windows(parte)

    resolvidas = _resolver_partes(partes, absoluto=bool(unidade))
    rebaixadas = tuple(p.casefold() for p in resolvidas)
    raiz = unidade.casefold() + "\\" if unidade else ""
    return CaminhoCanonico(
        texto=raiz + "\\".join(rebaixadas),
        partes=((unidade.casefold(),) if unidade else ()) + rebaixadas,
        absoluto=bool(unidade),
        sistema=Sistema.WINDOWS,
    )


def _conferir_componente_windows(parte: str) -> None:
    if ":" in parte:
        raise CaminhoRecusado(f"fluxo de dados alternativo em {parte!r} (a.txt:oculto)")
    if any(c in parte for c in CARACTERES_INVALIDOS_WINDOWS):
        raise CaminhoRecusado(f"caractere inválido em {parte!r}")
    if parte != ".." and (parte.endswith((".", " ")) or parte.startswith(" ")):
        # `arquivo.txt.` e `arquivo.txt ` abrem o mesmo arquivo que `arquivo.txt` no Windows.
        raise CaminhoRecusado(f"componente com ponto ou espaço na borda: {parte!r}")
    base = parte.split(".")[0].casefold()
    if base in DISPOSITIVOS_RESERVADOS or parte.casefold() in DISPOSITIVOS_RESERVADOS:
        raise CaminhoRecusado(f"dispositivo reservado: {parte!r}")
    if NOME_8_3.match(parte):
        raise CaminhoRecusado(f"nome curto 8.3 ({parte!r}) é apelido de outro nome")
