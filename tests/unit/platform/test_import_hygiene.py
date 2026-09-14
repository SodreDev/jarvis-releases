"""Higiene de import: importar/usar jarvis.platform não puxa dependências pesadas."""
import os
import subprocess
import sys

PROIBIDOS = ["pynput", "webview", "qtpy", "PySide6", "pyautogui", "pystray", "sounddevice"]

_SNIPPET = (
    "import sys\n"
    "import jarvis.platform as p\n"
    "p.current()\n"
    "p.report()\n"
    "proibidos = %r\n"
    "carregados = [m for m in proibidos if m in sys.modules]\n"
    "print('CARREGADOS:' + ','.join(carregados))\n"
    "sys.exit(1 if carregados else 0)\n"
) % (PROIBIDOS,)


def test_import_nao_carrega_pesados():
    # report() sonda as capacidades (F2: NOTIFIER via D-Bus). Aponta o D-Bus
    # para um socket inexistente: o teste nunca fala com o barramento do host.
    # headless: report() não roda wl-paste/xclip na sessão gráfica de quem testa.
    env = dict(
        os.environ,
        JARVIS_PLATFORM="linux-headless",
        DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent/jarvis-sem-barramento",
        DBUS_SYSTEM_BUS_ADDRESS="unix:path=/nonexistent/jarvis-sem-barramento-sistema",
    )
    proc = subprocess.run(
        [sys.executable, "-c", _SNIPPET],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, (
        f"jarvis.platform carregou módulos pesados no import/uso:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
