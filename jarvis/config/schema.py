"""Schema tipado do `config.user.toml`.

Usa Pydantic v2 se disponível; senão cai num fallback dataclass simples
(para não obrigar instalação imediata da dependência durante o scaffold).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal

try:
    from pydantic import BaseModel, Field, ConfigDict

    _HAS_PYDANTIC = True
except Exception:  # pragma: no cover
    _HAS_PYDANTIC = False


if _HAS_PYDANTIC:

    class _Base(BaseModel):
        model_config = ConfigDict(extra="ignore")

    class GeneralCfg(_Base):
        language: str = "pt-BR"
        tts_voice: str = "pt-BR-AntonioNeural"
        user_name: str = "Senhor"

    class VoiceCfg(_Base):
        wake_word_enabled: bool = False
        ptt_enabled: bool = True
        mic_device: str = "default"

    class FeaturesCfg(_Base):
        spotify: bool = False
        whatsapp: bool = False
        instagram: bool = False
        discord: bool = False
        telegram: bool = False
        gmail: bool = False
        panel_stark: bool = False
        documents_generation: bool = False
        ocr: bool = False
        embeddings: bool = False
        mcp_server: bool = False
        browser_pool: bool = False

    class SecurityCfg(_Base):
        profile: Literal["normal", "paranoid", "kiosk"] = "normal"
        confirm_destructive: bool = True
        allowed_dirs: list[str] = Field(default_factory=lambda: ["~/Downloads", "~/Documents", "~/Desktop"])
        vault_encrypted: bool = False
        vault_os_keyring: bool = False

    class LlmCfg(_Base):
        provider: Literal["groq", "lmstudio", "ollama"] = "groq"
        groq_model: str = "llama-3.3-70b-versatile"
        classifier_model: str = "llama-3.1-8b-instant"
        lmstudio_url: str = "http://127.0.0.1:1234/v1"
        temperature: float = 0.7
        # Quando True, main.py instala o bridge e usa jarvis.llm.LLMClient
        # no lugar dos 4 métodos legados _lm_chat*/_groq_chat*.
        use_modular_client: bool = False

    class MessagingCfg(_Base):
        default_profile: Literal["jarvis", "user"] = "jarvis"
        ambiguity_policy: Literal["ask_user", "prefer_default", "abort"] = "ask_user"

    class BrowserCfg(_Base):
        engine: Literal["chromium", "firefox", "webkit"] = "chromium"
        headless_after_login: bool = True
        max_contexts: int = 3
        share_user_profile: bool = False
        stealth: bool = True
        off_screen_position: bool = True
        human_typing_wpm: int = 280
        human_click_jitter_px: int = 6
        human_pause_min_ms: int = 120
        human_pause_max_ms: int = 480

    class PanelCfg(_Base):
        enabled: bool = False
        host: str = "127.0.0.1"
        port: int = 8765
        remote_access: bool = False

    class Settings(_Base):
        general: GeneralCfg = Field(default_factory=GeneralCfg)
        voice: VoiceCfg = Field(default_factory=VoiceCfg)
        features: FeaturesCfg = Field(default_factory=FeaturesCfg)
        security: SecurityCfg = Field(default_factory=SecurityCfg)
        llm: LlmCfg = Field(default_factory=LlmCfg)
        messaging: MessagingCfg = Field(default_factory=MessagingCfg)
        browser: BrowserCfg = Field(default_factory=BrowserCfg)
        panel: PanelCfg = Field(default_factory=PanelCfg)

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Settings":
            return cls.model_validate(data)

        def to_dict(self) -> dict[str, Any]:
            return self.model_dump()

else:  # pragma: no cover — fallback raso sem pydantic

    @dataclass
    class _Section:
        def to_dict(self) -> dict[str, Any]:
            return asdict(self)

    @dataclass
    class GeneralCfg(_Section):
        language: str = "pt-BR"
        tts_voice: str = "pt-BR-AntonioNeural"
        user_name: str = "Senhor"

    @dataclass
    class VoiceCfg(_Section):
        wake_word_enabled: bool = False
        ptt_enabled: bool = True
        mic_device: str = "default"

    @dataclass
    class FeaturesCfg(_Section):
        spotify: bool = False
        whatsapp: bool = False
        instagram: bool = False
        discord: bool = False
        telegram: bool = False
        gmail: bool = False
        panel_stark: bool = False
        documents_generation: bool = False
        ocr: bool = False
        embeddings: bool = False
        mcp_server: bool = False
        browser_pool: bool = False

    @dataclass
    class SecurityCfg(_Section):
        profile: str = "normal"
        confirm_destructive: bool = True
        allowed_dirs: list[str] = field(default_factory=lambda: ["~/Downloads", "~/Documents", "~/Desktop"])
        vault_encrypted: bool = False
        vault_os_keyring: bool = False

    @dataclass
    class LlmCfg(_Section):
        provider: str = "groq"
        groq_model: str = "llama-3.3-70b-versatile"
        classifier_model: str = "llama-3.1-8b-instant"
        lmstudio_url: str = "http://127.0.0.1:1234/v1"
        temperature: float = 0.7
        use_modular_client: bool = False

    @dataclass
    class MessagingCfg(_Section):
        default_profile: str = "jarvis"
        ambiguity_policy: str = "ask_user"

    @dataclass
    class BrowserCfg(_Section):
        engine: str = "chromium"
        headless_after_login: bool = True
        max_contexts: int = 3
        share_user_profile: bool = False
        stealth: bool = True
        off_screen_position: bool = True
        human_typing_wpm: int = 280
        human_click_jitter_px: int = 6
        human_pause_min_ms: int = 120
        human_pause_max_ms: int = 480

    @dataclass
    class PanelCfg(_Section):
        enabled: bool = False
        host: str = "127.0.0.1"
        port: int = 8765
        remote_access: bool = False

    @dataclass
    class Settings:
        general: GeneralCfg = field(default_factory=GeneralCfg)
        voice: VoiceCfg = field(default_factory=VoiceCfg)
        features: FeaturesCfg = field(default_factory=FeaturesCfg)
        security: SecurityCfg = field(default_factory=SecurityCfg)
        llm: LlmCfg = field(default_factory=LlmCfg)
        messaging: MessagingCfg = field(default_factory=MessagingCfg)
        browser: BrowserCfg = field(default_factory=BrowserCfg)
        panel: PanelCfg = field(default_factory=PanelCfg)

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "Settings":
            kw: dict[str, Any] = {}
            mapping = {
                "general": GeneralCfg, "voice": VoiceCfg, "features": FeaturesCfg,
                "security": SecurityCfg, "llm": LlmCfg, "messaging": MessagingCfg,
                "browser": BrowserCfg, "panel": PanelCfg,
            }
            for k, klass in mapping.items():
                section = data.get(k) or {}
                if not isinstance(section, dict):
                    section = {}
                allowed = {f.name for f in klass.__dataclass_fields__.values()}  # type: ignore[attr-defined]
                section = {kk: vv for kk, vv in section.items() if kk in allowed}
                kw[k] = klass(**section)
            return cls(**kw)

        def to_dict(self) -> dict[str, Any]:
            return {k: asdict(getattr(self, k)) for k in (
                "general", "voice", "features", "security", "llm", "messaging", "browser", "panel"
            )}


__all__ = ["Settings"]
