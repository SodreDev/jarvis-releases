# security/permissions.py — J.A.R.V.I.S.
# Sistema de permissões por nível de risco para comandos de sistema.
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import os

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INTENTS_JSON = os.path.join(_DIR, "config", "intents.json")

# ── Tabela padrão de riscos (usada se config/intents.json não existir) ────────
_DEFAULT_RISK: dict[str, list[str]] = {
    "high": [
        "desligar",
        "reiniciar_pc",
        "proc_matar",
        "limpar_temp",
        "esvaziar_lixeira",
    ],
    "medium": [
        "sleep",
        "bloquear",
        "alarme_cancelar",
        "fechar_janela",
        "proc_listar",
    ],
}

# ── Carrega config/intents.json se disponível ─────────────────────────────────
def _load_risk_map() -> dict[str, str]:
    """Retorna dict {acao: nivel} carregado do JSON ou da tabela padrão."""
    raw = _DEFAULT_RISK.copy()
    try:
        if os.path.exists(_INTENTS_JSON):
            with open(_INTENTS_JSON, encoding="utf-8") as f:
                loaded = json.load(f)
            raw.update(loaded)
    except Exception:
        pass

    mapping: dict[str, str] = {}
    for level in ("high", "medium"):
        for acao in raw.get(level, []):
            mapping[acao] = level
    return mapping


# Mapa inicializado uma vez ao importar
_RISK_MAP: dict[str, str] = _load_risk_map()


def get_risk_level(acao: str) -> str:
    """
    Retorna "high", "medium" ou "low" para uma ação de sistema.

    Exemplos:
        get_risk_level("desligar")   → "high"
        get_risk_level("volume_set") → "low"
    """
    return _RISK_MAP.get(acao, "low")


def reload() -> None:
    """Força recarregamento do mapa de risco (usado pelo hot-reload de config)."""
    global _RISK_MAP
    _RISK_MAP = _load_risk_map()


# ─────────────────────────────────────────────────────────────────────────────
# Grants persistentes + decorator
# ─────────────────────────────────────────────────────────────────────────────
import sys as _sys
import time as _time
import threading as _threading
from functools import wraps as _wraps
from typing import Callable as _Callable, Optional as _Optional


def _data_base() -> str:
    if getattr(_sys, "frozen", False):
        return os.path.dirname(_sys.executable)
    return _DIR


_GRANTS_PATH = os.path.join(_data_base(), "data", "permissions_grants.json")
_grants_lock = _threading.RLock()
_grants_cache: _Optional[dict] = None


def _load_grants() -> dict:
    global _grants_cache
    if _grants_cache is not None:
        return _grants_cache
    try:
        if os.path.exists(_GRANTS_PATH):
            with open(_GRANTS_PATH, encoding="utf-8") as fh:
                _grants_cache = json.load(fh) or {}
        else:
            _grants_cache = {}
    except Exception:
        _grants_cache = {}
    return _grants_cache


def _save_grants() -> None:
    try:
        os.makedirs(os.path.dirname(_GRANTS_PATH), exist_ok=True)
        with _grants_lock:
            tmp = _GRANTS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(_grants_cache or {}, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, _GRANTS_PATH)
    except Exception:
        pass


def grant(acao: str, *, scope: str = "session", ttl_s: float = 3600) -> None:
    """Concede permissão para `acao` por `ttl_s` segundos (scope=session)
    ou indefinidamente (scope=forever)."""
    with _grants_lock:
        g = _load_grants()
        expires = None if scope == "forever" else _time.time() + ttl_s
        g[acao] = {"scope": scope, "expires": expires, "granted_at": _time.time()}
        _save_grants()


def revoke(acao: str) -> bool:
    with _grants_lock:
        g = _load_grants()
        if acao in g:
            del g[acao]
            _save_grants()
            return True
    return False


def is_granted(acao: str) -> bool:
    with _grants_lock:
        g = _load_grants().get(acao)
        if not g:
            return False
        exp = g.get("expires")
        if exp is None:
            return True
        if _time.time() < float(exp):
            return True
        # Expirado — remove
        del _load_grants()[acao]
        _save_grants()
        return False


class PermissionDenied(Exception):
    """Erro lançado quando uma ação de risco não tem grant ativo."""


def requires_permission(
    acao: str,
    *,
    confirmer: _Optional[_Callable[[str, str], bool]] = None,
):
    """Decorator que exige confirmação humana antes de executar acoes high/medium.

    `confirmer(acao, risk)` deve retornar True/False. Se None, considera negado
    quando não há grant ativo.
    """

    def deco(fn: _Callable):
        @_wraps(fn)
        def wrapper(*args, **kwargs):
            risk = get_risk_level(acao)
            if risk == "low" or is_granted(acao):
                return fn(*args, **kwargs)
            ok = bool(confirmer and confirmer(acao, risk))
            if not ok:
                raise PermissionDenied(
                    f"Permissão necessária para '{acao}' (risk={risk})."
                )
            # Auto-grant temporário para evitar duplo prompt na mesma sessão
            grant(acao, scope="session", ttl_s=300)
            return fn(*args, **kwargs)

        return wrapper

    return deco


__all__ = [
    "get_risk_level",
    "reload",
    "grant",
    "revoke",
    "is_granted",
    "requires_permission",
    "PermissionDenied",
]
