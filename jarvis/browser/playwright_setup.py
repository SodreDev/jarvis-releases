"""playwright_setup.py — Auto-instalação do Chromium para o Playwright.

Problema: o Playwright (pypi) não vem com os binários do Chromium — eles
precisam ser baixados uma vez via `playwright install chromium`.
Em desenvolvimento isso é feito manualmente; no bundle PyInstaller (instalador)
o passo é facilmente esquecido após uma nova instalação ou update de payload.

Esta utilidade detecta a ausência do binário e executa o install
automaticamente, funcionando tanto em modo dev (venv) quanto em bundle
frozen.  Pode ser chamada de forma síncrona (startup do main.py) ou
assíncrona (pool.py antes do primeiro launch_persistent_context).
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

# ── Detecção do binário ────────────────────────────────────────────────────

def _playwright_driver_args() -> Optional[List[str]]:
    """Retorna a lista de argumentos para invocar o CLI do Playwright.

    O playwright pypi não distribui um `playwright.cmd` único; o ponto de
    entrada real é `node.exe package/cli.js`.  Funciona igual em venv e em
    bundle PyInstaller (os módulos ficam em _MEIPASS no segundo caso).

    Retorna lista como  [node_exe, cli_js]  ou None se não encontrado.
    """
    try:
        import playwright as _pw_pkg
        pkg_dir = Path(_pw_pkg.__file__).parent          # .../playwright/
        driver_dir = pkg_dir / "driver"

        node_exe = driver_dir / "node.exe"               # Windows
        cli_js   = driver_dir / "package" / "cli.js"

        if node_exe.exists() and cli_js.exists():
            return [str(node_exe), str(cli_js)]

        # Linux/macOS: node sem extensão
        node_bin = driver_dir / "node"
        if node_bin.exists() and cli_js.exists():
            return [str(node_bin), str(cli_js)]

        # Fallback: playwright.cmd/playwright.sh (builds mais antigos)
        for name in ("playwright.cmd", "playwright.sh", "playwright"):
            candidate = driver_dir / name
            if candidate.exists():
                return [str(candidate)]
    except Exception:
        pass

    # Último recurso: shutil.which (venv ativado ou playwright no PATH)
    import shutil
    which = shutil.which("playwright")
    if which:
        return [which]

    return None


def _chromium_exe() -> Optional[Path]:
    """Retorna o executável Chromium esperado pelo Playwright, ou None.

    Usa `playwright.sync_api` apenas para leitura do caminho — NÃO lança
    o browser.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
            return Path(exe) if exe else None
    except Exception:
        return None


def _browsers_dir() -> Optional[Path]:
    """Retorna o diretório raiz de browsers do Playwright (para PLAYWRIGHT_BROWSERS_PATH).

    Calculado a partir do caminho esperado do Chromium:
      .../BROWSERS_DIR/chromium-XXXX/chrome-winXX/chrome.exe  →  BROWSERS_DIR

    Funciona tanto em dev mode (aponta para %LOCALAPPDATA%\\ms-playwright) quanto
    em modo frozen/PyInstaller (aponta para .local-browsers/ dentro de _internal).
    Não requer que o binário exista — usa apenas a string de caminho.
    """
    exe = _chromium_exe()
    if exe is None:
        return None
    try:
        return exe.parent.parent.parent
    except Exception:
        return None


def chromium_missing() -> bool:
    """True se o binário Chromium não existe (precisa instalar)."""
    exe = _chromium_exe()
    return exe is None or not exe.exists()


# ── Instalação ─────────────────────────────────────────────────────────────

def ensure_chromium_sync(
    notify_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """Garante que o Chromium existe (instala se necessário).

    Síncrono — bloqueia até o download concluir (pode demorar 1-3 min).
    Retorna True se OK (já existia ou foi instalado), False se falhou.
    `notify_fn(msg)` é chamado opcionalmente para feedback ao usuário.
    """
    if not chromium_missing():
        return True

    msg = (
        "Chromium não encontrado — baixando para o Playwright "
        "(pode demorar 1-3 min na primeira vez)…"
    )
    log.warning(msg)
    if notify_fn:
        notify_fn(msg)

    args = _playwright_driver_args()
    if args is None:
        log.error(
            "playwright driver não encontrado em nenhum caminho conhecido. "
            "Execute manualmente: playwright install chromium"
        )
        return False

    env = {**os.environ}
    # Garante que playwright instala no mesmo diretório que o runtime espera.
    # Em modo frozen: _internal/playwright/driver/package/.local-browsers
    # Em dev: %LOCALAPPDATA%/ms-playwright (ou ~/.cache/ms-playwright no Linux)
    if "PLAYWRIGHT_BROWSERS_PATH" not in env:
        bd = _browsers_dir()
        if bd:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(bd)
    try:
        result = subprocess.run(
            args + ["install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
        if result.returncode == 0:
            ok_msg = "Chromium instalado com sucesso. Recursos de browser disponíveis."
            log.info(ok_msg)
            if notify_fn:
                notify_fn(ok_msg)
            return True
        else:
            log.error(
                "playwright install chromium falhou (rc=%s):\n%s\n%s",
                result.returncode, result.stdout[-2000:], result.stderr[-2000:],
            )
            return False
    except subprocess.TimeoutExpired:
        log.error("playwright install chromium excedeu timeout de 300s")
        return False
    except Exception as exc:  # noqa: BLE001
        log.error("Erro inesperado ao instalar Chromium: %s", exc, exc_info=exc)
        return False


async def ensure_chromium_async(
    notify_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """Versão assíncrona de ensure_chromium_sync — usa asyncio.subprocess."""
    if not chromium_missing():
        return True

    msg = (
        "Chromium não encontrado — baixando para o Playwright "
        "(pode demorar 1-3 min na primeira vez)…"
    )
    log.warning(msg)
    if notify_fn:
        notify_fn(msg)

    args = _playwright_driver_args()
    if args is None:
        log.error(
            "playwright driver não encontrado. "
            "Execute manualmente: playwright install chromium"
        )
        return False

    env = {**os.environ}
    if "PLAYWRIGHT_BROWSERS_PATH" not in env:
        bd = _browsers_dir()
        if bd:
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(bd)
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        except asyncio.TimeoutError:
            proc.kill()
            log.error("playwright install chromium excedeu timeout de 300s")
            return False

        if proc.returncode == 0:
            ok_msg = "Chromium instalado com sucesso. Recursos de browser disponíveis."
            log.info(ok_msg)
            if notify_fn:
                notify_fn(ok_msg)
            return True
        else:
            log.error(
                "playwright install chromium falhou (rc=%s):\n%s\n%s",
                proc.returncode,
                stdout.decode(errors="replace")[-2000:],
                stderr.decode(errors="replace")[-2000:],
            )
            return False
    except Exception as exc:  # noqa: BLE001
        log.error("Erro inesperado ao instalar Chromium (async): %s", exc, exc_info=exc)
        return False


__all__ = [
    "chromium_missing",
    "ensure_chromium_sync",
    "ensure_chromium_async",
]
