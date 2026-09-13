# -*- coding: utf-8 -*-
"""
security.vault — Cofre central para segredos do JARVIS.

Objetivos:
    • API uniforme `get / set / list_keys / delete` para qualquer credencial.
    • Backend padrão: `credentials/.env` (lido e escrito linha a linha).
    • Backend opcional criptografado AES-GCM (`credentials/vault.enc`)
      quando a env-var `JARVIS_VAULT_PASSPHRASE` estiver presente.
    • Auditoria leve em `credentials/vault_audit.log` (rotina append-only,
      apenas nome da chave + ação + timestamp — nunca o valor).

Esse módulo NÃO depende de mais nada do JARVIS — pode ser importado por
qualquer comando, ferramenta MCP ou tarefa standalone.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Dict, List, Optional

# Preserva builtins antes de definirmos `set(...)` como função do módulo.
_builtin_set = set


# ── Resolução de caminhos (compatível com PyInstaller --onedir) ──────────────
def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _creds_dir() -> str:
    d = os.path.join(_base_dir(), "credentials")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


_ENV_PATH = os.path.join(_creds_dir(), ".env")
_VAULT_ENC = os.path.join(_creds_dir(), "vault.enc")
_AUDIT_LOG = os.path.join(_creds_dir(), "vault_audit.log")

_lock = threading.RLock()


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────
def _audit(action: str, key: str, *, detail: str = "") -> None:
    try:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {action:<6} | {key} | {detail}\n"
        with open(_AUDIT_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Backend .env (texto)
# ─────────────────────────────────────────────────────────────────────────────
def _read_env_file() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.exists(_ENV_PATH):
        return out
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip()
                if v.startswith('"') and v.endswith('"') and len(v) >= 2:
                    v = v[1:-1]
                out[k] = v
    except Exception:
        return {}
    return out


def _write_env_file(data: Dict[str, str]) -> None:
    """Reescreve `.env` preservando comentários originais quando possível.

    Estratégia: lê linha a linha, substitui valores das chaves já presentes,
    e anexa novas chaves no final.
    """
    lines: List[str] = []
    seen = _builtin_set()

    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, "r", encoding="utf-8") as fh:
            for raw in fh:
                stripped = raw.strip()
                if (
                    not stripped
                    or stripped.startswith("#")
                    or "=" not in stripped
                ):
                    lines.append(raw.rstrip("\n"))
                    continue
                k = stripped.split("=", 1)[0].strip()
                if k in data:
                    v = data[k]
                    needs_quote = any(c in v for c in " \t#")
                    val = f'"{v}"' if needs_quote else v
                    lines.append(f"{k}={val}")
                    seen.add(k)
                else:
                    lines.append(raw.rstrip("\n"))

    for k, v in data.items():
        if k in seen:
            continue
        needs_quote = any(c in v for c in " \t#")
        val = f'"{v}"' if needs_quote else v
        lines.append(f"{k}={val}")

    tmp = _ENV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    os.replace(tmp, _ENV_PATH)


# ─────────────────────────────────────────────────────────────────────────────
# Backend criptografado opcional (AES-GCM via cryptography)
# ─────────────────────────────────────────────────────────────────────────────
def _enc_enabled() -> bool:
    return bool(os.environ.get("JARVIS_VAULT_PASSPHRASE"))


def _derive_key(passphrase: str) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = b"jarvis-vault-v1"  # estático — passphrase já é o segredo
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _read_enc() -> Dict[str, str]:
    if not os.path.exists(_VAULT_ENC):
        return {}
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        with open(_VAULT_ENC, "rb") as fh:
            blob = fh.read()
        if len(blob) < 13:
            return {}
        nonce, ct = blob[:12], blob[12:]
        key = _derive_key(os.environ["JARVIS_VAULT_PASSPHRASE"])
        pt = AESGCM(key).decrypt(nonce, ct, None)
        return json.loads(pt.decode("utf-8"))
    except Exception:
        return {}


def _write_enc(data: Dict[str, str]) -> None:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    key = _derive_key(os.environ["JARVIS_VAULT_PASSPHRASE"])
    ct = AESGCM(key).encrypt(nonce, json.dumps(data).encode("utf-8"), None)
    tmp = _VAULT_ENC + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(nonce + ct)
    os.replace(tmp, _VAULT_ENC)


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────
def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Recupera um segredo. Ordem: vault.enc → .env → os.environ → default."""
    with _lock:
        if _enc_enabled():
            data = _read_enc()
            if key in data:
                _audit("READ", key, detail="enc")
                return data[key]
        env = _read_env_file()
        if key in env:
            _audit("READ", key, detail="env")
            return env[key]
        val = os.environ.get(key)
        if val is not None:
            _audit("READ", key, detail="proc")
            return val
        return default


def set(key: str, value: str) -> None:
    """Armazena/atualiza um segredo. Usa vault.enc se passphrase presente."""
    with _lock:
        if _enc_enabled():
            data = _read_enc()
            data[key] = value
            _write_enc(data)
            _audit("WRITE", key, detail="enc")
        else:
            data = _read_env_file()
            data[key] = value
            _write_env_file(data)
            _audit("WRITE", key, detail="env")
        # Reflete no processo atual também para callers que já leram config.
        os.environ[key] = value


def delete(key: str) -> bool:
    """Remove um segredo. Retorna True se removeu de pelo menos um backend."""
    removed = False
    with _lock:
        if _enc_enabled():
            data = _read_enc()
            if key in data:
                del data[key]
                _write_enc(data)
                removed = True
        env = _read_env_file()
        if key in env:
            del env[key]
            _write_env_file(env)
            removed = True
        os.environ.pop(key, None)
        if removed:
            _audit("DEL", key)
    return removed


def list_keys() -> List[str]:
    """Lista chaves conhecidas (união dos backends, sem valores)."""
    with _lock:
        keys = _builtin_set()
        if _enc_enabled():
            keys.update(_read_enc().keys())
        keys.update(_read_env_file().keys())
        return sorted(keys)


def has(key: str) -> bool:
    return get(key) not in (None, "")


__all__ = ["get", "set", "delete", "list_keys", "has"]
