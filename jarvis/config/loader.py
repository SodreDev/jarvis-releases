"""Loader do `config.user.toml`.

Estratégia:
1. Merge profundo dos `DEFAULTS` com o conteúdo do TOML do usuário.
2. Validação via `Settings.from_dict`.
3. Cache singleton; `reload_settings()` re-lê do disco.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

from .defaults import DEFAULTS
from .paths import dev_config_override, user_config_file
from .schema import Settings

# tomllib é stdlib desde 3.11; em 3.10 usa-se `tomli`.
try:
    import tomllib  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except Exception:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


_settings_cache: Settings | None = None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file() or tomllib is None:
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except Exception as exc:  # pragma: no cover
        print(f"[config] aviso: falha lendo {path}: {exc}", file=sys.stderr)
        return {}


def _resolve_source() -> tuple[Path | None, dict[str, Any]]:
    """Procura override de dev, depois APPDATA."""
    for candidate in (dev_config_override(), user_config_file()):
        data = _read_toml(candidate)
        if data:
            return candidate, data
    return None, {}


def get_settings() -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = _load()
    return _settings_cache


def reload_settings() -> Settings:
    global _settings_cache
    _settings_cache = _load()
    return _settings_cache


def _load() -> Settings:
    _, user_dict = _resolve_source()
    merged = _deep_merge(DEFAULTS, user_dict)
    return Settings.from_dict(merged)


def _cli() -> int:  # pragma: no cover - utilitário manual
    src, user = _resolve_source()
    settings = get_settings()
    print(f"[config] fonte: {src or '(defaults internos)'}")
    print(f"[config] features ativas:")
    feats = settings.features.model_dump() if hasattr(settings.features, "model_dump") else settings.features.__dict__
    for k, v in feats.items():
        flag = "ON " if v else "off"
        print(f"  [{flag}] {k}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())


__all__ = ["get_settings", "reload_settings"]
