"""Tray no Linux (F2-02): ``QSystemTrayIcon`` do PySide6 (no Plasma vira StatusNotifierItem).

- Sonda: kind ``linux-x11`` (XEmbed do próprio Qt, sem consultar o D-Bus) ou
  ``org.kde.StatusNotifierWatcher`` com dono no D-Bus de sessão. No Wayland sem
  watcher o tray fica indisponível (feature ``tray`` desligada) e o X fecha o app.
- Tudo que toca Qt roda na thread da GUI via ``run_in_gui_thread`` (contexto = o
  ``QApplication`` do pywebview). Chamado da própria GUI (clique no menu), roda direto.
- ``setup``: ícone de ``make_image()`` (PIL → PNG em memória → ``QPixmap``), ``QMenu`` na
  ordem dos itens (separador e ação padrão), clique no ícone dispara a ação padrão;
  começa oculto. ``set_visible`` e ``stop`` também passam pela GUI.
PySide6 só é importado dentro das funções.
"""
from __future__ import annotations

import io
from typing import Callable, Optional, Sequence

from ..common.base import BackendBase, Probe
from . import dbus as _dbus
from .qt_gui import run_in_gui_thread

WATCHER = "org.kde.StatusNotifierWatcher"
GUI_TIMEOUT = 5.0


def _png(imagem) -> bytes:
    buffer = io.BytesIO()
    imagem.save(buffer, "PNG")
    return buffer.getvalue()


def _chamar(callback: Callable) -> None:
    try:
        callback()
    except Exception as e:
        print(f"[TRAY] ação do menu falhou: {e}")


class QtSystemTray(BackendBase):
    name = "qt_sni"

    def __init__(self, ctx=None):
        self.ctx = ctx
        self._icone = None
        self._menu = None
        self._acao_padrao: Optional[Callable] = None

    @classmethod
    def probe(cls, ctx) -> Probe:
        if getattr(ctx, "kind", "") == "linux-x11":
            return Probe(True)
        if _dbus.name_has_owner(WATCHER):
            return Probe(True)
        return Probe(False, f"sem {WATCHER} no D-Bus de sessão (tray indisponível)")

    def setup(self, title: str, make_image: Callable, items: Sequence) -> bool:
        try:
            png = _png(make_image())
            return bool(run_in_gui_thread(None, lambda: self._criar(title, png, items), timeout=GUI_TIMEOUT))
        except Exception as e:
            print(f"[TRAY] não foi possível criar o ícone da bandeja: {e}")
            return False

    def _criar(self, title: str, png: bytes, items: Sequence) -> bool:
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        pixmap = QPixmap()
        pixmap.loadFromData(png, "PNG")
        icone = QSystemTrayIcon(QIcon(pixmap))
        icone.setToolTip(title)

        menu = QMenu()
        for item in items:
            if item.separator:
                menu.addSeparator()
                continue
            acao = menu.addAction(item.label)
            if item.callback is not None:
                acao.triggered.connect(lambda _marcado=False, cb=item.callback: _chamar(cb))
            if item.default:
                menu.setDefaultAction(acao)
                self._acao_padrao = item.callback
        icone.setContextMenu(menu)

        gatilhos = (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick)

        def _ativado(motivo):
            if motivo in gatilhos and self._acao_padrao is not None:
                _chamar(self._acao_padrao)

        icone.activated.connect(_ativado)
        icone.setVisible(False)
        self._icone, self._menu = icone, menu
        return True

    def set_visible(self, visible: bool) -> None:
        if self._icone is not None:
            run_in_gui_thread(None, lambda: self._icone.setVisible(bool(visible)), timeout=GUI_TIMEOUT)

    def stop(self) -> None:
        icone, self._icone = self._icone, None
        if icone is not None:
            run_in_gui_thread(None, icone.hide, timeout=GUI_TIMEOUT)
