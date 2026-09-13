"""Orquestrador multi-agente do JARVIS (roadmap/15).

Fase 3 (atual): roteador SEMÂNTICO de domínio (`router.py`) + registro de
sub-agentes = recortes de TOOL_LAYERS (`registry.py`). O cérebro recebe só as
tools do domínio do turno (mata o 413, melhora a seleção). Tudo atrás de
`config.AGENT_SUBAGENTS` (OFF por padrão). O orquestrador "vira" o sub-agente
trocando tools/prompt no MESMO motor `_pensar_e_agir` — sem processos novos.

Fases futuras: roteador de complexidade (4 tiers) + decomposição/supervisor
para tarefas compostas (TIER_SUPERVISE) + identidade read-only.
"""
from __future__ import annotations


def enabled() -> bool:
    try:
        import config as _c
        return bool(getattr(_c, "AGENT_SUBAGENTS", False))
    except Exception:
        return False
