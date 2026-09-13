"""Cliente LLM unificado — provider-agnostic.

Implementação inicial conservadora: usa o pacote `openai` (cliente do LM Studio
e Groq também é compatível com a interface OpenAI). Não depende de nada
específico do `main.py`; pode ser usado isolado.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Generator, Iterable, Literal

from jarvis.config import settings

log = logging.getLogger(__name__)

Provider = Literal["lmstudio", "groq", "auto"]


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str

    def as_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


# Disclaimers que aparecem com frequência e precisam ser limpos das respostas
_DISCLAIMER_PATTERNS = [
    "como uma ia",
    "como uma inteligência artificial",
    "como assistente virtual",
    "as an ai",
    "i'm just an ai",
]


def scrub_disclaimer(text: str) -> str:
    """Remove disclaimers comuns de LLMs (case-insensitive)."""
    if not text:
        return text
    low = text.lower()
    cleaned = text
    for pat in _DISCLAIMER_PATTERNS:
        idx = low.find(pat)
        while idx >= 0:
            # apaga até o próximo ponto final, mas conservador
            end = cleaned.find(".", idx)
            if end < 0:
                end = idx + len(pat)
            cleaned = (cleaned[:idx] + cleaned[end + 1:]).strip()
            low = cleaned.lower()
            idx = low.find(pat)
    return cleaned.strip()


class LLMClient:
    """Cliente LLM thread-safe com histórico múltiplo por chave."""

    DEFAULT_HISTORY_KEY = "default"
    HISTORY_LIMIT = 21  # system + 10 trocas

    def __init__(self) -> None:
        self._histories: dict[str, list[ChatMessage]] = {}
        self._lock = threading.RLock()
        self._lm = None
        self._groq = None
        self._init_clients()

    # ----------------------------------------------------------------- init
    def _init_clients(self) -> None:
        try:
            from openai import OpenAI
        except Exception:
            log.warning("[llm] pacote `openai` não instalado")
            return

        # Cliente LM Studio (URL local) — sempre tenta criar, é barato
        try:
            self._lm = OpenAI(
                base_url=settings.llm.lmstudio_url,
                api_key="lm-studio",  # qualquer valor
                timeout=30.0,
            )
        except Exception as exc:
            log.debug("[llm] LM Studio indisponível: %s", exc)
            self._lm = None

        # Cliente Groq — precisa de API key no vault ou env
        try:
            import os
            from jarvis.credentials import get_vault

            api_key = os.environ.get("GROQ_API_KEY") or get_vault().get(
                "groq_api_key", profile="shared"
            )
            if api_key:
                self._groq = OpenAI(
                    base_url="https://api.groq.com/openai/v1",
                    api_key=api_key,
                    timeout=30.0,
                )
        except Exception as exc:
            log.debug("[llm] Groq não inicializado: %s", exc)
            self._groq = None

    # ----------------------------------------------------------------- API
    def history(self, key: str = DEFAULT_HISTORY_KEY) -> list[ChatMessage]:
        with self._lock:
            return list(self._histories.setdefault(key, []))

    def reset_history(self, key: str = DEFAULT_HISTORY_KEY) -> None:
        with self._lock:
            self._histories.pop(key, None)

    def chat(
        self,
        text: str,
        *,
        system: str | None = None,
        stream: bool = False,
        provider: Provider = "auto",
        history_key: str = DEFAULT_HISTORY_KEY,
        max_tokens: int = 1024,
    ) -> str | Generator[str, None, None]:
        """Conversa simples; retorna `str` se `stream=False` ou gerador se True."""
        client, model = self._pick(provider)
        if client is None:
            err = "Nenhum provider LLM disponível. Configure LM Studio ou GROQ_API_KEY."
            if stream:
                def _err_gen() -> Generator[str, None, None]:
                    yield err
                return _err_gen()
            return err

        msgs = self._prepare(text, system=system, history_key=history_key)
        if stream:
            return self._stream(client, model, msgs, history_key, max_tokens)
        return self._call(client, model, msgs, history_key, max_tokens)

    # ----------------------------------------------------------------- internals
    def _pick(self, provider: Provider):
        # ordem: provider explícito > settings.llm.provider > fallbacks
        cfg_provider = provider
        if provider == "auto":
            cfg_provider = settings.llm.provider  # type: ignore[assignment]

        if cfg_provider == "lmstudio" and self._lm is not None:
            return self._lm, "local-model"  # LM Studio aceita qualquer string
        if cfg_provider == "groq" and self._groq is not None:
            return self._groq, settings.llm.groq_model
        # fallback: tenta o outro
        if self._groq is not None:
            return self._groq, settings.llm.groq_model
        if self._lm is not None:
            return self._lm, "local-model"
        return None, ""

    def _prepare(self, text: str, *, system: str | None, history_key: str) -> list[dict]:
        with self._lock:
            hist = self._histories.setdefault(history_key, [])
            if system is None:
                system = self._default_system()
            if not hist:
                hist.append(ChatMessage("system", system))
            elif hist[0].content != system:
                hist[0] = ChatMessage("system", system)
            hist.append(ChatMessage("user", text))
            return [m.as_dict() for m in hist]

    def _default_system(self) -> str:
        # Importa lazy para evitar acoplamento — usa `config.py` legado se
        # disponível; senão um prompt mínimo.
        try:
            from config import SYSTEM_PROMPT  # type: ignore
            return SYSTEM_PROMPT
        except Exception:
            return "Você é JARVIS, assistente pessoal."

    def _commit_assistant(self, history_key: str, reply: str) -> None:
        with self._lock:
            hist = self._histories.setdefault(history_key, [])
            hist.append(ChatMessage("assistant", reply))
            limit = self.HISTORY_LIMIT
            if len(hist) > limit:
                self._histories[history_key] = hist[:1] + hist[-(limit - 1):]

    def _call(self, client, model: str, msgs: list[dict], history_key: str, max_tokens: int) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=settings.llm.temperature,
        )
        raw = resp.choices[0].message.content or ""
        reply = scrub_disclaimer(raw)
        self._commit_assistant(history_key, reply)
        return reply

    def _stream(
        self,
        client,
        model: str,
        msgs: list[dict],
        history_key: str,
        max_tokens: int,
    ) -> Generator[str, None, None]:
        stream = client.chat.completions.create(
            model=model,
            messages=msgs,
            max_tokens=max_tokens,
            temperature=settings.llm.temperature,
            stream=True,
        )
        parts: list[str] = []
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and getattr(delta, "content", None):
                parts.append(delta.content)
                yield delta.content
        reply = scrub_disclaimer("".join(parts))
        self._commit_assistant(history_key, reply)


_client_singleton: LLMClient | None = None


def get_client() -> LLMClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = LLMClient()
    return _client_singleton


__all__ = ["LLMClient", "ChatMessage", "scrub_disclaimer", "get_client"]
