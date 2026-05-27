"""Migração: lê `config.py` legado + `credentials/.env` e popula:
- `%APPDATA%/JARVIS/config.user.toml`  (toggles + LLM provider)
- vault tier-1 com `groq_api_key`, `gemini_api_key`, `cohere_api_key`, etc.

Idempotente: rodar várias vezes não duplica nem sobrescreve sem confirmação.

Uso:
    .\\.venv\\Scripts\\python.exe -m tools.migrate_to_user_config           # dry-run
    .\\.venv\\Scripts\\python.exe -m tools.migrate_to_user_config --apply   # grava
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# faz imports do projeto funcionarem mesmo executado direto
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _read_legacy_secrets() -> dict[str, str]:
    secrets: dict[str, str] = {}
    # carrega via dotenv se disponível
    try:
        from dotenv import dotenv_values

        for candidate in (_ROOT / "credentials" / ".env", _ROOT / ".env"):
            if candidate.is_file():
                for k, v in dotenv_values(candidate).items():
                    if k and v and k not in secrets:
                        secrets[k] = v
    except Exception:
        pass
    # também aceita já presente no env
    for key in ("GROQ_API_KEY", "GEMINI_API_KEY", "COHERE_API_KEY", "OPENWEATHER_API_KEY"):
        if key in os.environ and key not in secrets:
            secrets[key] = os.environ[key]
    return secrets


def _build_user_toml() -> str:
    """Snippet TOML inicial — toggles em OFF, provider lido do legado se ok."""
    try:
        import config as legacy  # type: ignore
        provider = getattr(legacy, "LLM_PROVIDER", "groq")
        groq_model = getattr(legacy, "GROQ_MODELO_CHAT", "llama-3.3-70b-versatile")
        cls_model = getattr(legacy, "GROQ_MODELO_CLS", "llama-3.1-8b-instant")
        lm_url = getattr(legacy, "LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    except Exception:
        provider, groq_model, cls_model, lm_url = "groq", "llama-3.3-70b-versatile", "llama-3.1-8b-instant", "http://127.0.0.1:1234/v1"

    return f"""# Migrado de config.py legado em {os.path.basename(sys.argv[0])}

[general]
language = "pt-BR"
tts_voice = "pt-BR-AntonioNeural"

[llm]
provider = "{provider}"
groq_model = "{groq_model}"
classifier_model = "{cls_model}"
lmstudio_url = "{lm_url}"

# Toggles permanecem OFF — habilite manualmente conforme for usar.
[features]
spotify = false
whatsapp = false
instagram = false
discord = false
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.migrate_to_user_config")
    parser.add_argument("--apply", action="store_true", help="grava no disco (default: dry-run)")
    args = parser.parse_args(argv)

    from jarvis.config.paths import user_config_file
    from jarvis.credentials import get_vault

    out_toml = user_config_file()
    toml_content = _build_user_toml()
    secrets = _read_legacy_secrets()

    print(f"[migrate] arquivo destino: {out_toml}")
    print(f"[migrate] TOML a gerar:\n---\n{toml_content}---")
    print(f"[migrate] segredos detectados:")
    for k in sorted(secrets.keys()):
        print(f"  • {k}: {'*' * 8} ({len(secrets[k])} chars)")

    if not args.apply:
        print("[migrate] dry-run (use --apply para gravar).")
        return 0

    # grava TOML — não sobrescreve se já existe
    if out_toml.exists():
        print(f"[migrate] já existe {out_toml}; pulando escrita do TOML.")
    else:
        out_toml.write_text(toml_content, encoding="utf-8")
        print(f"[migrate] escrito {out_toml}")

    # popula vault
    vault = get_vault()
    mapping = {
        "GROQ_API_KEY": "groq_api_key",
        "GEMINI_API_KEY": "gemini_api_key",
        "COHERE_API_KEY": "cohere_api_key",
        "OPENWEATHER_API_KEY": "openweather_api_key",
    }
    for env_name, vault_key in mapping.items():
        if env_name in secrets and secrets[env_name]:
            existing = vault.get(vault_key, profile="shared")
            if existing:
                print(f"[migrate] vault já possui {vault_key}; mantendo valor existente.")
            else:
                vault.set(vault_key, secrets[env_name], profile="shared")
                print(f"[migrate] vault.set shared/{vault_key}")

    print("[migrate] concluído.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
