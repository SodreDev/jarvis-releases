"""
ApiKeyPool — rotação de chaves de API com fallback automático.

Permite configurar múltiplas chaves para um provedor (ex: ElevenLabs) e
rotacionar automaticamente quando uma esgota (401/429/quota).

Convenção .env:
    PROVIDER_API_KEY        (primária — compatível com setup legado)
    PROVIDER_API_KEY_2      (fallback 1)
    PROVIDER_API_KEY_3      (fallback 2)
    ... até _5

Estado persistido em jarvis_prefs.json:
    {
      "key_pools": {
        "elevenlabs": {
          "active_idx": 0,
          "exhausted": [false, false, ...],
          "last_error_ts": [0.0, ...],
          "last_error_msg": ["", ...],
          "last_reset_date": "2026-05-24"
        }
      }
    }

Reset automático: ao detectar mudança de data, marca todas como livres
(quotas mensais/diárias podem ter sido restauradas).

Uso:
    from core.api_key_pool import get_pool
    pool = get_pool("elevenlabs")
    key = pool.get_active()
    if not key:
        # nenhuma chave disponível
        ...
    try:
        chamar_api(key)
    except RateLimitError as e:
        pool.mark_failed("429", msg=str(e))
        # tenta de novo:
        key = pool.get_active()
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import date
from typing import Any

# Provedores que suportam pool (e o env var base correspondente)
PROVIDERS = {
    "elevenlabs": "ELEVENLABS_API_KEY",
}

_MAX_KEYS = 5


def _load_keys_from_env(provider: str) -> list[str]:
    """Lê PROVIDER_API_KEY, _2, _3, ... do environment. Retorna não-vazias."""
    base = PROVIDERS.get(provider)
    if not base:
        return []
    keys: list[str] = []
    primary = (os.environ.get(base) or "").strip()
    if primary:
        keys.append(primary)
    for i in range(2, _MAX_KEYS + 1):
        v = (os.environ.get(f"{base}_{i}") or "").strip()
        if v:
            keys.append(v)
    return keys


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return key[:4] + "•••" + key[-4:]


class ApiKeyPool:
    """Pool de chaves para um provedor — rotação por falha."""

    def __init__(self, provider: str, prefs_path: str | None = None) -> None:
        self.provider = provider
        self._lock = threading.RLock()
        self._prefs_path = prefs_path or self._resolve_prefs_path()
        self._keys: list[str] = []
        self._state: dict[str, Any] = {
            "active_idx": 0,
            "exhausted": [],
            "last_error_ts": [],
            "last_error_msg": [],
            "last_reset_date": "",
        }
        self.refresh()

    def _resolve_prefs_path(self) -> str:
        try:
            from config import PATHS as _P  # type: ignore
            return _P["prefs"]
        except Exception:
            try:
                from config import creds_path  # type: ignore
                return creds_path("jarvis_prefs.json")
            except Exception:
                here = os.path.dirname(os.path.abspath(__file__))
                return os.path.join(os.path.dirname(here), "jarvis_prefs.json")

    # ── carregar / salvar estado ─────────────────────────────────────────────
    def _load_state(self) -> dict[str, Any]:
        try:
            if not os.path.exists(self._prefs_path):
                return {}
            with open(self._prefs_path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            pools = data.get("key_pools") or {}
            return pools.get(self.provider) or {}
        except Exception:
            return {}

    def _save_state(self) -> None:
        existing: dict[str, Any] = {}
        try:
            if os.path.exists(self._prefs_path):
                with open(self._prefs_path, "r", encoding="utf-8") as f:
                    existing = json.load(f) or {}
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        pools = existing.get("key_pools") or {}
        if not isinstance(pools, dict):
            pools = {}
        pools[self.provider] = dict(self._state)
        existing["key_pools"] = pools

        d = os.path.dirname(self._prefs_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".pool_", suffix=".json.tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._prefs_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def refresh(self) -> None:
        """Recarrega chaves do .env e restaura/normaliza estado."""
        with self._lock:
            self._keys = _load_keys_from_env(self.provider)
            n = len(self._keys)
            saved = self._load_state()
            # Restaura, garantindo tamanho consistente
            self._state["active_idx"] = int(saved.get("active_idx") or 0)
            ex = saved.get("exhausted") or []
            ts = saved.get("last_error_ts") or []
            msg = saved.get("last_error_msg") or []
            self._state["exhausted"] = [bool(ex[i]) if i < len(ex) else False for i in range(n)]
            self._state["last_error_ts"] = [float(ts[i]) if i < len(ts) else 0.0 for i in range(n)]
            self._state["last_error_msg"] = [str(msg[i]) if i < len(msg) else "" for i in range(n)]
            self._state["last_reset_date"] = str(saved.get("last_reset_date") or "")
            # Clampa active_idx
            if not (0 <= self._state["active_idx"] < n):
                self._state["active_idx"] = 0
            # Auto-reset diário
            self._maybe_daily_reset()

    def _maybe_daily_reset(self) -> None:
        today = date.today().isoformat()
        if self._state.get("last_reset_date") != today and self._keys:
            self._state["exhausted"] = [False] * len(self._keys)
            self._state["last_reset_date"] = today
            try:
                self._save_state()
            except Exception:
                pass

    # ── API pública ───────────────────────────────────────────────────────────
    def get_active(self) -> str:
        """Retorna chave ativa não-esgotada (ou '' se nenhuma disponível)."""
        with self._lock:
            self._maybe_daily_reset()
            n = len(self._keys)
            if n == 0:
                return ""
            ex = self._state["exhausted"]
            idx = self._state["active_idx"]
            if 0 <= idx < n and not ex[idx]:
                return self._keys[idx]
            # Procura próxima não-esgotada
            for i in range(n):
                j = (idx + i) % n
                if not ex[j]:
                    self._state["active_idx"] = j
                    try:
                        self._save_state()
                    except Exception:
                        pass
                    return self._keys[j]
            return ""

    def mark_failed(self, reason: str = "", msg: str = "") -> str:
        """Marca chave atual como esgotada e devolve a próxima disponível.

        reason: '401' | '429' | 'quota' | 'network' (qualquer string)
        """
        with self._lock:
            n = len(self._keys)
            if n == 0:
                return ""
            idx = self._state["active_idx"]
            if 0 <= idx < n:
                # Apenas 401/429/quota marcam como esgotada — erros de rede não
                r = str(reason).lower()
                if "401" in r or "429" in r or "quota" in r or "unauthorized" in r or "rate" in r:
                    self._state["exhausted"][idx] = True
                self._state["last_error_ts"][idx] = time.time()
                self._state["last_error_msg"][idx] = str(msg)[:200]
            # Avança para a próxima
            for i in range(1, n + 1):
                j = (idx + i) % n
                if not self._state["exhausted"][j]:
                    self._state["active_idx"] = j
                    try:
                        self._save_state()
                    except Exception:
                        pass
                    return self._keys[j]
            try:
                self._save_state()
            except Exception:
                pass
            return ""

    def status(self) -> list[dict[str, Any]]:
        """Snapshot para UI."""
        with self._lock:
            self._maybe_daily_reset()
            out = []
            for i, k in enumerate(self._keys):
                out.append({
                    "idx": i,
                    "masked": _mask(k),
                    "active": (i == self._state["active_idx"]),
                    "exhausted": bool(self._state["exhausted"][i]) if i < len(self._state["exhausted"]) else False,
                    "last_error_ts": float(self._state["last_error_ts"][i]) if i < len(self._state["last_error_ts"]) else 0.0,
                    "last_error_msg": self._state["last_error_msg"][i] if i < len(self._state["last_error_msg"]) else "",
                })
            return out

    def has_any(self) -> bool:
        with self._lock:
            return any(not e for e in self._state["exhausted"]) if self._keys else False

    def count(self) -> int:
        return len(self._keys)

    def reset_all(self) -> None:
        """Marca todas as chaves como livres (manual)."""
        with self._lock:
            self._state["exhausted"] = [False] * len(self._keys)
            self._state["last_reset_date"] = date.today().isoformat()
            try:
                self._save_state()
            except Exception:
                pass


# ── Singletons por provedor ──────────────────────────────────────────────────
_POOLS: dict[str, ApiKeyPool] = {}
_POOLS_LOCK = threading.Lock()


def get_pool(provider: str) -> ApiKeyPool:
    """Singleton por provedor. Cria se não existir."""
    with _POOLS_LOCK:
        if provider not in _POOLS:
            _POOLS[provider] = ApiKeyPool(provider)
        return _POOLS[provider]


def refresh_all() -> None:
    """Recarrega chaves do .env em todos os pools (use após save_env_keys)."""
    with _POOLS_LOCK:
        for p in _POOLS.values():
            p.refresh()
