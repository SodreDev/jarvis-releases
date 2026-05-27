"""Vault — armazena credenciais por perfil (`jarvis`, `user`, `shared`).

Tiers (escolha por `security.vault_encrypted`):
- Tier 1 (default): JSON puro com permissão 0600 em `<credentials_dir>/profiles/<profile>/<key>.json`.
- Tier 2: arquivo único `vault.enc` cifrado em AES-GCM, chave derivada PBKDF2-HMAC-SHA256(senha, salt, 200_000).

Auditoria: cada `get/set/delete` registra evento em `<logs_dir>/credentials_access.jsonl`
(timestamp ISO, op, key, profile, module chamador) — nunca o valor.

Esta primeira versão implementa Tier 1 + ganchos Tier 2 (criptografia plugada
apenas se `cryptography` estiver disponível). Sem `cryptography`, tentar Tier 2
levanta `VaultError`.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from jarvis.config import settings
from jarvis.config.paths import credentials_dir, logs_dir


class VaultError(RuntimeError):
    """Erros operacionais do vault."""


@dataclass(frozen=True)
class _AuditEvent:
    ts: str
    op: str
    profile: str
    key: str
    caller: str


_VALID_PROFILES: tuple[str, ...] = ("jarvis", "user", "shared")


def _profile_path(profile: str) -> Path:
    if profile not in _VALID_PROFILES:
        raise VaultError(f"perfil inválido: {profile!r}")
    p = credentials_dir() / "profiles" / profile
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_caller_module() -> str:
    # 2 frames acima: chamada externa → método público → este helper
    try:
        frame = inspect.stack()[3]
        return frame.frame.f_globals.get("__name__", "<unknown>")
    except Exception:
        return "<unknown>"


def _audit(op: str, profile: str, key: str) -> None:
    log_path = logs_dir() / "credentials_access.jsonl"
    evt = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "op": op,
        "profile": profile,
        "key": key,
        "caller": _safe_caller_module(),
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except Exception:
        # auditoria nunca pode quebrar o vault em si
        pass


def _restrict_perms(path: Path) -> None:
    """Tenta restringir permissões a 0600 (no-op no Windows tradicional)."""
    try:
        os.chmod(path, 0o600)
    except Exception:
        # Windows: ACLs requerem pywin32; deixamos pro plano futuro
        pass


# ---------------------------------------------------------------------------
# Backend Tier 1 — JSON por arquivo
# ---------------------------------------------------------------------------

class _JsonBackend:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def get(self, profile: str, key: str) -> Any | None:
        path = _profile_path(profile) / f"{_sanitize_key(key)}.json"
        if not path.is_file():
            return None
        with self._lock, path.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except Exception as exc:
                raise VaultError(f"falha lendo {path}: {exc}") from exc

    def set(self, profile: str, key: str, value: Any) -> None:
        path = _profile_path(profile) / f"{_sanitize_key(key)}.json"
        with self._lock:
            tmp = path.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)
            tmp.replace(path)
            _restrict_perms(path)

    def delete(self, profile: str, key: str) -> bool:
        path = _profile_path(profile) / f"{_sanitize_key(key)}.json"
        if not path.is_file():
            return False
        with self._lock:
            path.unlink()
        return True

    def list_keys(self, profile: str) -> list[str]:
        p = _profile_path(profile)
        return sorted(f.stem for f in p.glob("*.json"))


def _sanitize_key(key: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in key)
    if not safe:
        raise VaultError("chave vazia")
    return safe


# ---------------------------------------------------------------------------
# Backend Tier 2 — AES-GCM com PBKDF2 (placeholder operacional)
# ---------------------------------------------------------------------------

class _EncryptedBackend:
    """Implementação enxuta: 1 arquivo único `vault.enc` em JSON cifrado.

    Requer `cryptography`. Se ausente, `__init__` levanta `VaultError`.
    Ativado apenas quando `security.vault_encrypted=True` e master password
    foi fornecida (env var `JARVIS_VAULT_PASS` ou parâmetro).
    """

    _SALT_FILE = "vault.salt"
    _DATA_FILE = "vault.enc"
    _PBKDF2_ITERS = 200_000

    def __init__(self, master_password: str) -> None:
        try:
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: F401
            from cryptography.hazmat.primitives import hashes  # noqa: F401
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except Exception as exc:  # pragma: no cover
            raise VaultError(
                "Tier 2 (AES-GCM) precisa do pacote `cryptography`. "
                "Instale com `pip install cryptography`."
            ) from exc
        if not master_password:
            raise VaultError("master password vazia")
        self._password = master_password.encode("utf-8")
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, Any]] | None = None

    # — chaves derivadas —
    def _key(self) -> bytes:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        salt_path = credentials_dir() / self._SALT_FILE
        if salt_path.is_file():
            salt = salt_path.read_bytes()
        else:
            salt = os.urandom(16)
            salt_path.write_bytes(salt)
            _restrict_perms(salt_path)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=self._PBKDF2_ITERS)
        return kdf.derive(self._password)

    def _path(self) -> Path:
        return credentials_dir() / self._DATA_FILE

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        if not self._path().is_file():
            self._cache = {p: {} for p in _VALID_PROFILES}
            return self._cache
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = self._path().read_bytes()
        nonce, ct = raw[:12], raw[12:]
        aes = AESGCM(self._key())
        try:
            plain = aes.decrypt(nonce, ct, None)
        except Exception as exc:
            raise VaultError("senha mestra incorreta ou vault corrompido") from exc
        data = json.loads(plain.decode("utf-8"))
        # garantir presença dos perfis
        for p in _VALID_PROFILES:
            data.setdefault(p, {})
        self._cache = data
        return data

    def _flush(self) -> None:
        if self._cache is None:
            return
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        plain = json.dumps(self._cache, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(12)
        aes = AESGCM(self._key())
        ct = aes.encrypt(nonce, plain, None)
        tmp = self._path().with_suffix(".enc.tmp")
        tmp.write_bytes(nonce + ct)
        tmp.replace(self._path())
        _restrict_perms(self._path())

    def get(self, profile: str, key: str) -> Any | None:
        with self._lock:
            return self._load().get(profile, {}).get(key)

    def set(self, profile: str, key: str, value: Any) -> None:
        with self._lock:
            data = self._load()
            data.setdefault(profile, {})[key] = value
            self._flush()

    def delete(self, profile: str, key: str) -> bool:
        with self._lock:
            data = self._load()
            existed = key in data.get(profile, {})
            if existed:
                del data[profile][key]
                self._flush()
            return existed

    def list_keys(self, profile: str) -> list[str]:
        with self._lock:
            return sorted(self._load().get(profile, {}).keys())


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

class Vault:
    """Frente única do vault, escolhe tier automaticamente pelo `settings`."""

    def __init__(self, master_password: str | None = None) -> None:
        encrypted = bool(settings.security.vault_encrypted)
        if encrypted:
            pwd = master_password or os.environ.get("JARVIS_VAULT_PASS")
            if not pwd:
                raise VaultError(
                    "vault_encrypted=True exige master password. "
                    "Defina JARVIS_VAULT_PASS ou passe `master_password=`."
                )
            self._backend: _JsonBackend | _EncryptedBackend = _EncryptedBackend(pwd)
            self._tier = "encrypted"
        else:
            self._backend = _JsonBackend()
            self._tier = "json"

    @property
    def tier(self) -> str:
        return self._tier

    def get(self, key: str, profile: str = "shared", default: Any = None) -> Any:
        _audit("get", profile, key)
        val = self._backend.get(profile, key)
        return val if val is not None else default

    def set(self, key: str, value: Any, profile: str = "shared") -> None:
        _audit("set", profile, key)
        self._backend.set(profile, key, value)

    def delete(self, key: str, profile: str = "shared") -> bool:
        _audit("delete", profile, key)
        return self._backend.delete(profile, key)

    def list_keys(self, profile: str = "shared") -> list[str]:
        return self._backend.list_keys(profile)

    def profiles(self) -> Iterable[str]:
        return _VALID_PROFILES


_vault_singleton: Vault | None = None


def get_vault() -> Vault:
    global _vault_singleton
    if _vault_singleton is None:
        _vault_singleton = Vault()
    return _vault_singleton


def _cli() -> int:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis.credentials.vault")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub_list = sub.add_parser("list")
    sub_list.add_argument("--profile", default="shared")
    sub_set = sub.add_parser("set")
    sub_set.add_argument("key")
    sub_set.add_argument("value")
    sub_set.add_argument("--profile", default="shared")
    sub_get = sub.add_parser("get")
    sub_get.add_argument("key")
    sub_get.add_argument("--profile", default="shared")
    args = parser.parse_args()
    vault = get_vault()
    if args.cmd == "list":
        for k in vault.list_keys(args.profile):
            print(k)
    elif args.cmd == "set":
        vault.set(args.key, args.value, profile=args.profile)
        print(f"ok (tier={vault.tier})")
    elif args.cmd == "get":
        val = vault.get(args.key, profile=args.profile)
        print(val)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())


__all__ = ["Vault", "VaultError", "get_vault"]
