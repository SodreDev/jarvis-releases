# ADR-001 — Camada de plataforma `jarvis/platform/`

| | |
|---|---|
| **Status** | Proposto pelo arquiteto em 2026-09-13. Vale a partir da Fase 1, depois da revisão. |
| **Base** | branch `linux-port`, commit `1c32e38` (baseline 2.7.0). Os números de linha citados são desse commit. |
| **Relacionados** | [SPEC-fase1-boot-linux.md](SPEC-fase1-boot-linux.md) · [FILA-fase1-executor.md](FILA-fase1-executor.md) · [MAPA_EXECUCAO.md](MAPA_EXECUCAO.md) · [../../REVISAO_2026-09.md](../../REVISAO_2026-09.md) |

---

## 1. Contexto

### 1.1 Decisões do dono (fixas, não se rediscutem aqui)
- **Dual-target** Windows + Linux, com a camada `jarvis/platform/`. O Windows continua funcionando e o caminho atual vira o backend `windows`.
- Alvo gráfico **Wayland-nativo**, com X11 também suportado.
- pywebview com **backend Qt via PySide6**. Sandbox do WebEngine **ligado**, com **fallback automático** para `--no-sandbox`.
- `ydotool` é opcional e fica fora do v1. glibc baseline **2.28**. Chromium do Playwright baixado **sob demanda**. ffmpeg estático embutido. AppImage via PyInstaller + appimagetool. Distros-alvo: dnf, pacman e apt.
- **v1** = app + voz + LLM + mensageria + sistema básico. Gestos, overlay e leitura de notificações ficam para depois.
- A corrida do `reload_ui` e o `faulthandler` que enche o `crash_native.log` são corrigidos **no v1**.

### 1.2 Fatos do código que moldam a decisão
- `main.py` tem 13.535 linhas. Rodei um **scanner AST** do import-time a partir do `main.py`: só 11 módulos locais executam no import, e os únicos imports de topo que dependem de plataforma estão no próprio `main.py`: `webview` (:26), `sounddevice` (:132, precisa de PortAudio no Linux) e `pynput` (:137-138). O `winreg` (:114) já está protegido por `if sys.platform == "win32"`.
- O resto do contato com o Windows (cerca de 20 arquivos, ver MAPA §4) já é **lazy**: imports dentro de funções, `ctypes.windll` dentro de `try`.
- `jarvis/config/paths.py:13-18` já faz `if os.name == "nt"`. É o embrião da camada, mas mistura config, dados e logs em `XDG_CONFIG_HOME` no Linux.
- No **Linux as capacidades variam pela sessão, não só pelo SO**: hotkeys globais, injeção de input, captura e janelas funcionam de um jeito no X11 e de outro (ou nem funcionam) no Wayland. Volume, notificações, MPRIS e XDG são iguais nas duas sessões.
- Até a Fase 0 não havia testes. O qa montou `pytest.ini` (markers `windows_only`, `linux_only`, `wayland`, `x11`, `needs_display` e `slow`) e `tests/conftest.py` com as fixtures `fake_platform` e `isolated_home`.

## 2. Requisitos da solução

| # | Requisito |
|---|---|
| R1 | **Zero regressão no Windows.** O backend `windows` reproduz o comportamento atual e isso é provado por teste. |
| R2 | **Import barato e seguro.** Importar a camada não pode importar `pynput`, `pyautogui`, `webview`, `qtpy`, `PySide6`, `pystray` nem `sounddevice`. |
| R3 | **Escolha por sessão** (`win32`, `linux-wayland`, `linux-x11` e `linux-headless`), com **fallback por capacidade**. Exemplo: no Wayland, se o portal de atalhos falhar, tenta o KGlobalAccel sem afetar o volume. |
| R4 | **Testável sem o SO-alvo.** A detecção e os backends aceitam contexto e ambiente injetados, e o Windows é testado no Linux com fakes. |
| R5 | **Migração incremental** do god object: um call site por vez, sem big-bang. |
| R6 | **Diagnóstico.** Dá para saber qual backend está ativo em cada capacidade e por que os outros foram descartados. |
| R7 | **Compatível com PyInstaller** (.exe hoje, AppImage na Fase 5). |
| R8 | Não criar outro god object. |

## 3. Opções avaliadas

### A. Classe `Platform` única (ABC) com subclasses `WindowsPlatform`, `LinuxWaylandPlatform` e `LinuxX11Platform`
- **Prós:** fácil de descobrir (um objeto, autocomplete) e poucos arquivos no começo.
- **Contras:** vira outro god object, com uns 15 grupos de métodos numa classe. X11 e Wayland compartilham volume/notificações e divergem em hotkeys/captura, o que força mixins ou herança múltipla. Fallback **por capacidade** fica desajeitado: se o portal falha, a plataforma inteira troca? Carga lazy exige disciplina manual em cada método. Os testes precisam montar a plataforma inteira.

### B. `typing.Protocol` por capacidade + registro com carga lazy e cadeia de fallback ✅
- **Prós:** isolamento (um contrato e um backend por arquivo). O import acontece só quando a capacidade é pedida, então o `pynput` só é carregado se alguém pedir hotkeys. O fallback é por capacidade. O diagnóstico sai natural (o registro sabe o que tentou). O teste é por capacidade, e o encaixe com a migração modular do `jarvis/` é direto.
- **Contras:** mais arquivos, uma indireção, e caminhos por string são invisíveis ao PyInstaller e ao IDE. Mitigações: fachada tipada (§8.4) e teste estático do hiddenimports (W6).

### C. Funções soltas com `if sys.platform` espalhados (status quo + shims, estilo `paths.py`)
- **Prós:** diff mínimo e zero infraestrutura.
- **Contras:** os condicionais se multiplicam por call site e não há distinção X11/Wayland sem mais `if`. Não tem fallback nem diagnóstico, e a condicional de plataforma continua dentro da regra de negócio, o que atrapalha o teste. Não escala para a Fase 3.

### D. Plugins via `importlib.metadata.entry_points`
- **Prós:** extensível por pacote externo.
- **Contras:** o Jarvis não é pacote instalado (roda de `python main.py` e do truque live-source do `launcher.py`). Entry points dependem de metadados de distribuição, o que é hostil ao PyInstaller e ao AppImage. É exagero para backends internos.

| Critério | A | **B** | C | D |
|---|:-:|:-:|:-:|:-:|
| R1 Windows provado igual | médio | **alto** | médio | alto |
| R2 import seguro | baixo | **alto** | médio | alto |
| R3 fallback por capacidade/sessão | baixo | **alto** | baixo | médio |
| R4 testável sem SO | médio | **alto** | baixo | médio |
| R5 incremental | médio | **alto** | alto | baixo |
| R6 diagnóstico | baixo | **alto** | nenhum | médio |
| R7 PyInstaller | alto | médio (com W6) | alto | baixo |
| Custo inicial | médio | médio | **baixo** | alto |

## 4. Decisão

**Opção B:** um `typing.Protocol` por capacidade, **registro declarativo** capacidade → sessão → cadeia de backends, **carga lazy com cache**, e uma **fachada fina** (`jarvis.platform`) com helpers tipados, para quem chama ter a ergonomia da opção A.

Também faz parte da decisão uma tabela de **features** (portões de migração, §9). Durante a transição, o `main.py` pergunta "este recurso existe nesta sessão?" sem conhecer o SO. No Windows todas as features são verdadeiras.

## 5. Estrutura

```
jarvis/platform/
├── __init__.py          # fachada: current(), get(), has(), has_feature(), report(), helpers tipados
├── detect.py            # PlatformContext + detect() — função pura (sys_platform e environ injetáveis)
├── capabilities.py      # enum Cap
├── protocols.py         # typing.Protocol de cada capacidade (só typing/stdlib)
├── features.py          # ALL_FEATURES, features_for(ctx, environ)
├── registry.py          # REGISTRY + resolve()/refresh()/report() com cache e lock
├── errors.py            # CapabilityUnavailable
├── common/
│   ├── base.py          # BackendBase (name, probe(ctx), __init__(ctx)), Probe
│   └── unavailable.py   # objeto que implementa qualquer protocolo levantando CapabilityUnavailable
├── windows/             # ADAPTERS: embrulham o código atual (regras W1–W7)
│   ├── env.py           # refresh_path_from_registry()          (F1-15, veio de main.py:114-129)
│   ├── paths.py         # WindowsPaths                          (F1-02)
│   ├── processes.py     # WindowsProcesses + Job Object literal (F1-08, F1-14)
│   └── webview_engine.py# EdgeChromiumEngine                    (F1-06)
├── linux/               # comum a X11 e Wayland
│   ├── xdg.py           # resolução XDG Base Directory
│   ├── paths.py         # XdgPaths
│   ├── processes.py     # PosixProcesses (registro de filhos + atexit)
│   └── webview_engine.py# QtWebEngine + decide_sandbox()
├── linux_x11/           # Fase 2/3: hotkeys pynput, captura mss, janelas EWMH, clipboard xclip
└── linux_wayland/       # Fase 2/3: portal GlobalShortcuts/KGlobalAccel, portal Screenshot, kdotool, wl-clipboard
```

> O nome `jarvis.platform` **não conflita** com o `platform` da stdlib: é subpacote e o Python 3 usa import absoluto. Regra: **nunca** colocar a pasta `jarvis/` diretamente no `sys.path`.

## 6. Detecção de plataforma e sessão

```python
# jarvis/platform/detect.py
@dataclass(frozen=True)
class PlatformContext:
    kind: str                  # "win32" | "linux-wayland" | "linux-x11" | "linux-headless" | "unsupported"
    sys_platform: str
    desktops: tuple[str, ...]  # XDG_CURRENT_DESKTOP em minúsculas, separado por ":" — ("kde",), ("ubuntu", "gnome")
    xwayland: bool             # kind == linux-wayland e DISPLAY definido
    frozen: bool               # sys.frozen (PyInstaller)
    appimage: bool             # variável APPIMAGE presente
    source: str                # de onde saiu o kind: override|qt_qpa|xdg_session|wayland_display|display|fallback|os

    @property
    def is_windows(self) -> bool: return self.kind == "win32"
    @property
    def is_linux(self) -> bool: return self.kind.startswith("linux-")

def detect(sys_platform: str | None = None, environ: Mapping[str, str] | None = None,
           frozen: bool | None = None) -> PlatformContext: ...
```

**Algoritmo** (a ordem importa, e o princípio é que *o kind reflete onde a janela Qt vai morar*):
1. `sys.platform == "win32"` → `win32`. `darwin` e outros → `unsupported` (sem features e sem backends; não quebra o import).
2. Linux: `JARVIS_PLATFORM` ∈ {`linux-wayland`, `linux-x11`, `linux-headless`} → usa (valor inválido gera aviso e é ignorado).
3. `QT_QPA_PLATFORM` definido: começa com `wayland` → wayland; `xcb` → x11; `offscreen`/`minimal` → headless.
4. `XDG_SESSION_TYPE == "wayland"` **e** `WAYLAND_DISPLAY` definido → wayland. `XDG_SESSION_TYPE == "x11"` **e** `DISPLAY` definido → x11.
5. Só `WAYLAND_DISPLAY` → wayland. Só `DISPLAY` → x11.
6. Nada disso → `linux-headless` (tty, SSH, container sem display, CI).

`current()` na fachada chama `detect()` uma única vez e guarda o resultado. `_reset_for_tests(ctx=...)` troca o contexto nos testes.

## 7. Capacidades e contratos

```python
# jarvis/platform/capabilities.py
class Cap(str, Enum):
    PATHS = "paths"; OPEN_PATH = "open_path"; PROCESSES = "processes"; CLIPBOARD = "clipboard"
    NOTIFIER = "notifier"; NOTIFICATION_READER = "notification_reader"; VOLUME = "volume"
    HOTKEYS = "hotkeys"; INPUT = "input"; SCREEN_CAPTURE = "screen_capture"
    WINDOW_MANAGER = "window_manager"; SESSION = "session"; TRAY = "tray"; MEDIA = "media"
    WEBVIEW_ENGINE = "webview_engine"
```

```python
# jarvis/platform/protocols.py  (só typing/stdlib; tipos pesados ficam sob TYPE_CHECKING)
class Backend(Protocol):
    name: str                                   # ex.: "windows.job_object", "linux.xdg", "wayland.portal"

class Paths(Backend, Protocol):                 # F1
    def user_config_dir(self) -> Path: ...      # win: %APPDATA%/JARVIS            linux: $XDG_CONFIG_HOME/jarvis
    def user_data_dir(self) -> Path: ...        # win: %APPDATA%/JARVIS/data       linux: $XDG_DATA_HOME/jarvis
    def credentials_dir(self) -> Path: ...      # win: %APPDATA%/JARVIS/credentials linux: $XDG_CONFIG_HOME/jarvis/credentials (0700)
    def logs_dir(self) -> Path: ...             # win: %APPDATA%/JARVIS/logs       linux: $XDG_STATE_HOME/jarvis/logs
    def cache_dir(self) -> Path: ...            # win: %LOCALAPPDATA%/JARVIS/cache linux: $XDG_CACHE_HOME/jarvis
    def webview_storage_dir(self) -> str: ...   # win: expressão literal de main.py:2622 | linux: $XDG_DATA_HOME/jarvis/webview_data

class Processes(Backend, Protocol):             # F1
    def hidden_console_flags(self) -> int: ...  # win: CREATE_NO_WINDOW | linux: 0
    def install_child_cleanup(self) -> None: ...# win: Job Object KILL_ON_JOB_CLOSE|BREAKAWAY_OK (literal) | linux: atexit sobre o registro
    def register_child(self, proc: "subprocess.Popen", *, tree: bool = False) -> None: ...  # win: no-op (o Job cobre)
    def alive_children(self) -> list[int]: ...  # PIDs registrados ainda vivos (diagnóstico/smoke)
    def new_session_kwargs(self) -> dict: ...   # linux: {"start_new_session": True} p/ filhos com subárvore; win: {}

class WebviewEngine(Backend, Protocol):         # F1
    def prepare_env(self, environ: MutableMapping[str, str]) -> None: ...  # ANTES de `import webview`
    def start_kwargs(self) -> dict: ...         # win: {} | linux: {"gui": "qt"}
    def sandbox_state(self) -> str: ...         # "n/a" | "on: <motivo>" | "off: <motivo>"

class OpenPath(Backend, Protocol):              # F2 — win: os.startfile | linux: xdg-open → gio open
    def open(self, target: "str | Path") -> None: ...
    def reveal(self, path: Path) -> None: ...

class Clipboard(Backend, Protocol):             # F2 — wayland: wl-copy/wl-paste | x11: xclip/xsel
    def get_text(self) -> str | None: ...
    def set_text(self, text: str) -> None: ...
    def watch(self, on_change: Callable[[str], None], stop: threading.Event) -> None: ...

class Notifier(Backend, Protocol):              # F2 — linux: D-Bus org.freedesktop.Notifications
    def notify(self, title: str, body: str, *, icon: Path | None = None, urgency: str = "normal") -> None: ...

class NotificationReader(Backend, Protocol):    # F4 — linux: monitor D-Bus
    def start(self, on_notification: Callable[[dict], None]) -> bool: ...
    def stop(self) -> None: ...

class Volume(Backend, Protocol):                # F2 — linux: wpctl → pactl
    def get_output(self) -> float: ...          # 0.0..1.0
    def set_output(self, level: float) -> None: ...
    def set_output_muted(self, muted: bool) -> None: ...
    def set_input_muted(self, muted: bool) -> None: ...

class Hotkeys(Backend, Protocol):               # F3 — x11: pynput | wayland: portal GlobalShortcuts → KGlobalAccel
    def register(self, bindings: Mapping[str, Callable[[], None]]) -> None: ...  # combos no formato pynput "<ctrl>+<alt>+j"
    def start_push_to_talk(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None: ...
    def stop(self) -> None: ...

class InputInjector(Backend, Protocol):         # F3 — x11: pynput/xdotool | wayland: ydotool (opcional, fora do v1)
    def type_text(self, text: str) -> None: ...
    def press(self, combo: str) -> None: ...

class ScreenCapture(Backend, Protocol):         # F3 — x11: mss | wayland: portal Screenshot → spectacle
    def grab(self, region: tuple[int, int, int, int] | None = None, monitor: int | None = None) -> "Image": ...
    def monitors(self) -> list[dict]: ...

class WindowManager(Backend, Protocol):         # F3 — x11: EWMH | wayland/KDE: kdotool/KWin D-Bus
    def active_window(self) -> "WindowInfo | None": ...
    def list_windows(self) -> list["WindowInfo"]: ...
    def focus(self, match: str) -> bool: ...
    def minimize(self, match: str) -> bool: ...

class Session(Backend, Protocol):               # F2 — idle: org.freedesktop.ScreenSaver / logind IdleHint
    def idle_seconds(self) -> float: ...
    def locale(self) -> str: ...

class Tray(Backend, Protocol):                  # F2 — linux: StatusNotifierItem
    def show(self, title: str, icon_png: bytes, menu: Sequence["TrayItem"]) -> None: ...
    def hide(self) -> None: ...

class Media(Backend, Protocol):                 # F2 — linux: MPRIS (playerctl/D-Bus)
    def play_pause(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...
```

Os contratos de F2 a F4 são **esboço**. Cada fase refina o seu no próprio SPEC antes de implementar. Os de F1 (`Paths`, `Processes`, `WebviewEngine`) são **normativos**.

## 8. Registro e carga lazy

### 8.1 Declaração
```python
# jarvis/platform/registry.py
REGISTRY: dict[Cap, dict[str, tuple[str, ...]]] = {
    Cap.PATHS: {
        "win32":   ("jarvis.platform.windows.paths:WindowsPaths",),
        "linux-*": ("jarvis.platform.linux.paths:XdgPaths",),
    },
    Cap.PROCESSES: {
        "win32":   ("jarvis.platform.windows.processes:WindowsProcesses",),
        "linux-*": ("jarvis.platform.linux.processes:PosixProcesses",),
    },
    Cap.WEBVIEW_ENGINE: {
        "win32":   ("jarvis.platform.windows.webview_engine:EdgeChromiumEngine",),
        "linux-*": ("jarvis.platform.linux.webview_engine:QtWebEngine",),
    },
    # Exemplo da Fase 3 — cadeia com fallback só nesta capacidade:
    # Cap.HOTKEYS: {
    #     "win32":         ("jarvis.platform.windows.hotkeys:PynputHotkeys",),
    #     "linux-x11":     ("jarvis.platform.linux_x11.hotkeys:PynputHotkeys",),
    #     "linux-wayland": ("jarvis.platform.linux_wayland.hotkeys:PortalGlobalShortcuts",
    #                       "jarvis.platform.linux_wayland.hotkeys:KGlobalAccelHotkeys"),
    # },
}
```

### 8.2 Contrato do backend
```python
class Probe(NamedTuple):
    ok: bool
    reason: str = ""

class BackendBase:
    name: ClassVar[str]
    @classmethod
    def probe(cls, ctx: PlatformContext) -> Probe:   # barato e sem efeito colateral: env, shutil.which, import
        return Probe(True)
    def __init__(self, ctx: PlatformContext) -> None:
        self.ctx = ctx
```

### 8.3 Resolução (`get(cap)`)
1. Chaves na ordem: `ctx.kind` exato → `"<família>-*"` (ex.: `linux-*`) → `"*"`. Vale a **primeira chave presente** (não mistura cadeias).
2. Para cada `"módulo:Classe"`: `importlib.import_module`. Se falhar (qualquer exceção), registra `(caminho, "import: Tipo: msg")` e passa para o próximo. Senão chama `Classe.probe(ctx)`; se `ok=False`, registra o motivo e passa. Senão instancia `Classe(ctx)`.
3. O primeiro que passa vai para o cache. Se ninguém passa, o cache recebe um `Unavailable(cap, tentativas)`: qualquer método dele levanta `CapabilityUnavailable(cap, tentativas)`. Falha não é re-tentada a cada chamada. `refresh(cap)` limpa o cache daquela capacidade (ex.: depois de o usuário instalar o `wl-clipboard`).
4. Resolução sob `threading.RLock` com double-checked cache: as ~83 threads do app podem pedir a mesma capacidade ao mesmo tempo.
5. `has(cap)` → `bool` sem levantar. `report()` → `{"kind", "source", "desktops", "capabilities": {cap: {"backend": nome|None, "tried": [...]}}, "features": [...]}`, para o log de boot e o futuro painel de diagnóstico.

### 8.4 Fachada
```python
from jarvis.platform import current, get, has, has_feature, report, Cap
from jarvis.platform import paths, processes, webview_engine   # helpers tipados: paths() -> Paths etc.
```
Regras de import-time: `jarvis/platform/__init__.py` importa só stdlib e os módulos `detect`, `capabilities`, `features`, `registry` e `errors`. **Nenhum subprocess e nenhum backend no import.** A sonda do sandbox só roda em `QtWebEngine.prepare_env()`.

## 9. Features: portões de migração

```python
# jarvis/platform/features.py
ALL_FEATURES = frozenset({
    "global_hotkeys",       # PTT Shift+G (keyboard.Listener) + GlobalHotKeys — pynput
    "tray",                 # pystray + fechar-para-bandeja
    "notification_reader",  # comandos.notif_ctrl.NotificationMonitor (SetWinEventHook/UIAutomation)
    "clipboard_monitor",    # comandos.clipboard_hist_ctrl.start_monitor (ctypes user32)
    "self_update_payload",  # AutoUpdater + JarvisApi.apply_update_now (payload/instalador Windows)
    "gestures",             # GestureSystem, controle ocular (pyautogui, tkinter, overlays)
})
_DEFAULTS = {
    "win32":          ALL_FEATURES,
    "linux-x11":      frozenset({"global_hotkeys"}),   # pynput xorg funciona
    "linux-wayland":  frozenset(),                     # PTT global chega na Fase 3 (portal)
    "linux-headless": frozenset(),
    "unsupported":    frozenset(),
}
def features_for(ctx: PlatformContext, environ: Mapping[str, str]) -> frozenset[str]: ...
# Override só para dev/teste: JARVIS_FEATURES="+tray,-gestures" (nome desconhecido → aviso e ignora).
```

**Invariante de não-regressão:** `features_for(win32, {}) == ALL_FEATURES`. Todo portão novo no `main.py` tem a forma `if _has_feature("<nome>"):`, com `<nome>` ∈ `ALL_FEATURES`. Logo, **no Windows todo portão é verdadeiro** e o fluxo é o de hoje.

As features são a ponte **temporária**: quando uma capacidade ganhar backend Linux (ex.: `Cap.TRAY` na Fase 2), a feature correspondente passa a ser derivada de `has(Cap.TRAY)`, e o call site migra para `get(Cap.TRAY)`.

## 10. Como o backend `windows` embrulha o código atual

| Regra | Descrição |
|---|---|
| **W1** | O adapter windows **delega** para a função existente ou contém uma **cópia literal** do trecho que hoje vive no `main.py`: mesmas chamadas, mesma ordem, mesmos `print` e mesmos valores padrão. Copiar, não reescrever. |
| **W2** | Imports de Windows continuam **lazy dentro do método** (`ctypes.WinDLL`, `winreg`, `pycaw`, `win32gui`), para o módulo do adapter ser importável no Linux (teste) sem quebrar. Dependências como `ctypes`/`winreg` entram como parâmetro opcional (`ct=None`, `winreg_mod=None`) para os fakes. |
| **W3** | Cada adapter tem um **teste de caracterização**: compara o resultado com um **oráculo copiado de `1c32e38`** (`tests/golden/`), rodando no Linux com fakes, mais um teste `windows_only` equivalente para o N4 (Windows real). |
| **W4** | Invariante das features (§9): no Windows todo portão é verdadeiro. |
| **W5** | Mudança de comportamento no Windows **só com item explícito** marcado "mudança intencional" na SPEC. Na Fase 1 são três: F1-11 (limites do faulthandler), F1-12 (protótipos ctypes do clipboard) e F1-13 (`reload_ui` adiado com debounce). |
| **W6** | Todo módulo carregado por string no registro para `win32` (e todo módulo novo importado pelo `main.py`) entra na lista `hidden` do `JARVIS.spec` **e** no bloco `if False:` do `launcher.py`, no **mesmo commit**. Um teste estático garante isso. Sem isso, o .exe em modo standalone quebra. |
| **W7** | Um call site só migra para a fachada **junto** com o adapter windows e o teste golden dele, no mesmo commit. |

### 10.1 Mapa capacidade → código atual → backends

| Capacidade | Windows hoje (arquivo:linha em `1c32e38`) | Adapter `windows` | `linux-wayland` | `linux-x11` | Fase |
|---|---|---|---|---|---|
| paths | `jarvis/config/paths.py:13-18`; `main.py:2622-2626`, `:13519-13523` | `WindowsPaths` (expressões literais) | `XdgPaths` | `XdgPaths` | **F1** |
| processes | `main.py:13416-13493` (Job Object); `:12726` (`CREATE_NO_WINDOW`); `:6449` (`CREATE_NEW_CONSOLE`) | `WindowsProcesses` + `install_kill_on_close_job()` literal | `PosixProcesses` | `PosixProcesses` | **F1** (6449 na F2) |
| webview_engine | `main.py:13512-13532` (`storage_path`, `WEBVIEW2_ADDITIONAL_FLAGS`) | `EdgeChromiumEngine` (`start_kwargs()=={}`) | `QtWebEngine` (PySide6, sandbox auto) | idem | **F1** |
| env (PATH) | `main.py:113-129` (`winreg`) | `windows/env.py` literal | — (AppRun da F5 põe o ffmpeg embutido no PATH) | — | **F1** |
| open_path | `os.startfile`: `executor:27`, `msg_sender:432/526/578/709`, `janela_ctrl:248/260/636`, `games_ctrl:27`, `tool_registry:1761/2089/2199/2355/2389`, `main.py:8928/8949` | `os.startfile` | `xdg-open` → `gio open` | idem | F2 |
| clipboard | `comandos/clipboard_hist_ctrl.py:14-37`; `pyperclip`; `main.py:12018/12147` | delega | `wl-paste --watch`/`wl-copy` (Qt clipboard como alternativa) | `xclip`/`xsel` | F2 |
| notifier | `notif_ctrl`/`plyer` | delega | D-Bus `org.freedesktop.Notifications` | idem | F2 |
| notification_reader | `comandos/notif_ctrl.py:20,223`; `core/winrt_notification_listener.py` | delega | monitor D-Bus | idem | F4 |
| volume | `comandos/system_ctrl.py:89-156` (pycaw) | delega | `wpctl` → `pactl` | idem | F2 |
| session (idle/locale) | `main.py:7164-7184` (`GetLastInputInfo`); `core/win_locale.py` | delega/literal | ScreenSaver `GetSessionIdleTime` → logind `IdleHint` | idem | F2 |
| tray | `main.py:13251-13296` (pystray) | delega | StatusNotifierItem | idem | F2 |
| media | `comandos/midia_ctrl.py:92,134-142` | delega | MPRIS (`playerctl`) | idem | F2 |
| hotkeys | `main.py:137-138,186,11600-11645` (pynput) | `PynputHotkeys` (literal) | portal GlobalShortcuts → KGlobalAccel | `PynputHotkeys` (xorg) | F1 portão / F3 |
| input | `main.py:11990-12060` (pynput Controller); `msg_sender` (pyautogui); gestos | delega | ydotool (opcional, fora do v1) | pynput/xdotool | F3 |
| screen_capture | `ocr_ctrl:29-46`; `janela_ctrl:935-939`; `discord_ctrl:684-695`; `main.py:6558-7065` | delega | portal Screenshot → `spectacle -b -n` | `mss` | F3 |
| window_manager | `janela_ctrl:34,879`; `condicional_ctrl:66-81`; `main.py:11800,12002` | delega | `kdotool`/KWin D-Bus (GNOME: indisponível no v1) | EWMH (`python-xlib`/`wmctrl`) | F3 |

## 11. Regras para quem chama a camada

- **C1.** Código novo fora de `jarvis/platform/` não usa `sys.platform`, `os.name` nem `ctypes.windll`. Um teste estático compara com uma **allowlist congelada em `1c32e38`**, que só pode diminuir.
- **C2.** Não importar módulos de backend diretamente. Usar `get(Cap.X)`, os helpers tipados ou `has_feature()`.
- **C3.** `CapabilityUnavailable` vira mensagem ao usuário (chat/voz) **uma vez**. Nunca é engolida dentro de loop de polling. O anti-padrão atual é o `clipboard_hist_ctrl`, que no Linux engoliria `AttributeError` a cada 0,8 s.
- **C4.** `get()` não é chamado no import de módulos, só dentro de funções. **Única exceção:** o bootstrap do motor da webview no `main.py`, antes de `import webview` (F1-06).

## 12. Testes da própria camada
- **Detecção:** tabela parametrizada `sys_platform × environ → kind/source` (SPEC F1-01).
- **Registro:** módulos falsos em `sys.modules`, cobrindo ordem da cadeia, falha de import, `probe` negativo, cache (import uma vez só), 10 threads recebendo a mesma instância, `Unavailable` levantando e `refresh()`.
- **Higiene de import:** subprocess com `import jarvis.platform; jarvis.platform.current(); jarvis.platform.report()` não carrega `pynput`, `webview`, `qtpy`, `PySide6`, `pyautogui`, `pystray` nem `sounddevice`.
- **Adapters windows:** caracterização contra oráculos de `1c32e38` (W3).
- **Estáticos:** allowlist de C1 e hiddenimports de W6.

## 13. Consequências e riscos conhecidos
1. **O pywebview 6.1 força `--no-sandbox`** quando `QSysInfo.productType()` ∈ {`arch`, `manjaro`, `nixos`, `rhel`, `pop`} (`webview/platforms/qt.py`). **No Arch (um dos três alvos) o WebEngine roda sem sandbox**, seja qual for a nossa decisão. `QtWebEngine.sandbox_state()` reporta isso (decisão do dono, §14).
2. **`PR_SET_PDEATHSIG` não serve** como equivalente do Job Object: o sinal dispara quando **a thread** que criou o filho termina, não o processo. O Jarvis cria filhos em threads curtas. No Linux a limpeza usa **registro de PIDs + atexit**. O `QtWebEngineProcess` morre com o pai (IPC do Chromium) e o `ffplay` sai por EOF no stdin.
3. **`killpg` do próprio grupo é proibido.** Mataria o pipeline (`python main.py | tee log`) e, se o grupo foi herdado, processos alheios. Só se encerram **PIDs registrados** e grupos **criados por nós** (`start_new_session=True`), o que casa com a regra do dono de nunca matar por padrão.
4. **Handler de sinal Python não roda** enquanto a thread principal está no loop do Qt. Por isso a limpeza em SIGTERM não é garantida na Fase 1; os filhos atuais morrem sozinhos (item 2).
5. **O registro por string é invisível ao PyInstaller.** A mitigação é a regra W6 com teste estático.
6. **PySide6 ≥ 6.10 publica wheel `manylinux_2_34`** (glibc 2.34). A 6.9.3 é a última `manylinux_2_28` (conferido no PyPI em 2026-09-13). Com a baseline 2.28, fixa-se `PySide6==6.9.3` (§14).
7. **Python 3.12 é obrigatório** (`kokoro 0.9.4` exige `<3.13`; o venv do Windows é 3.12.10). O host tem 3.14, então os testes usam `.venv-linux` via `uv`.
8. **GNOME/Wayland não tem API de janelas**, então `window_manager` fica indisponível lá. O portal GlobalShortcuts depende da versão do portal de cada desktop.
9. **Nome da pasta no Linux em minúsculas: `jarvis`** (o `paths.py` já usa assim). O MAPA §6.5 cita `~/.local/share/JARVIS/ms-playwright`; o certo passa a ser `$XDG_DATA_HOME/jarvis/ms-playwright` (ajuste na Fase 5).
10. Em dev no Linux, `_data()` continua apontando para a raiz do repositório, como no dev do Windows (logs/prefs ao lado do `main.py`, cobertos pelo `.gitignore`). XDG vale para os caminhos da camada e, na Fase 5, para o `_data()` congelado no AppImage, que é read-only.

## 14. Pendências para o dono

**Resolvido em 2026-09-13** (decisões do dono registradas no log de decisões; ADR aprovado na opção B):
1. **glibc × Qt:** fica a baseline **2.28**, com **`PySide6==6.9.3`** fixado no v1.
2. **Arch sem sandbox do WebEngine** no v1 (imposto pelo pywebview), **reportado por `sandbox_state()`**.
3. **Validação no Windows real (N4):** fica **com o dono**, antes de qualquer merge na `master`. **Não bloqueia** as fases.
4. **Hotkeys no Wayland:** o portal **GlobalShortcuts, com KGlobalAccel de fallback, foi antecipado para a Fase 2**. No v1 em Wayland ficam o botão de microfone e a wake word. Por isso, onde o §7 (`Hotkeys`), o §9 (`_DEFAULTS`) e o §10.1 dizem "Fase 3"/"F3" para as hotkeys do Wayland, leia **Fase 2**. Na Fase 1, `features_for("linux-wayland")` continua vazio.
