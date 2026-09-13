"""Higiene de import: importar/usar jarvis.platform não puxa dependências pesadas."""
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
    proc = subprocess.run(
        [sys.executable, "-c", _SNIPPET],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"jarvis.platform carregou módulos pesados no import/uso:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
