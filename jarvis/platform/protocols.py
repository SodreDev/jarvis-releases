"""Contratos (typing.Protocol) das capacidades de plataforma.

Só stdlib/typing aqui — nenhum import pesado. Tipos que exigiriam dependências
externas ficam sob TYPE_CHECKING. Os protocolos NORMATIVOS da F1 (Paths,
Processes, WebviewEngine) estão completos; os demais são ESBOÇO e serão
refinados nas fases seguintes.
"""
from __future__ import annotations

from pathlib import Path
from typing import (
    TYPE_CHECKING,
    List,
    MutableMapping,
    Protocol,
    runtime_checkable,
)

if TYPE_CHECKING:  # pragma: no cover - só para type checkers
    import subprocess


@runtime_checkable
class Backend(Protocol):
    """Todo backend expõe um nome estável."""

    name: str


# ── Normativos F1 ──────────────────────────────────────────────────────────────

class Paths(Protocol):
    """Diretórios de dados do app (XDG no Linux, %APPDATA%/afins no Windows)."""

    name: str

    def user_config_dir(self) -> Path: ...
    def user_data_dir(self) -> Path: ...
    def credentials_dir(self) -> Path: ...
    def logs_dir(self) -> Path: ...
    def cache_dir(self) -> Path: ...
    def webview_storage_dir(self) -> str: ...


class Processes(Protocol):
    """Criação/limpeza de processos filhos (WebView2/Chromium, ffplay, etc.)."""

    name: str

    def hidden_console_flags(self) -> int: ...
    def install_child_cleanup(self) -> None: ...
    def register_child(self, proc, *, tree: bool = False) -> None: ...
    def alive_children(self) -> List[int]: ...
    def new_session_kwargs(self) -> dict: ...


class WebviewEngine(Protocol):
    """Preparação do engine de webview (WebView2 no Windows, Qt/GTK no Linux)."""

    name: str

    def prepare_env(self, environ: MutableMapping[str, str]) -> None: ...
    def start_kwargs(self) -> dict: ...
    def sandbox_state(self) -> str: ...


# ── Esboços (refinados nas fases seguintes) ────────────────────────────────────

class OpenPath(Protocol):
    """esboço — refinado na fase 2."""

    name: str

    def open_path(self, path: str) -> None: ...
    def open_url(self, url: str) -> None: ...


class Clipboard(Protocol):
    """esboço — refinado na fase 2."""

    name: str

    def get_text(self) -> str: ...
    def set_text(self, text: str) -> None: ...


class Notifier(Protocol):
    """esboço — refinado na fase 2."""

    name: str

    def notify(self, title: str, message: str) -> None: ...


class NotificationReader(Protocol):
    """esboço — refinado na fase 4."""

    name: str

    def start(self, callback) -> None: ...
    def stop(self) -> None: ...


class Volume(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def get_volume(self) -> float: ...
    def set_volume(self, level: float) -> None: ...
    def mute(self) -> None: ...


class Hotkeys(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def register(self, combo: str, callback) -> None: ...
    def unregister_all(self) -> None: ...


class InputInjector(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def type_text(self, text: str) -> None: ...
    def press(self, combo: str) -> None: ...


class ScreenCapture(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def grab(self, region=None): ...


class WindowManager(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def active_window(self): ...
    def list_windows(self) -> list: ...


class Session(Protocol):
    """esboço — refinado na fase 4."""

    name: str

    def lock(self) -> None: ...
    def idle_seconds(self) -> float: ...


class Tray(Protocol):
    """esboço — refinado na fase 4."""

    name: str

    def show(self) -> None: ...
    def hide(self) -> None: ...


class Media(Protocol):
    """esboço — refinado na fase 3."""

    name: str

    def play_pause(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...
