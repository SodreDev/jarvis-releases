# SPEC — Fase 1: o J.A.R.V.I.S abre no Fedora sem crash

| | |
|---|---|
| **Autor** | arquiteto · 2026-09-13 |
| **Base** | branch `linux-port`, commit `1c32e38`. Os números de linha são desse commit e **mudam a cada commit**: localize pelo **trecho-âncora** citado. |
| **Arquitetura** | [ADR-001](ADR-001-camada-plataforma.md), **aprovado (opção B)**. |
| **Já feito pelo executor** | `5c55322` (flags de subprocess via `getattr` + `tests/unit/test_windows_subprocess_flags.py`) · `df9b245` (`janela_ctrl` com winreg lazy; `midia_ctrl`/`notif_ctrl` com proxy `_LazyUser32`). |
| **Em andamento** | F1-11 (faulthandler), em `core/crash_log.py`. |
| **Fila** | [FILA-fase1-executor.md](FILA-fase1-executor.md) |

---

## 0. Escopo e definição de pronto

**Objetivo:** `python main.py` (Python 3.12, `.venv-linux`) abre a janela principal no Fedora 44, em Wayland e em X11, sem crash e sem regressão no Windows.

**Fora do escopo:** hotkeys via portal (Fase 2, decisão do dono), tray/volume/clipboard/notificações no Linux (Fase 2), captura/janelas/input (Fase 3), gestos e leitura de notificações (Fase 4), AppImage (Fase 5).

**Marco M1 — "abre":** nos níveis N2 (X11) e N3 (Wayland virtual), com `JARVIS_SMOKE_SECONDS=8`:
- o stdout contém `JARVIS_SMOKE_READY kind=linux-x11` (ou `kind=linux-wayland`);
- `window.JARVIS_READY` é verdadeiro;
- o processo sai com código 0 em ≤ 90 s;
- o `crash.log` não tem entrada nova;
- o `crash_native.log` fica em ≤ 5 MB;
- a última linha é `JARVIS_SMOKE_EXIT children_alive=0`.

**Marco M2 — "Fase 1 pronta":**
- M1 passa 3 vezes seguidas;
- N0 e N1 verdes;
- `JARVIS_SMOKE_RELOADS=10` roda sem erro de `reload_ui`;
- o diff de produção toca **só** arquivos da lista fechada (§3);
- o revisor aprovou.

O N4 (Windows real) fica **com o dono, antes de qualquer merge na `master`**, e **não bloqueia** as fases.

## 1. Níveis de teste e ambientes

| Nível | Onde | O que roda | Seleção |
|---|---|---|---|
| **N0** | host, `.venv-linux` (uv, Python 3.12, só deps de teste) | unit, AST e golden | `pytest -m "not slow and not needs_display and not windows_only"` |
| **N1** | podman `fedora:44` e `debian:stable-slim` (`archlinux:latest` opcional), requirements completos (torch pelo índice CPU) | N0 + imports reais + resolução de requirements | `pytest -m "not needs_display and not windows_only"` |
| **N2** | container `fedora:44` + Xvfb (`XDG_SESSION_TYPE=x11`) | smoke boot X11 | `pytest -m x11` |
| **N3** | container `fedora:44` ligado ao socket de um `kwin_wayland --virtual --xwayland` do host | smoke boot Wayland | `pytest -m wayland` |
| **N4** | Windows real, a cargo do dono | `pytest -m "not linux_only and not x11 and not wayland"` + checklist manual (§4, F1-11 a F1-14) | — |

**Regras de segurança dos testes (obrigatórias, vêm da memória "Ambiente de teste do port Linux"):**
- Os testes de smoke **pulam** se `JARVIS_TEST_SANDBOXED != "1"`. Só o entrypoint do container define essa variável.
- Nada de `WAYLAND_DISPLAY`/`DISPLAY`/PipeWire/D-Bus da sessão do dono. O container não recebe `/dev/snd` nem o socket do PipeWire. Usar `SDL_AUDIODRIVER=dummy`, `LIBGL_ALWAYS_SOFTWARE=1` e `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`.
- O código entra por `git archive linux-port` numa **cópia gravável** (só arquivos versionados, sem segredos). O `_data()` grava logs na raiz da cópia.
- Encerrar **só PIDs registrados** pelo próprio teste. Nunca usar `pkill`, `killall` nem `pgrep -f`.
- Esboço N3 (o qa confere as flags com `kwin_wayland --help`):
  ```
  kwin_wayland --virtual --xwayland --socket jarvis-test-0 --width 1400 --height 900 &  # guardar $! e encerrar só esse PID
  podman run --rm --userns=keep-id --security-opt label=disable \
    -v "$XDG_RUNTIME_DIR/jarvis-test-0:/run/jt/jarvis-test-0" -e XDG_RUNTIME_DIR=/run/jt \
    -e WAYLAND_DISPLAY=jarvis-test-0 -e XDG_SESSION_TYPE=wayland \
    -e JARVIS_TEST_SANDBOXED=1 jarvis-fedora44 pytest -m wayland tests/smoke
  ```

## 2. Convenções de teste

- **Nunca importar `main.py` em teste.** O import grava logs na raiz, move arquivos para a pasta de credenciais e carrega libs pesadas. Para o `main.py`, use **testes AST** no estilo do `tests/unit/test_windows_subprocess_flags.py` que já existe.
- **Oráculos:** `tests/golden/legacy_1c32e38.py` guarda uma cópia **literal** dos trechos de `1c32e38`, embrulhados em funções que recebem fakes. O executor **nunca** edita `tests/golden/`.
- **Tipos de teste:**
  - **C, caracterização:** passa antes e depois da mudança. É o que prova que o Windows não mudou.
  - **K, contrato:** entra como `@pytest.mark.xfail(strict=True, reason="F1-xx")` e o commit do executor remove o `xfail`.
- **Windows sem Windows:**
  - usar `fake_platform("win32")`;
  - `monkeypatch.setitem(sys.modules, "winreg", fake)`;
  - `monkeypatch.setattr(ctypes, "WinDLL", fake, raising=False)`;
  - se `ctypes.wintypes` não importar no Linux, usar o stub `SimpleNamespace(DWORD=c_ulong, HANDLE=c_void_p, BOOL=c_long, LPCWSTR=c_wchar_p)`.
- **Pastas:**
  - `tests/unit/` (unit e AST) e `tests/unit/platform/`: qa;
  - `tests/golden/`: qa;
  - `tests/smoke/`: qa;
  - `tests/tools/`: tools-lab.

## 3. Lista fechada

| ID | Mudança | Arquivos de produção | Risco Windows | Estado |
|---|---|---|---|---|
| F1-01 | Esqueleto `jarvis/platform/` | `jarvis/platform/**` (novo), `JARVIS.spec`, `launcher.py` | nenhum | a fazer |
| F1-02 | Paths: adapter windows + XDG | `jarvis/platform/{windows,linux}/paths.py`, `jarvis/platform/linux/xdg.py`, `jarvis/config/paths.py` | baixo | a fazer |
| F1-03 | `requirements.txt` com marcadores e pins | `requirements.txt` | baixo | a fazer |
| F1-04 | `pynput` protegido + portão de hotkeys | `main.py` | baixo | a fazer |
| F1-05 | `sounddevice` protegido (sem PortAudio) | `main.py` | nenhum | a fazer |
| F1-06 | pywebview Qt/PySide6 + sandbox automático | `main.py`, `jarvis/platform/{windows,linux}/webview_engine.py` | baixo | a fazer |
| F1-07 | `storage_path` da webview via paths | `main.py` | baixo | a fazer |
| F1-08 | `CREATE_NO_WINDOW` do ffplay | `main.py`, `comandos/browser_ctrl.py` | nenhum | **FEITO `5c55322`** |
| F1-09 | Portões Windows-only no boot + `pyautogui` dos gestos | `main.py`, `gesture_interface/main.py`, `gesture_interface/desktop_control/controller.py` | baixo | a fazer |
| F1-10 | Gancho de smoke boot | `main.py` | nenhum | a fazer |
| F1-11 | faulthandler com rotação | `core/crash_log.py`, `main.py` | baixo (intencional) | **EM ANDAMENTO** + ajuste F1-11b |
| F1-12 | Causa raiz Windows: protótipos ctypes do clipboard | `comandos/clipboard_hist_ctrl.py` | baixo/médio (intencional) | a fazer |
| F1-13 | Corrida do `reload_ui` | `main.py`, `jarvis/webui/{__init__,reload_guard}.py` | baixo (intencional) | a fazer |
| F1-14 | Job Object → adapter windows; limpeza de filhos no Linux | `main.py`, `jarvis/platform/{windows,linux}/processes.py` | médio | a fazer |
| F1-15 | winreg do PATH → adapter windows | `main.py`, `jarvis/platform/windows/env.py` | baixo | a fazer |

Já aceitos fora da lista: `df9b245` (`comandos/janela_ctrl.py`, `comandos/midia_ctrl.py`, `comandos/notif_ctrl.py`). **Qualquer outro arquivo de produção** só entra com emenda do arquiteto, por exemplo quando o smoke revelar um crash novo. W6 (hiddenimports no `JARVIS.spec` e no `launcher.py`) vale para toda tarefa que criar módulo novo.

---

## 4. Mudanças detalhadas

### F1-01 — Esqueleto `jarvis/platform/`
- **Depois:** implementar o ADR §5–§9 de forma normativa:
  - `detect.py`, `capabilities.py`, `features.py`, `registry.py`, `protocols.py` (Paths, Processes, WebviewEngine), `errors.py`, `common/base.py` e `common/unavailable.py`;
  - o `REGISTRY` só com `PATHS`, `PROCESSES` e `WEBVIEW_ENGINE`;
  - pacotes `windows/`, `linux/`, `linux_x11/` e `linux_wayland/` vazios;
  - `features_for("linux-wayland")` é vazio na Fase 1: o portal de hotkeys entra na Fase 2.
- **Risco Windows:** nenhum. Nada no app importa o pacote ainda.
- **Aceite:**
  - a detecção segue a tabela abaixo;
  - `features_for(win32, {}) == ALL_FEATURES`;
  - importar a camada não carrega libs de GUI;
  - `report()` é serializável em JSON.
- **Testes (qa, antes da mudança):**
  - K `tests/unit/platform/test_detect.py`, parametrizado:

    | sys.platform | ambiente | kind / source |
    |---|---|---|
    | win32 | {} | win32 / os |
    | linux | XDG_SESSION_TYPE=wayland, WAYLAND_DISPLAY=wayland-0, DISPLAY=:0 | linux-wayland / xdg_session, `xwayland=True` |
    | linux | XDG_SESSION_TYPE=x11, DISPLAY=:0 | linux-x11 / xdg_session |
    | linux | só WAYLAND_DISPLAY | linux-wayland / wayland_display |
    | linux | só DISPLAY=:99 | linux-x11 / display |
    | linux | {} ou XDG_SESSION_TYPE=tty | linux-headless / fallback |
    | linux | QT_QPA_PLATFORM=xcb + ambiente wayland | linux-x11 / qt_qpa |
    | linux | QT_QPA_PLATFORM=offscreen | linux-headless / qt_qpa |
    | linux | JARVIS_PLATFORM=linux-x11 + ambiente wayland | linux-x11 / override |
    | linux | JARVIS_PLATFORM=lixo + DISPLAY | linux-x11 / display (com aviso) |
    | darwin | {} | unsupported |
    | linux | XDG_CURRENT_DESKTOP=ubuntu:GNOME | desktops=("ubuntu","gnome") |

  - K `test_features.py`:
    - win32 == ALL;
    - x11 == {global_hotkeys};
    - wayland e headless == ∅;
    - `JARVIS_FEATURES="+tray,-global_hotkeys"`;
    - nome desconhecido é ignorado.
  - K `test_registry.py`, com módulos falsos em `sys.modules`:
    - ordem da cadeia;
    - falha de import e `probe` negativo;
    - cache (1 import só);
    - 10 threads recebem a mesma instância;
    - `Unavailable` levanta `CapabilityUnavailable`;
    - `refresh()`;
    - curinga `linux-*`.
  - K `test_import_hygiene.py`: em subprocess, `import jarvis.platform as p; p.current(); p.report()` não põe `pynput`, `webview`, `qtpy`, `PySide6`, `pyautogui`, `pystray` nem `sounddevice` em `sys.modules`.
  - K `tests/unit/test_pyinstaller_hiddenimports.py` (W6): todo módulo `win32` do `REGISTRY` aparece na lista `hidden` do `JARVIS.spec` e no bloco `if False:` do `launcher.py`.
  - C `tests/unit/test_platform_checks_allowlist.py` (ADR C1): as ocorrências de `sys.platform`, `os.name` e `ctypes.windll` fora de `jarvis/platform/` cabem na allowlist congelada no HEAD em que o teste entrar.

### F1-02 — Paths: adapter windows + XDG
- **Onde:** `jarvis/config/paths.py:13-18` (`_appdata_root`) e as funções `user_config_dir`, `user_data_dir`, `credentials_dir` e `logs_dir`.
- **Antes:** `if os.name == "nt": APPDATA/JARVIS` e, fora do Windows, `XDG_CONFIG_HOME/jarvis` para tudo.
- **Depois:** o `paths.py` mantém a API pública e delega a `jarvis.platform.paths()`.
  - `WindowsPaths` reproduz as expressões literais:
    - `Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")) / "JARVIS"`;
    - subpastas `data`, pasta de credenciais e `logs`, com o mesmo `mkdir(parents=True, exist_ok=True)`.
  - `XdgPaths`:
    - config → `$XDG_CONFIG_HOME/jarvis`;
    - dados → `$XDG_DATA_HOME/jarvis`;
    - pasta de credenciais → `$XDG_CONFIG_HOME/jarvis/<pasta de credenciais>`;
    - logs → `$XDG_STATE_HOME/jarvis/logs`;
    - cache → `$XDG_CACHE_HOME/jarvis`;
    - `webview_storage_dir()` → `$XDG_DATA_HOME/jarvis/webview_data`.
  - Regras XDG:
    - variável vazia ou **relativa** é ignorada e vale o padrão (`~/.config`, `~/.local/share`, `~/.local/state`, `~/.cache`);
    - os níveis `jarvis/...` que forem criados ganham modo `0700`;
    - as pastas-base XDG existentes não são alteradas.
  - `project_root`, `browser_profiles_dir`, `dev_config_override` e `model_dir` ficam **inalterados**.
- **Risco Windows:** baixo (W1 literal). Atenção: o `paths.py` usa `or` (APPDATA vazio vira o fallback), enquanto a expressão da webview no `main.py` usa `.get(..., default)` (APPDATA vazio continua vazio). **As duas semânticas são preservadas.**
- **Aceite:**
  - golden idêntico;
  - no Linux, nenhum dado ou log vai para `XDG_CONFIG_HOME`;
  - valor XDG relativo é ignorado;
  - pastas criadas com `0700`.
- **Testes (qa):**
  - C `tests/golden/test_paths_windows.py`: oráculo `_appdata_root` com `os.name` forçado para `"nt"` × `WindowsPaths`, com APPDATA definido, ausente e vazio, e as quatro funções;
  - K `tests/unit/platform/test_paths_xdg.py` (`isolated_home`): padrões sem `XDG_*`, variável relativa ignorada, permissões `0700` e `webview_storage_dir`.

### F1-03 — `requirements.txt` com marcadores e pins
- **Antes → depois:**
  ```
  pywin32        → pywin32; sys_platform == "win32"
  pycaw          → pycaw; sys_platform == "win32"
  uiautomation   → uiautomation; sys_platform == "win32"
  pygetwindow    → pygetwindow; sys_platform == "win32"
  pystray        → pystray; sys_platform == "win32"          # tray Linux = SNI na Fase 2
  pywebview      → pywebview==6.1                            # versão do venv Windows atual
  (novo)         → PySide6==6.9.3; sys_platform == "linux"   # decisão do dono: última wheel manylinux_2_28
  (novo)         → QtPy>=2.4,<3; sys_platform == "linux"
  ```
  Cabeçalho: "Python 3.12 obrigatório (kokoro exige <3.13)". Nota para o container: no Linux o `pynput` puxa `evdev`, que pode compilar (gcc, python3-devel e kernel-headers).
- **Risco Windows:** baixo. Só fixa o pywebview na versão já instalada.
- **Aceite:**
  - todas as linhas parseiam com `packaging`;
  - o conjunto de nomes para win32 é **idêntico** ao de `1c32e38`;
  - o conjunto para linux é o de `1c32e38` − {pywin32, pycaw, uiautomation, pygetwindow, pystray} + {PySide6, QtPy};
  - resolve para Windows e para `manylinux_2_28`.
- **Testes (qa):**
  - C+K `tests/unit/test_requirements_markers.py` (N0), comparando com `tests/golden/requirements_1c32e38.txt`;
  - slow `tests/unit/test_requirements_resolve.py` (N1, rede): `uv pip compile --python-version 3.12 --python-platform x86_64-pc-windows-msvc` (a diferença para o compile do baseline só pode estar no pywebview) e `--python-platform x86_64-manylinux_2_28` (precisa resolver).

### F1-04 — `pynput` protegido + portão de hotkeys
- **Onde:** `main.py:137-138`, `:186`, `_start_keyboard_listener` (`:11600`) e `_start_global_hotkeys` (`:11615`).
- **Antes:**
  ```python
  from pynput import keyboard
  from pynput.keyboard import Key, GlobalHotKeys
  ...
  _SHIFT_KEYS = {Key.shift, Key.shift_r, Key.shift_l}
  ```
- **Depois:**
  ```python
  try:
      from pynput import keyboard
      from pynput.keyboard import Key, GlobalHotKeys
  except Exception as _e_pynput:          # Linux sem X (headless) / backend indisponível
      keyboard = Key = GlobalHotKeys = None
      print(f"[HOTKEYS] pynput indisponível: {_e_pynput}")
  from jarvis.platform import has_feature as _has_feature
  ...
  _SHIFT_KEYS = {Key.shift, Key.shift_r, Key.shift_l} if Key is not None else set()
  ```
  No começo dos dois métodos:
  ```python
  if keyboard is None or not _has_feature("global_hotkeys"):
      print("[PTT] Atalho global indisponível nesta sessão — use o botão de microfone ou a wake word.")
      return
  ```
  Em `_start_keyboard_listener`, antes do `return`, definir `self._listener = None`. Os usos lazy em `:11992/12011/12059` ficam como estão.
- **Risco Windows:** baixo. Nomes idênticos e portão verdadeiro.
- **Aceite:**
  - N3: nenhum listener criado e a mensagem aparece uma vez;
  - N2: listener criado;
  - sem `DISPLAY`, o import do `pynput` falha e o app não quebra.
- **Testes:**
  - K `tests/unit/test_main_pynput_guard.py` (qa, AST): imports dentro de `Try` com `except` que zera os três nomes; `_SHIFT_KEYS` tolera `None`; os dois métodos testam `_has_feature("global_hotkeys")` antes de `keyboard.Listener(` e de `GlobalHotKeys(`;
  - N1 `tests/smoke/test_imports.py`: `import pynput` sem `DISPLAY` levanta `ImportError`, o que documenta por que o guard existe.

### F1-05 — `sounddevice` protegido
- **Onde:** `main.py:132` e os métodos que usam `sd.`: `:10700`, `:11277` (`_wake_word_loop`), `:11863` (`_gravar_audio`) e `:12342`.
- **Depois:**
  ```python
  try:
      import sounddevice as sd
  except OSError as _e_sd:                # PortAudio ausente
      sd = None
      print(f"[AUDIO] sounddevice indisponível: {_e_sd} — instale PortAudio "
            "(dnf install portaudio | pacman -S portaudio | apt install libportaudio2)")
  ```
  Em cada método que usa `sd.`, logo no início: `if sd is None: self._set_status("Microfone indisponível: PortAudio não instalado", _TEXT_DIM); return` (ou lista vazia na listagem de dispositivos). Só `OSError`: pacote ausente continua falhando alto, como hoje.
- **Risco Windows:** nenhum. A wheel do Windows traz a DLL do PortAudio.
- **Aceite:** num container **sem** `portaudio` a janela abre e a mensagem aparece; **com** `portaudio`, os dispositivos são listados.
- **Testes:**
  - K `tests/unit/test_main_sounddevice_guard.py` (qa, AST): import em `Try/except OSError` e todo método com `sd.` tem guarda `sd is None` antes do primeiro uso;
  - N1: import real com e sem o pacote `portaudio`.

### F1-06 — pywebview com Qt/PySide6 + sandbox automático
- **Onde:** logo antes de `import webview` (`main.py:26`) e em `webview.start(...)` (`:13532`).
- **Depois (`main.py`):**
  ```python
  _wv_start_kwargs: dict = {}
  try:
      from jarvis.platform import webview_engine as _webview_engine
      _eng = _webview_engine()
      _eng.prepare_env(os.environ)        # Windows: não faz nada
      _wv_start_kwargs = _eng.start_kwargs()   # Windows: {}
  except Exception as _e_plat:
      print(f"[PLATAFORMA] preparação da webview falhou: {_e_plat}")

  import webview
  ...
  webview.start(_on_ready, debug=os.environ.get("JARVIS_DEV") == "1",
                storage_path=_wv_data, **_wv_start_kwargs)
  ```
  No `except` do boot (`_write_crash("BOOT", ...)`), no Linux, imprimir também: "Qt WebEngine indisponível: use Python 3.12 e `pip install -r requirements.txt`".
- **`EdgeChromiumEngine`:** `prepare_env` não mexe em nada, `start_kwargs() == {}` e `sandbox_state() == "n/a"`. O `WEBVIEW2_ADDITIONAL_FLAGS` continua onde está no `main.py`.
- **`QtWebEngine.prepare_env(environ)`:**
  - `setdefault("QT_API", "pyside6")` e `setdefault("PYWEBVIEW_GUI", "qt")`;
  - `QT_QPA_PLATFORM`: `setdefault` com `"wayland;xcb"` (wayland) ou `"xcb"` (x11), nada no headless;
  - aplica `decide_sandbox()`: se o sandbox ficar desligado, `environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"`;
  - loga `[WEBENGINE] backend=qt/pyside6 qpa=<valor> sandbox=<estado>`;
  - `start_kwargs() == {"gui": "qt"}`.
- **`decide_sandbox(environ, *, read_sysctl, run_probe, euid, os_release_id)`**, com funções injetáveis e nesta ordem:
  1. `JARVIS_WEBENGINE_SANDBOX` = `on`/`off` manda. `auto`/ausente segue. Valor inválido gera aviso e segue como `auto`.
  2. `QTWEBENGINE_DISABLE_SANDBOX=1` ou `--no-sandbox` em `QTWEBENGINE_CHROMIUM_FLAGS` → off ("ambiente").
  3. euid 0 → off ("root").
  4. `ID` do os-release ∈ {arch, manjaro, nixos, rhel, pop} → off: "forçado pelo pywebview" (**decisão do dono: aceito no v1, reportado em `sandbox_state()`**).
  5. `kernel.unprivileged_userns_clone == 0` ou `user.max_user_namespaces == 0` → off.
  6. Existe `unshare`: rodar `unshare --user --map-root-user true` (timeout 3 s). Código 0 → on; senão off com a 1ª linha do stderr. Não existe `unshare`: `kernel.apparmor_restrict_unprivileged_userns == 1` → off; caso contrário → on.
- **Risco Windows:** baixo. `**{}` deixa a chamada idêntica, e falha no bootstrap só gera `print`.
- **Aceite:**
  - N2/N3 abrem com backend Qt e o log mostra o estado do sandbox;
  - `import webview` sozinho não importa `qtpy` (N1);
  - no Fedora (container), a decisão vem da sonda.
- **Testes:**
  - K `tests/unit/platform/test_webview_engine.py` (qa): uma linha por passo do `decide_sandbox`, usando fakes; `prepare_env` não sobrescreve variável já definida; `start_kwargs` linux == `{"gui": "qt"}`;
  - C `tests/golden/test_webview_windows.py`: `EdgeChromiumEngine.prepare_env` deixa o environ igual e `start_kwargs() == {}`;
  - K `tests/unit/test_main_webview_bootstrap.py` (AST): o bootstrap vem antes de `import webview`; `webview.start` recebe `**_wv_start_kwargs`; os demais argumentos são iguais aos de `1c32e38`;
  - N1 `tests/smoke/test_imports.py`: depois de `import webview`, `"qtpy" not in sys.modules`.

### F1-07 — `storage_path` da webview via paths
- **Onde:** `main.py:2622-2626` (`JarvisApp.__init__`) e `:13519-13523` (`__main__`).
- **Antes:** `os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "JARVIS", "webview_data")`.
- **Depois:** `_wv_storage = _plat_paths().webview_storage_dir()` (e o mesmo para `_wv_data`), mantendo o `os.makedirs(..., exist_ok=True)`. `WindowsPaths.webview_storage_dir()` usa **`ntpath.join`/`ntpath.expanduser`** com a mesma expressão (no Windows, `ntpath` é o `os.path`). `XdgPaths` cria `$XDG_DATA_HOME/jarvis/webview_data` com `0700`. Não mexer em `private_mode`.
- **Risco Windows:** baixo.
- **Aceite:** `main.py` sem `os.environ.get("APPDATA"`, e nada é criado em `~/JARVIS` no Linux.
- **Testes:**
  - C `tests/golden/test_paths_windows.py`: oráculo (`ntpath`) × `webview_storage_dir()` com APPDATA definido, ausente e vazio;
  - K AST em `tests/unit/test_main_webview_bootstrap.py`.

### F1-08 — `CREATE_NO_WINDOW` do ffplay — **FEITO em `5c55322`**
Usa o idioma `getattr(subprocess, "CREATE_NO_WINDOW", 0)` em `main.py:12726` e em `comandos/browser_ctrl.py`, com o teste AST `tests/unit/test_windows_subprocess_flags.py`. Aceito como está: `Processes.hidden_console_flags()` fica para call sites novos. O registro do processo do ffplay para limpeza entra na **F1-14**. Se o `5c55322` não cobriu `main.py:6449` (`CREATE_NEW_CONSOLE` no restart em dev), isso vai para o backlog da F2 (§5).

### F1-09 — Portões Windows-only no boot + `pyautogui` dos gestos
- **Onde e depois:**
  - `main.py:13141` → `if _has_feature("tray"): self._criar_tray_icon()`. Sem tray, o X fecha o app (é o fallback de hoje quando falta o pystray).
  - `main.py:13143` → `if _has_feature("self_update_payload"): self._iniciar_verificador_updates()`. **No Linux, o updater aplicaria o payload do Windows por cima da árvore.**
  - `JarvisApi.apply_update_now` (`:1902`), 1ª linha: `if not _has_feature("self_update_payload"): return {"ok": False, "error": "Atualização automática ainda não disponível nesta plataforma."}`.
  - `main.py:2784` → a thread de `_iniciar_monitor_notif` só sobe com `_has_feature("notification_reader")`. O `df9b245` já tornou o import seguro; o portão evita subir um monitor que falharia nas chamadas.
  - `main.py:2792-2797` → o bloco do `clipboard_hist_ctrl.start_monitor()` sob `_has_feature("clipboard_monitor")`, para evitar o loop que engole `AttributeError` a cada 0,8 s.
  - `_ativar_gesture` (`:6943`), `_ativar_eye_control` (`:7016`) e `_calibrar_olhos` (`:7044`), 1ª linha: `if not _has_feature("gestures"): self.root.after(0, self._exibir_resposta, "Interface gestual ainda não disponível nesta plataforma."); return`.
  - `gesture_interface/main.py:25` e `gesture_interface/desktop_control/controller.py:19` → `try: import pyautogui` / `except Exception: pyautogui = None`. Em `controller.py:30` → `if pyautogui is not None: pyautogui.FAILSAFE = False`.
- **Risco Windows:** baixo. Todos os portões são verdadeiros (W4), e o import do `pyautogui` fica idêntico quando existe.
- **Aceite:**
  - N2/N3 sem entradas `THREAD:` no `crash.log` vindas de notificações, clipboard, tray ou updater;
  - nenhum download de update no Linux;
  - "ativar gestos" responde com a mensagem.
- **Testes:**
  - K `tests/unit/test_main_feature_gates.py` (qa, AST): cada call site acima está sob o portão certo, e `apply_update_now` e os três métodos de gestos começam pelo portão;
  - K `tests/tools/test_gesture_imports.py` (tools-lab): `pyautogui` dentro de `Try` nos dois arquivos; `import gesture_interface.desktop_control.controller` funciona com `sys.modules["pyautogui"] = None`.

### F1-10 — Gancho de smoke boot
- **Depois (`main.py`):** helper único no nível do módulo.
  ```python
  def _smoke_seconds() -> float | None:
      v = os.environ.get("JARVIS_SMOKE_SECONDS", "").strip()
      try:
          return float(v) if v else None
      except ValueError:
          return None
  ```
  Efeitos só quando o helper não devolve `None`:
  - (a) em `__main__`, não sobe a thread `PlaywrightChromiumCheck` (sem rede);
  - (b) em `_on_webview_ready`, pula a restauração do modo wake (`:13126`, não abre microfone) e o verificador de updates;
  - (c) no fim de `_on_webview_ready`, imprime `JARVIS_SMOKE_READY kind=<ctx.kind> qpa=<QT_QPA_PLATFORM|n/a> sandbox=<estado>`. Se `JARVIS_SMOKE_RELOADS=N` estiver definido, dispara N vezes `evaluate_js("window.dispatchEvent(new KeyboardEvent('keydown',{key:'F5'}))")`, com 300 ms entre elas e esperando `JARVIS_READY` voltar. Depois agenda `threading.Timer(segundos, self._window.destroy)`;
  - (d) quando `webview.start` retorna, imprime `JARVIS_SMOKE_EXIT children_alive=<len(processes().alive_children())>`.
- **Risco Windows:** nenhum sem a variável.
- **Aceite:** M1.
- **Testes:**
  - K `tests/unit/test_main_smoke_hook.py` (qa, AST): toda leitura de `JARVIS_SMOKE_*` passa pelo helper, e cada efeito fica dentro de `if`;
  - qa `tests/smoke/test_boot_x11.py` (markers `linux_only`, `x11`, `needs_display`, `slow`);
  - qa `tests/smoke/test_boot_wayland.py` (markers `linux_only`, `wayland`, `needs_display`, `slow`);
  - qa `tests/smoke/test_reload_ui_qt.py` (`JARVIS_SMOKE_RELOADS=10`).

### F1-11 — faulthandler — **EM ANDAMENTO** (executor: `core/crash_log.py`)
- **Aceito:** `setup_native_crash_log(path, max_bytes=5_000_000)` com rotação para `.1` e `enable()` mantido para crash fatal. O módulo fica em `core/` (é diferente do `jarvis/diagnostics/` que eu tinha esboçado; não precisa mover).
- **Causa (evidência, para não corrigir a coisa errada):**
  - o log tem 45.788 dumps `Windows fatal exception: access violation` em 150 sessões;
  - o 1º stack está em `comandos/clipboard_hist_ctrl.py:30` (`ctypes.wstring_at`, no polling de 0,8 s);
  - no Windows o `faulthandler.enable()` instala também um **handler vetorizado de exceções** e despeja todas as threads mesmo quando o ctypes converte a exceção em `OSError` e o código a trata;
  - **não existe `dump_traceback_later(repeat=True)` no código**: tirar "repeat" não resolve;
  - a rotação só limita **entre** sessões.
- **Ajuste posterior F1-11b (commit separado, depois do atual):**
  1. **Teto por sessão:** uma thread daemon `FaulthandlerGuard` checa `os.fstat(fp.fileno()).st_size` a cada 30 s. Se o crescimento desde o armamento passar de 20 MB, chama `faulthandler.disable()` e escreve `=== faulthandler DESARMADO: teto da sessão ===`. O intervalo e o teto são parâmetros, para teste.
  2. `JARVIS_FAULTHANDLER=0` desliga tudo e não abre o arquivo.
  3. O cabeçalho continua `=== faulthandler armado em <data> ===`, e a chamada no `main.py` continua antes de `import numpy`.
- **Risco Windows:** baixo, mudança intencional (W5).
- **Aceite:**
  - no boot o arquivo tem ≤ 5 MB;
  - o crescimento por sessão fica ≤ teto + 1 dump;
  - um segfault real continua registrado.
- **Testes (qa), `tests/unit/test_crash_log.py`:**
  - rotação acima do limite e nenhuma rotação abaixo;
  - cabeçalho;
  - `JARVIS_FAULTHANDLER=0` sem arquivo;
  - guard com teto de 1 KB e intervalo de 0,05 s → `faulthandler.is_enabled()` fica falso e aparece a linha-marcador;
  - slow/linux_only: subprocess com `ctypes.string_at(0)` gera "Segmentation fault" no arquivo;
  - windows_only (N4): 1.000 chamadas `ctypes.wstring_at(1)` capturadas → arquivo ≤ teto.

### F1-12 — Causa raiz no Windows: protótipos ctypes do clipboard (mudança intencional)
- **Onde:** `comandos/clipboard_hist_ctrl.py:14-37` (`_get_clipboard_text`).
- **Antes:**
  - `user32.GetClipboardData` roda sem `restype` (o padrão `c_int` **trunca o HANDLE de 64 bits**);
  - `ctypes.wstring_at(p)` lê sem tamanho;
  - usa o `ctypes.windll` **compartilhado**.
- **Depois:**
  - instâncias **privadas**, criadas uma vez e guardadas no módulo: `ctypes.WinDLL("user32", use_last_error=True)` e `ctypes.WinDLL("kernel32", use_last_error=True)`;
  - protótipos:
    - `OpenClipboard(c_void_p) -> c_int`;
    - `GetClipboardData(c_uint) -> c_void_p`;
    - `CloseClipboard() -> c_int`;
    - `GlobalLock(c_void_p) -> c_void_p`;
    - `GlobalUnlock(c_void_p) -> c_int`;
    - `GlobalSize(c_void_p) -> c_size_t`;
  - leitura com `ctypes.wstring_at(p, size // ctypes.sizeof(ctypes.c_wchar))`, cortando no 1º `\x00`;
  - `GlobalUnlock` e `CloseClipboard` sempre em `finally`.
  - **Proibido** definir protótipos no `ctypes.windll.user32` compartilhado: afetaria `main.py:12018/12147` e o `_LazyUser32` do `df9b245`.
- **Risco Windows:** baixo/médio. Exige N4 do dono antes do merge.
- **Aceite (N4):** 10 min copiando textos variados (curto, longo, emoji, vazio, imagem) → zero `access violation` no `crash_native.log` e histórico funcionando.
- **Testes (tools-lab), `tests/tools/test_clipboard_hist_ctrl_win.py`:**
  - K com `ctypes.WinDLL` falso: protótipos definidos antes da 1ª chamada; `wstring_at` chamado **com tamanho**; NUL cortado; `GlobalUnlock` e `CloseClipboard` chamados até com exceção; `ctypes.windll` intocado;
  - windows_only: grava "olá ✓" no clipboard e lê de volta igual.

### F1-13 — Corrida do `reload_ui` (mudança intencional)
- **Onde:** `JarvisApi.reload_ui` (`main.py:2500-2509`) e `JarvisApp.__init__`, logo depois de `self.root = _RootProxy(self)`.
- **Causa:** o `js_bridge_call` do pywebview roda o método numa thread e, quando ele retorna, faz `evaluate_js('window.pywebview._returnValuesCallbacks["reload_ui"]["<id>"](...)')`. Só que o `load_html`/`load_url` já trocou a página e o callback não existe mais. O `set_ui_pref` (`main.py:2078`) já contorna isso com `root.after(180, ...)`.
- **Depois:**
  ```python
  # jarvis/webui/reload_guard.py
  class DeferredReload:
      def __init__(self, after, reload_fn, *, delay_ms=180, debounce_s=1.0, clock=time.monotonic): ...
      def request(self, theme: str) -> bool:   # True = agendou; False = já havia um pendente ou está no debounce
  ```
  ```python
  # JarvisApp.__init__
  self._ui_reloader = DeferredReload(self.root.after, self._reload_with_theme)
  # JarvisApi.reload_ui
  theme = getattr(self._app, "_current_theme", None) or JarvisApp._read_theme_pref_early()
  scheduled = self._app._ui_reloader.request(theme)
  return {"ok": True, "theme": theme, "scheduled": scheduled}
  ```
  O JS ignora o retorno (`ui/core/jarvis-bridge.js:201`). Exceção dentro do reload limpa a pendência.
- **Risco Windows:** baixo. O reload acontece 180 ms depois, e F5 repetido em menos de 1 s é ignorado.
- **Aceite:**
  - N2/N3 com `JARVIS_SMOKE_RELOADS=10`: nenhum `_returnValuesCallbacks.reload_ui` no `crash.log`, e `JARVIS_READY` volta a verdadeiro;
  - N4: F5 dez vezes, mesma verificação.
- **Testes (qa):**
  - K `tests/unit/test_reload_guard.py`: `after` recebe 180 e a função; debounce devolve `False`; depois de executar, um novo pedido agenda; relógio injetável; exceção no reload não trava a pendência;
  - K `tests/unit/test_main_reload_ui.py` (AST): `reload_ui` não chama `_reload_with_theme` diretamente.

### F1-14 — Job Object → adapter windows; limpeza de filhos no Linux
- **Onde:** bloco `if _sys_crash.platform == "win32":` (`main.py:13412-13493`) e o `Popen` do ffplay em `_tts_player` (âncora `self._tts_process = proc`).
- **Depois:**
  - `jarvis/platform/windows/processes.py`:
    - `install_kill_on_close_job(ct=None, wt=None) -> int | None` é **cópia literal** do bloco (mesmas estruturas, flags `0x2000 | 0x800` e `print("[JOB] ...")`), com o handle guardado em global do módulo;
    - `WindowsProcesses.install_child_cleanup()` chama essa função;
    - `register_child` é no-op.
  - `main.py` (mesmo lugar):
    ```python
    try:
        _plat_processes().install_child_cleanup()
    except Exception as _je:
        print(f"[JOB] Falha ao configurar limpeza de filhos: {_je}")
    ```
    O executor faz grep por `_JARVIS_JOB_HANDLE`. Se alguém lê esse nome, mantém `globals()["_JARVIS_JOB_HANDLE"]` apontando para o handle.
  - `PosixProcesses`:
    - `register_child` usa lista + lock e poda os mortos;
    - `install_child_cleanup` registra no `atexit`: terminate → espera até 2 s no total → kill;
    - com `tree=True`, usa `killpg(pid)` **só se** `getpgid(pid) == pid`;
    - **nunca** `killpg` do próprio grupo, sem `PR_SET_PDEATHSIG` e sem handler de SIGTERM (ADR §13.2–13.4).
  - ffplay: `_plat_processes().register_child(proc)` logo depois do `Popen` (no-op no Windows).
- **Risco Windows:** médio (código crítico movido). Golden com fakes + N4.
- **Aceite:**
  - golden idêntico;
  - N2/N3 terminam com `children_alive=0`;
  - N4: depois de fechar, nenhum `msedgewebview2.exe` órfão.
- **Testes (qa):**
  - C `tests/golden/test_job_object_windows.py`, oráculo `legacy_job_object(ct, wt)` × `install_kill_on_close_job(ct=fake, wt=stub)`:
    - mesma sequência: `CreateJobObjectW` → `SetInformationJobObject(h, 9, info, sizeof)` → `AssignProcessToJobObject(h, GetCurrentProcess())`;
    - `LimitFlags == 0x2800`;
    - mesmos `print` (capsys);
    - handle retido;
    - ramos de falha (`CreateJobObjectW` = 0, `SetInformationJobObject` = 0, exceção);
  - K `tests/unit/platform/test_processes_posix.py`: um subprocess registra um `sleep 60` e sai normalmente → o PID do `sleep` morre em ≤ 3 s; `tree=True` mata o neto; espião em `os.killpg` prova que nunca é chamado com `os.getpgrp()`;
  - K AST: `main.py` sem `_JOBOBJECT_*`, e `register_child` logo depois do `Popen` do ffplay.

### F1-15 — winreg do PATH → adapter windows
- **Onde:** `main.py:113-129`.
- **Depois:**
  - `jarvis/platform/windows/env.py::refresh_path_from_registry(environ=None, winreg_mod=None)`, cópia literal;
  - no `main.py`:
    ```python
    from jarvis.platform import current as _plat_current
    if _plat_current().is_windows:
        from jarvis.platform.windows.env import refresh_path_from_registry as _refresh_path
        _refresh_path()
    ```
- **Risco Windows:** baixo.
- **Aceite:** golden idêntico e `main.py` sem `import winreg`.
- **Testes (qa):**
  - C `tests/golden/test_windows_env.py`: `winreg` falso (HKLM e HKCU com `Path`, e um hive sem a chave levantando `OSError`); o **conjunto** de entradas do PATH do oráculo é igual ao da função nova, sem entradas vazias;
  - K AST.

---

## 5. Backlog encontrado (fora da Fase 1)
- `main.py:6425-6451`: restart em dev via PowerShell + `CREATE_NEW_CONSOLE` → F2 (`processes.restart_self`).
- `main.py:2895`: fallback para `notepad.exe` → F2 (`open_path`).
- `main.py:7164-7184`: `_idle_seconds` com `GetLastInputInfo` devolve 0 no Linux, então o modo ausente por ociosidade não dispara → F2 (`session`).
- `main.py:8928/8949`: `os.startfile` → F2 (`open_path`).
- `main.py:11800/12002/12018/12147`: HWND e clipboard do ditado → F2/F3.
- `comandos/condicional_ctrl.py:66-97`: janela em foco e `PlaySoundW` (exceções engolidas) → F3 (`window_manager`).
- **Hotkeys globais no Wayland:** portal GlobalShortcuts com KGlobalAccel de fallback → **Fase 2** (decisão do dono).
- Tray SNI, notifier, volume, MPRIS e clipboard no Linux → F2. Updater AppImage (zsync) → F5.
- `config.py:786`: `APP_SCAN_DIRS` com `C:\` → F4 (detector de apps).

## 6. Decisões do dono aplicadas (2026-09-13)
1. glibc 2.28 com **`PySide6==6.9.3`** fixado no v1 (F1-03).
2. **Arch sem sandbox do WebEngine** no v1, reportado por `sandbox_state()` (F1-06, passo 4).
3. **N4 (Windows real) fica com o dono**, antes de qualquer merge na `master`. Não bloqueia as fases.
4. **Portal GlobalShortcuts (fallback KGlobalAccel) antecipado para a Fase 2.** No v1 em Wayland ficam botão de microfone e wake word. Na Fase 1, `features_for("linux-wayland")` é vazio.
