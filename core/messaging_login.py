"""Mensageria — gerenciamento de login por (plataforma × perfil).

Sprint 3 / Fase 1 do roadmap "Credenciais & Login via UI".

Funciona com os 10 backends do Sprint 2 (`jarvis/messaging/backends/`):
    plataformas: whatsapp, instagram, discord, telegram, gmail
    perfis: jarvis, user

Funções públicas:
    - list_platforms() -> lista das 10 combinações (platform, profile).
    - get_status(platform, profile) -> dict {status, udd_exists, cookies_exists,
        last_login_at, last_check_at, in_progress, message}.
    - list_status() -> dict {platform: {profile: {...}}} para a UI.
    - start_login(platform, profile, timeout_s=180) -> dispara fluxo em thread.
    - logout(platform, profile) -> mata sessão + remove UDD.

Estados possíveis (status):
    "never_logged"   — UDD não existe ainda.
    "needs_login"    — UDD existe mas Cookies ausente.
    "connected"      — Cookies presente (sessão potencialmente válida).
    "logging_in"     — fluxo de login em andamento.
    "login_failed"   — última tentativa falhou (timeout ou erro).
    "expired"        — última verificação online detectou sessão expirada.

Eventos publicados no event_bus:
    "messaging.login.start"   {platform, profile}
    "messaging.login.success" {platform, profile}
    "messaging.login.failed"  {platform, profile, error}
    "messaging.logout"        {platform, profile}
"""
from __future__ import annotations

import logging
import shutil
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

# ── Catálogo fixo (espelha Sprint 2) ──────────────────────────────────────
PLATFORMS: tuple[str, ...] = ("whatsapp", "instagram", "discord", "telegram", "gmail")
PROFILES: tuple[str, ...] = ("jarvis", "user")

# Mapa (platform, profile) -> backend class
_BACKEND_MAP: dict[tuple[str, str], Any] = {}


def _load_backends() -> dict[tuple[str, str], Any]:
    """Carrega lazy as classes de backend (1x por processo)."""
    global _BACKEND_MAP
    if _BACKEND_MAP:
        return _BACKEND_MAP
    try:
        from jarvis.messaging.backends.whatsapp_web import (
            WhatsAppWebJarvis, WhatsAppWebUser,
        )
        from jarvis.messaging.backends.instagram_web import (
            InstagramJarvis, InstagramUser,
        )
        from jarvis.messaging.backends.discord_web import (
            DiscordJarvis, DiscordUser,
        )
        from jarvis.messaging.backends.telegram_web import (
            TelegramJarvis, TelegramUser,
        )
        from jarvis.messaging.backends.gmail_web import (
            GmailJarvis, GmailUser,
        )
        _BACKEND_MAP = {
            ("whatsapp",  "jarvis"): WhatsAppWebJarvis,
            ("whatsapp",  "user"):   WhatsAppWebUser,
            ("instagram", "jarvis"): InstagramJarvis,
            ("instagram", "user"):   InstagramUser,
            ("discord",   "jarvis"): DiscordJarvis,
            ("discord",   "user"):   DiscordUser,
            ("telegram",  "jarvis"): TelegramJarvis,
            ("telegram",  "user"):   TelegramUser,
            ("gmail",     "jarvis"): GmailJarvis,
            ("gmail",     "user"):   GmailUser,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("messaging_login: não consegui carregar todos os backends: %s", e)
    return _BACKEND_MAP


# ── Estado em memória (thread-safe) ───────────────────────────────────────
_state_lock = threading.RLock()
_state: dict[tuple[str, str], dict[str, Any]] = {}


def _get_or_init(platform: str, profile: str) -> dict[str, Any]:
    key = (platform, profile)
    with _state_lock:
        st = _state.get(key)
        if st is None:
            st = {
                "platform": platform,
                "profile": profile,
                "status": "unknown",
                "udd_exists": False,
                "cookies_exists": False,
                "last_login_at": None,
                "last_check_at": None,
                "in_progress": False,
                "message": "",
            }
            _state[key] = st
        return st


def list_platforms() -> list[tuple[str, str]]:
    return [(p, prof) for p in PLATFORMS for prof in PROFILES]


def _check_disk(platform: str, profile: str) -> tuple[bool, bool]:
    """Retorna (udd_exists, cookies_exists) lendo o disco.

    Chromium 96+ armazena cookies em `<udd>/Default/Network/Cookies`.
    Versões antigas usavam `<udd>/Default/Cookies` ou `<udd>/Cookies`.
    Verificamos todos os caminhos conhecidos para compatibilidade.
    """
    try:
        from jarvis.browser.profiles import profile_dir
        d = profile_dir(profile, platform)  # type: ignore[arg-type]
    except Exception:
        return (False, False)
    udd_exists = d.exists()
    if not udd_exists:
        return (False, False)
    candidates = [
        d / "Default" / "Network" / "Cookies",  # Chromium 96+
        d / "Default" / "Cookies",              # Chromium <96
        d / "Cookies",                          # Fallback raiz
    ]
    cookies_exists = any(p.exists() for p in candidates)
    return (udd_exists, cookies_exists)


def _refresh_status(platform: str, profile: str) -> dict[str, Any]:
    """Re-lê disco e atualiza status sem chamar Chromium."""
    st = _get_or_init(platform, profile)
    udd, cookies = _check_disk(platform, profile)
    with _state_lock:
        st["udd_exists"] = udd
        st["cookies_exists"] = cookies
        st["last_check_at"] = time.time()
        # Não sobrescreve status se estiver em login_in_progress
        if st["status"] == "logging_in":
            return dict(st)
        if cookies:
            # Mantém "expired" se foi marcado assim; senão volta a "connected"
            if st["status"] != "expired":
                st["status"] = "connected"
        elif udd:
            st["status"] = "needs_login"
        else:
            st["status"] = "never_logged"
        return dict(st)


def get_status(platform: str, profile: str) -> dict[str, Any]:
    """Status atual (snapshot)."""
    return _refresh_status(platform, profile)


def list_status() -> dict[str, dict[str, dict[str, Any]]]:
    """Status de todas as 10 combinações, formato `{platform: {profile: {...}}}`."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for p in PLATFORMS:
        out[p] = {}
        for prof in PROFILES:
            out[p][prof] = _refresh_status(p, prof)
    return out


# ── Login (background thread + Chromium visível) ─────────────────────────
def _login_worker(platform: str, profile: str, timeout_s: int) -> None:
    """Thread que dispara login: abre contexto, espera SEL_LOGGED_IN, registra."""
    from core.event_bus import publish as ev_publish
    backends = _load_backends()
    BackendCls = backends.get((platform, profile))
    if BackendCls is None:
        st = _get_or_init(platform, profile)
        with _state_lock:
            st["status"] = "login_failed"
            st["in_progress"] = False
            st["message"] = f"backend desconhecido para ({platform},{profile})"
        ev_publish("messaging.login.failed",
                   {"platform": platform, "profile": profile,
                    "error": "backend_not_found"})
        return

    ev_publish("messaging.login.start",
               {"platform": platform, "profile": profile})

    try:
        from jarvis.browser import get_pool
        from jarvis.browser.pool import run_sync as _run_sync
        pool = get_pool()

        async def _do_login():
            # Garante 1ª-vez visível mesmo se cookies já existem (re-login forçado).
            # Para isso, se UDD existe e queremos forçar visível, removemos Cookies
            # antes — mas isso é destrutivo. Em vez disso, contamos com o flag
            # "BROWSER_FIRST_LOGIN_VISIBLE" + UDD novo: se o usuário já tinha
            # logado, "Conectar" abre o contexto silenciosamente e revalida.
            ctx = await pool.get_context(platform, profile=profile)
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            backend = BackendCls()
            return await backend._ensure_logged_in(page)

        # Aplica timeout customizado sobre LOGIN_TIMEOUT_S do backend
        BackendCls.LOGIN_TIMEOUT_S = max(60, int(timeout_s))
        ok = _run_sync(_do_login())
    except Exception as e:  # noqa: BLE001
        log.exception("messaging_login worker falhou: %s", e)
        st = _get_or_init(platform, profile)
        with _state_lock:
            st["status"] = "login_failed"
            st["in_progress"] = False
            st["message"] = f"{type(e).__name__}: {e}"
        ev_publish("messaging.login.failed",
                   {"platform": platform, "profile": profile, "error": str(e)})
        return

    st = _get_or_init(platform, profile)
    with _state_lock:
        st["in_progress"] = False
        st["last_check_at"] = time.time()
        if ok:
            st["status"] = "connected"
            st["last_login_at"] = time.time()
            st["message"] = "login bem-sucedido"
            _refresh_status(platform, profile)  # atualiza cookies_exists
        else:
            st["status"] = "login_failed"
            st["message"] = "tempo esgotado ou falha de autenticação"
    if ok:
        ev_publish("messaging.login.success",
                   {"platform": platform, "profile": profile})
    else:
        ev_publish("messaging.login.failed",
                   {"platform": platform, "profile": profile,
                    "error": "timeout_or_auth_fail"})


def start_login(platform: str, profile: str, timeout_s: int = 180) -> dict[str, Any]:
    """Dispara fluxo de login em thread daemon. Retorna {ok, message, status}.

    Idempotente: se já há login em andamento, retorna ok=False com motivo.
    """
    if platform not in PLATFORMS:
        return {"ok": False, "message": f"plataforma inválida: {platform}"}
    if profile not in PROFILES:
        return {"ok": False, "message": f"perfil inválido: {profile}"}

    st = _get_or_init(platform, profile)
    with _state_lock:
        if st["in_progress"]:
            return {"ok": False, "message": "já existe login em andamento",
                    "status": dict(st)}
        st["in_progress"] = True
        st["status"] = "logging_in"
        st["message"] = "abrindo navegador…"

    t = threading.Thread(
        target=_login_worker,
        args=(platform, profile, timeout_s),
        name=f"jarvis-login-{platform}-{profile}",
        daemon=True,
    )
    t.start()
    return {"ok": True, "message": "login iniciado em background",
            "status": dict(st)}


# ── Logout (mata sessão + apaga UDD) ─────────────────────────────────────
def logout(platform: str, profile: str, *, delete_udd: bool = True) -> dict[str, Any]:
    """Encerra contexto (se aberto) e remove UDD do disco.

    Atenção: destrutivo — apaga cookies, localStorage, IndexedDB do
    `data/browser_profiles/<profile>/<platform>/`.
    """
    from core.event_bus import publish as ev_publish
    if platform not in PLATFORMS or profile not in PROFILES:
        return {"ok": False, "message": "platform/profile inválidos"}

    try:
        from jarvis.browser import get_pool
        from jarvis.browser.pool import run_sync as _run_sync
        pool = get_pool()
        try:
            _run_sync(pool.close_context(platform, profile=profile))  # type: ignore[arg-type]
        except Exception as e:  # noqa: BLE001
            log.debug("logout: close_context ignorado (%s)", e)
    except Exception:
        pass

    removed = False
    if delete_udd:
        try:
            from jarvis.browser.profiles import profile_dir
            d = profile_dir(profile, platform)  # type: ignore[arg-type]
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                removed = True
        except Exception as e:  # noqa: BLE001
            log.warning("logout: falha removendo UDD: %s", e)
            return {"ok": False, "message": f"erro ao remover UDD: {e}"}

    st = _get_or_init(platform, profile)
    with _state_lock:
        st["status"] = "never_logged" if removed else "needs_login"
        st["udd_exists"] = False if removed else st["udd_exists"]
        st["cookies_exists"] = False
        st["last_login_at"] = None
        st["in_progress"] = False
        st["message"] = "logout efetuado"

    ev_publish("messaging.logout",
               {"platform": platform, "profile": profile, "removed": removed})
    return {"ok": True, "removed": removed, "status": dict(st)}


__all__ = [
    "PLATFORMS", "PROFILES",
    "list_platforms", "list_status", "get_status",
    "start_login", "logout",
]
