"""
ConfigManager — single source of truth para configurações do JARVIS.

Fonte de verdade hierárquica:
    1. Defaults em config.py (carregados no import)
    2. credentials/.env (sobrepõe via os.environ ↔ config._load_dotenv)
    3. credentials/jarvis_prefs.json → seção "settings" (sobrepõe tudo)

Características:
    - Thread-safe (RLock)
    - Pub/sub via core.event_bus ("config.changed.<KEY>")
    - set() atualiza atributo no módulo `config` em tempo real
      (todo `import config; config.X` futuro vê o novo valor)
    - Persistência atômica em jarvis_prefs.json
    - Schema mínimo para validação de tipo

Uso:
    from core.config_manager import get_config_manager
    cm = get_config_manager()
    cm.subscribe("TTS_PROVIDER", lambda payload: print("mudou:", payload))
    cm.set("TTS_PROVIDER", "edge")
    print(cm.get("TTS_PROVIDER"))   # → "edge"
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from typing import Any, Callable

try:
    from core.event_bus import publish as _ev_publish
except Exception:  # pragma: no cover
    def _ev_publish(topic: str, payload: dict | None = None) -> None:
        pass


# ── Schema mínimo (estende conforme expor mais campos na UI) ─────────────────
# Para cada chave configurável: type + (opcional) choices/min/max
# Campos NÃO listados aqui ainda podem ser lidos via get() (passa pelo defaut
# de config.py). set() rejeita campos sem schema (whitelist de segurança).
_SCHEMA: dict[str, dict[str, Any]] = {
    # — TTS / Voz —
    "TTS_PROVIDER":          {"type": "str",   "choices": ["auto", "edge", "elevenlabs", "gemini", "kokoro"]},
    "VOZ_EDGE":              {"type": "str"},
    "VOZ_EDGE_EN":           {"type": "str"},
    "VOZ_RATE":              {"type": "str"},
    "VOZ_PITCH":             {"type": "str"},
    "ELEVENLABS_VOICE_ID":   {"type": "str"},
    "ELEVENLABS_MODEL":      {"type": "str"},
    "GEMINI_TTS_VOICE":      {"type": "str"},
    "GEMINI_TTS_MODEL":      {"type": "str"},

    # — Modelos LLM —
    "LLM_PROVIDER":          {"type": "str",   "choices": ["groq", "lmstudio"]},
    "GROQ_MODELO_CHAT":      {"type": "str"},
    "GROQ_MODELO_CLS":       {"type": "str"},
    "GROQ_VISION_MODEL":     {"type": "str"},
    "LMSTUDIO_TEXT_MODEL":   {"type": "str"},
    "LMSTUDIO_VISION_MODEL": {"type": "str"},
    "LMSTUDIO_BASE_URL":     {"type": "str"},
    "MAX_CHAT_TURNS":        {"type": "int",   "min": 1, "max": 40},
    "MAX_GROQ_TURNS":        {"type": "int",   "min": 1, "max": 40},

    # — Localização / comportamento básico —
    "CIDADE_PADRAO":         {"type": "str"},
    "DITADO_AUTO_COLAR":     {"type": "bool"},

    # — Away mode / notificações —
    "AWAY_ENABLED":                       {"type": "bool"},
    "AWAY_IDLE_MINUTES":                  {"type": "int",   "min": 1,  "max": 240},
    "AWAY_CAMERA_MINUTES":                {"type": "int",   "min": 1,  "max": 240},
    "AWAY_AUTO_REPLY":                    {"type": "bool"},
    "AWAY_REPORT_ON_RETURN":              {"type": "bool"},
    "AWAY_REPLY_APPS":                    {"type": "list_str"},
    "AWAY_REPLY_PROMPT":                  {"type": "str"},
    "INSTAGRAM_USE_API":                  {"type": "bool"},
    "INSTAGRAM_AWAY_REPLY_COOLDOWN_MIN":  {"type": "float", "min": 0.0, "max": 600.0},
    "INSTAGRAM_AWAY_REPLY_COOLDOWN_MAX":  {"type": "float", "min": 0.0, "max": 600.0},
    "DISCORD_REPLY_COOLDOWN_MIN":         {"type": "float", "min": 0.0, "max": 600.0},
    "DISCORD_MY_USERNAME":                {"type": "str"},

    # — Áudio ambiente —
    "AMBIENT_LISTEN_ENABLED":     {"type": "bool"},
    "AMBIENT_STT_BACKEND":        {"type": "str",   "choices": ["groq", "faster_whisper"]},
    "AMBIENT_BUFFER_MINUTES":     {"type": "int",   "min": 1,  "max": 480},
    "AMBIENT_PERSIST_TO_DISK":    {"type": "bool"},
    "AMBIENT_PROACTIVE_ENABLED":  {"type": "bool"},
    "AMBIENT_PROACTIVE_COOLDOWN_S": {"type": "int", "min": 0,  "max": 3600},

    # — Câmera / presença —
    "CAMERA_BROKER_ENABLED":  {"type": "bool"},
    "PRESENCE_ENABLED":       {"type": "bool"},
    "PRESENCE_FPS":           {"type": "int",   "min": 1,  "max": 30},

    # — System audio loopback —
    "SYSTEM_AUDIO_ENABLED":      {"type": "bool"},
    "SYSTEM_AUDIO_CHUNK_S":      {"type": "int",   "min": 1,  "max": 60},
    "SYSTEM_AUDIO_MIN_RMS":      {"type": "int",   "min": 0,  "max": 10000},
    "SYSTEM_AUDIO_REACT_CHANCE": {"type": "float", "min": 0.0, "max": 1.0},

    # — Segurança / embeddings (avançado) —
    "SECURITY_ENABLED":        {"type": "bool"},
    "INJECTION_BLOCK_ENABLED": {"type": "bool"},
    "EMBEDDING_ENABLED":       {"type": "bool"},
    "EMBEDDING_THRESHOLD":     {"type": "float", "min": 0.0, "max": 1.0},

    # — Browser —
    "BROWSER_CDP_PORT":  {"type": "int",   "min": 1, "max": 65535,
                          "desc": "Porta de depuração remota para conectar ao browser já aberto (CDP)."},
    "BROWSER_PREFERRED": {"type": "str",
                          "desc": "Browser preferido para automação (brave, chrome, edge). Vazio = auto-detect."},
    # Sprint 2 — controle do Chromium humanizado (mensageria)
    "BROWSER_OFFSCREEN":            {"type": "bool", "new": True,
                                     "desc": "Janela do Chromium da mensageria fica fora da tela (-32000,0) p/ não roubar foco. Recomendado: LIGADO."},
    "BROWSER_FIRST_LOGIN_VISIBLE":  {"type": "bool", "new": True,
                                     "desc": "Na 1ª execução de cada plataforma (WhatsApp/Insta/Discord/etc.) abre visível p/ você escanear QR ou logar. Depois volta ao normal. Recomendado: LIGADO."},

    # — LLM (cliente modular opt-in, Sprint 2) —
    "LLM_USE_MODULAR_CLIENT": {"type": "bool", "new": True,
                              "desc": "Usa o cliente LLM unificado (jarvis/llm) com retry/streaming consistentes. Experimental. Reinicie após alterar."},

    # — Mensageria (Sprint 3) —
    "MESSAGING_SEND_METHOD": {"type": "str", "new": True,
                              "choices": ["browser", "pyautogui", "auto"],
                              "desc": "Como enviar mensagens: 'browser' (Chromium humanizado), 'pyautogui' (cola texto no app desktop) ou 'auto' (browser → fallback pyautogui)."},
    "MESSAGING_PYAUTOGUI_DELAY_MS": {"type": "int", "new": True, "min": 0, "max": 5000,
                              "desc": "Delay entre teclas ao usar pyautogui (ms). Mais alto = mais humano, menos detectável."},

    # — Inbox Watcher (Sprint 3) —
    "INBOX_WATCHER_ENABLED": {"type": "bool", "new": True,
                              "desc": "Liga o monitoramento periódico de novas mensagens nas plataformas conectadas."},
    "INBOX_POLL_INTERVAL_S": {"type": "int", "new": True, "min": 10, "max": 600,
                              "desc": "Intervalo (segundos) entre cada varredura de mensagens não lidas. Mínimo 10s."},
    "INBOX_NOTIFY_TTS": {"type": "bool", "new": True,
                              "desc": "Se ligado, o Jarvis fala 'nova mensagem de X' em voz alta quando algo chega."},

    # — WhatsApp —
    "WHATSAPP_COUNTRY_CODE": {"type": "str",
                              "desc": "Código do país (DDI) usado ao enviar WhatsApp via número. Brasil = 55."},
}


def _coerce(value: Any, kind: str) -> Any:
    """Coerce + valida tipo. Levanta ValueError em entrada inválida."""
    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on", "sim"):
                return True
            if v in ("false", "0", "no", "off", "nao", "não"):
                return False
        raise ValueError(f"valor booleano inválido: {value!r}")
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    if kind == "str":
        return str(value) if value is not None else ""
    if kind == "list_str":
        if isinstance(value, (list, tuple)):
            return [str(x) for x in value]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        raise ValueError(f"esperado lista de strings: {value!r}")
    return value


class ConfigManager:
    """Singleton — use get_config_manager()."""

    def __init__(self, prefs_path: str | None = None) -> None:
        self._lock = threading.RLock()
        # Lazy import — evita ciclo
        try:
            import config as _cfg
            self._cfg = _cfg
        except Exception:
            self._cfg = None  # tests podem instanciar sem config.py
        self._prefs_path = prefs_path or self._resolve_prefs_path()
        self._overrides: dict[str, Any] = {}
        self._load_overrides()
        # Aplica overrides no módulo config para reads imediatos verem
        self._apply_overrides_to_config_module()

    # ── persistência ──────────────────────────────────────────────────────────
    def _resolve_prefs_path(self) -> str:
        try:
            from config import PATHS as _P  # type: ignore
            return _P["prefs"]
        except Exception:
            try:
                from config import creds_path  # type: ignore
                return creds_path("jarvis_prefs.json")
            except Exception:
                base = os.path.dirname(os.path.abspath(__file__))
                return os.path.join(os.path.dirname(base), "jarvis_prefs.json")

    def _load_overrides(self) -> None:
        try:
            if not os.path.exists(self._prefs_path):
                return
            with open(self._prefs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            settings = data.get("settings") or {}
            if isinstance(settings, dict):
                self._overrides = dict(settings)
        except Exception:
            self._overrides = {}

    def _persist(self) -> None:
        """Grava overlay 'settings' no jarvis_prefs.json preservando outras chaves."""
        existing: dict[str, Any] = {}
        try:
            if os.path.exists(self._prefs_path):
                with open(self._prefs_path, "r", encoding="utf-8") as f:
                    existing = json.load(f) or {}
        except Exception:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing["settings"] = dict(self._overrides)
        # write atômico (tmp + replace)
        d = os.path.dirname(self._prefs_path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".prefs_", suffix=".json.tmp", dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self._prefs_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _apply_overrides_to_config_module(self) -> None:
        """Aplica overrides como atributos no módulo `config` (live read)."""
        if not self._cfg:
            return
        for k, v in self._overrides.items():
            try:
                setattr(self._cfg, k, v)
            except Exception:
                pass

    # ── API pública ───────────────────────────────────────────────────────────
    def get(self, key: str, default: Any = None) -> Any:
        """Lê valor atual: override → módulo config → default."""
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
        if self._cfg and hasattr(self._cfg, key):
            return getattr(self._cfg, key)
        return default

    def set(self, key: str, value: Any, persist: bool = True) -> dict[str, Any]:
        """Atualiza chave. Retorna {ok, key, value, msg}.

        - Valida contra _SCHEMA (whitelist de segurança)
        - Coerce automático de tipo
        - Atualiza módulo `config` (todos os `import config; config.X` veem)
        - Persiste em prefs JSON
        - Publica `config.changed.<KEY>` no event_bus
        """
        if key not in _SCHEMA:
            return {"ok": False, "key": key, "msg": f"chave '{key}' não está no schema"}
        spec = _SCHEMA[key]
        try:
            coerced = _coerce(value, spec["type"])
        except (ValueError, TypeError) as e:
            return {"ok": False, "key": key, "msg": f"tipo inválido: {e}"}
        if "choices" in spec and coerced not in spec["choices"]:
            return {"ok": False, "key": key,
                    "msg": f"valor deve ser um de: {spec['choices']}"}
        if "min" in spec and coerced < spec["min"]:
            return {"ok": False, "key": key, "msg": f"abaixo do mínimo ({spec['min']})"}
        if "max" in spec and coerced > spec["max"]:
            return {"ok": False, "key": key, "msg": f"acima do máximo ({spec['max']})"}

        with self._lock:
            old = self.get(key)
            self._overrides[key] = coerced
            if self._cfg:
                try:
                    setattr(self._cfg, key, coerced)
                except Exception:
                    pass
            if persist:
                try:
                    self._persist()
                except Exception as e:
                    return {"ok": False, "key": key, "msg": f"erro ao persistir: {e}"}

        # Publica fora do lock para evitar deadlock de subscribers
        try:
            _ev_publish(f"config.changed.{key}",
                        {"key": key, "old": old, "new": coerced})
            _ev_publish("config.changed",
                        {"key": key, "old": old, "new": coerced})
        except Exception:
            pass
        return {"ok": True, "key": key, "value": coerced, "msg": "aplicado"}

    def subscribe(self, key: str, handler: Callable[[dict], None]):
        """Inscreve handler para mudanças em `key`. Use '*' para todas."""
        try:
            from core.event_bus import subscribe as _sub
        except Exception:
            return lambda: None
        topic = "config.changed" if key == "*" else f"config.changed.{key}"
        return _sub(topic, handler)

    def schema(self) -> dict[str, dict[str, Any]]:
        """Retorna cópia do schema (para a UI montar formulários)."""
        return {k: dict(v) for k, v in _SCHEMA.items()}

    def all_settings(self) -> dict[str, Any]:
        """Snapshot atual de todas as chaves do schema (resolvidas)."""
        return {k: self.get(k) for k in _SCHEMA.keys()}

    def reset(self, key: str) -> dict[str, Any]:
        """Remove override (volta ao default de config.py)."""
        with self._lock:
            if key not in self._overrides:
                return {"ok": True, "key": key, "msg": "sem override"}
            self._overrides.pop(key, None)
            # Recarrega config.py para pegar default original
            try:
                import importlib
                importlib.reload(self._cfg)  # type: ignore[arg-type]
            except Exception:
                pass
            try:
                self._persist()
            except Exception as e:
                return {"ok": False, "key": key, "msg": f"erro ao persistir: {e}"}
        try:
            _ev_publish(f"config.changed.{key}", {"key": key, "old": None,
                        "new": self.get(key), "reset": True})
        except Exception:
            pass
        return {"ok": True, "key": key, "value": self.get(key), "msg": "resetado"}

    def reload_from_disk(self) -> None:
        """Recarrega .env, config.py e overrides do disco. Use quando .env muda."""
        try:
            from dotenv import load_dotenv  # type: ignore
            from config import creds_path  # type: ignore
            env_path = creds_path(".env")
            if os.path.exists(env_path):
                load_dotenv(dotenv_path=env_path, override=True)
        except Exception:
            pass
        try:
            import importlib
            if self._cfg:
                importlib.reload(self._cfg)
        except Exception:
            pass
        with self._lock:
            self._load_overrides()
            self._apply_overrides_to_config_module()
        try:
            _ev_publish("config.reloaded", {})
        except Exception:
            pass


# ── Singleton ────────────────────────────────────────────────────────────────
_INSTANCE: ConfigManager | None = None
_INSTANCE_LOCK = threading.Lock()


def get_config_manager() -> ConfigManager:
    """Singleton accessor."""
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = ConfigManager()
    return _INSTANCE
