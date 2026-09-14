# SPEC — Fase 2: capacidades de sistema no Linux (e a base da versão unificada)

| | |
|---|---|
| **Autor** | arquiteto · 2026-09-14 |
| **Base** | branch `linux-port`, commit `31bc0ce` (Fase 1 concluída: M1/M2 verdes, revisor aprovou com ressalvas). As linhas citadas são desse commit e **mudam a cada commit**: localize pelo **trecho-âncora**. |
| **Arquitetura** | [ADR-001](ADR-001-camada-plataforma.md) (opção B). Nesta fase continuam valendo W1–W7 e C1–C4. |
| **Fila** | [FILA-fase2-executor.md](FILA-fase2-executor.md) |
| **Objetivo do dono** | O Windows já funciona. A meta é deixar o Jarvis compatível com Linux e depois trabalhar numa **versão unificada**: toda mudança vale para as duas plataformas, e depois do N4 a `linux-port` vira a `master`. Ver §7. |

---

## 0. Escopo e definição de pronto

**Entra na Fase 2:**
- PTT global no Wayland: portal GlobalShortcuts, com KGlobalAccel de fallback.
- Tray StatusNotifierItem.
- Volume e microfone via PipeWire.
- Clipboard e monitor de clipboard.
- Notificações via D-Bus.
- `open_path` (xdg-open → gio).
- Session: idle e locale/timezone.
- Mídia via MPRIS.
- `processes.restart_self`.
- Dívidas da revisão da Fase 1: flags via `hidden_console_flags()`, `sounddevice` com `ImportError`, encerramento do smoke sem `os._exit` com áudio, e **planejamento** do `Cap.INPUT` (a implementação é da Fase 3).

**Fora da Fase 2:**
- injeção de input, captura de tela e janelas (Fase 3);
- leitura de notificações, gestos e detector de apps/jogos (Fase 4);
- AppImage e updater (Fase 5);
- notificador no Windows (decisão **D-F2-5**).

**Marco M1 — "Linux funcional em container":**
- **N0** verde.
- **N1** verde na matriz do qa (fedora44, debian12, ubuntu2404, arch), incluindo os testes de D-Bus em **barramento privado**.
- **N2** (X11): smoke com `JARVIS_SMOKE_HOTKEYS=1` imprime `JARVIS_SMOKE_HOTKEYS backend=pynput`.
- **N3** (Wayland virtual): smoke com `JARVIS_SMOKE_HOTKEYS=1` imprime `JARVIS_SMOKE_HOTKEYS backend=kglobalaccel`, e o `invokeShortcut` da §4 F2-01 produz `JARVIS_SMOKE_PTT press`.
- Em todos: `children_alive=0` e nenhuma entrada nova no `crash.log`.

**Marco M2 — "Fase 2 pronta":**
- M1 passa 3 vezes seguidas.
- O smoke de áudio (F2-10c) sai **sem** `JARVIS_SMOKE_FORCED_EXIT`, com `children_alive=0`.
- `git diff --stat 31bc0ce..linux-port` só toca arquivos da §3.
- O revisor aprovou.
- Existe o checklist **N-dono** (§1) para você rodar na sessão real.

O N4 (Windows real) continua com você, antes do merge na `master`, e agora cobre também as Fases 1 e 2.

## 1. Níveis de teste

| Nível | Onde | O que roda |
|---|---|---|
| **N0** | host, `.venv-linux` (Python 3.12) | unit, AST, golden e fakes de ferramentas (`wpctl`, `wl-paste`, `xdg-open`… como scripts num `PATH` temporário) |
| **N1** | containers da matriz | N0 + **D-Bus privado** (`dbus-daemon --session` próprio do teste). Serviços falsos: portal GlobalShortcuts, KGlobalAccel, Notifications, ScreenSaver, Mutter IdleMonitor, logind, Klipper, MPRIS e StatusNotifierWatcher. Recomendado: `python-dbusmock` com `AddMethod`/`EmitSignal`, só em requirements-dev e só no Linux |
| **N2** | container + Xvfb | smoke X11 (PTT via pynput reportado, sem abrir o microfone) |
| **N3** | container ligado ao `kwin_wayland --virtual` (`tests/docker/run_n3_wayland.sh`) + `dbus-run-session` + `kglobalacceld` no container | smoke Wayland e PTT via KGlobalAccel `invokeShortcut` |
| **N-dono** | **sessão real do Plasma, feito por você** (os agentes são proibidos de fazer isto) | diálogo do portal GlobalShortcuts e PTT segurando a tecla; ícone no painel; notificação; volume/mic; monitor de clipboard; `xdg-open`; restart em dev |
| **N4** | Windows real (você) | `pytest -m "not linux_only and not x11 and not wayland"` + checklist da Fase 1 + tray, volume, mídia, clipboard, restart em dev e abrir documento gerado |

As regras de segurança da Fase 1 continuam valendo:
- smoke só roda com `JARVIS_TEST_SANDBOXED=1`;
- nada da sessão, do D-Bus ou do PipeWire do dono;
- encerrar só PIDs registrados.

**Barramento privado é obrigatório:** nenhum teste pode falar com o `DBUS_SESSION_BUS_ADDRESS` do host.

## 2. Convenções (as da Fase 1, mais estas)
- **Nunca importar `main.py` em teste.** Para o `main.py`, use AST.
- **Golden (C):** oráculo **literal** de `31bc0ce` em `tests/golden/legacy_31bc0ce.py`. Quem grava é o qa, **antes** das tarefas que movem código do Windows.
- **K:** entra como `xfail(strict=True, reason="F2-xx")` e o commit do executor remove o `xfail`.
- **Fixtures novas (qa, tarefa T0):**
  - `private_session_bus` (sobe um `dbus-daemon`, exporta o endereço só para o teste e o encerra pelo PID);
  - `fake_tools(tmp_path, {"wpctl": script, ...})` (monta o `PATH` com scripts que gravam argumentos e devolvem saídas prontas);
  - `fake_windll` (reaproveita o padrão da Fase 1).
- **Toda chamada externa tem timeout:** D-Bus até 1 s na sonda e até 3 s na operação; ferramentas até 3 s. Timeout faz a sonda falhar e a cadeia seguir. Nunca pode travar o boot.

## 3. Lista fechada

| ID | Mudança | Arquivos de produção | Risco Windows |
|---|---|---|---|
| F2-00 | Infra: contratos normativos F2, features derivadas, D-Bus (jeepney), ferramentas, app-id | `jarvis/platform/{protocols,registry,features,__init__}.py`, `jarvis/platform/linux/{dbus,tools,app_id}.py`, `requirements.txt`, `JARVIS.spec`, `launcher.py` | nenhum |
| F2-01 | Hotkeys: pynput (win32/x11) + portal GlobalShortcuts → KGlobalAccel (wayland) | `jarvis/platform/common/pynput_hotkeys.py`, `jarvis/platform/linux_wayland/hotkeys_portal.py`, `jarvis/platform/linux/{hotkeys_kglobalaccel,desktop_entry}.py`, `main.py` | **médio** |
| F2-02 | Tray: pystray (win32) + QSystemTrayIcon/SNI (linux) | `jarvis/platform/windows/tray.py`, `jarvis/platform/linux/{tray_qt,qt_gui}.py`, `main.py` | médio |
| F2-03 | Volume/mic: pycaw (win32) + wpctl → pactl | `jarvis/platform/windows/volume.py`, `jarvis/platform/linux/volume.py`, `comandos/system_ctrl.py` | baixo |
| F2-04 | Clipboard + monitor | `jarvis/platform/windows/clipboard.py`, `jarvis/platform/linux_wayland/clipboard.py`, `jarvis/platform/linux_x11/clipboard.py`, `jarvis/platform/linux/clipboard_klipper.py`, `comandos/{system_ctrl,clipboard_hist_ctrl}.py` | baixo |
| F2-05 | Notifier D-Bus → notify-send (só Linux) | `jarvis/platform/linux/notifier.py`, `main.py` | nenhum |
| F2-06 | open_path: `os.startfile`/notepad (win32) + xdg-open → gio | `jarvis/platform/windows/open_path.py`, `jarvis/platform/linux/open_path.py`, `main.py`, `comandos/{executor,games_ctrl,msg_sender,janela_ctrl,tool_registry}.py` | baixo |
| F2-07 | Session: idle + locale/timezone | `jarvis/platform/windows/session.py`, `jarvis/platform/linux/session.py`, `jarvis/platform/linux_x11/session.py`, `main.py`, `core/win_locale.py` | baixo |
| F2-08 | Media: teclas virtuais + PowerShell (win32) + MPRIS → playerctl | `jarvis/platform/windows/media.py`, `jarvis/platform/linux/media.py`, `comandos/midia_ctrl.py` | baixo |
| F2-09 | `processes.restart_self` | `jarvis/platform/{windows,linux}/processes.py`, `main.py` | baixo |
| F2-10a | `CREATE_NO_WINDOW` via `hidden_console_flags()` | `main.py`, `comandos/games_ctrl.py`, `core/game_platform_detector.py`, `classifiers/modelo_local.py` | nenhum |
| F2-10b | `sounddevice`: `except (OSError, ImportError)` | `main.py` | nenhum |
| F2-10c | Smoke sai sem `os._exit` + smoke de áudio | `main.py`, `jarvis/platform/{windows,linux}/processes.py` | nenhum (só com a variável de smoke) |
| F2-11 | `Cap.INPUT`: **só planejamento** (§5), sem código | — | — |

Regra W6 para tudo: **todo** módulo novo `jarvis.platform.windows.*` e `jarvis.platform.common.*` entra no `JARVIS.spec` e no `if False:` do `launcher.py` no mesmo commit. Arquivo de produção fora da tabela só entra com emenda do arquiteto.

---

## 4. Mudanças detalhadas

### F2-00 — Infra da Fase 2

**Contratos (substituem os esboços em `jarvis/platform/protocols.py`; normativos):**

```python
@dataclass(frozen=True)
class HotkeyBinding:
    id: str                       # "ptt", "screenshot_analise", ...
    description: str              # texto que o usuário vê no diálogo do portal / nas configurações do KDE
    trigger: str                  # formato pynput: "<shift>+g", "<ctrl>+<alt>+j"
    on_press: Callable[[], None]
    on_release: Callable[[], None] | None = None

class Hotkeys(Protocol):
    name: str
    def listen_keys(self, on_press, on_release) -> bool: ...        # listener passivo tecla a tecla (pynput). Portal/KGA: False
    def bind(self, bindings: Sequence[HotkeyBinding]) -> dict[str, str]: ...  # id -> descrição do gatilho efetivo
    def stop(self) -> None: ...

class Tray(Protocol):
    name: str
    def setup(self, title: str, make_image: Callable[[], "PIL.Image.Image"], items: Sequence["TrayItem"]) -> bool: ...
    def set_visible(self, visible: bool) -> None: ...
    def stop(self) -> None: ...
# TrayItem(label: str, callback: Callable | None, default: bool = False, separator: bool = False)

class Volume(Protocol):
    name: str
    def get_output(self) -> int: ...          # 0..100
    def set_output(self, pct: int) -> None: ...
    def get_input(self) -> int: ...
    def set_input(self, pct: int) -> None: ...
    def toggle_output_mute(self) -> None: ...
    def step_output(self, delta_pct: int) -> None: ...

class Clipboard(Protocol):
    name: str
    can_watch: bool
    def get_text(self) -> str | None: ...
    def set_text(self, text: str) -> bool: ...
    def watch(self, on_change: Callable[[str], None], stop: threading.Event) -> bool: ...  # bloqueia até stop; False = não suporta

class Notifier(Protocol):
    name: str
    def notify(self, title: str, body: str, *, urgency: str = "normal", timeout_ms: int = -1) -> bool: ...

class OpenPath(Protocol):
    name: str
    def open(self, target: str) -> bool: ...            # arquivo, pasta, URL ou esquema (whatsapp://)
    def open_text_file(self, path: str) -> bool: ...    # win: notepad.exe literal | linux: open(path)

class Session(Protocol):
    name: str
    def idle_seconds(self) -> float | None: ...   # None = desconhecido
    def locale(self) -> str: ...                  # "pt-BR"
    def timezone_name(self) -> str: ...           # IANA

class Media(Protocol):
    name: str
    def play_pause(self) -> None: ...
    def stop(self) -> None: ...
    def next(self) -> None: ...
    def previous(self) -> None: ...
    def now_playing(self) -> dict | None: ...     # {"title","artist","player","status"}
    def toggle_mute(self) -> None: ...
    def volume_step(self, steps: int) -> None: ...  # win: VK; linux: Volume.step_output(steps*2)

class Processes(Protocol):                     # acrescenta à F1
    def restart_self(self, *, main_path: str, frozen: bool) -> None: ...  # dispara a nova instância; NÃO sai
    def shutdown_children(self, timeout: float = 2.0) -> None: ...        # limpeza explícita (F2-10c); win: no-op
```

**Registro (`registry.py`).** Cada entrada só entra no commit da tarefa correspondente:

| Cap | win32 | linux-wayland | linux-x11 | linux-headless |
|---|---|---|---|---|
| HOTKEYS | `common.pynput_hotkeys:PynputHotkeys` | `linux_wayland.hotkeys_portal:PortalGlobalShortcuts` → `linux.hotkeys_kglobalaccel:KGlobalAccelHotkeys` | `common.pynput_hotkeys:PynputHotkeys` → `linux.hotkeys_kglobalaccel:KGlobalAccelHotkeys` | — |
| TRAY | `windows.tray:PystrayTray` | `linux.tray_qt:QtSystemTray` | idem | — |
| VOLUME | `windows.volume:PycawVolume` | `linux.volume:WpctlVolume` → `linux.volume:PactlVolume` | idem | idem |
| CLIPBOARD | `windows.clipboard:WindowsClipboard` | `linux_wayland.clipboard:WlClipboard` → `linux.clipboard_klipper:KlipperClipboard` | `linux_x11.clipboard:XclipClipboard` → `linux_x11.clipboard:XselClipboard` → `linux.clipboard_klipper:KlipperClipboard` | — |
| NOTIFIER | — (D-F2-5) | `linux.notifier:DbusNotifier` → `linux.notifier:NotifySendNotifier` | idem | — |
| OPEN_PATH | `windows.open_path:StartfileOpenPath` | `linux.open_path:XdgOpen` → `linux.open_path:GioOpen` | idem | idem |
| SESSION | `windows.session:WindowsSession` | `linux.session:ScreenSaverSession` → `linux.session:MutterSession` → `linux.session:LogindSession` | `linux.session:ScreenSaverSession` → `linux_x11.session:XssSession` → `linux.session:LogindSession` | `linux.session:LogindSession` |
| MEDIA | `windows.media:VirtualKeyMedia` | `linux.media:MprisMedia` → `linux.media:PlayerctlMedia` | idem | — |

(Prefixo `jarvis.platform.` omitido.) **Todas as sondas são baratas:** `shutil.which`, `NameHasOwner` com timeout de 1 s e leitura de propriedade `version`. Nenhuma sonda abre diálogo nem grava estado.

**Features derivadas (`__init__.has_feature`):**
- `features_for()` continua pura e estática. Os testes da Fase 1 ficam intactos e **win32 continua == ALL**.
- No Linux, `has_feature(nome)` passa a ser `nome ∈ estático OU derivado(nome)`, onde:
  - `global_hotkeys` = `has(HOTKEYS)`;
  - `tray` = `has(TRAY)`;
  - `clipboard_monitor` = `has(CLIPBOARD) and get(CLIPBOARD).can_watch`.
- O `-nome` do `JARVIS_FEATURES` continua vencendo o derivado.
- Sem cache de valor negativo além do cache do registro (`refresh(cap)` limpa).

**`linux/dbus.py`** usa `jeepney.io.threading`: um roteador de sessão por processo, criado de forma lazy e protegido por lock.
- Oferece `call(dest, path, iface, method, signature, args, timeout)`, `get_property(...)`, `name_has_owner(name)` e `subscribe(match_rule) -> SignalQueue` (thread daemon; `AddMatch` via `message_bus`).
- A API blocking do jeepney **não é thread-safe**; por isso o módulo usa `io.threading`.
- **Conexão dedicada** para o portal (F2-01), porque o `Registry.Register` precisa vir antes de qualquer outra chamada de portal na conexão.
- Dependência nova: `jeepney>=0.8,<1; sys_platform == "linux"` (pure Python) — **D-F2-4**.

**`linux/tools.py`:**
- `run_tool(argv, *, timeout=3.0, input=None) -> CompletedProcess | None`;
- sem shell, com `LC_ALL=C` para saída parseável;
- `which()` com cache;
- nunca registra o processo como filho (é curto e aguardado).

**`linux/app_id.py`:** `APP_ID = "io.github.ninjazins2.Jarvis"` (**provisório, D-F2-2**) e `APP_NAME = "J.A.R.V.I.S."`.

- **Risco Windows:** nenhum (win32 estático e registro win32 intocado nesta tarefa).
- **Aceite:**
  - sondas sem serviço terminam em ≤ 1,2 s;
  - `report()` lista as cadeias;
  - `has_feature` no win32 continua verdadeiro para todas, sem sondar nada (espião prova zero chamadas ao registro).
- **Testes (executor, junto):**
  - K `tests/unit/platform/test_features_derived.py`;
  - K `tests/unit/platform/test_linux_dbus.py` (N1, `private_session_bus`: call, propriedade, sinal, timeout);
  - K `tests/unit/platform/test_linux_tools.py`;
  - W6 e C1 atualizados.

### F2-01 — Hotkeys: PTT global no Wayland (área crítica; o executor pode pedir detalhe)

**Onde:**
- `main.py` `_start_keyboard_listener` (âncora `self._listener = keyboard.Listener(`);
- `_start_global_hotkeys` (âncora `self._hotkeys_listener = GlobalHotKeys(handlers)`);
- `_on_key_press` e `_on_key_release` (âncora `if key in _SHIFT_KEYS:`).

**Antes:** pynput passivo no win32/x11. No Wayland, o portão `global_hotkeys` bloqueia e mostra "[PTT] Atalho global indisponível".

**Depois:**
1. **`common/pynput_hotkeys.py::PynputHotkeys`** (win32 e linux-x11). Cópia **literal** do que o `main.py` faz hoje:
   - `listen_keys` cria `keyboard.Listener(on_press=..., on_release=...)` e dá `.start()`;
   - `bind` monta `GlobalHotKeys({combo: handler})` com parada do listener anterior e o mesmo `_log.info` de sucesso/falha. O `print` de ação desconhecida continua no `main.py`.
   - A sonda falha se `pynput` não importar.
2. **`main.py`:**
   - a detecção Shift+G continua em `_on_key_press`/`_on_key_release`;
   - os **corpos** que iniciam e finalizam a gravação saem, literalmente, para `_ptt_iniciar()` e `_ptt_finalizar()`, e as duas funções originais passam a chamá-los;
   - `_start_keyboard_listener`:
     ```python
     hk = _plat_get(Cap.HOTKEYS) if _has_feature("global_hotkeys") else None
     if hk is None: print(<mensagem atual>); self._listener = None; return
     if hk.listen_keys(self._on_key_press, self._on_key_release): return   # win32/x11: igual a hoje
     hk.bind([HotkeyBinding("ptt", "Falar com o JARVIS (segurar)", _ptt_trigger(),
                            self._ptt_iniciar, self._ptt_finalizar)])
     ```
     `_ptt_trigger()` lê `config.PTT_TRIGGER_GLOBAL` (padrão definido em **D-F2-1**);
   - `_start_global_hotkeys` monta `HotkeyBinding(id=acao, description=cmd, trigger=combo, on_press=_handler)` e chama `hk.bind(...)`. No win32 isso resulta no mesmo `GlobalHotKeys(handlers)`.
3. **`linux_wayland/hotkeys_portal.py::PortalGlobalShortcuts`** ([xdg-desktop-portal GlobalShortcuts v2](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)):
   - **Sonda:** `org.freedesktop.portal.Desktop` tem dono, e a propriedade `version` de `org.freedesktop.portal.GlobalShortcuts` é ≥ 1.
   - **Conexão dedicada.** Se `org.freedesktop.host.portal.Registry` existir, chama `Register(APP_ID, {})` **antes de qualquer outra chamada** ([Registry](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.host.portal.Registry.html); o `app_id` precisa casar com o basename de um `.desktop`). O Fedora 44 tem xdg-desktop-portal 1.22.1.
   - **`CreateSession({handle_token, session_handle_token})`.** Assinar o `Response` do caminho de request **previsto** (`/org/freedesktop/portal/desktop/request/<sender sem ':' e com '.'→'_'>/<token>`) **antes** de chamar, para não perder a resposta. O resultado traz `session_handle`.
   - **`BindShortcuts(session, [(id, {description, preferred_trigger})], "", {handle_token})`:**
     - o gatilho pynput é convertido para o formato do portal (`<shift>+g` → `SHIFT+g`, `<ctrl>` → `CTRL`, `<alt>` → `ALT`, `<cmd>` → `LOGO`);
     - resposta 0 = ok (devolve `trigger_description`); 1 = usuário cancelou → `CapabilityUnavailable("usuário recusou")` e **não repete o pedido nesta sessão**; 2 = erro → próximo da cadeia.
     - **Timeout do `Response`: 120 s**, porque o KDE mostra um diálogo. Não bloqueia o boot: o bind roda numa thread daemon `PortalHotkeys`, e o PTT fica inativo até a resposta.
   - **Sinais `Activated`/`Deactivated`** `(o session, s id, t ts, a{sv})` filtrados por sessão → `on_press`/`on_release` via `root.after(0, ...)` (no `main.py`).
   - `stop()` chama `Close` na `org.freedesktop.portal.Session`.
   - **`listen_keys` → False.**
4. **`linux/desktop_entry.py::ensure_desktop_entry()`** (**D-F2-3**):
   - grava `$XDG_DATA_HOME/applications/<APP_ID>.desktop` com `NoDisplay=true`, `Exec=<sys.executable> <main.py>` e `Icon=`;
   - só se não existir ou se o `Exec` mudou;
   - chamado pelo `PortalGlobalShortcuts.__init__`;
   - no AppImage (Fase 5) quem cuida é o `AppRun`.
5. **`linux/hotkeys_kglobalaccel.py::KGlobalAccelHotkeys`** (KDE, X11 e Wayland, sem diálogo; interface [org.kde.KGlobalAccel](https://invent.kde.org/frameworks/kglobalaccel/-/blob/master/src/org.kde.KGlobalAccel.xml)):
   - **Sonda:** `org.kde.kglobalaccel` tem dono.
   - `actionId = ["jarvis", id, "J.A.R.V.I.S.", description]`, depois `doRegister(actionId)` e `setShortcut(actionId, [qt_key], flags)`:
     - `qt_key` = modificadores Qt (`Shift 0x02000000`, `Ctrl 0x04000000`, `Alt 0x08000000`, `Meta 0x10000000`) | código da tecla (`Key_G = 0x47`, letras A–Z = ASCII maiúsculo, `Key_Space = 0x20`);
     - `flags`: **o executor confirma os valores de `SetPresent`/`NoAutoloading` em `kglobalaccel.h` antes de usar**; se não achar, pede ao arquiteto.
   - `getComponent("jarvis")` devolve o caminho. Assinar `globalShortcutPressed`/`globalShortcutReleased` `(s component, s action, x ts)` ([Component](https://invent.kde.org/frameworks/kglobalaccel/-/blob/master/src/org.kde.kglobalaccel.Component.xml)).
   - Se o `setShortcut` devolver lista vazia (atalho em conflito), registra o aviso e devolve `trigger="(sem atalho — configure em Configurações do sistema › Atalhos)"`.
   - `stop()` chama `unRegister` para cada ação.
6. **Features:** no linux-wayland, `global_hotkeys` passa a ser derivada (F2-00).

**Gancho de smoke:**
- com `JARVIS_SMOKE_HOTKEYS=1`, depois do ready, imprime `JARVIS_SMOKE_HOTKEYS backend=<hk.name|none> ptt=<descrição>`;
- **no modo smoke**, `_ptt_iniciar`/`_ptt_finalizar` só imprimem `JARVIS_SMOKE_PTT press`/`release` e **não abrem o microfone**.

**Risco Windows:** médio (é o caminho do PTT). Mitigação:
- adapter literal;
- a extração de `_ptt_iniciar`/`_ptt_finalizar` só **move** linhas;
- golden AST;
- N4: Shift+G e os quatro atalhos do `config.HOTKEYS`.

**Aceite:**
- N2: `backend=pynput`;
- N3: `backend=kglobalaccel` e `invokeShortcut("ptt")` gera `JARVIS_SMOKE_PTT press`;
- N1: fluxo completo do portal falso (Register → CreateSession → Bind → Activated/Deactivated → press/release; resposta 1 → indisponível sem repetir o pedido);
- N-dono: diálogo do KDE aparece uma vez, PTT funciona segurando a tecla, e digitar texto comum não é afetado.

**Testes:**
- **qa, antes:**
  - C `tests/golden/test_hotkeys_windows.py` (AST: os kwargs de `keyboard.Listener(` e a construção do `GlobalHotKeys(handlers)` no adapter são iguais aos de `31bc0ce`; `_on_key_press`/`_on_key_release` + `_ptt_iniciar`/`_ptt_finalizar` somam as mesmas instruções);
  - K `tests/unit/platform/test_hotkeys_portal.py` (N1, portal falso, inclusive a ordem Register → CreateSession e a assinatura prévia do Response);
  - K `tests/unit/platform/test_hotkeys_kglobalaccel.py` (N1, KGlobalAccel falso; conversão para `qt_key`);
  - K `tests/unit/platform/test_trigger_convert.py`;
  - K `tests/smoke/test_hotkeys_n2_n3.py`.
- **qa (infra):** imagem N3 com `dbus-run-session`, `kglobalacceld` e `kf6-kglobalaccel`. O portal real no container é **opcional**: se o `xdg-desktop-portal-kde` não subir sem o Plasma, o portal fica coberto pelo N1 com fake + N-dono.

### F2-02 — Tray StatusNotifierItem

**Onde:** `main.py` `_criar_tray_icon` (âncora `self._tray_icon = pystray.Icon(`), `_minimizar_para_tray`, `_restaurar_da_tray` e `_encerrar_de_tray`.

**Depois:**
- **`windows/tray.py::PystrayTray`:** cópia literal da montagem `pystray.Menu`/`MenuItem`/`Icon`, da thread `self._tray_icon.run` e de `.visible`/`.stop()`. A imagem continua sendo gerada no `main.py` (passada via `make_image`). O `events.closing += _on_window_close_request` fica no `main.py`, e só se `setup()` devolver True.
- **`linux/tray_qt.py::QtSystemTray`:**
  - `QSystemTrayIcon` + `QMenu` do PySide6 (Plasma: SNI via D-Bus; X11 sem watcher: XEmbed do próprio Qt);
  - **sonda:** `org.kde.StatusNotifierWatcher` tem dono **ou** kind == linux-x11 com `DISPLAY`. No GNOME sem extensão não há watcher, o tray fica indisponível e o X fecha o app, como hoje sem pystray;
  - tudo que toca Qt passa por **`linux/qt_gui.py::run_in_gui_thread(fn, timeout=5)`**, que usa `QTimer.singleShot(0, <QObject da janela: window.native>, fn)` e um `threading.Event` para o resultado;
  - **gate:** o K N2/N3 `test_qt_gui_thread.py` precisa provar que funciona a partir de thread não-Qt. Se falhar, a alternativa é uma ponte `QObject` com `Signal` criada no primeiro `loaded` (pedir detalhe ao arquiteto);
  - o ícone vem de `make_image()` (PIL → `QPixmap` via PNG em memória).
- **`main.py`:**
  - `_criar_tray_icon` passa a chamar `tray = _plat_get(Cap.TRAY)`, depois `ok = tray.setup("J.A.R.V.I.S.", _make_img, items)`; `self._tray_icon = tray if ok else None`;
  - `_minimizar_para_tray`/`_restaurar_da_tray` usam `set_visible`;
  - `_encerrar_de_tray` usa `stop()`, e o resto fica igual.
- O portão `_has_feature("tray")` (Fase 1) continua. No Linux ele passa a ser derivado.

**Risco Windows:** médio (fechar-para-bandeja). Golden + N4.

**Aceite:**
- O tray **nasce oculto** (`visible=False`, igual ao golden do pystray no Windows), e o Qt só se registra no watcher quando o ícone fica visível (provado no N3 em `a886ee9`: oculto → `calls=[]`; visível → `Register`);
- N1/K: o watcher falso recebe `RegisterStatusNotifierItem` **só depois de `set_visible(True)`**; antes disso, nenhuma chamada;
- N3 com watcher falso no barramento do container: feature `tray` ativa (`setup()` devolve True) e o processo sai com código 0;
- N3 sem watcher: igual a hoje (tray indisponível, o X fecha o app e o processo sai com código 0);
- N-dono: ícone aparece no painel ao minimizar para a bandeja, e Restaurar/Briefing/Encerrar funcionam.

**Testes:**
- qa, antes: C `tests/golden/test_tray_windows.py` (AST/literal: itens, ordem, `default=True`, `SEPARATOR`, thread `.run`, `visible=False`);
- qa: K `tests/unit/platform/test_tray_qt.py` (N2/N3) e K `tests/unit/platform/test_qt_gui_thread.py` (N2/N3).

### F2-03 — Volume e microfone (PipeWire)

**Onde:** `comandos/system_ctrl.py`: `set_volume`, `get_volume`, `set_mic_volume`, `get_mic_volume` (âncoras `vol = _get_audio_volume()` e `vol = _get_mic_volume()`).

**Depois:**
- **`windows/volume.py::PycawVolume`:** `_get_audio_volume`/`_get_mic_volume` passam para lá **literais** e `Get/SetMasterVolumeLevelScalar` viram `get_output`/`set_output`/`get_input`/`set_input`. `toggle_output_mute`/`step_output` usam `SetMute`/`GetMute` e `VolumeStepUp/Down` do mesmo `IAudioEndpointVolume` (**novo no Windows, só usado pela F2-08 se você aprovar**; senão a F2-08 mantém as teclas virtuais).
- As funções do `system_ctrl` chamam `get(Cap.VOLUME)`, e as **strings de retorno ficam idênticas**.
- **`linux/volume.py::WpctlVolume`:**
  - `wpctl get-volume @DEFAULT_AUDIO_SINK@` → `Volume: 0.40` (`[MUTED]` opcional), em pct = round(v×100);
  - `set-volume @DEFAULT_AUDIO_SINK@ 0.40 --limit 1.0`;
  - `@DEFAULT_AUDIO_SOURCE@` para o microfone;
  - `set-mute @DEFAULT_AUDIO_SINK@ toggle`;
  - `set-volume ... 2%+`/`2%-` para o passo;
  - **sonda:** `wpctl` no `PATH` e `wpctl status` com código 0 em 2 s.
- **`PactlVolume`:**
  - `pactl get-sink-volume @DEFAULT_SINK@` (1º `NN%`);
  - `set-sink-volume @DEFAULT_SINK@ NN%`;
  - `get-source-volume @DEFAULT_SOURCE@`, `set-source-volume`;
  - `set-sink-mute @DEFAULT_SINK@ toggle`;
  - **sonda:** `pactl info` com código 0.

**Risco Windows:** baixo (golden das mensagens e das chamadas COM com fakes).

**Aceite:**
- N0 com `fake_tools` cobre parse e argumentos de cada comando, inclusive `[MUTED]`, valores > 1.0 (boost) e saída inesperada → exceção tratada com a mensagem atual;
- N-dono: "volume 30" e "microfone 80" funcionam.

**Testes:**
- qa, antes: C `tests/golden/test_volume_windows.py` (`_get_audio_volume` literal com COM falso; `set_volume(150)` → 100; mensagens idênticas);
- qa: K `tests/unit/platform/test_volume_linux.py`.

### F2-04 — Clipboard e monitor

**Onde:**
- `comandos/system_ctrl.py`: `get_clipboard`/`set_clipboard` (âncora `import pyperclip`);
- `comandos/clipboard_hist_ctrl.py`: `_monitor_loop`/`start_monitor` (âncoras `def _monitor_loop` e `time.sleep(0.8)`).

**Depois:**
- **`windows/clipboard.py::WindowsClipboard`:**
  - `get_text`/`set_text` = pyperclip literal (mesmos `try/except` e retornos);
  - `watch` = loop literal do `_monitor_loop` (0,8 s, `_get_clipboard_text` com o WinDLL privado da F1-12);
  - `can_watch = True`.
- O `clipboard_hist_ctrl.start_monitor` passa a rodar `get(Cap.CLIPBOARD).watch(_on_change, _stop_event)` numa thread. `_on_change` guarda no `_history`, com as mesmas regras (sem repetir o último, `strip > 1` e limite `_MAX`).
- **`linux_wayland/clipboard.py::WlClipboard`:**
  - `get_text` = `wl-paste --no-newline --type text` (código ≠ 0 → `None`);
  - `set_text` = `wl-copy` com o texto em stdin (o `wl-copy` se desanexa sozinho; não registrar como filho);
  - **`can_watch`:** sonda `wl-paste --list-types` com o stderr checado. Se aparecer "data-control" → False. O KWin implementa **ext-data-control-v1**, suportado pelo wl-clipboard **≥ 2.3.0**, e o Fedora 44 traz `2.2.1^git20251124` ([fonte](https://github.com/bugaevc/wl-clipboard/releases)); por isso a decisão sai da sonda em runtime;
  - `watch` = `wl-paste --type text --watch echo __JARVIS_CLIP__` (processo registrado com `register_child`; cada linha-marcador dispara `get_text()`; `stop` encerra o PID).
- **`linux/clipboard_klipper.py::KlipperClipboard`** (só KDE):
  - `org.kde.klipper` `/klipper` `org.kde.klipper.klipper`: `getClipboardContents`/`setClipboardContents`;
  - `watch` = sinal `clipboardHistoryUpdated` → `getClipboardContents`;
  - **sonda:** `org.kde.klipper` tem dono.
- **`linux_x11/clipboard.py`:**
  - `XclipClipboard` (`xclip -selection clipboard -o` / `-i`);
  - `XselClipboard` (`xsel --clipboard --output/--input`);
  - `watch` = polling de 0,8 s (o mesmo comportamento do Windows).
- **Fora do escopo:** os `pyperclip.copy` que servem para **colar via injeção** (`msg_sender`, `janela_ctrl`, `pyautogui_sender`) ficam para a Fase 3 (`Cap.INPUT`).

**Risco Windows:** baixo.

**Aceite:**
- N0 com fakes: get/set/watch; wl-paste velho → `can_watch=False` e Klipper assume;
- N1: Klipper falso emite o sinal → histórico atualizado;
- sem nenhum backend com `watch` → `clipboard_monitor` desligado e **uma** mensagem;
- N-dono: copiar 3 textos → "histórico do clipboard" lista os três.

**Testes:**
- qa, antes: C `tests/golden/test_clipboard_windows.py` (pyperclip falso; loop do monitor com `_get_clipboard_text` falso e `sleep` espionado: 0,8);
- qa: K `tests/unit/platform/test_clipboard_linux.py` e K `tests/tools/test_clipboard_hist_ctrl_platform.py` (tools-lab).

### F2-05 — Notifier (só Linux nesta fase)

**Onde:** `main.py` `_exibir_resposta` (âncora `def _exibir_resposta`).

**Depois:**
- **`linux/notifier.py::DbusNotifier`:**
  - `org.freedesktop.Notifications` `/org/freedesktop/Notifications` `Notify(s app_name="J.A.R.V.I.S.", u 0, s icon="", s title, s body, as [], a{sv} {"urgency": byte 0|1|2, "desktop-entry": APP_ID}, i timeout_ms)`;
  - **sonda:** nome tem dono.
- **`NotifySendNotifier`:** `notify-send -a J.A.R.V.I.S. -u <urgency> [-t ms] title body`.
- **`main.py`:** em `_exibir_resposta`, **só quando `self._tray_visible`** (janela escondida na bandeja) e `_plat_has(Cap.NOTIFIER)`, chama `notify("J.A.R.V.I.S.", texto[:200])` numa thread daemon. No win32 `has` é falso → **sem mudança**.

**Aceite:**
- N1: o daemon falso recebe `Notify` com os argumentos acima;
- fallback `notify-send` via `fake_tools`;
- N-dono: com a janela na bandeja, um alarme gera notificação.

**Testes (executor, junto):** K `tests/unit/platform/test_notifier_linux.py` e K AST `tests/unit/test_main_notifier_gate.py`.

### F2-06 — open_path

**Onde (lista fechada de call sites):**
- `main.py`:
  - `_mostrar_texto_longo` (âncora `subprocess.Popen(["notepad.exe", path], close_fds=True)`);
  - bloco "tipo desconhecido" (âncora `_os.startfile(path)  # type: ignore`, ~8970);
  - `_gerar_imagem_thread` (âncora `_os.startfile(caminho)`, ~8991).
- `comandos/executor.py:27` (âncora `if hasattr(os, "startfile"):`).
- `comandos/games_ctrl.py:27`.
- `comandos/msg_sender.py:432`, `:526`, `:578` (`"discord://"`) e `:709` (`"whatsapp://"`).
- `comandos/janela_ctrl.py:248`, `:260` e `:640`.
- `comandos/tool_registry.py:1761`, `:2089`, `:2199`, `:2355`, `:2389` e `:2445`.

Os **nomes** de apps `notepad` em `executor.py:563` e `janela_ctrl.py:131/775/798/893` são mapa de apps e ficam para a **Fase 4**.

**Depois:**
- Fachada `jarvis.platform.open_path(target) -> bool`. Cada `os.startfile(X)` vira `_open_path(X)`, **dentro do mesmo `try/except`**. Onde havia `hasattr(os, "startfile")`, usar `if _open_path(url): return True`.
- `windows/open_path.py::StartfileOpenPath`:
  - `open` = `os.startfile(target)` literal, devolve True e **propaga a exceção** (os call sites já tratam);
  - `open_text_file` = `subprocess.Popen(["notepad.exe", path], close_fds=True)` literal.
- `linux/open_path.py::XdgOpen`:
  - `Popen(["xdg-open", target], stdin/stdout/stderr=DEVNULL, close_fds=True, start_new_session=True)`;
  - **não** registrar como filho (o app aberto precisa sobreviver ao Jarvis);
  - uma thread daemon faz `proc.wait()` para não virar zumbi;
  - código ≠ 0 dentro de 3 s → levanta `OSError` (para o `except` do call site cair no fallback de hoje).
- `GioOpen`: igual com `gio open`.
- `open_text_file` no Linux = `open(path)`.

**Risco Windows:** baixo (a mesma chamada, só atrás de uma indireção).

**Aceite:**
- N0: `fake_tools` recebe os argumentos;
- nenhum `os.startfile` nem `notepad.exe` fora de `jarvis/platform/windows/` e dos mapas de nome da Fase 4 (**C1 atualizado**);
- N-dono: "gerar PDF" abre o visualizador padrão.

**Testes:**
- qa, antes: C `tests/golden/test_open_path_windows.py` (o `os.startfile` falso é chamado 1× com o mesmo argumento; notepad literal) e C AST `tests/golden/test_startfile_callsites.py` (cada call site da lista chama `_open_path` com **a mesma expressão de argumento** de `31bc0ce`);
- qa: K `tests/unit/platform/test_open_path_linux.py`.

### F2-07 — Session: idle, locale e timezone

**Onde:** `main.py` `_idle_seconds` (âncora `ctypes.windll.user32.GetLastInputInfo`) e `core/win_locale.py` (`get_timezone_name`, `get_locale`).

**Depois:**
- **`windows/session.py::WindowsSession`:**
  - `idle_seconds` = corpo literal de `_idle_seconds`, incluindo `return 0.0` em exceção. **No Windows nunca devolve `None`**;
  - `locale` = `core.win_locale.get_locale` e `timezone_name` = `get_timezone_name` (delegação).
- **`main._idle_seconds`:** `v = _plat_get(Cap.SESSION).idle_seconds(); return 0.0 if v is None else v` (semântica atual preservada: "desconhecido" = não ausente).
- **`linux/session.py`:**
  - `ScreenSaverSession`: `org.freedesktop.ScreenSaver` `/ScreenSaver` `GetSessionIdleTime → u` **segundos** ([kscreenlocker](https://github.com/KDE/kscreenlocker/blob/master/dbus/org.freedesktop.ScreenSaver.xml)). Houve bug antigo que devolvia ms: se o valor for maior que o uptime em s, dividir por 1000 e avisar uma vez.
  - `MutterSession`: `org.gnome.Mutter.IdleMonitor` `/org/gnome/Mutter/IdleMonitor/Core` `GetIdletime → t` **ms**.
  - `LogindSession`: `org.freedesktop.login1` `/org/freedesktop/login1/session/auto`, propriedades `IdleHint` (b) e `IdleSinceHintMonotonic` (t, µs). Idle = `CLOCK_MONOTONIC - since` quando `IdleHint`, senão 0; sem acesso → `None`.
  - `locale()`: `LC_ALL` > `LC_MESSAGES` > `LANG` → `pt_BR.UTF-8` → `pt-BR` (padrão `pt-BR`).
  - `timezone_name()`: `TZ` > link `/etc/localtime` → parte depois de `zoneinfo/` > `UTC`.
- **`linux_x11/session.py::XssSession`:** `ctypes` em `libXss.so.1` (`XScreenSaverQueryInfo(dpy, root, info).idle` em ms); **sonda:** a lib carrega e o `DISPLAY` abre.
- **`core/win_locale.py`:** `get_timezone_name` e `get_locale` ganham no topo `if not _plat_current().is_windows: return _plat_get(Cap.SESSION).<m>()`. **O ramo Windows fica literal.**

**Risco Windows:** baixo.

**Aceite:**
- N1: cada serviço falso → valor certo e unidade certa;
- sem serviço → `None` → `_is_away` fica igual a hoje;
- N-dono: modo ausente por ociosidade dispara depois de `AWAY_IDLE_MINUTES`.

**Testes:**
- qa, antes: C `tests/golden/test_session_windows.py` (`GetLastInputInfo`/`GetTickCount` com windll falso; exceção → 0.0; win_locale igual);
- qa: K `tests/unit/platform/test_session_linux.py`.

### F2-08 — Mídia (MPRIS)

**Onde:** `comandos/midia_ctrl.py`: `play_pause`, `parar`, `proxima_faixa`, `faixa_anterior`, `mutar`, `volume_up`, `volume_down` e `o_que_esta_tocando` (âncoras `_press_key(VK_` e `_get_media_info_ps`).

**Depois:**
- **`windows/media.py::VirtualKeyMedia`:**
  - `_press_key` e as constantes `VK_*` passam literais (via `_LazyUser32`);
  - `now_playing` = `_get_media_info_ps` literal;
  - `toggle_mute`/`volume_step` = teclas virtuais literais (`VK_VOLUME_MUTE`/`UP`/`DOWN` × passos).
- As funções do `midia_ctrl` chamam `get(Cap.MEDIA)`, e **as strings de retorno ficam idênticas**. O texto de `o_que_esta_tocando` é montado com o dict, com o mesmo formato de hoje.
- **`linux/media.py::MprisMedia`:**
  - `ListNames` filtrando `org.mpris.MediaPlayer2.*`;
  - escolhe o player com `PlaybackStatus == "Playing"`, senão `Paused`, senão o primeiro;
  - `org.mpris.MediaPlayer2.Player`: `PlayPause`/`Stop`/`Next`/`Previous`;
  - `Metadata` (`xesam:title`, `xesam:artist[0]`);
  - `toggle_mute`/`volume_step` delegam a `Cap.VOLUME`;
  - sem player → `CapabilityUnavailable("nenhum player MPRIS")`, e o `midia_ctrl` responde "Nenhum player de mídia ativo, Senhor.".
- **`PlayerctlMedia`:** `playerctl play-pause|stop|next|previous` e `playerctl metadata --format '{{title}}\t{{artist}}\t{{playerName}}\t{{status}}'`.

**Risco Windows:** baixo.

**Aceite:**
- N1: dois players falsos (um pausado e um tocando) → o comando vai para o que está tocando;
- N-dono: "próxima música" no Spotify/navegador funciona.

**Testes:**
- qa, antes: C `tests/golden/test_media_windows.py` (`keybd_event` falso com a mesma sequência down/up e códigos; PowerShell falso; mensagens);
- qa: K `tests/unit/platform/test_media_linux.py`.

### F2-09 — `processes.restart_self`

**Onde:** `main.py` `_fazer_restart` (âncora `creationflags=subprocess.CREATE_NEW_CONSOLE`).

**Depois:**
- `_fazer_restart`: `sleep(1.2)` → `_plat_processes().restart_self(main_path=os.path.abspath(__file__), frozen=getattr(sys, "frozen", False))` → `destroy` → `os._exit(0)`. O sleep, o destroy e o `os._exit` ficam **no `main.py`**.
- **`WindowsProcesses.restart_self`:** literal (frozen: `Popen([sys.executable])`; dev: bloco PowerShell/`Activate.ps1`/`CREATE_NEW_CONSOLE`).
- **`PosixProcesses.restart_self`:**
  - AppImage (`APPIMAGE` definido) → `[APPIMAGE] + sys.argv[1:]`;
  - frozen → `[sys.executable] + sys.argv[1:]`;
  - dev → `[sys.executable, main_path] + sys.argv[1:]`;
  - `cwd=dirname(main_path)`, `start_new_session=True`, `stdin=DEVNULL`;
  - **não** registrar como filho.

**Risco Windows:** baixo.

**Aceite:**
- N0: `Popen` falso recebe os argumentos acima;
- N2: `JARVIS_SMOKE_RESTART=1` → a 2ª instância imprime `JARVIS_SMOKE_READY` e o teste encerra as duas pelos PIDs registrados;
- N4/N-dono: "reinicie o Jarvis" funciona.

**Testes:**
- qa, antes: C `tests/golden/test_restart_windows.py` (literal: comando PowerShell idêntico e `creationflags == 0x10`; frozen → `[sys.executable]`);
- qa: K `tests/unit/platform/test_restart_posix.py`.

### F2-10a — `CREATE_NO_WINDOW` via `hidden_console_flags()`
- **Onde:** `main.py` (âncora `creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),` no ffplay), `comandos/games_ctrl.py:34`, `core/game_platform_detector.py:592` e `classifiers/modelo_local.py:110` (esse tem `os.name == "nt"`).
- **Depois:** `creationflags=_plat_processes().hidden_console_flags()`. No Windows o valor é o mesmo `CREATE_NO_WINDOW`. `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` do `browser_ctrl` ficam para a Fase 4.
- **Aceite:** o `tests/unit/test_windows_subprocess_flags.py` é atualizado para exigir a fachada nesses 4 lugares, e a allowlist C1 diminui.
- **Testes (executor, junto):** esse mesmo teste AST.

### F2-10b — `sounddevice` também com `ImportError`
- **Onde:** `main.py` (âncora `except OSError as _e_sd:`).
- **Depois:** `except (OSError, ImportError) as _e_sd:`, com a mesma mensagem.
- **Testes (executor, junto):** atualizar `tests/unit/test_main_sounddevice_guard.py`.

### F2-10c — Smoke encerra sem `os._exit` + smoke de áudio
- **Onde:** fim do `__main__` (âncora `JARVIS_SMOKE_EXIT children_alive=` e o `os._exit(0)` logo abaixo) e `_smoke_boot_finish`.
- **Depois:**
  1. Depois de `webview.start` retornar, no smoke:
     - imprime `EXIT` e `THREADS` como hoje;
     - chama `_plat_processes().shutdown_children(2.0)`;
     - arma `threading.Timer(10, _forcar)` com daemon, onde `_forcar` imprime `JARVIS_SMOKE_FORCED_EXIT threads=<não-daemon vivas>` e chama `os._exit(0)`;
     - termina com `sys.exit(0)` (o atexit roda).
  2. O executor identifica as threads não-daemon que sobram (Thread-29..32 no M1). Candidatas: o `threading.Timer` do `_RootProxy.after(ms>0)` (hoje não-daemon) e o uvicorn do dashboard. Correção:
     - Timers do `_RootProxy` com `daemon = True`, com nome `RootAfter`;
     - thread do dashboard nomeada;
     - **não** tornar daemon o que grava arquivo sem antes checar o que ela faz.

     Se precisar mudar outro arquivo, pede emenda.
  3. `JARVIS_SMOKE_AUDIO=1`: depois do ready, enfileira em `_audio_queue` um WAV de 0,3 s gerado com `numpy` (senoide) + `b""` de flush. Isso exercita o `ffplay` com `SDL_AUDIODRIVER=dummy` e verifica, via `alive_children()`, que o ffplay foi registrado.
  4. `PosixProcesses.shutdown_children` expõe o `_cleanup` atual; `WindowsProcesses.shutdown_children` é no-op.
- **Risco Windows:** nenhum no uso normal (tudo sob `_smoke_seconds()`, exceto os Timers do `_RootProxy` virarem daemon). Isso é **mudança intencional** baixa: um timer pendente não segura mais o processo no fechamento, e os `os._exit` do app já se comportam assim.
- **Aceite:**
  - N2/N3 com `JARVIS_SMOKE_AUDIO=1`: `children_alive=0` depois do shutdown, código 0, **sem** `FORCED_EXIT`;
  - `JARVIS_SMOKE_THREADS` vazio ou só com nomes justificados no relatório do qa.
- **Testes (executor, junto):** K AST `tests/unit/test_main_smoke_exit.py`; qa: `tests/smoke/test_audio_exit.py`.

---

## 5. F2-11 — Planejamento do `Cap.INPUT` (implementação na Fase 3)

**Contrato proposto:**
```python
class InputInjector(Protocol):
    name: str
    requires_consent: bool                         # portal RemoteDesktop pede autorização
    def hotkey(self, *keys: str) -> None: ...      # nomes pyautogui: "win","ctrl","tab","left"...
    def press(self, key: str, times: int = 1) -> None: ...
    def type_text(self, text: str) -> None: ...
    def paste_text(self, text: str) -> None: ...   # clipboard (Cap.CLIPBOARD) + ctrl+v, restaurando o clipboard
    def move_to(self, x: int, y: int) -> None: ...
    def click(self, button: str = "left") -> None: ...
    def screen_size(self) -> tuple[int, int]: ...
```

**Inventário (commit `31bc0ce`), vira a lista fechada da Fase 3:**
- `gesture_interface/desktop_control/controller.py`: `hotkey`, `press`, `moveTo`, `size`… (12+ chamadas sem checagem de `None`, conforme o revisor);
- `gesture_interface/main.py`;
- `comandos/msg_sender.py` (colar via pyperclip + pyautogui);
- `jarvis/messaging/pyautogui_sender.py`;
- `comandos/janela_ctrl.py`, `comandos/tool_registry.py`, `comandos/system_ctrl.py`;
- `main.py` ditado (`_get_kb_controller`, HWND `:11854/12059/12075/12204`);
- `main.py:6594/7106` `pyautogui.screenshot()` → vai para **`Cap.SCREEN_CAPTURE`**, não para input.

**Backends previstos:**

| Kind | Cadeia |
|---|---|
| win32 | pyautogui/pynput literal |
| linux-x11 | pynput Controller → `xdotool` |
| linux-wayland | **portal RemoteDesktop** (`NotifyKeyboardKeysym`/`NotifyPointerMotion`, pede consentimento; `persist_mode` para lembrar) → `ydotool` só se o dono ligar (fora do v1) → indisponível |

**Consequência para a Fase 2:** nenhuma. A feature `gestures` continua desligada no Linux e o portão da Fase 1 continua valendo. **Decisão D-F2-9** antes da SPEC da Fase 3.

## 6. Backlog visto nesta análise (fora da Fase 2)
- Os `os._exit(0)` do app (`_encerrar_de_tray`, `_RootProxy.destroy`, `:5622`) pulam o atexit (limpeza de filhos). Tratar na **versão unificada** com um `app_shutdown()` único.
- `updater` `_restart` monta `[sys.executable] + sys.argv[1:]` sem o `main.py` em dev (no Linux o portão bloqueia) → Fase 5.
- Fonte `consola.ttf` do ícone do tray é só do Windows (no Linux cai na fonte padrão; é cosmético).
- `core/win_locale.py` deveria ser renomeado para `core/locale_info.py` depois do merge (versão unificada).
- `browser_ctrl` `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` e os mapas de apps `notepad` → Fase 4.

---

## 7. Versão unificada: como fica o desenvolvimento depois do merge na `master`

### 7.1 Linha única
1. Você roda o **N4** (Fases 1 e 2) no Windows real e aprova. A `linux-port` entra na `master` (merge ou fast-forward, **decisão sua**), e a `master` passa a ser **a única linha**.
2. Trabalho novo sai em branches curtas, a partir da `master`, com um commit por tarefa e revisão antes do merge. Não existe mais "branch do Linux".
3. Uma **única** `VERSION`, e o mesmo tag gera o `.exe`/instalador do Windows e o AppImage do Linux (Fase 5).

### 7.2 Regras permanentes (valem para toda feature nova)

| # | Regra |
|---|---|
| U1 | **Feature escrita uma vez.** A lógica (voz, LLM, mensageria, documentos, UI) não conhece o SO. O que depende do SO é pedido a `jarvis.platform` (`get(Cap.X)`, `has_feature`). |
| U2 | **Código específico de SO só em `jarvis/platform/<windows|linux|linux_x11|linux_wayland|common>/`.** O teste C1 (allowlist de `sys.platform`/`os.name`/`ctypes.windll`/`winreg`/`os.startfile`) só pode **diminuir**; aumentar exige emenda do arquiteto. |
| U3 | **Toda capacidade nova nasce com os dois lados:** backend windows **e** cadeia linux, ou um lado declarado `Unavailable` com mensagem ao usuário e item de backlog com fase. Sem "funciona só no meu SO" silencioso. |
| U4 | **Testes nas duas plataformas:** N0 roda no Linux **e** no Windows; testes `windows_only`/`linux_only` só onde o SO real é indispensável; fakes (`fake_platform`, `fake_windll`, `fake_tools`, `private_session_bus`) para o resto. |
| U5 | **Golden vira regressão comum.** Depois do merge, os oráculos `legacy_*` continuam protegendo o comportamento. Mudar comportamento no Windows **ou** no Linux de propósito exige atualizar o golden no mesmo commit, marcado "mudança intencional", e passar pelo N4/N-dono. |
| U6 | **Dependências num `requirements.txt` só, com marcadores**, e Python 3.12 nos dois SOs. Recomendado: lock por plataforma gerado com `uv pip compile` (`requirements-lock-win.txt` e `requirements-lock-linux.txt`, D-F2-7b). |
| U7 | **W6 permanente:** módulo carregado por string entra no `JARVIS.spec`/`launcher.py` (e no spec do AppImage na Fase 5), com o teste estático. |
| U8 | **Scripts de dev multiplataforma:** `tools/dev.py` (run, test, lint, build) substitui a dependência de `dev.ps1`/`build-fast.ps1`. Os `.ps1` ficam como atalhos finos para o Windows. |
| U9 | **Definição de pronto de qualquer PR:** N0 verde em Windows e Linux; N1–N3 verdes nos containers; C1/W6 verdes; se tocou `jarvis/platform/windows` ou comportamento visível no Windows, checklist N4 marcado. |

### 7.3 O que precisa existir (e de quem depende)

| Item | O que é | Depende de |
|---|---|---|
| **CI em nuvem** | GitHub Actions: `windows-latest` + Python 3.12 → N0 + `windows_only`; `ubuntu-latest` → N0; jobs em container `fedora44`/`debian12`/`ubuntu2404`/`arch` → N1; Xvfb → N2; imagem com `kwin_wayland --virtual` + `dbus-run-session` → N3 (pode rodar só noturno, por ser pesado) | **D-F2-7a: remoto + push + minutos de Actions (decisão sua; não executar)** |
| **CI local (sem push)** | `tools/ci_local.sh` (podman: N0–N3 na matriz) e `tools/ci_windows.ps1` (N0 + `windows_only` na sua máquina Windows). É o que dá para ter **já** | qa (Fase 2/3) |
| **Máquina Windows de teste** | Hoje só a sua. Opcional: VM Windows ou runner self-hosted **isolado** (nunca no desktop pessoal) | D-F2-7c |
| **Rebaseline do golden** | Depois do merge, `legacy_31bc0ce.py` é congelado como regressão (U5) | qa |
| **Checklist N-dono Linux** | Portal, tray, notificações, volume, clipboard, mídia, restart: roteiro de 10 min na sessão real | qa escreve, você roda |

## 8. Decisões que precisam do dono

| ID | Decisão | Recomendação do arquiteto |
|---|---|---|
| **D-F2-1** | **Gatilho padrão do PTT global no Linux.** No portal/KGlobalAccel o atalho é **exclusivo**: `Shift+G` global impediria digitar "G" maiúsculo em qualquer app. O pynput do Windows e do X11 é passivo e não tem esse problema. | `Meta+Shift+G` no Linux (`config.PTT_TRIGGER_GLOBAL`), mantendo `Shift+G` passivo no Windows e no X11. O usuário pode trocar no diálogo do KDE. |
| **D-F2-2** | **App ID** (reverse-DNS), usado pelo portal, pelas notificações, pelo `.desktop` e pelo AppImage. | `io.github.ninjazins2.Jarvis` (não muda depois sem perder os atalhos já vinculados). |
| **D-F2-3** | **Gravar automaticamente** `~/.local/share/applications/<APP_ID>.desktop` (`NoDisplay=true`) em dev, necessário para o portal identificar o app. | Sim, idempotente e só no `XDG_DATA_HOME` do usuário. |
| **D-F2-4** | **Dependência nova `jeepney`** (D-Bus pure Python, só no Linux). Alternativas: QtDBus (preso à thread da GUI) e dbus-python (extensão C, compila). | `jeepney`. |
| **D-F2-5** | **Notificação no Windows** (paridade da versão unificada): implementar agora (toast via WinRT/`winotify`, comportamento novo no Windows) ou manter indisponível até depois do N4. | Depois do N4, como primeira tarefa da versão unificada. |
| **D-F2-6** | **Validação N-dono** na sessão real do Plasma (diálogo do portal, PTT, tray, notificações, volume, clipboard), que os agentes são proibidos de fazer. | Sim, 10 min pelo checklist do qa, antes do M2. |
| **D-F2-7a** | **CI em nuvem:** criar/usar remoto, dar push e usar minutos do GitHub Actions. | Repositório privado + Actions com N3 noturno; até lá, CI local. |
| **D-F2-7b** | **Lock de dependências** por plataforma (`uv pip compile`). | Sim. |
| **D-F2-7c** | **Windows de teste** além da sua máquina (VM ou runner self-hosted isolado). | VM descartável, só se o Actions não for aprovado. |
| **D-F2-7d** | **Estratégia do merge** `linux-port` → `master` depois do N4 (merge commit ou fast-forward) e se a `master` antiga (`ec30af2`) ganha tag de arquivo. | Merge commit + tag `v2.7.0-windows-legacy` em `ec30af2`. |
| **D-F2-8** | **Monitor de clipboard indisponível** no GNOME/Wayland e no KDE com wl-clipboard < 2.3.0 sem Klipper: aceitar (feature desligada, com mensagem). | Aceitar. |
| **D-F2-9** | **Injeção de input no Wayland (Fase 3):** portal RemoteDesktop (diálogo de consentimento) como padrão, e `ydotool` só como opção que você liga. | Portal RemoteDesktop. |
| **D-F2-10** | **Volume/mute no Windows via COM** (`IAudioEndpointVolume`) em vez das teclas virtuais, para o mesmo caminho nos dois SOs (F2-03/F2-08). | Não agora: manter as teclas virtuais no Windows até depois do N4. |
