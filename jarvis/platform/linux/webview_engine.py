"""Motor de webview no Linux: Qt WebEngine via PySide6 (pywebview gui=qt).

Prepara o ambiente (QT_API, PYWEBVIEW_GUI, QT_QPA_PLATFORM) e decide o estado
do sandbox do Chromium/QtWebEngine de forma automática. A sonda de userns só
roda dentro de prepare_env (nunca no import).
"""
from __future__ import annotations

import os
import subprocess

from ..common.base import BackendBase
from ..detect import detect

_FORCED_DISTROS = {"arch", "manjaro", "nixos", "rhel", "pop"}
_VALID_TOGGLE = {"on", "off", "auto"}


# ── Decisão do sandbox (funções injetáveis para teste) ─────────────────────────

def decide_sandbox(environ, *, read_sysctl, run_probe, euid, os_release_id):
    """Decide (ligado, motivo) do sandbox, na ordem exata da SPEC F1-06."""
    # 1. Override manual
    toggle = environ.get("JARVIS_WEBENGINE_SANDBOX")
    if toggle is not None:
        low = toggle.strip().lower()
        if low == "on":
            return True, "config: on"
        if low == "off":
            return False, "config: off"
        if low not in _VALID_TOGGLE:
            import warnings
            warnings.warn(f"JARVIS_WEBENGINE_SANDBOX inválido: {toggle!r} (usando auto)")
        # auto/ausente/inválido → segue

    # 2. Variáveis de ambiente já pedem sandbox desligado
    if environ.get("QTWEBENGINE_DISABLE_SANDBOX") == "1":
        return False, "ambiente"
    if "--no-sandbox" in environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
        return False, "ambiente"

    # 3. root não usa userns sandbox
    if euid == 0:
        return False, "root"

    # 4. distros onde o pywebview força --no-sandbox
    if (os_release_id or "").lower() in _FORCED_DISTROS:
        return False, "forçado pelo pywebview"

    # 5. sysctl de user namespaces desabilitado
    if read_sysctl("kernel.unprivileged_userns_clone") == "0":
        return False, "userns desativado (kernel.unprivileged_userns_clone=0)"
    if read_sysctl("user.max_user_namespaces") == "0":
        return False, "userns desativado (user.max_user_namespaces=0)"

    # 6. sonda unshare (ou apparmor, se não houver unshare)
    try:
        proc = run_probe(["unshare", "--user", "--map-root-user", "true"], timeout=3)
    except FileNotFoundError:
        if read_sysctl("kernel.apparmor_restrict_unprivileged_userns") == "1":
            return False, "apparmor restringe userns"
        return True, "userns disponível (sem unshare para sondar)"
    except Exception as e:  # timeout ou outra falha da sonda
        return False, f"sonda falhou: {type(e).__name__}"

    if proc.returncode == 0:
        return True, "sonda unshare ok"
    primeira_linha = (proc.stderr or "").splitlines()[0] if (proc.stderr or "").strip() else "unshare falhou"
    return False, primeira_linha


# ── helpers reais (usados em prepare_env) ──────────────────────────────────────

def _read_sysctl(name: str):
    path = "/proc/sys/" + name.replace(".", "/")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _run_probe(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _os_release_id():
    try:
        with open("/etc/os-release", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("ID="):
                    return line.partition("=")[2].strip().strip('"').lower()
    except OSError:
        pass
    return None


class QtWebEngine(BackendBase):
    name = "linux.qt_pyside6"

    def __init__(self, ctx=None):
        self.ctx = ctx if ctx is not None else detect()
        self._sandbox_state = "desconhecido"

    def prepare_env(self, environ) -> None:
        environ.setdefault("QT_API", "pyside6")
        environ.setdefault("PYWEBVIEW_GUI", "qt")

        if self.ctx.kind == "linux-wayland":
            environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
        elif self.ctx.kind == "linux-x11":
            environ.setdefault("QT_QPA_PLATFORM", "xcb")
        # headless: não define QT_QPA_PLATFORM

        on, reason = decide_sandbox(
            environ,
            read_sysctl=_read_sysctl,
            run_probe=_run_probe,
            euid=os.geteuid(),
            os_release_id=_os_release_id(),
        )
        if not on:
            environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        self._sandbox_state = "on" if on else f"off ({reason})"

        qpa = environ.get("QT_QPA_PLATFORM", "")
        print(f"[WEBENGINE] backend=qt/pyside6 qpa={qpa} sandbox={self._sandbox_state}")

    def start_kwargs(self) -> dict:
        return {"gui": "qt"}

    def sandbox_state(self) -> str:
        return self._sandbox_state
