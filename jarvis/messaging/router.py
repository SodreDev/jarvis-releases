"""Router de mensageria — escolhe backend por (plataforma, perfil)."""
from __future__ import annotations

from typing import Callable, Optional

from jarvis.config import settings

from .base import MessageBackend, Platform, Profile, SendResult, get_backend, iter_backends


class AmbiguityError(RuntimeError):
    """Levantada quando há mais de um backend possível e a policy é `abort`."""


# tipo de callback para perguntar ao usuário (UI plugada de fora)
AskUserFn = Callable[[str, list[str]], str]


class MessagingRouter:
    def __init__(self, ask_user: AskUserFn | None = None) -> None:
        self._ask_user = ask_user

    def set_ask_user(self, fn: AskUserFn) -> None:
        self._ask_user = fn

    def resolve(
        self,
        platform: Platform,
        *,
        profile_hint: Profile | None = None,
    ) -> MessageBackend:
        """Resolve qual backend usar respeitando settings + policy."""
        default = profile_hint or settings.messaging.default_profile

        # se temos backend pro perfil pedido, retornamos.
        be = get_backend(platform, default)  # type: ignore[arg-type]
        if be is not None:
            return be

        # tenta o outro perfil disponível
        candidates = [p for (pl, p) in iter_backends() if pl == platform]
        if not candidates:
            raise AmbiguityError(f"nenhum backend registrado para {platform!r}")

        if len(candidates) == 1:
            only = candidates[0]
            return get_backend(platform, only)  # type: ignore[return-value, arg-type]

        # múltiplos candidatos disponíveis e o preferido não respondeu
        policy = settings.messaging.ambiguity_policy
        if policy == "abort":
            raise AmbiguityError(
                f"múltiplos perfis disponíveis para {platform!r}: {candidates}"
            )
        if policy == "prefer_default":
            chosen = candidates[0]
        else:  # ask_user
            if self._ask_user is None:
                # sem callback registrado — defaulta para o primeiro com aviso
                chosen = candidates[0]
            else:
                chosen = self._ask_user(
                    f"De qual perfil enviar via {platform}?", candidates
                )
        be = get_backend(platform, chosen)  # type: ignore[arg-type]
        if be is None:
            raise AmbiguityError(f"backend {platform}/{chosen} não disponível")
        return be

    def send(
        self,
        platform: Platform,
        dest: str,
        content: str,
        *,
        profile_hint: Profile | None = None,
    ) -> SendResult:
        method = _get_send_method()
        if method == "pyautogui":
            return _send_via_pyautogui(platform, dest, content, profile_hint or "user")
        backend = self.resolve(platform, profile_hint=profile_hint)
        res = backend.send(dest, content)
        if (not res.ok) and method == "auto":
            # Fallback pyautogui
            return _send_via_pyautogui(platform, dest, content, profile_hint or "user")
        return res


def _get_send_method() -> str:
    try:
        import config as _cfg
        m = str(getattr(_cfg, "MESSAGING_SEND_METHOD", "browser")).lower().strip()
        return m if m in ("browser", "pyautogui", "auto") else "browser"
    except Exception:
        return "browser"


def _send_via_pyautogui(platform, dest, content, profile) -> SendResult:
    from datetime import datetime
    try:
        from .pyautogui_sender import send_via_pyautogui
        r = send_via_pyautogui(str(platform), dest, content)
        return SendResult(
            ok=r.ok, platform=platform, profile=profile,
            dest=dest, error=r.error,
            sent_at=datetime.utcnow() if r.ok else None,
        )
    except Exception as e:                                          # noqa: BLE001
        return SendResult(
            ok=False, platform=platform, profile=profile,
            dest=dest, error=f"pyautogui:{type(e).__name__}:{e}",
        )


_router_singleton: MessagingRouter | None = None


def get_router() -> MessagingRouter:
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = MessagingRouter()
    return _router_singleton


__all__ = ["MessagingRouter", "AmbiguityError", "get_router"]
