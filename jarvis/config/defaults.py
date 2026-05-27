"""Defaults internos do JARVIS — usados quando o `config.user.toml` está
ausente ou incompleto. **Todos os toggles default OFF** (Plano 12).
"""
from __future__ import annotations

DEFAULTS: dict = {
    "general": {
        "language": "pt-BR",
        "tts_voice": "pt-BR-AntonioNeural",
        "user_name": "Senhor",
    },
    "voice": {
        "wake_word_enabled": False,
        "ptt_enabled": True,
        "mic_device": "default",
    },
    "features": {
        "spotify": False,
        "whatsapp": False,
        "instagram": False,
        "discord": False,
        "telegram": False,
        "gmail": False,
        "panel_stark": False,
        "documents_generation": False,
        "ocr": False,
        "embeddings": False,
        "mcp_server": False,
        "browser_pool": False,
    },
    "security": {
        "profile": "normal",  # normal | paranoid | kiosk
        "confirm_destructive": True,
        "allowed_dirs": ["~/Downloads", "~/Documents", "~/Desktop"],
        "vault_encrypted": False,
        "vault_os_keyring": False,
    },
    "llm": {
        "provider": "groq",  # groq | lmstudio | ollama
        "groq_model": "llama-3.3-70b-versatile",
        "classifier_model": "llama-3.1-8b-instant",
        "lmstudio_url": "http://127.0.0.1:1234/v1",
        "temperature": 0.7,
        # Quando True, main.py instala o bridge modular (jarvis.llm.LLMClient).
        "use_modular_client": False,
    },
    "messaging": {
        "default_profile": "jarvis",  # jarvis | user
        "ambiguity_policy": "ask_user",  # ask_user | prefer_default | abort
    },
    "browser": {
        "engine": "chromium",
        "headless_after_login": True,
        "max_contexts": 3,
        "share_user_profile": False,
        "stealth": True,
        "off_screen_position": True,  # posiciona fora da área visível p/ não atrapalhar
        "human_typing_wpm": 280,  # ~280 char/min, gaussiano
        "human_click_jitter_px": 6,
        "human_pause_min_ms": 120,
        "human_pause_max_ms": 480,
    },
    "panel": {
        "enabled": False,
        "host": "127.0.0.1",
        "port": 8765,
        "remote_access": False,
    },
}


__all__ = ["DEFAULTS"]
