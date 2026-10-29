"""A lista de servidores MCP que o dono configurou (ADR-0052): `~/.config/jarvis/mcp.toml`.

Padrão **vazio/desligado**: sem o arquivo, nenhum servidor e nenhuma tool MCP. Cada servidor diz
o transporte, o comando, se está ligado, e o **tier** de cada tool (decidido pelo dono, nunca pelo
servidor). O arquivo nunca carrega chave nem segredo: um arquivo com cara de segredo é recusado
inteiro, como a configuração do classificador de nuvem (ADR-0029).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

TIERS_VALIDOS: Final = frozenset({"leitura", "livre", "moderado", "perigoso"})
TIER_PADRAO: Final = "moderado"
# Um arquivo de configuração não guarda segredo (a chave vai no ambiente/chaveiro, ADR-0029). Se
# parecer que guarda, é recusado inteiro — não se tenta adivinhar o que é chave e o que não é.
_CARA_DE_SEGREDO: Final = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|senha|password|bearer|authorization)\b|sk-[a-z0-9]{8,}"
)


class ConfiguracaoMcpInvalida(ValueError):
    """O arquivo de MCP não cabe no contrato (ou tem cara de segredo)."""


@dataclass(frozen=True, slots=True)
class ServidorMcp:
    nome: str
    comando: tuple[str, ...]
    transporte: str = "stdio"
    ligado: bool = False
    tier_padrao: str = TIER_PADRAO
    tiers: dict[str, str] = field(default_factory=dict)
    """Tier por tool do servidor (`tool -> tier`), decidido pelo dono."""

    def tier_de(self, tool: str) -> str:
        return self.tiers.get(tool, self.tier_padrao)


def caminho_padrao(lar: Path | None = None) -> Path:
    base = lar if lar is not None else Path.home()
    return base / ".config" / "jarvis" / "mcp.toml"


def carregar_mcp(caminho: Path | None = None, *, lar: Path | None = None) -> list[ServidorMcp]:
    """Os servidores do arquivo. Sem o arquivo, lista vazia (o padrão: MCP desligado)."""
    alvo = caminho if caminho is not None else caminho_padrao(lar)
    if not alvo.exists():
        return []
    texto = alvo.read_text(encoding="utf-8")
    if _CARA_DE_SEGREDO.search(texto):
        raise ConfiguracaoMcpInvalida(
            f"{alvo} tem cara de segredo (chave/token/senha): recusado inteiro — a chave vai no "
            "ambiente ou no chaveiro, nunca na configuração"
        )
    try:
        dados = tomllib.loads(texto)
    except tomllib.TOMLDecodeError as erro:
        raise ConfiguracaoMcpInvalida(f"{alvo}: TOML inválido ({erro})") from None
    return [_servidor(nome, bruto) for nome, bruto in _servidores(dados)]


def _servidores(dados: object) -> list[tuple[str, dict[str, object]]]:
    if not isinstance(dados, dict):
        raise ConfiguracaoMcpInvalida("a raiz do mcp.toml tem de ser uma tabela")
    bloco = dados.get("servidor", {})
    if not isinstance(bloco, dict):
        raise ConfiguracaoMcpInvalida("`servidor` tem de ser uma tabela de servidores")
    saida: list[tuple[str, dict[str, object]]] = []
    for nome, bruto in bloco.items():
        if not isinstance(bruto, dict):
            raise ConfiguracaoMcpInvalida(f"servidor {nome!r} tem de ser uma tabela")
        saida.append((str(nome), bruto))
    return saida


def _servidor(nome: str, bruto: dict[str, object]) -> ServidorMcp:
    if not re.fullmatch(r"[a-z0-9_-]{1,40}", nome):
        raise ConfiguracaoMcpInvalida(f"nome de servidor fora de [a-z0-9_-]: {nome!r}")
    comando_bruto = bruto.get("comando")
    if not isinstance(comando_bruto, list) or not all(isinstance(c, str) for c in comando_bruto):
        raise ConfiguracaoMcpInvalida(f"servidor {nome!r}: `comando` tem de ser uma lista de texto")
    if not comando_bruto:
        raise ConfiguracaoMcpInvalida(f"servidor {nome!r}: `comando` vazio")
    transporte = str(bruto.get("transporte", "stdio"))
    if transporte != "stdio":
        raise ConfiguracaoMcpInvalida(
            f"servidor {nome!r}: só o transporte 'stdio' existe hoje (ADR-0052)"
        )
    tier_padrao = str(bruto.get("tier_padrao", TIER_PADRAO))
    if tier_padrao not in TIERS_VALIDOS:
        raise ConfiguracaoMcpInvalida(
            f"servidor {nome!r}: tier_padrao fora de {sorted(TIERS_VALIDOS)}"
        )
    tiers_bruto = bruto.get("tools", {})
    if not isinstance(tiers_bruto, dict):
        raise ConfiguracaoMcpInvalida(f"servidor {nome!r}: `tools` tem de ser uma tabela")
    tiers: dict[str, str] = {}
    for tool, tier in tiers_bruto.items():
        if str(tier) not in TIERS_VALIDOS:
            raise ConfiguracaoMcpInvalida(
                f"servidor {nome!r}: tier {tier!r} de {tool!r} fora de {sorted(TIERS_VALIDOS)}"
            )
        tiers[str(tool)] = str(tier)
    return ServidorMcp(
        nome=nome,
        comando=tuple(comando_bruto),
        transporte=transporte,
        ligado=bool(bruto.get("ligado", False)),
        tier_padrao=tier_padrao,
        tiers=tiers,
    )
