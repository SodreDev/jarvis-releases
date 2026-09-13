"""PyAutoGUI Sender — alternativa ao envio via browser.

Quando `config.MESSAGING_SEND_METHOD = "pyautogui"` (ou "auto" e o browser
falhou), abre o app desktop correspondente (WhatsApp Desktop, Telegram Desktop,
etc.), foca o campo de mensagem e digita o texto com delay humano.

LIMITAÇÕES:
  • Requer que o app desktop esteja instalado e logado.
  • Tem que abrir/focar a janela — pode roubar foco do usuário.
  • Funciona melhor com Telegram Desktop e WhatsApp Desktop (têm deep-links
    `tg://resolve` e `whatsapp://send`). Instagram/Discord não têm protocolo
    universal, então caem para abrir o app via Start menu e busca.
  • Gmail NÃO suporta pyautogui (não tem cliente desktop oficial).

Arquitetura: cada plataforma tem uma função `_send_<platform>(dest, content, delay_ms)`
que:
  1. dispara o deep-link `os.startfile()` ou abre o app via subprocess
  2. espera N ms a janela aparecer
  3. digita o texto via pyautogui.write/typewrite
  4. envia com Enter

A janela alvo é encontrada via título — não usamos hwnd direto pra evitar
dependência de pywin32.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class PyAutoGUIResult:
    ok: bool
    platform: str
    dest: str
    error: Optional[str] = None


def _delay() -> float:
    try:
        import config as _cfg
        return max(0.0, int(getattr(_cfg, "MESSAGING_PYAUTOGUI_DELAY_MS", 40))) / 1000.0
    except Exception:
        return 0.04


def _ensure_pyautogui():
    try:
        import pyautogui  # noqa: F401
        return True
    except Exception as e:                                          # noqa: BLE001
        log.warning("pyautogui indisponível: %s", e)
        return False


def _type_text(text: str) -> None:
    import pyautogui
    pyautogui.PAUSE = _delay()
    # write() não suporta acentuação em layouts não-US. Para conteúdo
    # com caracteres especiais, usa clipboard + Ctrl+V.
    has_special = any(ord(c) > 127 for c in text)
    if has_special:
        try:
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            return
        except Exception:
            pass
    pyautogui.typewrite(text, interval=_delay())


def _send_whatsapp(dest: str, content: str) -> PyAutoGUIResult:
    """WhatsApp Desktop — deep-link `whatsapp://send?phone=...&text=...`."""
    try:
        text_enc = urllib.parse.quote(content)
        url = f"whatsapp://send?phone={dest}&text={text_enc}"
        os.startfile(url)  # type: ignore[attr-defined]
        time.sleep(2.0)  # janela carregar
        import pyautogui
        pyautogui.PAUSE = _delay()
        # whatsapp:// já preenche o campo; só confirma com Enter
        pyautogui.press("enter")
        return PyAutoGUIResult(ok=True, platform="whatsapp", dest=dest)
    except Exception as e:                                          # noqa: BLE001
        return PyAutoGUIResult(ok=False, platform="whatsapp", dest=dest, error=str(e))


def _send_telegram(dest: str, content: str) -> PyAutoGUIResult:
    """Telegram Desktop — deep-link `tg://resolve?domain=<user>`."""
    try:
        # aceita @user, user, ou +55…
        d = dest.lstrip("@")
        url = f"tg://resolve?domain={d}"
        os.startfile(url)  # type: ignore[attr-defined]
        time.sleep(1.8)
        import pyautogui
        pyautogui.PAUSE = _delay()
        _type_text(content)
        pyautogui.press("enter")
        return PyAutoGUIResult(ok=True, platform="telegram", dest=dest)
    except Exception as e:                                          # noqa: BLE001
        return PyAutoGUIResult(ok=False, platform="telegram", dest=dest, error=str(e))


def _send_discord(dest: str, content: str) -> PyAutoGUIResult:
    """Discord Desktop — não tem deep-link estável; abre Discord (já logado)
    e cola texto. O usuário deve estar com o canal/DM correto aberto.

    Sprint 5+: usar busca rápida (Ctrl+K) com `dest`."""
    try:
        # Tenta deep-link experimental (Discord aceita discord:// em algumas versões)
        url = "discord://"
        os.startfile(url)  # type: ignore[attr-defined]
        time.sleep(1.5)
        import pyautogui
        pyautogui.PAUSE = _delay()
        # Quick-switcher: Ctrl+K, digita dest, Enter
        pyautogui.hotkey("ctrl", "k")
        time.sleep(0.3)
        _type_text(dest)
        time.sleep(0.4)
        pyautogui.press("enter")
        time.sleep(0.5)
        _type_text(content)
        pyautogui.press("enter")
        return PyAutoGUIResult(ok=True, platform="discord", dest=dest)
    except Exception as e:                                          # noqa: BLE001
        return PyAutoGUIResult(ok=False, platform="discord", dest=dest, error=str(e))


def _send_instagram(dest: str, content: str) -> PyAutoGUIResult:
    """Instagram NÃO tem cliente desktop nativo (só Web/Mobile).
    Tenta abrir o app via PWA / browser default."""
    return PyAutoGUIResult(
        ok=False, platform="instagram", dest=dest,
        error="instagram_no_desktop_client",
    )


def _send_gmail(dest: str, content: str) -> PyAutoGUIResult:
    """Gmail não tem cliente desktop. Pode-se usar `mailto:` + Outlook/Thunderbird,
    mas isso depende do default. Não implementado por enquanto."""
    return PyAutoGUIResult(
        ok=False, platform="gmail", dest=dest,
        error="gmail_no_desktop_client (use método 'browser')",
    )


_DISPATCH = {
    "whatsapp": _send_whatsapp,
    "telegram": _send_telegram,
    "discord":  _send_discord,
    "instagram": _send_instagram,
    "gmail":    _send_gmail,
}


def send_via_pyautogui(platform: str, dest: str, content: str) -> PyAutoGUIResult:
    """Entrypoint público."""
    if not _ensure_pyautogui():
        return PyAutoGUIResult(
            ok=False, platform=platform, dest=dest,
            error="pyautogui não instalado",
        )
    fn = _DISPATCH.get(platform)
    if fn is None:
        return PyAutoGUIResult(
            ok=False, platform=platform, dest=dest,
            error=f"plataforma '{platform}' não suportada via pyautogui",
        )
    return fn(dest, content)


__all__ = ["send_via_pyautogui", "PyAutoGUIResult"]
