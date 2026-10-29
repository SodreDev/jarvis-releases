"""Sonda: o texto rico do Qt busca na rede — e o conteúdo limpo da tela não (ADR-0055).

Uso (offscreen, sem rede de fora: o servidor é local, em 127.0.0.1):

    uv run --frozen python -m tools.sonda_rede_da_tela [--rodadas N]

Cada caso roda num processo só dele, N vezes:

- **cru**: um `Text` do QML em `RichText` com `<img src>`, `style="background-image:url(…)"` e um
  `<style>` com `url()`, todos apontando para o servidor local — é o controle: o Qt busca as três;
- **limpo**: o mesmo HTML depois de `jarvis.tela.sanitizar` (como a porta da tela o manda à janela)
  — nenhuma requisição.

Um processo à parte por rodada porque a carga de imagem remota do QML derruba o processo de vez em
quando (PySide6 6.9.3, 2026-10-29) — o que a sonda conta e mostra, em vez de esconder. É o controle
que o teste da janela (`tests/unit/gui/test_conteudo_na_tela.py`) não pode carregar.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Final

RAIZ: Final = Path(__file__).resolve().parent.parent
ESPERA_S: Final = 1.5


def html_com_recursos(base: str) -> str:
    return (
        f"<html><head><style>p {{ background-image: url({base}/folha.png) }}</style></head><body>"
        f'<h1>Lista</h1><p style="background-image: url({base}/inline.png)">oi</p>'
        f'<img src="{base}/imagem.png" width="10" height="10"></body></html>'
    )


def _caso(caso: str, base: str, pasta: Path) -> None:
    """Uma rodada, neste processo: desenha o HTML e espera o Qt buscar o que for buscar."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    sys.path.insert(0, str(RAIZ / "src"))
    from PySide6.QtCore import QEventLoop, QObject, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView

    from jarvis.tela import sanitizar

    app = QGuiApplication([])
    arquivo = pasta / "sonda.qml"
    arquivo.write_text(
        "import QtQuick\n"
        'Rectangle { width: 400; height: 300; color: "black"\n'
        '  Text { objectName: "sonda"; anchors.fill: parent; textFormat: Text.RichText } }\n',
        encoding="utf-8",
    )
    janela = QQuickView()
    janela.setSource(QUrl.fromLocalFile(str(arquivo)))
    janela.show()
    raiz = janela.rootObject()
    assert raiz is not None
    sonda = raiz.findChild(QObject, "sonda")
    assert sonda is not None
    html = html_com_recursos(base)
    sonda.setProperty("text", html if caso == "cru" else sanitizar(html, grade=True).documento)
    fim = time.monotonic() + ESPERA_S
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)


def _servidor() -> tuple[socketserver.TCPServer, list[str]]:
    pedidos: list[str] = []

    class Contador(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            pedidos.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    servidor = socketserver.TCPServer(("127.0.0.1", 0), Contador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, pedidos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rodadas", type=int, default=5)
    parser.add_argument("--caso", choices=("cru", "limpo"), help=argparse.SUPPRESS)
    parser.add_argument("--base", help=argparse.SUPPRESS)
    parser.add_argument("--pasta", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.caso:  # a rodada, no processo filho
        _caso(args.caso, args.base, args.pasta)
        return 0

    import tempfile

    resultado: dict[str, dict[str, list[int]]] = {}
    with tempfile.TemporaryDirectory(prefix="sonda-rede-") as pasta:
        for caso in ("cru", "limpo"):
            pedidos_por_rodada: list[int] = []
            caidas: list[int] = []
            for rodada in range(args.rodadas):
                servidor, pedidos = _servidor()
                base = f"http://127.0.0.1:{servidor.server_address[1]}"
                filho = subprocess.run(
                    [sys.executable, "-m", "tools.sonda_rede_da_tela", "--caso", caso,
                     "--base", base, "--pasta", pasta],
                    cwd=RAIZ, capture_output=True, timeout=60, check=False,
                )  # fmt: skip
                servidor.shutdown()
                servidor.server_close()
                pedidos_por_rodada.append(len(pedidos))
                if filho.returncode != 0:
                    caidas.append(rodada)
            resultado[caso] = {
                "pedidos_por_rodada": pedidos_por_rodada,
                "rodadas_que_cairam": caidas,
            }
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
