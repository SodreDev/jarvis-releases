"""A chave que liga a delegação ao Claude Code (ADR-0054): `~/.config/jarvis/delegar.toml`.

Padrão **desligado**: sem o arquivo, ou sem `ligado = true`, a `delegar.claude_code` não existe
para o modelo. O arquivo só diz se está ligada, qual executável (`claude` no PATH, ou um caminho
absoluto), o prazo, o teto de turnos e, se o dono quiser, o modelo. Nunca carrega chave nem
segredo: um arquivo com cara de segredo é recusado inteiro, como o `mcp.toml` (ADR-0052).

    [claude_code]
    ligado = true
    # executavel = "/home/eu/.local/bin/claude"
    prazo_s = 300
    max_turnos = 30
    # modelo = "sonnet"
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ARQUIVO: Final = "delegar.toml"
EXECUTAVEL_PADRAO: Final = "claude"
PRAZO_PADRAO_S: Final = 300.0
PRAZO_MINIMO_S: Final = 30.0
PRAZO_MAXIMO_S: Final = 600.0
"""O teto do `timeout_ms` do manifesto (600 s): o dono aperta, nunca passa disso."""
MAX_TURNOS_PADRAO: Final = 30
MAX_TURNOS_TETO: Final = 100
_CARA_DE_SEGREDO: Final = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|senha|password|bearer|authorization)\b|sk-[a-z0-9]{8,}"
)
_MODELO: Final = re.compile(r"[A-Za-z0-9._\[\]-]{1,60}")
_NOME_DE_PROGRAMA: Final = re.compile(r"[A-Za-z0-9._-]{1,60}")
_CHAVES: Final = frozenset({"ligado", "executavel", "prazo_s", "max_turnos", "modelo"})


class ConfiguracaoDaDelegacaoInvalida(ValueError):
    """O `delegar.toml` não cabe no contrato (ou tem cara de segredo)."""


@dataclass(frozen=True, slots=True)
class ConfiguracaoDaDelegacao:
    ligado: bool = False
    executavel: str = EXECUTAVEL_PADRAO
    """`claude` (procurado no PATH) ou um caminho absoluto — nunca texto que vire comando."""
    prazo_s: float = PRAZO_PADRAO_S
    max_turnos: int = MAX_TURNOS_PADRAO
    modelo: str = ""
    """Vazio = o padrão da conta do dono."""


def caminho_padrao(pasta: Path | None = None) -> Path:
    base = pasta if pasta is not None else Path.home() / ".config" / "jarvis"
    return base / ARQUIVO


def carregar_delegacao(caminho: Path | None = None) -> ConfiguracaoDaDelegacao:
    """A configuração do arquivo. Sem o arquivo: desligada (o padrão)."""
    alvo = caminho if caminho is not None else caminho_padrao()
    if not alvo.exists():
        return ConfiguracaoDaDelegacao()
    texto = alvo.read_text(encoding="utf-8")
    if _CARA_DE_SEGREDO.search(texto):
        raise ConfiguracaoDaDelegacaoInvalida(
            f"{alvo} tem cara de segredo (chave/token/senha): recusado inteiro — o Claude Code usa "
            "o login da conta do dono, nunca uma chave na configuração"
        )
    try:
        dados = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as erro:
        raise ConfiguracaoDaDelegacaoInvalida(f"{alvo}: TOML inválido ({erro})") from None
    bloco = dados.get("claude_code", {})
    if not isinstance(bloco, dict):
        raise ConfiguracaoDaDelegacaoInvalida("`claude_code` tem de ser uma tabela")
    fora = sorted(set(bloco) - _CHAVES)
    if fora:
        raise ConfiguracaoDaDelegacaoInvalida(f"`claude_code`: chave desconhecida {fora}")
    return ConfiguracaoDaDelegacao(
        ligado=_booleano(bloco.get("ligado", False)),
        executavel=_executavel(bloco.get("executavel", EXECUTAVEL_PADRAO)),
        prazo_s=_prazo(bloco.get("prazo_s", PRAZO_PADRAO_S)),
        max_turnos=_turnos(bloco.get("max_turnos", MAX_TURNOS_PADRAO)),
        modelo=_modelo(bloco.get("modelo", "")),
    )


def _booleano(valor: object) -> bool:
    if not isinstance(valor, bool):
        raise ConfiguracaoDaDelegacaoInvalida("`ligado` tem de ser true ou false")
    return valor


def _executavel(valor: object) -> str:
    """Um nome de programa (procurado no PATH) ou um caminho absoluto. Nada de argumento junto:
    o executável é um só, e os argumentos são os do código (ADR-0054)."""
    if not isinstance(valor, str) or not valor.strip():
        raise ConfiguracaoDaDelegacaoInvalida("`executavel` tem de ser um texto não vazio")
    texto = valor.strip()
    if Path(texto).is_absolute() and " " not in texto:
        return texto
    if _NOME_DE_PROGRAMA.fullmatch(texto):
        return texto
    raise ConfiguracaoDaDelegacaoInvalida(
        "`executavel` é o nome do programa (`claude`) ou um caminho absoluto, sem argumentos"
    )


def _prazo(valor: object) -> float:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise ConfiguracaoDaDelegacaoInvalida("`prazo_s` tem de ser um número de segundos")
    return min(PRAZO_MAXIMO_S, max(PRAZO_MINIMO_S, float(valor)))


def _turnos(valor: object) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ConfiguracaoDaDelegacaoInvalida("`max_turnos` tem de ser um número inteiro")
    return min(MAX_TURNOS_TETO, max(1, valor))


def _modelo(valor: object) -> str:
    if not isinstance(valor, str):
        raise ConfiguracaoDaDelegacaoInvalida("`modelo` tem de ser um texto")
    texto = valor.strip()
    if texto and not _MODELO.fullmatch(texto):
        raise ConfiguracaoDaDelegacaoInvalida("`modelo` fora de [A-Za-z0-9._-]")
    return texto
