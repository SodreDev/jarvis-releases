"""O log da abertura e a tela de erro de quando a janela não abre mesmo (bug do dono, 2026-11-14:
«o Jarvis não abre», sem nenhum rastro para ler).

Três peças, todas sem segredo (o texto passa por `redigir_do_ambiente` antes de sair daqui):

- `ligar(caminho)`: só a janela de verdade (`principal.main`) liga o arquivo, em
  `$XDG_STATE_HOME/jarvis/abertura.log`. Sem ligar (os testes), as frases vão só ao `stderr`:
  nenhum teste escreve na pasta do dono.
- `registrar_na_abertura(frase, erro)`: uma linha com hora, e o traceback quando houver. É o que
  a parte opcional que falhou na abertura deixa (config recusada, monitor das redes, portal).
- `mostrar_erro_fatal(...)`: quando nem a janela principal sobe, uma janela mínima diz o porquê e
  onde está o log, em vez de o processo sumir calado.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
import traceback
from collections.abc import Mapping
from pathlib import Path
from types import TracebackType
from typing import Final

from jarvis.ambiente import ambiente_ou_os
from jarvis.voz.chaves import redigir_do_ambiente

NOME_DO_LOG: Final = "abertura.log"
TETO_DO_LOG: Final = 256 * 1024
"""Passou disso, o log começa de novo (a cópia anterior fica em `abertura.log.1`)."""

_destino: Path | None = None
_trava = threading.Lock()


def caminho_do_log(ambiente: Mapping[str, str] | None = None) -> Path:
    fonte = ambiente_ou_os(ambiente)
    base = fonte.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "jarvis" / NOME_DO_LOG


def ligar(caminho: Path) -> Path | None:
    """Passa a gravar no arquivo (e roda o anterior se ficou grande). `None` = não deu."""
    global _destino
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        if caminho.exists() and caminho.stat().st_size > TETO_DO_LOG:
            caminho.replace(caminho.with_name(caminho.name + ".1"))
    except OSError:
        return None
    _destino = caminho
    return caminho


def desligar() -> None:
    global _destino
    _destino = None


def registrar_na_abertura(frase: str, erro: BaseException | None = None) -> None:
    """Uma linha no log da abertura. Nunca levanta: o log não pode ser o que derruba."""
    texto = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {frase}"
    if erro is not None:
        texto += "\n" + "".join(traceback.format_exception(erro)).rstrip()
    texto = redigir_do_ambiente(texto)
    with contextlib.suppress(OSError, ValueError):  # stderr fechado (aberto pelo menu)
        print(f"jarvis: {texto}", file=sys.stderr)
    destino = _destino
    if destino is None:
        return
    try:
        with _trava, destino.open("a", encoding="utf-8") as arquivo:
            arquivo.write(texto + "\n")
    except OSError:
        return


def instalar_ganchos() -> None:
    """Exceção solta na thread principal ou numa thread de trabalho vai ao log, com o traceback.
    O comportamento de antes continua (o gancho original roda depois)."""
    original = sys.excepthook
    original_da_thread = threading.excepthook

    def gancho(
        tipo: type[BaseException], erro: BaseException, rastro: TracebackType | None
    ) -> None:
        registrar_na_abertura("exceção não tratada", erro.with_traceback(rastro))
        original(tipo, erro, rastro)

    def gancho_da_thread(argumentos: threading.ExceptHookArgs) -> None:
        if argumentos.exc_value is not None:
            nome = argumentos.thread.name if argumentos.thread is not None else "?"
            registrar_na_abertura(f"exceção na thread {nome}", argumentos.exc_value)
        original_da_thread(argumentos)

    sys.excepthook = gancho
    threading.excepthook = gancho_da_thread


def frase_do_erro_fatal(erro: BaseException | str, log: Path | None) -> str:
    motivo = erro if isinstance(erro, str) else f"{type(erro).__name__}: {erro}"
    onde = f"\n\nO detalhe está em {log}." if log is not None else ""
    return redigir_do_ambiente(
        f"O Jarvis não conseguiu abrir a janela.\n\n{motivo}{onde}\n\n"
        "Rode `jarvis --diagnostico` no terminal e mande a saída (ela não tem segredo)."
    )


def mostrar_erro_fatal(frase: str) -> None:
    """Uma janela mínima com a frase, quando a principal não sobe. Sem Qt utilizável, só o
    `stderr` (já escrito por quem chamou)."""
    try:
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQml import QQmlApplicationEngine
    except ImportError:
        return
    try:
        aplicativo = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        motor = QQmlApplicationEngine()
        motor.rootContext().setContextProperty("fraseDoErro", frase)
        motor.loadData(QByteArray(_QML_DO_ERRO.encode("utf-8")))
        if not motor.rootObjects():
            return
        aplicativo.exec()
    except Exception as erro:  # a tela de erro não pode virar outro erro
        registrar_na_abertura("a tela de erro também não abriu", erro)


_QML_DO_ERRO: Final = """
import QtQuick
import QtQuick.Window
Window {
    width: 560; height: 300; visible: true; title: "Jarvis"
    color: "#0b1220"
    Text {
        anchors.fill: parent; anchors.margins: 24
        text: fraseDoErro; color: "#e6edf7"; wrapMode: Text.Wrap
        font.pixelSize: 15; textFormat: Text.PlainText
    }
    MouseArea { anchors.fill: parent; onClicked: Qt.quit() }
}
"""


__all__ = [
    "NOME_DO_LOG",
    "caminho_do_log",
    "desligar",
    "frase_do_erro_fatal",
    "instalar_ganchos",
    "ligar",
    "mostrar_erro_fatal",
    "registrar_na_abertura",
]
