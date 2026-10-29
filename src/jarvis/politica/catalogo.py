"""Leitura dos manifestos de capacidade para efeito de política (SPEC §4, §5.5).

O validador completo do manifesto, o codegen e o lint anti-canivete-suíço são o cartão
F0-07. Aqui se lê apenas o que **decide acesso**, mais o suficiente para os dois testes que
o cartão F0-06 cobra: nenhuma capacidade muda nível ou elevação, e capacidade que exige
elevação não aparece na allowlist quando o interruptor está desligado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import yaml

from jarvis.dados import caminho
from jarvis.politica.modos import Modo

PASTA_CATALOGO: Final = caminho("catalogo")

PADROES_DE_CANIVETE: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\.run_command$"),
    re.compile(r"\.do_anything$"),
    re.compile(r"\.exec$"),
    re.compile(r"\.eval$"),
    re.compile(r"\.shell$"),
    re.compile(r"^shell\."),
)
CAMPOS_DE_POLITICA: Final[frozenset[str]] = frozenset(
    {"access_level_min", "requires_elevation", "roots", "risk_class", "confirmation", "tier"}
)
"""Campos que **só** o repositório define: não vêm do LLM nem de servidor remoto (§4)."""

RISCOS_QUE_SEMPRE_CONFIRMAM: Final[frozenset[str]] = frozenset(
    {
        "apagar_permanente",
        "sobrescrita_sem_desfazer",
        "lote_acima_do_teto",
        "renomear_em_massa",
        "egress",
        "representacao_do_dono",
        "instalar_ou_executar_baixado",
        "mudanca_de_sistema",
        "elevacao",
        "fora_do_diretorio_do_dono",
    }
)
"""O que continua exigindo confirmação **mesmo no `total`** (§5.5, P13) — e que, por isso, só pode
ser de tier `perigoso` (o validador recusa o resto)."""

PALAVRAS_DE_CONTROLE_DE_ACESSO: Final[tuple[str, ...]] = (
    "access_level",
    "nivel_de_acesso",
    "elevation",
    "elevacao",
    "policy_epoch",
    "allowed_tools",
)


class ManifestoInvalido(ValueError):
    """Manifesto sem campo de política obrigatório, ou com id de canivete suíço."""


@dataclass(frozen=True, slots=True)
class Capacidade:
    """A parte do manifesto que a política precisa."""

    id: str
    capability: str
    risk_class: str
    confirmation: str
    tier: str
    """`livre`, `moderado` ou `perigoso` (dono, 2026-10-18): quem decide se pergunta, só avisa ou
    não diz nada. Vem do manifesto — nunca do modelo."""
    access_level_min: Modo
    requires_elevation: bool
    roots: tuple[str, ...]
    side_effect: str
    idempotency: str
    data_egress: str
    bruto: dict[str, Any]

    @property
    def muda_controle_de_acesso(self) -> bool:
        """A capacidade mexe em nível, elevação ou allowlist? (Nenhuma pode — P12.)"""
        alvo = " ".join(
            [
                self.id,
                self.capability,
                str(self.bruto.get("title", "")),
                str(self.bruto.get("description", "")),
                str(self.bruto.get("executor", "")),
                " ".join(self.bruto.get("input_schema", {}).get("properties", {})),
            ]
        ).casefold()
        escreve = self.side_effect != "none" or self.risk_class not in ("leitura",)
        return escreve and any(p in alvo for p in PALAVRAS_DE_CONTROLE_DE_ACESSO)


def carregar(arquivo: Path) -> Capacidade:
    dados: Any = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
    if not isinstance(dados, dict):
        raise ManifestoInvalido(f"{arquivo.name}: manifesto não é um mapa")
    return de_dados(dados, origem=arquivo.name)


def de_dados(dados: dict[str, Any], *, origem: str = "(memória)") -> Capacidade:
    """A `Capacidade` (a parte de política) de um manifesto já carregado — do disco ou promovido
    de um servidor MCP (ADR-0052). A promoção valida o manifesto inteiro antes; aqui só a leitura
    dos campos de política, com a mesma recusa de canivete suíço."""
    faltando = sorted(CAMPOS_DE_POLITICA - set(dados))
    if faltando:
        raise ManifestoInvalido(f"{origem}: sem {', '.join(faltando)}")
    identificador = str(dados["id"])
    for padrao in PADROES_DE_CANIVETE:
        if padrao.search(identificador):
            raise ManifestoInvalido(f"{identificador}: capacidade de canivete suíço (§4)")
    return Capacidade(
        id=identificador,
        capability=str(dados["capability"]),
        risk_class=str(dados["risk_class"]),
        confirmation=str(dados["confirmation"]),
        tier=str(dados["tier"]),
        access_level_min=Modo(str(dados["access_level_min"])),
        requires_elevation=bool(dados["requires_elevation"]),
        roots=tuple(dados["roots"] or ()),
        side_effect=str(dados.get("side_effect", "none")),
        idempotency=str(dados.get("idempotency", "not_required")),
        data_egress=str(dados.get("data_egress", "none")),
        bruto=dados,
    )


def carregar_catalogo(pasta: Path = PASTA_CATALOGO) -> dict[str, Capacidade]:
    return {c.id: c for c in (carregar(a) for a in sorted(pasta.glob("*.yaml")))}


def allowlist_do_turno(
    catalogo: dict[str, Capacidade],
    *,
    modo: Modo,
    elevacao_ligada: bool,
) -> tuple[str, ...]:
    """O que o planejador pode **ver** neste turno (§5.5).

    Elevação desligada filtra `requires_elevation: true` **antes** de o modelo ver o
    catálogo: o planejador não pode nem propor, em vez de propor e ser negado depois.
    """
    visiveis = [
        c.id
        for c in catalogo.values()
        if c.access_level_min.amplitude <= modo.amplitude
        and (elevacao_ligada or not c.requires_elevation)
    ]
    return tuple(sorted(visiveis))
