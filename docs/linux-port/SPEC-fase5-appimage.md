# SPEC — Fase 5 (antecipada): AppImage do J.A.R.V.I.S para Linux

| | |
|---|---|
| **Autor** | arquiteto · 2026-09-14 |
| **Base** | branch `linux-port`, commit `ab4404c`. Fases 1 e 2 fechadas no Linux: M1 nas 4 distros e M2 aprovado com ressalvas. N-dono (Plasma) e N4 (Windows) estão com o dono. As linhas mudam a cada commit; localize pelo **trecho-âncora**. |
| **Por que agora** | Decisão do orquestrador: o dono quer instalador e release. O AppImage empacota o que as Fases 1 e 2 entregam. As Fases 3 (captura/janelas/input) e 4 (gestos, leitura de notificações, detecção de apps) chegam depois, como **atualizações do AppImage**. |
| **Arquitetura** | [ADR-001](ADR-001-camada-plataforma.md) (W1–W7, C1–C4), [SPEC-fase2](SPEC-fase2.md) §7 (versão unificada U1–U9), [MAPA_EXECUCAO](MAPA_EXECUCAO.md) §5–§6, [tests/docker/MATRIZ.md](../../tests/docker/MATRIZ.md). |
| **Fila** | [FILA-fase5.md](FILA-fase5.md) |

---

## 0. Escopo, marcos e o que não entra

**Entra:**
- `JARVIS-x86_64.AppImage` construído em container `manylinux_2_28` (glibc 2.28) com PyInstaller + appimagetool (runtime estático, sem libfuse);
- dados graváveis só em XDG;
- ambiente limpo para os processos externos;
- restart e desktop entry corretos no AppImage;
- Playwright/Chromium baixado sob demanda para XDG;
- updater próprio do AppImage (aviso + zsync);
- `.desktop`, ícones e AppStream;
- `SHA256SUMS-linux.txt` + scan de segredos;
- smoke do AppImage na matriz, numa imagem "enxuta" e na sandbox do orquestrador.

**Não entra:**
- Fases 3 e 4;
- release normal/Windows (só depois do N4). A **pré-release Linux** é publicada pela CLI release, sob ordem do orquestrador, depois do M2 (D-F5-6);
- aarch64 (D-F5-7);
- Flatpak, rpm e deb;
- mudança no build do Windows.

**Marco M1 — "AppImage roda":**
- `tests/docker/build_appimage.sh` gera, num container limpo, `dist-appimage/JARVIS-v<VERSION>-linux.<N>-x86_64.AppImage` + `.zsync` + `SHA256SUMS-linux.txt`;
- `objdump -T` de todo ELF do AppDir não exige `GLIBC_2.29+`;
- **N2** (Xvfb) boot smoke do AppImage passa em fedora44, debian12, ubuntu2404, arch **e** `debian:stable-slim` "enxuta" (só com a lista SISTEMA da §5);
- **N3** (KWin virtual, fedora44) boot smoke passa;
- a execução a partir de uma árvore **sem permissão de escrita** passa (§4 F5-13);
- o tamanho respeita a meta da §6.

**Marco M2 — "pronto para release":**
- M1 passa 3 vezes seguidas;
- smokes de tray, áudio (`children_alive=0`, sem `FORCED_EXIT`), PTT (N3, KGlobalAccel) e restart no AppImage;
- scan de segredos limpo e `sha256sum -c SHA256SUMS-linux.txt` ok;
- teste K prova que o updater do Windows ignora os assets Linux e que a tag não gera update falso;
- smoke na sandbox do orquestrador (Debian 13 + Xvfb);
- JARVIS.spec **idêntico** ao de `ab4404c`, e `git diff --stat ab4404c..linux-port` ⊆ §3;
- revisor aprovou.

**N-dono:** duplo clique no Plasma real (montagem FUSE de verdade), item no menu via `.desktop`, aviso de atualização, e o checklist N-dono da Fase 2 **dentro do AppImage**.

**Proibido:** instalar qualquer coisa no host do dono, rodar o AppImage na sessão real ou publicar fora do fluxo da D-F5-6 (só pré-release Linux, pela CLI release, sob ordem do orquestrador, depois do M2 verde). Tudo roda em container, no KWin virtual ou na sandbox.

**Publicação (D-F5-6):** o M2 verde (matriz + sandbox) libera a pré-release. O N-dono é recomendado, mas não bloqueia a pré-release.

## 1. Níveis de teste

| Nível | Onde | O que roda |
|---|---|---|
| **N0** | host `.venv-linux` | unit/AST/golden das mudanças de código (paths, env, restart, launcher, updater, script de release, spec) |
| **N1** | containers da matriz | N0 + `import` real no Python 3.12 do build |
| **B** (build) | `tests/docker/Dockerfile.appimage-build` (`quay.io/pypa/manylinux_2_28_x86_64`, `/opt/python/cp312-cp312`) | PyInstaller → AppDir → appimagetool; checagem de glibc (`objdump -T`) e de libs proibidas (§5) |
| **N2-AI** | fedora44/debian12/ubuntu2404/arch + `appimage-bare` (debian:stable-slim + lista SISTEMA) + **sandbox do orquestrador** (Debian 13, Xvfb :99) | `APPIMAGE_EXTRACT_AND_RUN=1 JARVIS_SMOKE_SECONDS=8 ./JARVIS-*.AppImage` (container sem `/dev/fuse`) |
| **N3-AI** | `run_n3_wayland.sh` com o AppImage montado no container fedora44 | boot Wayland + `JARVIS_SMOKE_HOTKEYS`/`PTT` |
| **N-dono** | Plasma real, você | FUSE real, menu, tray, PTT, áudio, aviso de update |
| **N4** | Windows real, você | nada muda no Windows nesta fase; o checklist é "build do .exe igual" (§4 F5-09) |

Regras que continuam valendo:
- smoke só com `JARVIS_TEST_SANDBOXED=1`;
- `podman run --init`;
- `HOME`/`XDG_*` temporários;
- encerrar só PIDs registrados;
- nada do D-Bus, do PipeWire ou da tela do dono;
- os artefatos ficam em `dist-appimage/` (ignorado pelo git) e **nunca** vão para o host fora do repo.

## 2. Convenções
- Tarefas que **tocam caminho do Windows** (F5-02, F5-07): o **qa** grava antes o oráculo literal de `ab4404c` em `tests/golden/legacy_ab4404c.py` + golden **C**. Tarefas só-Linux ou de packaging: o **executor** escreve os testes **K** junto.
- **O `JARVIS.spec` não é tocado.** Um teste C congela o sha256 de `ab4404c`.
- Nada de `main.py` em teste (use AST). Nada de publicar. Commits por pathspec.

## 3. Lista fechada

| ID | Mudança | Arquivos de produção | Risco Windows |
|---|---|---|---|
| F5-02 | `runtime_root()` gravável: XDG no Linux congelado | `jarvis/platform/{protocols}.py`, `jarvis/platform/{windows,linux}/paths.py`, `main.py` (`_data`), `config.py` (base do `creds_path`), `jarvis/config/paths.py` (`project_root`), `updater/check_update.py` (`_base_dir`), `rthook_errlog.py` | baixo (golden) |
| F5-03 | `host_env()`: ambiente limpo para ferramentas do sistema | `jarvis/platform/{protocols}.py`, `jarvis/platform/{windows,linux}/processes.py`, `jarvis/platform/linux/{tools,open_path,notifier,clipboard_klipper,volume,media}.py`, `jarvis/platform/linux_wayland/clipboard.py`, `jarvis/platform/linux_x11/clipboard.py` | nenhum |
| F5-04 | `restart_self` no AppImage: `$APPIMAGE`, cwd fora da montagem, `PYINSTALLER_RESET_ENVIRONMENT=1` | `jarvis/platform/linux/processes.py` | nenhum |
| F5-05 | desktop entry no AppImage (`Exec=$APPIMAGE`) | `jarvis/platform/linux/desktop_entry.py` | nenhum |
| F5-06 | Playwright: navegadores em `$XDG_DATA_HOME/jarvis/ms-playwright` no Linux congelado | `jarvis/browser/playwright_setup.py` | baixo |
| F5-07 | live-source do `launcher.py` no Linux congelado | `launcher.py` | baixo (golden) |
| F5-08 | runtime hook Linux: PortAudio embutido, ffmpeg embutido no PATH, defaults de ambiente | `packaging/linux/rthook_linux.py` (novo) | nenhum |
| F5-09 | `packaging/linux/JARVIS-linux.spec` (novo; o `JARVIS.spec` fica intacto) | `packaging/linux/JARVIS-linux.spec` | nenhum |
| F5-10 | AppDir + appimagetool + `.desktop`/ícones/AppStream/AppRun | `packaging/linux/{build_appimage.sh,AppRun,make_icons.py,<APP_ID>.desktop,<APP_ID>.metainfo.xml}`, `.gitignore` (`dist-appimage/`, `build-appimage/`) | nenhum |
| F5-11 | Updater do AppImage (aviso + zsync opcional) | `jarvis/platform/linux/appimage_update.py` (novo), `main.py` (âncoras `_iniciar_verificador_updates` e `def apply_update_now`) | baixo (ramo Windows intacto) |
| F5-12 | Script de release Linux (scan de segredos + checksums) | `tools/make_release_linux.py` (novo; importa de `tools/make_release.py` **sem alterá-lo**) | nenhum |

A infra de teste (`tests/docker/Dockerfile.appimage-build`, `tests/docker/build_appimage.sh`, `tests/docker/run_appimage_smoke.sh`, `tests/docker/Dockerfile.appimage-bare`, `tests/smoke/test_appimage_*.py`) é do qa. Arquivo de produção fora da tabela só com emenda do arquiteto.

---

## 4. Mudanças detalhadas

### F5-02 — Raiz gravável fora da montagem
**Problema:** no AppImage, `sys.executable` e `_MEIPASS` ficam em `/tmp/.mount_*` (ou `squashfs-root`), que é **read-only** e some quando o processo sai. Hoje o modo frozen grava ao lado do executável em:
- `main.py` `_data()` (âncora `if getattr(sys, 'frozen', False):` + `base = os.path.dirname(sys.executable)`): `crash_native.log`, `stderr.log`, `crash.log`, prefs, temp;
- `config.py` `creds_path` (base da pasta de credenciais e de `PATHS`);
- `jarvis/config/paths.py::project_root()` (frozen → pasta do exe; afeta `browser_profiles_dir`, `model_dir`, `person_*`, `inbox_watcher`);
- `updater/check_update.py::_base_dir()`;
- `rthook_errlog.py` (`jarvis_startup.log` ao lado do executável).

**Depois:**
- Protocolo `Paths` ganha `runtime_root() -> str`:
  - **win32:** literal de hoje (frozen → `os.path.dirname(sys.executable)`; dev → pasta do projeto);
  - **linux dev:** pasta do projeto (igual a hoje);
  - **linux frozen:** `$XDG_DATA_HOME/jarvis` (criado com `0700`).
- A pasta de credenciais do Linux frozen passa a ser `credentials_dir()` (já é XDG_CONFIG, `0700`).
- **`main._data`:** `base = _plat_paths().runtime_root()`. O cálculo **literal** do Windows vai para `WindowsPaths.runtime_root`.
- **`config.py`:** a base do `creds_path` passa a vir de `_plat_paths()` só quando `current().is_linux and frozen`. O ramo do Windows fica literal.
- **`jarvis/config/paths.py::project_root()` (frozen):** Windows literal; Linux frozen → `runtime_root()`.
- **`updater/_base_dir()`:** Linux frozen → `runtime_root()`. Windows literal. No AppImage o payload continua desligado.
- **`rthook_errlog.py`:** roda antes do pacote `jarvis`, então não pode importar a camada. Se `sys.platform != "win32"` e o executável não for gravável, grava em `$XDG_STATE_HOME/jarvis/logs/jarvis_startup.log` (resolução XDG inline, com o padrão `~/.local/state`). O ramo Windows fica literal. Este arquivo entra na allowlist C1 com justificativa: é executado antes do import.
- **`PASTA_TEMP = "temp"`** (relativo ao cwd) no Linux frozen passa a ser `runtime_root()/temp`: com `_data("temp")` quando o uso já passa por `_data`; os demais usos ficam registrados como **backlog**.

**Risco Windows:** baixo. Golden garante o mesmo caminho em frozen e em dev.

**Aceite:**
- N0: golden Windows (frozen/dev) idêntico;
- K linux frozen com `sys.frozen`/`sys.executable` falsos e `isolated_home` → tudo em XDG;
- N2-AI read-only (F5-13): nenhum `EROFS`/`PermissionError`, e `crash_native.log`/prefs aparecem em `$XDG_DATA_HOME/jarvis`.

**Testes:**
- qa antes: C `tests/golden/test_runtime_root_windows.py` (oráculos `_data`, `creds_path`, `project_root`, `_base_dir` e `rthook` de `ab4404c`);
- executor: K `tests/unit/platform/test_runtime_root_linux.py` e K AST `tests/unit/test_main_data_root.py`.

### F5-03 — `host_env()`: ferramentas do sistema com ambiente limpo
**Problema:** o bootloader do PyInstaller muda `LD_LIBRARY_PATH` (guarda o original em `LD_LIBRARY_PATH_ORIG`), e o bundle define `QT_PLUGIN_PATH`/`QTWEBENGINE*`/`PYTHON*`. Processos do **sistema** herdam isso e carregam libs do bundle. Isso quebra `xdg-open` → `kde-open`/navegador, `notify-send`, `wpctl`, `wl-paste`, `playerctl`, `gio` e o `appimageupdatetool`.

**Depois:** `Processes.host_env() -> dict | None`:
- **win32:** `None` (a chamada fica idêntica, herda como hoje);
- **linux:**
  - só limpa quando `sys.frozen`: copia `os.environ`;
  - restaura `LD_LIBRARY_PATH` a partir de `LD_LIBRARY_PATH_ORIG` (e remove a variável se o original não existia);
  - remove `QT_PLUGIN_PATH`, `QML2_IMPORT_PATH`, `QTWEBENGINEPROCESS_PATH`, `QTWEBENGINE_RESOURCES_PATH`, `QTWEBENGINE_LOCALES_PATH`, `PYTHONHOME`, `PYTHONPATH`, `GIO_MODULE_DIR`, `GDK_PIXBUF_MODULE_FILE`, `FONTCONFIG_FILE` e as `_PYI_*`;
  - mantém `APPIMAGE`/`APPDIR`/`OWD` (inofensivas);
  - dev devolve `None`.

Todo `Popen`/`run` de **ferramenta do sistema** na camada Linux passa `env=host_env()`: `linux/tools.run_tool`, `XdgOpen`/`GioOpen`, `NotifySendNotifier`, `wl-paste`/`wl-copy`/`xclip`/`xsel`, `wpctl`/`pactl` e `playerctl`.

**Não usam `host_env()`:** o `ffplay` embutido e o driver do Playwright. São do bundle e precisam do ambiente dele.

**Aceite:** K com ambiente falso de frozen: `LD_LIBRARY_PATH` restaurado, variáveis removidas e `run_tool` recebe o env limpo (espião em `Popen`); no dev é `None`. N2-AI: `JARVIS_SMOKE_OPEN=/etc/hostname`, com um `xdg-open` falso no container que grava o próprio `LD_LIBRARY_PATH`, prova que não há caminho de `/tmp/.mount_`/`squashfs-root`.

**Testes (executor, junto):** K `tests/unit/platform/test_host_env.py`.

### F5-04 — `restart_self` no AppImage
- **Onde:** `jarvis/platform/linux/processes.py::PosixProcesses.restart_self` (âncoras `appimage = os.environ.get("APPIMAGE")` e `cwd=os.path.dirname(main_path)`).
- **Depois:** com `APPIMAGE` definido:
  - `cmd = [APPIMAGE] + argv`;
  - `cwd` = `os.environ["OWD"]` se existir e for diretório, senão `dirname(APPIMAGE)`, senão `HOME`;
  - **nunca** um caminho sob `APPDIR`/montagem;
  - `env = host_env()` com `PYINSTALLER_RESET_ENVIRONMENT=1` (a nova instância não pode herdar o estado do bootloader antigo);
  - continua `start_new_session=True`, sem registrar como filho.
- Frozen sem AppImage: mesmo `env`/`PYINSTALLER_RESET_ENVIRONMENT`. Dev: sem mudança.
- **Aceite:**
  - K: cwd nunca começa com `APPDIR`; `PYINSTALLER_RESET_ENVIRONMENT=="1"`;
  - N2-AI `JARVIS_SMOKE_RESTART=1`: a 2ª instância imprime `READY` depois de a 1ª sair, e o teste encerra os dois PIDs registrados.
- **Testes (executor):** K `tests/unit/platform/test_restart_appimage.py`.

### F5-05 — Desktop entry no AppImage
- **Onde:** `jarvis/platform/linux/desktop_entry.py::ensure_desktop_entry` (âncora `Exec=`).
- **Depois:** com `APPIMAGE`, grava `Exec="<APPIMAGE>" %U`, `TryExec=<APPIMAGE>` e `Icon=<APP_ID>`, e copia o ícone 256px do AppDir para `$XDG_DATA_HOME/icons/hicolor/256x256/apps/<APP_ID>.png`. É idempotente e só regrava se o `Exec` mudou (o AppImage pode ter sido movido). Dev: sem mudança.
- A integração visível no menu (`NoDisplay=false`) é **opt-in** pelo comando "instalar atalho no menu" ou por AppImageLauncher/Gear Lever (D-F5-10). Por padrão continua `NoDisplay=true`: só identidade para o portal/notificações.
- **Testes (executor):** K `tests/unit/platform/test_desktop_entry_appimage.py`.

### F5-06 — Chromium do Playwright sob demanda em XDG
- **Onde:** `jarvis/browser/playwright_setup.py` (âncoras `# Em modo frozen: _internal/playwright/driver/package/.local-browsers` e `if "PLAYWRIGHT_BROWSERS_PATH" not in env:`).
- **Depois:** Linux frozen → `PLAYWRIGHT_BROWSERS_PATH` padrão `$XDG_DATA_HOME/jarvis/ms-playwright` (a variável do usuário vence). `ensure_chromium_sync` baixa para lá sob demanda. O driver (node) continua no bundle. Windows e dev literais.
- O Chromium baixado usa as libs do **sistema** (§5). Se faltar alguma, o erro do Playwright é mostrado ao usuário com a lista da §5 e o nome do pacote da distro. O `--no-sandbox` de fallback já existe.
- **Aceite:**
  - golden Windows;
  - K linux frozen;
  - N2-AI (**slow**, com rede no container): `JARVIS_SMOKE_PLAYWRIGHT=1` baixa e sobe o Chromium headless uma vez em fedora44.
- **Testes:** qa C `tests/golden/test_playwright_path_windows.py`; executor K `tests/unit/test_playwright_path_linux_frozen.py`.

### F5-07 — Live-source do `launcher.py` no Linux congelado
- **Onde:** `launcher.py::_find_source` (âncora `candidate = os.path.normpath(os.path.join(exe_dir, "..", ".."))`).
- **Problema:** no AppImage, "dois níveis acima do exe" cai dentro da montagem ou de `squashfs-root`. Se o usuário extraiu o AppImage dentro de um checkout, isso rodaria `.py` de outra versão com as libs do bundle.
- **Depois:**
  - `if sys.platform == "win32":` → corpo **literal** atual;
  - senão → só `JARVIS_SOURCE` explícito **e** `JARVIS_DEV=1` (**D-F5-8**), com aviso no stderr `[LAUNCHER] live-source: <path>`.
  - O `launcher.py` roda antes do pacote `jarvis`, então entra na allowlist C1 com justificativa.
- **Aceite:** golden Windows (as 4 combinações frozen/JARVIS_SOURCE); K linux (nunca usa `../..`; exige as duas variáveis).
- **Testes:** qa C `tests/golden/test_launcher_windows.py`; executor K `tests/unit/test_launcher_linux.py`.

### F5-08 — Runtime hook Linux
**`packaging/linux/rthook_linux.py`** (executado pelo bootloader antes do `launcher.py`, só no spec Linux):
1. **PortAudio:** o `sounddevice` procura a lib com `ctypes.util.find_library("portaudio")` (ldconfig) e **não acha a lib embutida**. O hook embrulha `ctypes.util.find_library`: para `"portaudio"` devolve `<_MEIPASS>/libportaudio.so.2` se o arquivo existir; os outros nomes passam direto.
2. **ffmpeg/ffplay embutidos:** prefixa o `PATH` com `<_MEIPASS>/bin` (o `shutil.which("ffplay")` do `main.py` encontra sem mudar o código).
3. `os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", <XDG_DATA_HOME>/jarvis/ms-playwright)` (redundante com a F5-06, por segurança).
4. **Não** mexe em `QT_*`: os hooks do PyInstaller para PySide6 já apontam `QtWebEngineProcess`/recursos. O `prepare_env` da F1-06 continua decidindo sandbox e QPA.

**Aceite:** N2-AI imprime `[AUDIO]` sem "indisponível" e `JARVIS_SMOKE_AUDIO ffplay=<_MEIPASS>/bin/ffplay`; na `appimage-bare` (sem portaudio/ffmpeg do sistema) funciona igual.

**Testes (executor):** K `tests/unit/test_rthook_linux.py` (carrega o hook com `sys._MEIPASS` falso).

### F5-09 — `packaging/linux/JARVIS-linux.spec`
**Decisão (ponto 1): spec Linux separado.** Motivos para não ramificar o `JARVIS.spec`:
- ele tem caminhos do Windows (`.venv\Lib\site-packages\webview\__pyinstaller`, `jarvis_icon.ico`, `win_*`);
- tem hiddenimports `webview.platforms.edgechromium/winforms/mshtml`;
- é lido pelo teste W6;
- **qualquer edição é risco no build do .exe sem ter Windows para provar**.

O custo é duplicar as listas `collect_all`. A mitigação é a hidden list do Linux ser **gerada** e um teste comparar os pacotes coletados.

**Conteúdo:**
- `Analysis(['launcher.py'])`, `pathex=[ROOT]`;
- `hookspath` = `webview/__pyinstaller` do Python do build, resolvido via `importlib.util.find_spec("webview")` (sem caminho fixo);
- `runtime_hooks=[packaging/linux/rthook_linux.py, rthook_errlog.py]`;
- `hiddenimports` = mesma base de pacotes do `JARVIS.spec` **sem** as plataformas Windows do webview + `webview.platforms.qt` + `collect_submodules("jarvis.platform")`, filtrando `jarvis.platform.windows.*` + todos os módulos das entradas `linux-*`/`common` do `REGISTRY` (lidos importando `jarvis.platform.registry`);
- `datas`: os mesmos assets do projeto (`ui/`, `config/` …), e `binaries` extras: `libportaudio.so.2` (compilada/instalada no container de build) e `bin/ffmpeg`, `bin/ffplay`, `bin/ffprobe` (estáticos, versão fixada com sha256, **D-F5-4**);
- `excludes`: os do Windows + os pacotes pesados definidos em **D-F5-3** (§6);
- `EXE(name="JARVIS", console=False, upx=False, strip=False)`;
- `COLLECT(name="JARVIS")`.

**Aceite:**
- C: sha256 do `JARVIS.spec` == `ab4404c`;
- K W6-Linux: todo módulo `linux-*`/`common` do `REGISTRY` está na hidden list gerada e **existe no bundle** (`build-appimage/.../base_library`/PYZ listado com `pyi-archive_viewer`);
- B: o build termina sem `WARNING: Hidden import ... not found` de `jarvis.*`.

**Testes:**
- qa: C `tests/golden/test_windows_spec_frozen.py` (hash);
- executor: K `tests/unit/test_linux_spec_hidden.py` (parse do spec + registro);
- qa: verificação B no script de build.

### F5-10 — AppDir, appimagetool e integração com o desktop
**`packaging/linux/build_appimage.sh`** roda **dentro** do container de build; o host não instala nada:
1. `python3.12 -m pip install -r requirements.txt` com o índice CPU do torch se D-F5-3 incluir torch, e `pyinstaller`;
2. `pyinstaller packaging/linux/JARVIS-linux.spec --noconfirm --distpath build-appimage/dist --workpath build-appimage/work`;
3. **AppDir:**
   - `usr/lib/jarvis/` = saída onedir;
   - `AppRun`;
   - `<APP_ID>.desktop` na raiz;
   - `usr/share/applications/<APP_ID>.desktop`;
   - `usr/share/icons/hicolor/{256x256,512x512}/apps/<APP_ID>.png`;
   - `.DirIcon`;
   - `usr/share/metainfo/<APP_ID>.metainfo.xml`;
   - **`THIRD_PARTY_LICENSES.txt`** na raiz do AppDir (D-F5-4): gerado no build com a licença do Jarvis (Apache-2.0), mais os textos de licença das wheels coletadas (`importlib.metadata` → `License`/arquivos `LICENSE*` do `dist-info`), do Qt/PySide6 (LGPLv3), do ffmpeg LGPL (com a origem e o sha256 do build) e do PortAudio. O build falha se faltar a licença de ffmpeg, Qt ou PortAudio.
4. **Remover do AppDir** as libs que precisam vir do sistema (§5, lista "PROIBIDO EMBUTIR"). O build **falha** se alguma sobrar.
5. **Checagem de glibc:** falha se algum ELF exigir `GLIBC_2.29` ou mais.
6. `appimagetool` com **runtime estático** (type2-runtime; release **fixada por versão + sha256** em `tests/docker/Dockerfile.appimage-build`): `ARCH=x86_64 appimagetool -u "gh-releases-zsync|SodreDev|jarvis-releases|latest-pre|JARVIS-*-x86_64.AppImage.zsync" AppDir dist-appimage/JARVIS-<TAG>-x86_64.AppImage`, que gera também o `.zsync`. `<TAG>` = `v<VERSION>-linux.<N>` (§4 F5-11), passado por `JARVIS_BUILD_TAG`;
7. `sha256sum` → `dist-appimage/SHA256SUMS-linux.txt`.

- **`AppRun`** (sh):
  ```sh
  #!/bin/sh
  HERE="$(dirname "$(readlink -f "$0")")"
  export JARVIS_APPDIR="$HERE"
  exec "$HERE/usr/lib/jarvis/JARVIS" "$@"
  ```
  O fallback `APPIMAGE_EXTRACT_AND_RUN=1` é do próprio runtime e fica documentado na mensagem de erro de FUSE e no README da release.
- **`.desktop`:** `Type=Application`, `Name=J.A.R.V.I.S.`, `Exec=JARVIS %U` (o appimagetool reescreve na integração), `Icon=<APP_ID>`, `Categories=Utility;`, `StartupWMClass=JARVIS`, `X-AppImage-Version=<VERSION>`.
- **AppStream** (`metainfo.xml`): `id=<APP_ID>`, `metadata_license=CC0-1.0`, `project_license` = licença do repositório (conferir `LICENSE`), `name`, `summary`, `launchable desktop-id`, `releases` com a versão. Validar com `appstreamcli validate` no container (aviso não bloqueia; erro bloqueia).
- **Ícones:** `packaging/linux/make_icons.py` gera PNGs 256/512 a partir de `jarvis_icon.ico` (Pillow; usa o maior frame disponível).
- **Nome do arquivo:** `JARVIS-<TAG>-x86_64.AppImage` (ex.: `JARVIS-v2.7.0-linux.1-x86_64.AppImage`). O `.zsync` aponta para o nome publicado, e nenhum nome casa com os padrões do updater do Windows (§4 F5-11).

**Aceite:** B verde; `appstreamcli validate` sem erro; `desktop-file-validate` sem erro; AppImage executável; N2-AI/N3-AI (F5-13).

**Testes:** executor K `tests/unit/test_packaging_linux_files.py` (desktop/metainfo parseáveis, `APP_ID` casa com `jarvis/platform/linux/app_id.py`, `AppRun` é executável); qa faz a verificação B.

### F5-11 — Atualização no AppImage
**Estado atual:** `self_update_payload` troca `.py` sobre a pasta do projeto. No AppImage isso é **impossível** (read-only) e **perigoso**: se o `_base_dir` apontasse para XDG, gravaria `.py` que ninguém executa. A feature **já é falsa no Linux** (tabela estática da Fase 1: só win32). Um teste K precisa garantir que continue falsa com `APPIMAGE` definido.

**Canal (DECIDIDO pelo dono em 2026-09-14, D-F5-1):** o AppImage sai como **pré-release no `SodreDev/jarvis-releases`**. O Windows só ganha release depois do N4.

**Proteção do updater do Windows** (`updater/check_update.py`, âncora `url = f"{API_BASE}/repos/{repo}/releases/latest"`). Ele consulta `/releases/latest`, que **ignora pré-releases**. Depois escolhe asset `name.lower()` que `startswith("update_payload") and endswith(".zip")` (payload aplicado automaticamente) ou que `endswith(".exe") and "setup" in name` (instalador). Três travas independentes:

1. **Nunca "Latest".** Toda release Linux é criada com `gh release create ... --prerelease --latest=false` e nunca é editada para release normal. O `tools/make_release_linux.py` (F5-12) imprime esse comando e, só no modo `--publish`, o executa com as duas flags. Um teste K garante isso, e nenhum outro comando de publicação existe no script.
2. **Nomes de asset que não casam com o updater do Windows:**
   - `JARVIS-<TAG>-x86_64.AppImage`;
   - `JARVIS-<TAG>-x86_64.AppImage.zsync`;
   - `SHA256SUMS-linux.txt`;
   - `RELEASE_NOTES-linux.md`.

   Proibido no Linux: qualquer asset com prefixo `update_payload`, extensão `.zip` ou `.exe`, ou "setup" no nome. Um teste K chama `check_for_update` com `_http_get` falso devolvendo uma release só com esses assets e exige `asset is None` e `installer is None`.
3. **A tag não confunde a comparação de VERSION** (`version.py::version_tuple` descarta tudo depois do primeiro `-`):
   - **esquema:** `v<VERSION>-linux.<N>` (ex.: `v2.7.0-linux.1`, `v2.7.0-linux.2`, e depois da próxima versão comum `v2.8.0-linux.1`);
   - `<VERSION>` é o `VERSION` compartilhado do commit do build (versão unificada, U1) e `<N>` é o contador de builds Linux daquela versão;
   - para o Windows, `version_tuple("2.7.0-linux.3") == (2, 7, 0)`, que **não** é maior que a 2.7.0 instalada. Mesmo que uma pré-release escapasse para "Latest", não haveria update falso na mesma versão, e sem asset compatível (trava 2) nada seria aplicado;
   - quando a próxima release normal do Windows sair (`v2.8.0`), a comparação dele é a de sempre;
   - o Linux compara com a própria chave `(version_tuple(base), N)`, ex.: `v2.8.0-linux.1` > `v2.7.0-linux.9`;
   - o `VERSION` do bundle recebe a tag completa em `X-AppImage-Version` e num arquivo `JARVIS_BUILD_TAG` dentro do AppDir.

**Update-info embutido.** Confirmado na [AppImageSpec (draft)](https://github.com/AppImage/AppImageSpec/blob/master/draft.md): o `latest` do `gh-releases-zsync` **ignora pré-releases**; **`latest-pre`** pega a pré-release mais recente; **`latest-all`** pega a mais recente entre release e pré-release; qualquer outro valor é tag fixa.

- **Escolhido:**
  ```
  gh-releases-zsync|SodreDev|jarvis-releases|latest-pre|JARVIS-*-x86_64.AppImage.zsync
  ```
  Hoje toda pré-release do repo é Linux. `latest-all` fica **rejeitado**: quando a primeira release normal do Windows sair (sem AppImage), ela vira a mais recente, o padrão não casa e a atualização do AppImage quebra.
- **Regra de convivência** (vale enquanto `latest-pre` estiver em uso): **toda pré-release no `jarvis-releases` precisa ter os assets Linux.** Beta do Windows não pode sair como pré-release lá, a menos que a mesma tag leve também o AppImage (versão unificada).
- **Plano B**, se essa regra não puder ser mantida: tag fixa de canal `linux-stable` (pré-release, assets substituídos a cada build) com `zsync|https://github.com/SodreDev/jarvis-releases/releases/download/linux-stable/JARVIS-x86_64.AppImage.zsync`. Não depende de "latest" nenhum. Ele custa uma release mutável.
- O repo e o canal ficam em um lugar só: `JARVIS_UPDATE_REPO=SodreDev/jarvis-releases` e `JARVIS_UPDATE_CHANNEL=latest-pre` no `build_appimage.sh`.

**No app** (`jarvis/platform/linux/appimage_update.py`) — **verificação própria**, que não depende do zsync:
- `check() -> dict | None` via `GET /repos/SodreDev/jarvis-releases/releases?per_page=30`:
  - filtra `prerelease is True`, tag que casa com `^v\d+\.\d+\.\d+-linux\.\d+$` e asset que termina em `-x86_64.AppImage`;
  - pega a maior chave `(version_tuple(base), N)` e compara com o `JARVIS_BUILD_TAG` do bundle;
  - devolve `{latest_tag, current_tag, url_pagina, url_appimage}`;
  - rede com timeout de 10 s e silêncio em falha (como o updater atual);
  - token opcional pelo mesmo caminho de config do `check_update` (sem ler segredo novo);
  - **nunca** usa `/releases/latest`.
- `can_apply` = `shutil.which("appimageupdatetool")` existe **e** `os.access(APPIMAGE, W_OK)`.
- `apply()` = `Popen(["appimageupdatetool", APPIMAGE], env=host_env())` (o arquivo antigo vira `.zs-old`); ao terminar com código 0, oferece reiniciar via `restart_self`.

**No `main.py`:**
- `_iniciar_verificador_updates` (âncora `if _smoke_seconds() is None and _has_feature("self_update_payload"):`) ganha `elif _smoke_seconds() is None and _plat_current().appimage:` → thread `AppImageUpdateCheck` 30 s depois do boot → mensagem no chat "Nova versão X disponível: <link>" (+ "diga 'atualizar' para aplicar" se `can_apply`).
- `apply_update_now` (âncora `if not _has_feature("self_update_payload"):`): no AppImage, devolve `{"ok": True, "updated": False, "msg": <aviso + link>}`, ou aplica via `appimageupdatetool` se `can_apply`.
- **O ramo do Windows não muda.**
- Embutir o `appimageupdatetool` no bundle fica fora do v1 (**D-F5-9**).

**Aceite:**
- K: API falsa (versão igual, maior, menor e erro) → mensagens; `self_update_payload` falso com `APPIMAGE`;
- AST: o ramo win32 fica idêntico;
- N2-AI `JARVIS_SMOKE_UPDATE_URL=<servidor http local no container>` → `JARVIS_SMOKE_UPDATE available=<v>`.

**Testes:** executor K `tests/unit/platform/test_appimage_update.py` e K AST `tests/unit/test_main_update_branches.py`.

### F5-12 — Release Linux: segredos e checksums
- **`tools/make_release_linux.py`** (novo) **importa** `scan_secrets` e `write_checksums` de `tools/make_release.py` (que não é editado). Etapas:
  1. `scan_secrets(ROOT)`: aborta se achar algo, **sem** `--force` por padrão;
  2. `scan_secrets` também no **AppDir** gerado (pega segredo que foi parar em `datas`) e confirma a **ausência** de: pasta de credenciais com arquivos além dos templates, `.spotify_cache`, `arquivos.vcf`, `data/`, `crash*.log`, `*.bak`, `.venv*`;
  3. roda `tests/docker/build_appimage.sh` via podman;
  4. `write_checksums([AppImage, zsync])` → `SHA256SUMS-linux.txt`;
  5. assinatura GPG destacada `SHA256SUMS-linux.txt.asc` **só** com `--sign` e chave configurada (**D-F5-5**);
  6. valida a tag (`^v\d+\.\d+\.\d+-linux\.\d+$`, com base igual ao `VERSION`) e os nomes dos assets (nenhum `update_payload*`, `.zip`, `.exe` ou "setup");
  7. gera `RELEASE_NOTES-linux.md` e **imprime** o comando de publicação: `gh release create <TAG> --repo SodreDev/jarvis-releases --prerelease --latest=false --title "J.A.R.V.I.S. <TAG> (Linux, pré-release)" --notes-file RELEASE_NOTES-linux.md <4 assets>`. **Por padrão só imprime.**
  8. **Modo `--publish` (explícito, D-F5-6):** executa **exatamente** esse comando.
     - A **CLI release** só roda com ordem do orquestrador, depois do M2 da Fase 5 verde.
     - Pré-condições (cada uma aborta sem publicar):
       - scan limpo (repo e AppDir);
       - `sha256sum -c` ok;
       - tag e nomes de asset válidos;
       - a tag ainda não existe no repo;
       - o comando montado contém `--prerelease` **e** `--latest=false`.
     - Não existe caminho no script para release normal, para `--latest` nem para editar release existente.
     - Depois de publicar, confere via API que a release tem `prerelease: true` e que `/releases/latest` **não** mudou.
- **Aceite:**
  - K com uma árvore falsa contendo um segredo de mentira → aborta;
  - `SHA256SUMS-linux.txt` confere com `sha256sum -c`;
  - tag ou nome de asset fora da regra → aborta;
  - o comando impresso tem `--prerelease` **e** `--latest=false`;
  - **sem `--publish`**, nenhum `subprocess` de publicação é chamado (espião);
  - **com `--publish`** e pré-condição falhando → aborta sem chamar;
  - **com `--publish`** e tudo ok → exatamente uma chamada, com as duas flags;
  - verificação pós-publicação com API falsa (`prerelease: false` ou `/releases/latest` mudado → erro alto).
- **Testes (executor):** K `tests/unit/test_make_release_linux.py`.

### F5-13 — Smoke do AppImage (qa)
- **`tests/docker/run_appimage_smoke.sh <imagem> [N2|N3]`:**
  - monta `dist-appimage/*.AppImage` **read-only** no container;
  - `HOME`/`XDG_*` em tmpfs;
  - `APPIMAGE_EXTRACT_AND_RUN=1`;
  - `JARVIS_TEST_SANDBOXED=1`;
  - `SDL_AUDIODRIVER=dummy`;
  - sem `/dev/snd`, PipeWire ou D-Bus do host.
- **Testes** (`tests/smoke/test_appimage_*.py`, markers `appimage`, `needs_display`, `slow`):
  - **boot** (as 4 distros + `appimage-bare` + sandbox Debian 13);
  - **tray** (watcher falso → `setup True`);
  - **áudio** (`JARVIS_SMOKE_AUDIO=1`, ffplay embutido, `children_alive=0`);
  - **PTT** (N3, `kglobalacceld` no container → `JARVIS_SMOKE_PTT press`);
  - **restart** (F5-04);
  - **host_env** (F5-03);
  - **update** (F5-11).
- **Read-only de verdade:** `--appimage-extract` para um diretório, `chmod -R a-w squashfs-root`, e rodar `squashfs-root/AppRun` com o smoke. Qualquer tentativa de escrita dentro da árvore falha o teste (grep de `Read-only file system`/`PermissionError` no stderr + `find squashfs-root -newer <marca>` vazio).
- **Sandbox do orquestrador:** copiar o AppImage para a workdir do Jarvis e rodar `APPIMAGE_EXTRACT_AND_RUN=1` com `DISPLAY=:99`.
- **Registro de tamanho:** o script imprime o tamanho do AppImage, do onedir e os 20 maiores diretórios do bundle. Esses números alimentam a §6.

---

## 5. Dependências de runtime: dentro × sistema

**DENTRO do AppImage (embutido):**
- Python 3.12 e todas as wheels (manylinux ≤ 2_28);
- **PySide6 6.9.3**: Qt6, QtWebEngine, `QtWebEngineProcess`, `qtwebengine_resources*.pak`, `icudtl.dat`, `v8_context_snapshot.bin`, `qtwebengine_locales/`, plugins `platforms/libqxcb.so` e `libqwayland-*.so`, `xcbglintegrations`, `wayland-*-integration`;
- libs de apoio do Qt que **não** estão na lista abaixo: `libxcb-cursor`, `libxcb-icccm`, `libxcb-keysyms`, `libxcb-shape`, `libxkbcommon-x11`, `libXtst`, `libwayland-cursor`, `nss`/`nspr` (usados pelo QtWebEngine);
- **PortAudio** (`libportaudio.so.2`) + hook F5-08;
- **ffmpeg/ffplay/ffprobe estáticos** (D-F5-4);
- driver do Playwright (node);
- assets `ui/`, `config/`;
- ícones e metainfo.

**SISTEMA (nunca embutir):**
- **glibc** e cia. (`libc`, `libm`, `libdl`, `libpthread`, `librt`);
- **stack de GPU**: `libGL`, `libEGL`, `libGLX`, `libGLdispatch`, `libgbm`, `libdrm`, drivers mesa/nvidia;
- **`libasound`**: o ALSA carrega plugins do sistema (`pipewire-alsa`/`pulse`), e com a lib embutida o áudio não chega ao PipeWire;
- `libwayland-client`/`libwayland-egl`, que casam com o compositor;
- `libX11`, `libxcb` (base), `libfontconfig`, `libfreetype`, `libharfbuzz`, `libdbus-1`, `libglib-2.0`/`libgobject` e `libz`.
- Regra: seguir o `excludelist` da comunidade AppImage (pkg2appimage/linuxdeploy) nesses nomes. O build **falha** se algum estiver no AppDir. Ajustes vêm do smoke na `appimage-bare`.

**Serviços do sistema (runtime, cada um com degradação já implementada nas Fases 1–2):**

| Serviço | Sem ele |
|---|---|
| PipeWire (ou PulseAudio) + `pipewire-alsa` | sem áudio / mic "indisponível" |
| `wpctl`/`pactl` | volume indisponível (F2-03) |
| D-Bus de sessão | tray/notificações/portal/idle indisponíveis |
| `xdg-desktop-portal` (+ `-kde`/`-gnome`) e `kglobalacceld` (KDE) | PTT global no Wayland → `backend=none` (F2-01) |
| StatusNotifierWatcher (Plasma; GNOME com extensão AppIndicator) | tray indisponível e o X fecha o app |
| `xdg-utils` (`xdg-open`)/`gio` | open_path indisponível |
| `wl-clipboard` ≥ 2.3.0 ou Klipper; `xclip`/`xsel` no X11 | clipboard/monitor indisponível (F2-04) |
| `playerctl` (opcional; MPRIS por D-Bus já cobre) | — |
| daemon de notificações | notificações indisponíveis |
| fontes (Arch base não traz nenhuma: `ttf-dejavu`/`noto-fonts`) | **o QtWebEngine trava** (MATRIZ) → a mensagem na release precisa listar |
| libs do **Chromium do Playwright** (baixado, não embutido): as mesmas da MATRIZ (`nss`, `libXcomposite`, `libXdamage`, `libXrandr`, `alsa-lib`, `libxkbcommon`, `mesa` …) | mensageria indisponível, com mensagem |
| FUSE | **não precisa** (runtime estático); sem FUSE no kernel ou no container → `APPIMAGE_EXTRACT_AND_RUN=1` |

A imagem `appimage-bare` instala **só** a coluna SISTEMA (nomes apt da MATRIZ). O smoke nela é a prova de que a coluna DENTRO está completa.

## 6. Tamanho e escopo do v1 (ponto 7)

**Números medidos** no `.venv-linux` do host (`du -sm`, CUDA incluso): `nvidia` 3.196 MB, `torch` 1.116 MB, `triton` 894 MB, `playwright` 134 MB, `spacy` 115 MB, `scipy` 80 MB, `cv2` 72 MB, `transformers` 53 MB, `pandas` 41 MB, `numpy` 32 MB. `site-packages` total: **6.960 MB**.

**Com torch CPU** (índice CPU, sem `nvidia`/`triton`), estimativa a confirmar no 1º build (F5-13):

| Variante | Conteúdo | onedir | AppImage (squashfs) |
|---|---|---|---|
| **Completa** | tudo, com torch CPU | ~1,8–2,2 GB | ~0,8–1,0 GB |
| **Núcleo** | sem `torch`, `triton`, `nvidia-*`, `kokoro`/`misaki`/`spacy`/`thinc`/`blis`, `easyocr`, `rembg`/`onnxruntime` (se só o rembg usar), `mediapipe`, `sentence-transformers`/`transformers` | ~700–900 MB | **~300–400 MB** |

**Quem usa os pesados** (imports encontrados):
- `VozIa/kokoro_tts_engine.py` (TTS offline);
- `core/vad_filter.py` (silero VAD);
- `classifiers/embeddings.py` e `comandos/memoria_contatos.py` (MiniLM);
- `comandos/ocr_ctrl.py` (easyocr, Fase 3);
- `comandos/image_gen_ctrl.py` (rembg);
- `core/presence_detector.py`, `gesture_interface/*` (mediapipe, Fase 4);
- `comandos/discord_ctrl.py`;
- `main.py`.

**DECIDIDO (D-F5-3, 2026-09-14):** v1 = **Núcleo**, meta **≤ 450 MB**; teto duro de 700 MB, acima disso o build falha.
- TTS por edge-tts/ElevenLabs/Gemini (nuvem), STT pelo Groq (nuvem).
- VAD e embeddings desligados com mensagem **se** a F5-01 (inventário) confirmar que degradam sem quebrar.
- Os pesados voltam depois como **"Pacote de modelos"** opcional: wheels baixadas para `$XDG_DATA_HOME/jarvis/extras/python3.12/site-packages`, entrando no `sys.path` pelo `rthook_linux`. Mesma ABI do Python embutido.
- Os pesados também podem vir numa variante `JARVIS-full` do AppImage.

**F5-01 (qa + executor, antes do spec):**
- inventário AST de cada import pesado;
- confirmar que está dentro de função/`try`;
- testar a degradação num venv sem os pacotes do Núcleo (N1: `import` de todos os módulos do boot + smoke N2 com esse venv).
- Se algum quebrar no import de topo → emenda (guard como na F1-05).

## 7. Riscos

| # | Risco | Mitigação |
|---|---|---|
| R1 | Build do Windows mudar sem ninguém perceber | `JARVIS.spec` intocado com hash congelado; `tools/make_release.py` não é editado; mudanças no `launcher.py`/`config.py`/`main._data`/`updater`/`playwright_setup` com golden (F5-02, F5-06, F5-07) + checklist N4 do .exe |
| R2 | Gravação dentro da montagem (EROFS) em caminho não inventariado | teste read-only da F5-13; todo `open(..., "w")` com caminho derivado de `__file__`/`sys.executable` vira backlog se aparecer |
| R3 | `LD_LIBRARY_PATH` do bundle vazando para ferramentas do sistema | F5-03 + smoke `host_env` |
| R4 | `libasound`/GL/wayland embutidos quebrando áudio ou GPU | lista PROIBIDO EMBUTIR com o build falhando + smoke na `appimage-bare` |
| R5 | Sandbox do QtWebEngine no AppImage (Ubuntu 24.04 AppArmor bloqueia userns; Arch forçado pelo pywebview) | `decide_sandbox` da F1-06 já cai para off com o motivo; N2-AI no ubuntu2404 |
| R6 | Runtime estático × AppImageLauncher antigo (issue conhecida do type2-runtime) | documentar na release; `APPIMAGE_EXTRACT_AND_RUN=1` como contorno; fixar a versão do runtime |
| R7 | PySide6 aarch64 é `manylinux_2_39` | v1 só x86_64 (D-F5-7) |
| R8 | Tamanho | meta/teto da §6 com o build falhando acima do teto |
| R9 | Pré-release Linux chegando às instalações Windows por auto-update, ou update do AppImage apontando para release só-Windows | três travas da F5-11 (nunca Latest, nomes de asset, esquema de tag); `latest-pre` + regra "toda pré-release leva assets Linux"; verificação própria via `/releases` filtrando pré-release e `*.AppImage`; plano B: tag fixa `linux-stable` |
| R10 | Sessão/portal: `.desktop` com `Exec` antigo depois de mover o AppImage | F5-05 regrava quando o `Exec` muda |
| R11 | Segredos ou PII no bundle (`datas` puxando pastas locais) | scan no AppDir + lista de ausência (F5-12) |
| R12 | Licenças: ffmpeg, Qt LGPL (PySide6 dinâmico está ok), libs no bundle | D-F5-4 decidida (ffmpeg LGPL, Jarvis Apache-2.0); `THIRD_PARTY_LICENSES.txt` obrigatório na F5-10 |
| R13 | Publicação automatizada virar release normal ou "Latest" | F5-12 `--publish` só com pré-condições; só `--prerelease --latest=false`; verificação pós-publicação de `/releases/latest`; só a CLI release roda, sob ordem do orquestrador, depois do M2 |

## 8. Decisões D-F5 (todas DECIDIDAS em 2026-09-14: D-F5-1 pelo dono; as demais pelo orquestrador, com autonomia delegada pelo dono)

| ID | Decisão | Recomendação |
|---|---|---|
| **D-F5-1** | **DECIDIDA pelo dono (2026-09-14):** o AppImage sai como **pré-release no `SodreDev/jarvis-releases`**; o Windows só ganha release depois do N4 | Aplicado na F5-11/F5-12: `--prerelease --latest=false`; tags `v<VERSION>-linux.<N>`; assets sem `update_payload`/`.zip`/`.exe`/"setup"; update-info `gh-releases-zsync|SodreDev|jarvis-releases|latest-pre|JARVIS-*-x86_64.AppImage.zsync`; plano B: tag fixa `linux-stable` |
| **D-F5-2** | **DECIDIDA (2026-09-14):** App ID = `io.github.ninjazins2.Jarvis`. Fecha também a D-F2-2. | Aplicado em `jarvis/platform/linux/app_id.py`, `.desktop`, metainfo e ícones. |
| **D-F5-3** | **DECIDIDA (2026-09-14):** AppImage **Núcleo** no v1, meta **≤ 450 MB**, teto **700 MB** (acima disso o build falha). O "Pacote de modelos" fica para depois. | `excludes` do Núcleo no `JARVIS-linux.spec` (F5-09), com base no inventário da F5-01. |
| **D-F5-4** | **DECIDIDA (2026-09-14):** ffmpeg estático **LGPL com ffplay**. A `LICENSE` do Jarvis será **Apache-2.0** (decisão do dono). | Versão fixada com sha256 no container de build. O `THIRD_PARTY_LICENSES.txt` no AppDir entra **na F5-10**, não no backlog. |
| **D-F5-5** | **DECIDIDA (2026-09-14):** só `SHA256SUMS-linux.txt` no v1, sem GPG. | A opção `--sign` da F5-12 fica fora do v1. |
| **D-F5-6** | **DECIDIDA (2026-09-14), MUDOU:** o dono autorizou o orquestrador a publicar depois dos testes. A **pré-release Linux** é publicada pela **CLI release, sob ordem do orquestrador**, depois do **M2 da Fase 5 verde** (matriz + sandbox). O N-dono é recomendado, mas **não bloqueia** a pré-release. A release normal/Windows continua **só depois do N4**. | Modo `--publish` explícito da F5-12, sempre `--prerelease --latest=false`. |
| **D-F5-7** | **DECIDIDA (2026-09-14):** só x86_64. | — |
| **D-F5-8** | **DECIDIDA (2026-09-14):** live-source no Linux congelado só com `JARVIS_SOURCE` + `JARVIS_DEV=1`. | F5-07 |
| **D-F5-9** | **DECIDIDA (2026-09-14):** aviso + link; aplicar via `appimageupdatetool` só se ele existir no sistema (não embutido). | F5-11 |
| **D-F5-10** | **DECIDIDA (2026-09-14):** atalho no menu é opt-in ("instalar atalho no menu"), além de AppImageLauncher/Gear Lever. | F5-05 |
