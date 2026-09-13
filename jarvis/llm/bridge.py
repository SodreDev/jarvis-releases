"""Bridge opt-in: redireciona os 4 chat methods do main.py para LLMClient.

USO (futuro, em main.py — não invasivo, controlado por config):

    from jarvis.llm.bridge import maybe_install_bridge
    maybe_install_bridge(self)   # self = instância da classe JARVIS no main

Só age se `settings.llm.use_modular_client = true` no `config.user.toml`.
Caso contrário, retorna sem fazer nada (zero efeito colateral).

Por que monkey-patch e não edição direta:
  • Mantém main.py legado intocado durante a transição.
  • Permite A/B testing: troca a flag, reinicia, compara comportamento.
  • Se algo der ruim, basta voltar a flag para `false`.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def maybe_install_bridge(jarvis_obj: Any) -> bool:
    """Substitui _lm_chat/_lm_chat_stream/_groq_chat/_groq_chat_stream por LLMClient.

    Retorna True se substituiu, False se não (config off ou falha).
    """
    # Aceita liga/desliga via 2 fontes (qualquer uma True basta):
    #   1) config.LLM_USE_MODULAR_CLIENT (editável pela UI — drawer "Tudo")
    #   2) settings.llm.use_modular_client (config.user.toml)
    enabled = False
    try:
        import config as _legacy_cfg
        if getattr(_legacy_cfg, "LLM_USE_MODULAR_CLIENT", False):
            enabled = True
    except Exception:                                            # noqa: BLE001
        pass
    if not enabled:
        try:
            from ..config import get_settings
            settings = get_settings()
            if getattr(settings.llm, "use_modular_client", False):
                enabled = True
        except Exception:                                        # noqa: BLE001
            pass
    if not enabled:
        return False

    try:
        from .client import get_client
        client = get_client()
    except Exception as e:                                       # noqa: BLE001
        log.warning("[llm.bridge] falha ao inicializar LLMClient: %s", e)
        return False

    # --- Wrappers que mantêm a assinatura legada ---
    def _lm_chat(self, text, system=None):                       # noqa: ARG001
        return client.chat(text, system=system, provider="lmstudio", stream=False)

    def _lm_chat_stream(self, text, system=None, max_tokens=1024):  # noqa: ARG001
        return client.chat(
            text, system=system, provider="lmstudio", stream=True, max_tokens=max_tokens,
        )

    def _groq_chat(self, text):                                  # noqa: ARG001
        return client.chat(text, provider="groq", stream=False)

    def _groq_chat_stream(self, text, system=None):              # noqa: ARG001
        return client.chat(text, system=system, provider="groq", stream=True)

    # Bind dos métodos na instância
    import types
    jarvis_obj._lm_chat = types.MethodType(_lm_chat, jarvis_obj)
    jarvis_obj._lm_chat_stream = types.MethodType(_lm_chat_stream, jarvis_obj)
    jarvis_obj._groq_chat = types.MethodType(_groq_chat, jarvis_obj)
    jarvis_obj._groq_chat_stream = types.MethodType(_groq_chat_stream, jarvis_obj)
    log.info("[llm.bridge] LLMClient modular instalado (4 métodos sobrescritos).")
    return True


__all__ = ["maybe_install_bridge"]
