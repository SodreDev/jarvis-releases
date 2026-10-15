# Revisão completa do J.A.R.V.I.S + avaliação de port para Linux

**Data:** 2026-09-13 · **Escopo:** somente leitura (a única escrita foi este arquivo).
**Ambiente-alvo do dono:** Nobara / Fedora 44, KDE Plasma 6, **Wayland**.
**Repo revisado:** `/home/sodre/GranaFacil/J.A.R.V.I.S` (git em `master`; existe também a branch `claude/upbeat-brattain-f5f61b`).

> Este relatório complementa (não substitui) `ARCHITECTURE.md`, `FEATURES.md` e `README.md`,
> que continuam sendo a documentação canônica. Aqui o foco é: estado atual, problemas e o **port para Linux**.

---

## 1. Visão geral

**O que é:** assistente de IA de desktop, escrito em **Python**, originalmente para **Windows**.
Conecta múltiplos LLMs (Groq, OpenAI, Gemini, LM Studio local) a um grande conjunto de
ferramentas — controle do sistema, automação web (Playwright/Chromium), mensageria
(WhatsApp/Discord/Instagram/Telegram/Gmail), mídia (Spotify, media keys), biblioteca de
jogos, geração de documentos, OCR/visão, gestos (MediaPipe) — acionáveis por **voz, chat ou gestos**.

**Stack:**
- **UI:** `pywebview` sobre **WebView2** (Edge/Windows). 5 superfícies de UI: app principal
  (`ui/`, temas Stark/macOS/minimal), gestos (`gesture_interface/`), dashboard FastAPI `:8765`,
  IDE web FastAPI `/ide` (Monaco + xterm.js), extensão VSCode (`vscode_extension/`, WS `:6589`).
- **Áudio:** captura via `sounddevice`/PortAudio; **STT** por Groq `whisper-large-v3` (nuvem) + `silero-vad`;
  **TTS** via `kokoro` (offline, torch), `edge-tts`, ElevenLabs e Gemini (nuvem).
- **IA:** `openai`, `groq`, `google-generativeai`, `transformers`/`torch`, `sentence-transformers`
  (classificador de intenção MiniLM em `classifiers/`).
- **Automação de SO (Windows):** `pywin32`, `uiautomation`, `pycaw` (volume), `pygetwindow`,
  `pyautogui`, `pynput` (hotkeys/input), `pystray` (bandeja), `winsdk`/WinRT (notificações), `winreg`.
- **Empacotamento:** **PyInstaller** (`JARVIS.spec`) → `.exe`; **Inno Setup** (`installer/jarvis.iss`)
  → instalador; auto-update via **GitHub Releases** (`updater/check_update.py`, repo `SodreDev/jarvis-releases`).

**Entrypoint e build:**
- **`main.py` (13.535 linhas)** — *god object* de produção: `JarvisApp` (UI pywebview, áudio,
  wake-word/PTT, hotkeys, estado), `JarvisApi` (ponte JS↔Python) e integração LLM + dispatch de
  ~150 regex de intenção. É o app real hoje.
- **`launcher.py`** — entrypoint do `.exe`. Truque "live-source": o exe carrega as libs nativas do
  bundle (`_internal/`) mas executa os `.py` direto da pasta do projeto → mudanças em `.py` valem no
  próximo restart **sem recompilar**. Contém um bloco `if False:` que existe só para o scanner
  estático do PyInstaller enxergar os imports do pacote `jarvis/`.
- **`config.py` (1.513 linhas)** — config legado (dict plano) + `os.environ` carregado de
  `credentials/.env`.
- **Pacote `jarvis/`** — nova arquitetura modular (TOML tipado com pydantic, browser pool, messaging,
  llm, intents, memory, agents), em **migração incremental**. Vários subpacotes ainda são stubs
  (`api/`, `mcp/`, `monitor/`, `plugins/`, `connectors/`, `dashboard/`, `filesystem/` = 1 linha cada).
- **Scripts de build (Windows/PowerShell):** `build-fast.ps1`, `dev.ps1`; `dist/`, `build/`,
  `dist_new/` (gitignored); pipeline em `tools/make_release.py` (8 etapas, começa por scan de segredos).

**Versão vs git:** `VERSION` = **2.7.0**, mas o **último commit é `ec30af2` (v2.2.6, 2026-05-28)**.
O working tree tem **251 arquivos modificados, 13 deletados e 38 não rastreados** — ou seja,
todo o salto 2.2.6 → 2.7.0 está **não commitado**. Ver §3.

---

## 2. Inventário de módulos, comandos e funções

Contagem de código-fonte Python (fora de `.git/.venv/dist/build`):

| Área | Arquivos | Linhas | Papel |
|---|---:|---:|---|
| raiz (`main.py`, `config.py`, `launcher.py`…) | 9 | 15.549 | app + config + entrypoints |
| `comandos/` | 47 | 16.374 | controllers `*_ctrl.py` + `tool_registry.py` + `executor.py` |
| `core/` | 27 | 6.191 | infra de runtime (event bus, listeners, managers, memória) |
| `documents/` | 12 | 3.750 | geração PDF/DOCX/PPTX/XLSX + charts + decks |
| `jarvis/` (modular) | ~55 | ~6.000 | nova arquitetura (config, browser, messaging, llm, memory, agents) |
| `tools/` | 7 | 2.448 | release, avaliação de roteador, corpus de treino |
| `VozIa/` | 5 | 743 | engines TTS |
| `ide/` | 5 | 710 | IDE web (workspace, terminal, planner) |
| `gesture_interface/` | ~25 | ~4.900 | gestos MediaPipe (engine, eye tracker, overlays 2D/3D) |
| `security/` | 4 | 695 | vault (memória), permissions, sanitizer |
| `classifiers/` | 3 | 556 | embeddings MiniLM + cliente de modelo local |
| `dashboard/` | 2 | 443 | FastAPI painel Stark + WebSocket |
| `updater/` | 2 | 409 | auto-update GitHub Releases |
| `entity/` | 2 | 263 | detecção de apps/jogos (Levenshtein, Steam) |
| `plugins/` | 2 | 131 | loader dinâmico + plugin "hello" |

### 2.1 `comandos/` — controllers (superfície de ferramentas do LLM)
`tool_registry.py` (2.664 L) é o registro central que expõe as tools ao LLM e faz o dispatch para os
controllers; `executor.py` (1.012 L) roda as intenções legadas (regex). **[WIN]** = usa API de Windows.

- **Sistema/janelas [WIN]:** `system_ctrl` (volume/mic via pycaw, power), `janela_ctrl` (1.219 L —
  foco/minimizar/mover janelas via pygetwindow/user32), `condicional_ctrl` (janela em foco via user32),
  `midia_ctrl` (media keys via tecla virtual), `macro_ctrl`, `terminal_ctrl`, `logger_ctrl`.
- **Automação web/mensageria [WIN parcial]:** `browser_ctrl` (833 L — Playwright no Chromium do
  usuário; detecção de navegador via **winreg**), `msg_sender` (1.208 L — envio via Chromium humano +
  `pyautogui`/`os.startfile`), `discord_ctrl` (801 L), `spotify_ctrl` (438 L via spotipy), `email_ctrl`
  (Gmail OAuth), `contato_ctrl`, `memoria_contatos`.
- **Produtividade:** `agenda_ctrl`, `alarme_ctrl`, `pomodoro_ctrl`, `descanso_ctrl`, `rotinas_ctrl`,
  `clipboard_hist_ctrl` [WIN], `notif_ctrl` (743 L) + `notif_history`, `painel_ctrl`, `memoria_ctrl`,
  `memoria_jarvis`.
- **Conhecimento/mídia:** `wikipedia_ctrl`, `dicionario_ctrl`, `traducao_ctrl`, `unidades_ctrl`,
  `cotacao_ctrl`, `noticias_ctrl` (RSS/Atom), `youtube_ctrl`, `url_fetch_ctrl` (com guarda anti-SSRF),
  `entretenimento_ctrl`, `image_gen_ctrl` (+ rembg), `ocr_ctrl` [WIN] (mss/ImageGrab + easyocr/tesseract),
  `vision_cache_ctrl` [WIN], `code_gen_ctrl`, `documentos_ctrl`/`pdf_ctrl`/`export_ctrl`, `file_ctrl`,
  `games_ctrl` [WIN], `ide_ctrl`.

> **Estado:** os controllers estão majoritariamente **funcionais** (poucos `TODO`: `tool_registry`=7,
> `browser_ctrl`=1). Os `[WIN]` são os que **quebram no Linux** e precisam de porte (§4).

### 2.2 `core/` — infra de runtime
Funcionais: `event_bus`, `ambient_listener`, `proactive_engine`, `api_key_pool`, `config_manager` [WIN],
`credentials_migrator`, `env_writer`, `person_registry`/`person_memory`, `presence_detector`,
`inbox_watcher`, `messaging_login`/`messaging_proactive`, `jarvis_prefix_router`, `utterance_router`,
`vad_filter` (silero), `system_audio_listener`, `camera_broker`, `learned_locations`, `game_library`,
`game_mode_manager`. **[WIN] a portar:** `screens.py` (multimonitor), `win_locale.py` (locale),
`winrt_notification_listener.py` (lê notificações do Windows via `winsdk`), `filesystem_indexer.py`,
`game_platform_detector.py` (699 L — Steam/Epic/etc. via registro + caminhos `C:\`).

### 2.3 `jarvis/` — pacote modular (migração em curso)
Substanciais: `config/` (schema pydantic + loader TOML + `paths.py`), `browser/` (pool LRU, human,
playwright_setup), `messaging/` (router + backends Chromium: WhatsApp/Discord/IG/Telegram/Gmail +
`pyautogui_sender.py` [WIN]), `llm/` (client unificado + bridge opt-in), `intents/` (registry regex),
`memory/` (store, layers, triage, skills, retrieval, dossiê — subsistema completo), `agents/` (router +
registry multi-agente), `credentials/vault.py` (Tier 1 JSON / Tier 2 AES-GCM).
**Stubs (1 linha):** `api/`, `mcp/`, `monitor/`, `plugins/`, `dashboard/`, `filesystem/`, `connectors/`.

### 2.4 Demais
- **`documents/`** — engines PDF/DOCX/XLSX/PPTX (tema Stark) + `report/deck/sheet_builder` (spec→render)
  + `design_system`. `pdf_convert.py` [WIN] (conversão nativa→PDF depende de componente Windows).
- **`VozIa/`** — `kokoro_tts_engine` (offline), `elevenlabs_tts`, `gemini_tts`, `tts_normalizer`. Portável.
- **`gesture_interface/`** — MediaPipe local (nenhum frame sai do processo): `gesture_engine` (tracker,
  recognizer, classifier, eye_tracker), `canvas2d`/`workspace3d` (overlays), `desktop_control/controller`
  [WIN] (pyautogui), `ui/live_view` (747 L). Câmera via cv2.
- **`security/`** — `vault` (em memória), `permissions` (níveis por ação), `sanitizer`.
- **`classifiers/`** — `embeddings` (MiniLM) + `modelo_local` (sidecar de modelo externo).
- **`tools/`** — `make_release.py` [WIN], `check_principles.py`, `eval_tools.py`, `nila_corpus*` (treino),
  `migrate_to_user_config.py`.
- **`ide/`**, **`dashboard/`**, **`updater/`**, **`plugins/`**, **`entity/`** — ver §2.1/§2.2.

**Código morto / órfão:** `main.py.bak` (360 KB), `requirements.txt.bak`, `_count_quotes.py`,
`_gen_icon.py`, `dist_new/` (vazia), `plugins/hello` (exemplo).

---

## 3. Problemas: bugs, crashes, débito técnico, lixo e segurança

### 3.1 Crashes recorrentes
- **`crash.log` (508 linhas):** dominado por **`JavascriptException` / `TypeError`** (62+62) do tipo
  `window.pywebview._returnValuesCallbacks.reload_ui.<id> is not a function`. É uma **corrida na ponte
  JS↔Python do pywebview durante `reload_ui`**: o callback é resolvido/limpo antes de a resposta do JS
  voltar. Sintoma repetitivo, não fatal, mas polui o log.
- **`crash_native.log` (≈514 MB):** é um **dump de `faulthandler` reescrito em loop** — stacks completas
  de todas as threads (pynput win32 listener, `_tts_player`/`_tts_fetcher`, `webview/winforms
  create_window`) gravadas repetidamente até estourar meio giga. Rodou no Windows (caminhos `B:\...` e
  `C:\Users\lilia\...`). **Não é um crash único**; é telemetria descontrolada. Deve ser apagado e o
  faulthandler precisa parar de redumpar em loop.

### 3.2 Débito técnico
- **`main.py` é um monólito de 13.535 linhas** (UI + áudio + LLM + dispatch + estado). Difícil de testar
  e de portar; é o principal obstáculo do port.
- **Duplo caminho de dispatch:** ~150 regex legados no `main.py` **e** tool-calling do LLM
  (`tool_registry`). Migração para `jarvis/intents/` incompleta.
- **Sem suíte de testes** (`pytest`) e **sem telemetria estruturada** (logs via `print`).
- **Histórico de chat sem janela deslizante** — pode crescer sem limite em sessões longas
  (o `jarvis/memory/compaction.py` endereça isso na camada modular, mas não está plugado no god-object).
- **Migração modular pela metade:** duplicação legado↔`jarvis/` (config, mensageria, browser, intents).

### 3.3 Lixo na raiz
- **`crash_native.log` (514 MB)** — apagar.
- `build_log.txt`, `build_log2..5.txt`, `build_log_last.txt`, `@AutomationLog.txt` (135 KB),
  `browser_diag.log`, `stderr.log` (1,2 MB), `stdout.log`, `exit.log`, `run_error.txt` — logs de build/run.
- `main.py.bak`, `requirements.txt.bak`, `dist_new/` (vazia).

### 3.4 Estado do versionamento (risco de perda)
- **251 modificados / 13 deletados / 38 não rastreados**, com `VERSION`=2.7.0 e último commit em 2.2.6.
  Todo o trabalho de ~4 meses (jun/2026) está **fora do git**. Risco alto de perda; recomenda-se
  commitar/organizar antes de qualquer refactor de port (Fase 0).

### 3.5 Segurança (SEM valores; só constatações)
- ✅ **Nenhum segredo versionado.** Na pasta de credenciais o git só rastreia os templates:
  `.env.example`, `.gitkeep` e `README.md`. O `.gitignore` cobre a pasta de credenciais, `data/`,
  logs, `.venv`, `dist/` e `build/`.
- ✅ **Zero chaves hardcoded** nos padrões conhecidos (OpenAI/Groq/Gemini/GitHub) em `config.py`/`main.py`.
- ⚠️ **Segredos e PII ficam locais e em claro:** a pasta de credenciais (Tier 1 = JSON por perfil,
  **não criptografado** por padrão; Tier 2 AES-GCM é opcional), o `.spotify_cache` (token OAuth na raiz)
  e o `arquivos.vcf` (189 KB de contatos). Todos **gitignored** e **não versionados** — expostos só a
  quem já tem acesso à máquina, mas sem criptografia em repouso.
- ⚠️ **Superfícies de rede sem auth:** dashboard `:8765`, IDE `/ide` (terminal multi-sessão) e a
  extensão VSCode (`:6589`, sem TLS/auth) — uso local, mas o **IDE com terminal** é uma superfície
  sensível se a porta escapar do loopback.
- ⚠️ **`.claude/settings.local.json` do Jarvis** libera `gh release *` e `git rm *` sem confirmação
  (por isso a regra é abrir CLIs com cwd no Orchestrator + `--add-dir`, onde os hooks valem).

---

## 4. Port para Linux (Wayland **e** X11; alvo do dono: Plasma 6 / Wayland)

### 4.1 O ponto central: Wayland
No Windows o app injeta input, lê a tela, enumera janelas e registra hotkeys globais livremente.
No **Wayland isso é bloqueado por design** (isolamento entre apps). `pynput` e `pyautogui` são
**X11-only** — sob Wayland só enxergam/atuam via **Xwayland** e apenas em apps X11, não nos nativos
([pynput docs](https://pynput.readthedocs.io/en/latest/keyboard.html)). Portanto, cada recurso
"invasivo" precisa migrar para o modelo Wayland: **portais XDG**, **KWin (D-Bus/scripting)**,
**PipeWire**, **MPRIS** e **uinput (ydotool)**.

**Boa notícia:** grande parte já é portável. `sounddevice`/PortAudio, `torch`/`kokoro`/`edge-tts`/
ElevenLabs/Gemini, Groq Whisper (nuvem), MediaPipe, `cv2` (V4L2), Playwright/Chromium, FastAPI,
`transformers`, geração de documentos — **tudo cross-platform**. E **muitos imports de Windows já são
lazy** (dentro de funções), o que facilita o port com shims por plataforma. A única trava de plataforma
no boot é `main.py:114` (`if sys.platform == "win32":` para ler o PATH do registro).

### 4.2 Mapa de dependências Windows → equivalentes Linux

| Recurso / dep Windows | Onde | X11 | **Wayland (KDE Plasma 6)** | Dificuldade | Estratégia |
|---|---|---|---|---|---|
| **UI: pywebview + WebView2** | `main.py`, `launcher.py` | GTK `webkit2gtk` ou Qt `QtWebEngine` | **Qt WebEngine** (PyQt6/PySide6) casa com Qt6/Wayland do Plasma 6 ([pywebview #805](https://github.com/r0x0r/pywebview/issues/805)) | Média | Instalar backend Qt; testar render/bridge; rever `storage_path`/perfil |
| **Job Object** (matar processos-filho do WebView2) | `main.py` (~13412) | — | `os.setsid` + grupo de processo / `prctl(PR_SET_PDEATHSIG)` / cgroup | Baixa | Substituir por process group no Linux |
| **Hotkeys globais** `pynput.GlobalHotKeys` | `main.py:138,11615` | `pynput` (funciona) | **Portal GlobalShortcuts** (`xdg-desktop-portal-kde`) ou **KGlobalAccel** via D-Bus ([XDG Portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.impl.portal.GlobalShortcuts.html)) | **Alta** | Backend por plataforma; no Wayland registrar via portal |
| **Injeção de input** `pyautogui`/`pynput.Controller` (digitar, colar, media) | `msg_sender`, `midia_ctrl`, `main.py`, `gesture .../controller` | `pyautogui`/`pynput` | **ydotool/dotool** (uinput) ou **wtype** | **Alta** | ydotool daemon (implica grupo/uinput → decisão do dono); ou evitar injeção |
| **Captura de tela / OCR** `mss`, `PIL.ImageGrab`, `pyautogui.screenshot` | `ocr_ctrl`, `janela_ctrl`, `discord_ctrl`, `main.py` | `mss` (funciona) | **Portal ScreenCast/Screenshot → PipeWire** ou `spectacle -b`/`grim` ([XDG Portal ArchWiki](https://wiki.archlinux.org/title/XDG_Desktop_Portal)) | **Alta** | Backend de captura via portal; OCR (easyocr/tesseract) já é portável |
| **Gestão de janelas** `pygetwindow`, `win32gui`, `user32.GetForegroundWindow` | `janela_ctrl` (1219 L), `condicional_ctrl` | `wmctrl`/`xdotool`/EWMH | **KWin scripting via D-Bus** ou **`kdotool`** (xdotool-like p/ KDE, funciona Wayland+X11) ([kdotool](https://github.com/jinliu/kdotool)) | **Alta** | Abstrair `WindowManager`; backend KWin/kdotool |
| **Volume do sistema/mic** `pycaw` (COM) | `system_ctrl` | PipeWire/Pulse | **PipeWire**: `wpctl`/`pactl` ou `pulsectl` (Python) | Baixa | Backend de áudio; `pulsectl` funciona nos dois |
| **Media keys** (tecla virtual) | `midia_ctrl` | MPRIS | **MPRIS** via `playerctl` (Plasma suporta) ([playerctl/MPRIS](https://work.lisk.in/2020/05/06/linux-media-control.html)) | Baixa | Trocar tecla virtual por comandos MPRIS |
| **Notificações (enviar)** WinRT/`plyer` | `notif_ctrl` | libnotify | **`notify-send`/libnotify/D-Bus `org.freedesktop.Notifications`** | Baixa | Backend notifier |
| **Notificações (LER as recebidas)** `winsdk` UserNotificationListener | `core/winrt_notification_listener`, `notif_ctrl` | — | **Monitorar D-Bus** `org.freedesktop.Notifications` (eavesdrop/monitor) | **Alta** | Reimplementar por D-Bus monitor; confiabilidade varia |
| **Registro (winreg)**: navegador/app padrão | `browser_ctrl`, `game_platform_detector` | XDG | **`xdg-settings`, `xdg-mime`, `.desktop` files, `update-alternatives`** | Média | Camada de descoberta por `.desktop`/XDG |
| **Abrir arquivos/apps/URIs** `os.startfile` | `msg_sender`, `janela_ctrl`, `executor`, `games_ctrl` | `xdg-open` | **`xdg-open`/`gio open`** | Baixa | Shim `open_path()` |
| **Detecção de jogos** (Steam/Epic via registro + `C:\`) | `game_platform_detector` (699 L), `entity/app_detector` | — | **Steam** `~/.local/share/Steam`, **Lutris**, **Heroic** (Epic/GOG), **Flatpak**, **Bottles**; scan de `.desktop` | Média | Reescrever detector p/ layout Linux |
| **Bandeja (tray)** `pystray` | `main.py:13252` | AppIndicator | **StatusNotifierItem** (KDE nativo; `pystray` + libayatana-appindicator/GObject) | Média | Backend SNI |
| **Overlay de gestos** (janela transparente click-through, 3D) | `gesture_interface/canvas2d`, `workspace3d` | override-redirect X11 | **`wlr-layer-shell`** (suportado pelo KWin) | **Alta** | Repensar overlay; talvez limitar no v1 |
| **Clipboard** `pyperclip`, `clipboard_hist_ctrl` | `comandos/clipboard_hist_ctrl` | `xclip`/`xsel` | **`wl-clipboard`** (`pyperclip` suporta) | Baixa | Instalar `wl-clipboard` |
| **Locale** `win_locale` | `core/win_locale` | `locale`/`$LANG` | idem | Baixa | Módulo `locale` stdlib |
| **subprocess** `CREATE_NO_WINDOW`/`STARTUPINFO` | vários | — | não existe no Linux | Baixa | Remover flags por plataforma |
| **Paths** `%APPDATA%`/`%LOCALAPPDATA%` | `config.py`, `jarvis/config/paths.py` | XDG | **XDG Base Dirs** (`~/.config`, `~/.local/share`, `~/.cache`) | Baixa | Centralizar em `paths.py` |
| **Build**: PyInstaller + Inno Setup | `JARVIS.spec`, `installer/`, `*.ps1`, `make_release.py` | — | **PyInstaller Linux** + **Flatpak** (portais nativos) ou **rpm**/AppImage (Fedora) | Média | Novo pipeline; reescrever `.ps1` em `.sh`/Python |
| **ffplay via PATH do registro** | `main.py:114` | `ffmpeg` do repo | idem (PipeWire) | Baixa | `dnf install ffmpeg`; remover hack de registro |

**Portáveis sem trabalho relevante:** STT (Groq nuvem + silero/torch), TTS (kokoro/edge/elevenlabs/gemini),
áudio (PortAudio/PipeWire), LLM clients, Playwright/Chromium (mensageria web!), MediaPipe + câmera V4L2,
documentos, FastAPI (dashboard/IDE), embeddings.

### 4.3 Arquiteturas de port — comparação

**Opção A — Camada de abstração por plataforma (dentro do próprio repo).**
Criar `jarvis/platform/` com *protocolos* (`WindowManager`, `InputController`, `ScreenCapture`,
`VolumeControl`, `Notifier`, `ShortcutManager`, `AppLauncher`, `TrayIcon`, `Paths`) e backends
`windows/`, `linux_x11/`, `linux_wayland/`, escolhidos em runtime. Um só código-base.
*Prós:* Windows continua funcionando; port incremental e testável; alinha com a migração modular já em curso.
*Contras:* exige disciplina e um refactor gradual do god-object (`main.py`) para chamar a camada.

**Opção B — Fork Linux dedicado.**
Ramificar, arrancar o código Windows e fixar Linux.
*Prós:* chega mais rápido a um primeiro binário Linux.
*Contras:* divergência e manutenção dupla; features apodrecem em um dos lados; conflitos de merge;
desperdício, já que a maior parte do código **já é cross-platform**. **Não recomendado.**

**Opção C — Híbrida incremental sobre o pacote `jarvis/` (recomendada).**
É a Opção A implementada **aproveitando a migração modular existente**: colocar a abstração em
`jarvis/platform/` e ir roteando as chamadas Windows do `main.py` para ela à medida que a migração
avança, na ordem "shim fácil primeiro" (paths, `open_path`, volume, notificações-enviar, clipboard,
media keys, tray) e depois os difíceis do Wayland (hotkeys, input, captura, janelas) atrás de
portais/KWin/ydotool.

**Recomendação:** **Opção C**, com **alvo Wayland-nativo** (portais + KWin + PipeWire + MPRIS + ydotool),
oferecendo fallback X11 só onde é barato. **Não fazer fork.** Rationale: ~70% do stack já é portável;
o risco está concentrado em 4 áreas Wayland (hotkeys, input, captura, janelas), que ficam isoladas atrás
de interfaces; e o esforço reforça a modularização que o projeto já quer fazer.

---

## 5. Plano em fases

- **Fase 0 — Higiene e baseline (pré-requisito).** Commitar/organizar as 251 mudanças pendentes
  (2.2.6→2.7.0) numa branch; apagar `crash_native.log` (514 MB) e logs-lixo; decidir destino de
  `main.py.bak`/`*.bak`/`dist_new`; garantir `.venv` fora do git. Corrigir o faulthandler que redumpa em loop.
- **Fase 1 — Boot no Fedora.** Tornar `requirements.txt` condicional por plataforma
  (`pywin32; sys_platform=="win32"`, idem pycaw/uiautomation/pygetwindow/pystray-win); tornar os imports
  de topo do `main.py` (`pynput`, `webview`) lazy/guarded; escolher e instalar o backend **Qt WebEngine**
  do pywebview; abrir a janela principal no Fedora. Meta: **sobe sem crashar**, mesmo com features WIN desativadas.
- **Fase 2 — Camada de plataforma + portes fáceis.** `jarvis/platform/` + backends Linux para: paths XDG,
  `open_path` (xdg-open), volume/mic (PipeWire), clipboard (wl-clipboard), notificações-enviar (libnotify),
  tray (SNI), locale, media keys (MPRIS), ffmpeg.
- **Fase 3 — Difíceis do Wayland.** Hotkeys globais (portal GlobalShortcuts/KGlobalAccel), injeção de
  input (ydotool/wtype), captura de tela + OCR (portal ScreenCast/Screenshot), gestão de janelas (KWin/kdotool).
- **Fase 4 — Recursos avançados.** Detecção de apps/jogos Linux (Steam/Lutris/Heroic/Flatpak/.desktop),
  leitura de notificações via D-Bus, overlay de gestos via `wlr-layer-shell` (ou adiar).
- **Fase 5 — Empacotamento e testes.** Pipeline Linux (**Flatpak** — sandbox + portais nativos — ou rpm/
  AppImage), adaptar o auto-update, introduzir `pytest` + CI.

---

## 6. Decisões que precisam do dono

> A escolha do port é do dono; abaixo estão as decisões, com a recomendação técnica quando cabe.

1. **Arquitetura do port:** camada de abstração incremental sobre `jarvis/` (**recomendada**) *vs* fork Linux.
2. **Alvo gráfico:** **Wayland-nativo** (recomendado) *vs* exigir X11/Xwayland *vs* suportar ambos.
3. **Backend do pywebview:** **Qt WebEngine** (PyQt6/PySide6, casa com Plasma 6 — recomendado) *vs* GTK webkit2gtk.
4. **Injeção de input:** aceitar dependência do **ydotool** (precisa de daemon + acesso a `uinput`/grupo,
   com implicação de segurança) *vs* limitar a automação a métodos sem injeção de teclado.
5. **Escopo do v1 Linux:** o que entra já (app + voz + LLM + mensageria web + sistema básico) e o que fica
   para depois (overlay de gestos/3D, leitura de notificações, IDE/dashboard).
6. **Manter Windows em paralelo** (dual-target, favorece a Opção C) *vs* migrar de vez para Linux.
7. **Empacotamento:** **Flatpak** (sandbox + portais) *vs* rpm nativo (Fedora) *vs* AppImage.
8. **Higiene do repo (Fase 0):** autorizar a limpeza do `crash_native.log` e dos logs-lixo, e definir o
   destino das 251 mudanças não commitadas.
9. **Débito:** introduzir `pytest` + logging estruturado e concluir a migração modular como parte do port?
10. **Criptografia em repouso** das credenciais locais (ligar Tier 2 AES-GCM por padrão)?

---

*Revisão gerada em modo somente-leitura. Fontes de pesquisa: pynput docs, pywebview #805, XDG Desktop
Portal (GlobalShortcuts/ScreenCast), kdotool, MPRIS/playerctl.*
