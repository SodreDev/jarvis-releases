"""Borda do barramento: valida contra o contrato em dados e recusa o que não bate (§3).

Regra de ouro deste módulo: **recusar, nunca ignorar**. Tipo desconhecido, prioridade
divergente da §3.2, origem errada, `trust` declarado por quem não pode declarar e efeito
sem chave de idempotência levantam exceção — não passam adiante em silêncio.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Final

import jsonschema

from jarvis.barramento.envelope import (
    FONTE_VALIDA,
    SCHEMA_VERSION,
    UUID_V7_VALIDO,
    Envelope,
    Prioridade,
    Tipo,
    Trust,
)
from jarvis.dados import caminho

ARQUIVO_CONTRATO: Final = caminho("schemas/events.v1.json")


class ErroDeContrato(ValueError):
    """Evento recusado na borda. Carrega o motivo para auditoria (§5.5)."""


class TipoDesconhecido(ErroDeContrato):
    """Tipo fora dos doze da §3.2 — recusado, nunca ignorado (aceite F0-02 a)."""


def _carregar() -> dict[str, Any]:
    with ARQUIVO_CONTRATO.open(encoding="utf-8") as f:
        dados: dict[str, Any] = json.load(f)
    return dados


CONTRATO: Final[dict[str, Any]] = _carregar()
TIPOS: Final[frozenset[str]] = frozenset(CONTRATO["$defs"]["payloads"])
PRIORIDADE_CANONICA: Final[dict[str, str]] = {
    tipo: valor for tipo, valor in CONTRATO["x-prioridade-canonica"].items() if tipo != "descricao"
}
ORIGEM_CANONICA: Final[dict[str, tuple[str, ...]]] = {
    tipo: tuple(valor)
    for tipo, valor in CONTRATO["x-origem-canonica"].items()
    if tipo != "descricao"
}
_VALIDADOR: Final = jsonschema.Draft202012Validator(CONTRATO)


def prioridade_canonica(tipo: Tipo, payload: dict[str, Any]) -> Prioridade:
    """Prioridade que a §3.2 fixa para o tipo. O emissor não escolhe.

    `AudioActivity` é o único caso dependente de payload: `speech_started` é P0.
    """
    if tipo is Tipo.AUDIO_ACTIVITY and bool(payload.get("speech")):
        return Prioridade(PRIORIDADE_CANONICA["AudioActivity_speech"])
    return Prioridade(PRIORIDADE_CANONICA[str(tipo)])


def validar_bruto(bruto: object) -> dict[str, Any]:
    """Valida um evento cru (vindo de IPC, arquivo ou rede) contra o contrato inteiro."""
    if not isinstance(bruto, dict):
        raise ErroDeContrato(f"evento não é objeto: {type(bruto).__name__}")

    tipo_cru = bruto.get("type")
    if not isinstance(tipo_cru, str) or tipo_cru not in TIPOS:
        raise TipoDesconhecido(f"tipo desconhecido: {tipo_cru!r}")

    if bruto.get("schema_version") != SCHEMA_VERSION:
        raise ErroDeContrato(
            f"schema_version {bruto.get('schema_version')!r} não é {SCHEMA_VERSION!r}"
        )

    erros = sorted(_VALIDADOR.iter_errors(bruto), key=lambda e: list(e.absolute_path))
    if erros:
        caminho = "/".join(str(p) for p in erros[0].absolute_path) or "(raiz)"
        raise ErroDeContrato(f"{tipo_cru} inválido em {caminho}: {erros[0].message}")

    _validar_regras_canonicas(bruto)
    return bruto


def _validar_regras_canonicas(bruto: dict[str, Any]) -> None:
    """O que o JSON Schema não expressa, mas a §3 exige."""
    tipo = Tipo(bruto["type"])
    payload: dict[str, Any] = bruto["payload"]
    fonte = str(bruto["source"])

    if not FONTE_VALIDA.match(fonte):
        raise ErroDeContrato(f"source inválido: {fonte!r}")
    for campo in ("event_id", "session_id"):
        if not UUID_V7_VALIDO.match(str(bruto[campo])):
            raise ErroDeContrato(f"{campo} não é uuid v7: {bruto[campo]!r}")

    try:
        momento = datetime.fromisoformat(str(bruto["ts_wall"]).replace("Z", "+00:00"))
    except ValueError as erro:
        raise ErroDeContrato(f"ts_wall não é data ISO-8601: {bruto['ts_wall']!r}") from erro
    if momento.tzinfo is None:
        raise ErroDeContrato("ts_wall sem fuso horário")

    esperada = prioridade_canonica(tipo, payload)
    if bruto["priority"] != str(esperada):
        raise ErroDeContrato(
            f"{tipo} tem prioridade {esperada} na §3.2, veio {bruto['priority']!r}"
        )

    origens = ORIGEM_CANONICA[str(tipo)]
    curinga_mcp = "mcp:*" in origens and fonte.startswith("mcp:")
    if fonte not in origens and not curinga_mcp:
        raise ErroDeContrato(f"{tipo} só pode vir de {origens}, veio de {fonte!r}")

    # §3.3 regra 3: tool de efeito carrega chave de idempotência, sempre.
    efeito_sem_chave = (
        tipo is Tipo.TOOL_CALL_REQUESTED
        and not payload["dry_run"]
        and not payload.get("idempotency_key")
    )
    if efeito_sem_chave:
        raise ErroDeContrato("ToolCallRequested de efeito sem idempotency_key (§3.3 r3)")

    com_epoch = (Tipo.PLAYBACK_PROGRESS, Tipo.STATE_REVISION, Tipo.RESPONSE_CHUNK)
    if tipo in com_epoch and payload["epoch"] != bruto["epoch"]:
        raise ErroDeContrato(
            f"{tipo}.payload.epoch ({payload['epoch']}) difere do envelope ({bruto['epoch']})"
        )

    if tipo is Tipo.DESKTOP_OBSERVATION and bruto["trust"] != str(Trust.THIRD_PARTY):
        # §3.2: observação de desktop é sempre third_party.
        raise ErroDeContrato("DesktopObservation tem de ser third_party")

    if fonte.startswith("mcp:") and bruto["trust"] != str(Trust.THIRD_PARTY):
        raise ErroDeContrato(f"evento de {fonte} tem de ser third_party, veio {bruto['trust']!r}")


def validar(envelope: Envelope) -> Envelope:
    """Valida um envelope já tipado (mesma borda, usada na saída de cada processo)."""
    validar_bruto(envelope.para_dict())
    return envelope
