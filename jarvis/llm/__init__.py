"""Cliente LLM unificado do JARVIS.

API pública:

    from jarvis.llm import LLMClient, get_client

    client = get_client()
    reply = client.chat("oi")
    for chunk in client.chat("conta uma piada", stream=True):
        print(chunk, end="", flush=True)

Suporta dois providers (auto-fallback):
- `lmstudio` (preferido se disponível em `settings.llm.lmstudio_url`)
- `groq` (fallback / default em produção)

Toda lógica de histórico, scrub de disclaimer e persistência viveem um
único ponto. Substitui os 4 métodos espalhados em `main.py`
(`_lm_chat`, `_lm_chat_stream`, `_groq_chat`, `_groq_chat_stream`).
"""

from .client import LLMClient, ChatMessage, get_client

__all__ = ["LLMClient", "ChatMessage", "get_client"]
