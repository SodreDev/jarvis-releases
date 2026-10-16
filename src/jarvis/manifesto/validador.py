"""Validação de manifesto contra `schemas/manifesto.v1.json` (SPEC §4).

Recusa, nunca ignora: manifesto sem `postcondition`, `risk_class`, `tests` ou
`access_level_min` não passa, e é isso que o CI roda (aceite F0-07 a).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema
import yaml

from jarvis.dados import caminho

ARQUIVO_SCHEMA: Final = caminho("schemas/manifesto.v1.json")
PASTA_CATALOGO: Final = caminho("catalogo")


class ManifestoInvalido(ValueError):
    """Manifesto recusado. A mensagem diz o campo e o motivo, para caber no log do CI."""


def _schema() -> dict[str, Any]:
    dados: dict[str, Any] = json.loads(ARQUIVO_SCHEMA.read_text(encoding="utf-8"))
    return dados


SCHEMA: Final[dict[str, Any]] = _schema()
_VALIDADOR: Final = jsonschema.Draft202012Validator(SCHEMA)

IDS_PROIBIDOS: Final[tuple[str, ...]] = tuple(SCHEMA["x-ids-proibidos"]["padroes"])
TOOLS_PROIBIDAS_DE_PROMOVER: Final[frozenset[str]] = frozenset(
    SCHEMA["x-tools-proibidas-de-promover"]["nomes"]
)
NUCLEO_DE_CONVERSA: Final[tuple[str, ...]] = tuple(SCHEMA["x-nucleo-de-conversa"]["ids"])
TETO_POR_NAMESPACE: Final[int] = int(SCHEMA["x-tetos-de-catalogo"]["por_namespace"])
TETO_POR_TURNO: Final[int] = int(SCHEMA["x-tetos-de-catalogo"]["por_turno"])


def validar_manifesto(bruto: object, *, origem: str = "(memória)") -> dict[str, Any]:
    """Valida um manifesto já carregado. Devolve o próprio mapa, para encadear."""
    if not isinstance(bruto, dict):
        raise ManifestoInvalido(f"{origem}: manifesto não é um mapa")

    erros = sorted(_VALIDADOR.iter_errors(bruto), key=lambda e: list(e.absolute_path))
    if erros:
        caminho = "/".join(str(p) for p in erros[0].absolute_path) or "(raiz)"
        raise ManifestoInvalido(f"{origem}: {caminho}: {erros[0].message}")

    _validar_coerencia(bruto, origem)
    return bruto


def _validar_coerencia(manifesto: dict[str, Any], origem: str) -> None:
    """O que o JSON Schema não expressa, mas a §4 exige."""
    identificador = str(manifesto["id"])

    niveis = identificador.split(".")
    if not 2 <= len(niveis) <= 4:
        raise ManifestoInvalido(
            f"{origem}: id {identificador!r} tem {len(niveis)} níveis; a §4 pede "
            "domínio.objeto.verbo (2 a 4)"
        )
    if manifesto["side_effect"] != "none" and manifesto["idempotency"] != "required":
        raise ManifestoInvalido(
            f"{origem}: {identificador} tem efeito e não exige idempotency_key (§3.3 r3)"
        )
    # Só efeito precisa de desfazer: leitura é "reversível" por não mudar nada.
    if manifesto["side_effect"] != "none" and manifesto["reversible"] and not manifesto.get("undo"):
        raise ManifestoInvalido(
            f"{origem}: {identificador} tem efeito reversível e não aponta `undo` (§4)"
        )
    if manifesto["side_effect"] != "none" and manifesto["confirmation"] == "never":
        raise ManifestoInvalido(
            f"{origem}: {identificador} tem efeito persistente com confirmation: never"
        )
    if manifesto["risk_class"] == "leitura" and manifesto["side_effect"] != "none":
        raise ManifestoInvalido(f"{origem}: {identificador} é 'leitura' mas tem efeito")
    if manifesto["requires_elevation"] and manifesto["confirmation"] != "per_action":
        raise ManifestoInvalido(
            f"{origem}: {identificador} exige elevação e precisa de confirmation: per_action"
        )
    egress = str(manifesto["data_egress"])
    if egress.startswith("network:") and manifesto["risk_class"] not in (
        "egress",
        "representacao_do_dono",
        "instalar_ou_executar_baixado",
        "mudanca_de_sistema",
    ):
        raise ManifestoInvalido(
            f"{origem}: {identificador} manda dado para fora e não é classificado como egress"
        )
    roots = list(manifesto["roots"])
    if roots and manifesto["access_level_min"] == "jarvis" and roots != ["jarvis_root"]:
        raise ManifestoInvalido(
            f"{origem}: {identificador} vale no modo `jarvis` mas pede raiz fora dele: {roots}"
        )
    if "windows" not in manifesto["platforms"] or not any(
        p.startswith("linux") for p in manifesto["platforms"]
    ):
        raise ManifestoInvalido(f"{origem}: {identificador} não cobre Linux e Windows (P11)")
    faltando = {"contract", "postcondition", "denial"} - set(manifesto["tests"])
    if faltando:
        raise ManifestoInvalido(
            f"{origem}: {identificador} sem os testes obrigatórios: {sorted(faltando)}"
        )


def carregar_manifesto(arquivo: Path) -> dict[str, Any]:
    """Lê o YAML e valida. É o que o CLI e o lint usam."""
    try:
        bruto: Any = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
    except yaml.YAMLError as erro:
        raise ManifestoInvalido(f"{arquivo.name}: YAML inválido: {erro}") from erro
    return validar_manifesto(bruto, origem=arquivo.name)


def carregar_catalogo(pasta: Path = PASTA_CATALOGO) -> dict[str, dict[str, Any]]:
    manifestos: dict[str, dict[str, Any]] = {}
    for arquivo in sorted(pasta.glob("*.yaml")):
        manifesto = carregar_manifesto(arquivo)
        identificador = str(manifesto["id"])
        if identificador in manifestos:
            raise ManifestoInvalido(f"{arquivo.name}: id repetido no catálogo: {identificador}")
        if arquivo.stem != identificador:
            raise ManifestoInvalido(
                f"{arquivo.name}: nome do arquivo tem de ser {identificador}.yaml"
            )
        manifestos[identificador] = manifesto
    return manifestos
