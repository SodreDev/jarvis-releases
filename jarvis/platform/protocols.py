"""Contratos (typing.Protocol) das capacidades de plataforma.

Só stdlib/typing aqui — nenhum import pesado. Tipos que exigiriam dependências
externas ficam sob TYPE_CHECKING. NORMATIVOS: Paths, Processes e WebviewEngine
(F1); Hotkeys, Tray, Volume, Clipboard, Notifier, OpenPath, Session e Media
(F2, SPEC-fase2 §4 F2-00). NotificationReader, InputInjector, ScreenCapture e
WindowManager continuam ESBOÇO e serão refinados nas fases 3 e 4.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    List,
    MutableMapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

if TYPE_CHECKING:  # pragma: no cover - só para type checkers
    import threading

    import PIL.Image


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

    # F2 (F2-09 e F2-10c)
    def restart_self(self, *, main_path: str, frozen: bool) -> None:
        """Dispara a nova instância do app; NÃO sai do processo atual."""
        ...

    def shutdown_children(self, timeout: float = 2.0) -> None:
        """Limpeza explícita dos filhos registrados (Windows: no-op)."""
        ...


class WebviewEngine(Protocol):
    """Preparação do engine de webview (WebView2 no Windows, Qt/GTK no Linux)."""

    name: str

    def prepare_env(self, environ: MutableMapping[str, str]) -> None: ...
    def start_kwargs(self) -> dict: ...
    def sandbox_state(self) -> str: ...


# ── Normativos F2 ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HotkeyBinding:
    """Atalho global com id estável (portal e KGlobalAccel guardam por id)."""

    id: str  # "ptt", "screenshot_analise", ...
    description: str  # texto do diálogo do portal / das configurações do KDE
    trigger: str  # formato pynput: "<shift>+g", "<ctrl>+<alt>+j"
    on_press: Callable[[], None]
    on_release: Optional[Callable[[], None]] = None


@dataclass(frozen=True)
class TrayItem:
    """Item do menu do tray (separator=True ignora label e callback)."""

    label: str
    callback: Optional[Callable[[], None]]
    default: bool = False
    separator: bool = False


class Hotkeys(Protocol):
    """Atalhos globais: pynput (win32/x11), portal GlobalShortcuts ou KGlobalAccel."""

    name: str

    def listen_keys(self, on_press: Callable, on_release: Callable) -> bool:
        """Listener passivo tecla a tecla (pynput). Portal/KGlobalAccel: False."""
        ...

    def bind(self, bindings: Sequence[HotkeyBinding]) -> Dict[str, str]:
        """Registra os atalhos; devolve id -> descrição do gatilho efetivo."""
        ...

    def stop(self) -> None: ...


class Tray(Protocol):
    """Ícone de bandeja: pystray (win32) ou QSystemTrayIcon/SNI (linux)."""

    name: str

    def setup(
        self,
        title: str,
        make_image: Callable[[], "PIL.Image.Image"],
        items: Sequence[TrayItem],
    ) -> bool: ...
    def set_visible(self, visible: bool) -> None: ...
    def stop(self) -> None: ...


class Volume(Protocol):
    """Volume de saída e de entrada em porcentagem (0..100)."""

    name: str

    def get_output(self) -> int: ...
    def set_output(self, pct: int) -> None: ...
    def get_input(self) -> int: ...
    def set_input(self, pct: int) -> None: ...
    def toggle_output_mute(self) -> None: ...
    def step_output(self, delta_pct: int) -> None: ...


class Clipboard(Protocol):
    """Área de transferência (texto) e monitor de mudanças."""

    name: str
    can_watch: bool

    def get_text(self) -> Optional[str]: ...
    def set_text(self, text: str) -> bool: ...

    def watch(self, on_change: Callable[[str], None], stop: "threading.Event") -> bool:
        """Bloqueia até `stop`; False = este backend não suporta monitorar."""
        ...


class Notifier(Protocol):
    """Envio de notificações do sistema (só Linux nesta fase, D-F2-5)."""

    name: str

    def notify(
        self, title: str, body: str, *, urgency: str = "normal", timeout_ms: int = -1
    ) -> bool: ...


class OpenPath(Protocol):
    """Abre arquivo, pasta, URL ou esquema (whatsapp://) no app padrão."""

    name: str

    def open(self, target: str) -> bool: ...

    def open_text_file(self, path: str) -> bool:
        """Windows: notepad.exe literal. Linux: o mesmo que open(path)."""
        ...


class Session(Protocol):
    """Estado da sessão do usuário: ociosidade, idioma e fuso."""

    name: str

    def idle_seconds(self) -> Optional[float]:
        """Segundos sem entrada do usuário; None = desconhecido."""
        ...

    def locale(self) -> str: ...         # "pt-BR"
    def timezone_name(self) -> str: ...  # IANA


class Media(Protocol):
    """Controle de mídia: teclas virtuais (win32) ou MPRIS/playerctl (linux)."""

    name: str

    def play_pause(self) -> None: ...
    def stop(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...

    def now_playing(self) -> Optional[dict]:
        """{"title", "artist", "player", "status"} ou None."""
        ...

    def toggle_mute(self) -> None: ...

    def volume_step(self, steps: int) -> None:
        """Windows: tecla virtual. Linux: Volume.step_output(steps * 2)."""
        ...


# ── Esboços (refinados nas fases seguintes) ────────────────────────────────────

class NotificationReader(Protocol):
    """esboço — refinado na fase 4."""

    name: str

    def start(self, callback) -> None: ...
    def stop(self) -> None: ...


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
