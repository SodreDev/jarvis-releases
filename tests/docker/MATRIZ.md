# Matriz de distros — dependências de sistema do Qt/WebEngine/xcb/wayland

Levantado rodando `tests/docker/Dockerfile.<distro>` (fase 1, M1/N1) e
tentando importar `PySide6.QtWebEngineWidgets`/`PySide6.QtWebEngineCore`.
Serve de lista-base para as dependências do AppImage (PyInstaller) e dos
pacotes nativos (rpm/deb/PKGBUILD) de cada distro.

| Propósito | Fedora/Nobara (dnf) | Debian 12 / Ubuntu 24.04 (apt) | Arch (pacman) |
|---|---|---|---|
| XTest (sintetiza eventos, Qt WebEngine usa) | `libXtst` | `libxtst6` | `libxtst` |
| Cursor XCB (plugin `xcb` do Qt) | `xcb-util-cursor` | `libxcb-cursor0` | `xcb-util-cursor` |
| XKB para XCB (teclado, plugin `xcb`) | `libxkbcommon-x11` | `libxkbcommon-x11-0` | `libxkbcommon-x11` |
| ICCCM (gerenciamento de janela sobre libxcb) | `xcb-util-wm` | `libxcb-icccm4` | `xcb-util-wm` |
| Keysyms sobre libxcb | `xcb-util-keysyms` | `libxcb-keysyms1` | `xcb-util-keysyms` |
| Cursor Wayland (plugin `wayland-generic`) | `libwayland-cursor` | `libwayland-cursor0` | `wayland` (inclui) |
| XKB base | `libxkbcommon` | `libxkbcommon0` | `libxkbcommon` |
| Composite/Damage/Randr (X11) | `libXcomposite`, `libXdamage`, `libXrandr` | `libxcomposite1`, `libxdamage1`, `libxrandr2` | `libxcomposite`, `libxdamage`, `libxrandr` |
| NSS (Chromium/QtWebEngine) | `nss` | `libnss3` | `nss` |
| ALSA (áudio) | `alsa-lib` | `libasound2` (Debian 12) / **`libasound2t64`** (Ubuntu 24.04, transição t64) | `alsa-lib` |
| PortAudio (sounddevice) | `portaudio` | `libportaudio2` | `portaudio` |
| Mesa GL | `mesa-libGL` | `libgl1` | `mesa` (inclui) |
| Mesa EGL | `mesa-libEGL` | `libegl1` | `mesa` (inclui) |
| Fontconfig | `fontconfig` | `libfontconfig1` | `fontconfig` |
| D-Bus (libdbus, QtWebEngine) | já vem com o sistema base | `libdbus-1-3` | `dbus` |
| D-Bus runtime (`dbus-run-session`/`dbus-daemon` — N1 K com `private_session_bus`, N3 `run_n3_wayland.sh`; achado no M1 da fase 2: sem isso, N3 falha com "catatonit: failed to exec pid1", e os K com `private_session_bus` só SKIPAM, não falham, escondendo o problema no N1) | `dbus-daemon` (já listado desde o T0) | **`dbus-daemon`** (puxa `dbus-bin`, que dá `dbus-run-session`; não vem só com `libdbus-1-3`/`libdbus-1-dev`) | `dbus` (já traz) |
| XInput2 (libXi, Qt xcb) | já vem com o sistema base | `libxi6` | `libxi` |
| Fontes (QtWebEngine renderiza texto; sem fonte nenhuma, trava em loop de `remote_font_face_source.cc NOTREACHED` antes de chegar a `JARVIS_SMOKE_READY`) | já vem com o sistema base (google-noto-fonts) | já vem com o sistema base (fonts-dejavu-core) | **`ttf-dejavu noto-fonts`** (Arch não traz nenhuma por padrão) — rodar `fc-cache -f` depois de instalar |
| GLib (base do Qt/QtWebEngine) | já vem com o sistema base | `libglib2.0-0` (Debian 12) / **`libglib2.0-0t64`** (Ubuntu 24.04, transição t64) | `glib2` |
| XFixes (Qt xcb/WebEngine, achado no Ubuntu) | já vem com o sistema base | `libxfixes3` | `libxfixes` |
| XShape (plugin `xcb` do Qt — sem ela o `libqxcb.so` não carrega; a mensagem de erro do Qt aponta pro xcb-cursor, enganosa, o real é `libxcb-shape.so.0`, achado no N2 de Debian/Ubuntu) | já vem com o sistema base | `libxcb-shape0` | já vem com o sistema base |
| Xvfb (N2, X11 virtual) | `xorg-x11-server-Xvfb` | `xvfb` | `xorg-server-xvfb` |
| xauth (`xvfb-run` precisa, achado no Debian: "xauth command not found") | já vem com `xorg-x11-server-Xvfb` | `xauth` | `xorg-xauth` |
| Toolchain de build (evdev do pynput etc.) | `gcc`, `python3-devel`, `kernel-headers` | `gcc`, `python3-dev`, `build-essential` | `gcc`, `base-devel` |
| ffmpeg/ffplay (RUNTIME — TTS via edge_tts + ffplay, F2-10c smoke de áudio; sem isso `self._ffplay` fica None e `JARVIS_SMOKE_AUDIO ffplay=ausente`) | **`ffmpeg-free`** (Fedora não traz `ffmpeg` puro nos repos padrão; `ffmpeg-free` tem `ffplay` sem os codecs com patente) | `ffmpeg` | `ffmpeg` |

## Notas

- **Ubuntu 24.04 / transição t64**: pacotes que usam `time_t` de 64 bits em
  arquiteturas de 32 bits ganharam sufixo `t64` nesta versão. O único caso
  que bateu aqui foi `libasound2` → `libasound2t64`; as libs X11/XCB/Wayland
  usadas continuam com o nome de sempre. Se aparecer um `E: Unable to
  locate package libFOO`, procurar `libFOOt64` antes de mais nada.
- **Arch**: `mesa` já traz GL e EGL juntos; `wayland` já traz
  `libwayland-cursor`. Não precisa separar como no dnf/apt.
- **`--index-strategy unsafe-best-match`** é necessário em toda distro que
  usa `--extra-index-url` (índice CPU do torch) — sem ele o uv pode
  resolver `instagrapi` num sdist quebrado (achado na fase 1, ver
  `Dockerfile.fedora44`).
- Cada `Dockerfile.<distro>` é standalone (sem `FROM` de outro Dockerfile
  do repo) e serve tanto pra N1 (sem display) quanto pra N2 (X11 virtual,
  via `xvfb-run`, CMD padrão). N3 (Wayland) usa `run_n3_wayland.sh` com
  `JARVIS_N3_IMAGE=<tag>`.
- **`podman run --init`**: sempre usar (N1/N2/N3). Sem init de verdade no
  container (PID 1 não recolhe órfãos), um neto morto pelo `killpg` que
  perde o pai antes do `wait()` fica reparentado ao PID 1 do container e
  vira ZUMBI pra sempre — achado rodando
  `tests/unit/platform/test_processes_posix.py::test_tree_true_kills_grandchild`
  no N1 das 4 distros (estado `Z` confirmado em `/proc/<pid>/stat`, ppid
  1). Não é bug de produção: num desktop real o systemd recolhe o órfão.
  `run_n3_wayland.sh` já usa `--init`; comandos manuais de N1/N2 devem
  usar também, ex.: `podman run --rm --init -e JARVIS_TEST_SANDBOXED=0
  jarvis-fedora44 pytest -m "not needs_display and not windows_only and
  not slow"`.
- **N3 e `kglobalacceld` (F2-01, fallback do portal)**: `run_n3_wayland.sh`
  sobe `dbus-run-session` + `/usr/libexec/kglobalacceld` (binário sem
  atalho no PATH) ANTES do comando real, no mesmo barramento de sessão.
  Duas variáveis só para o processo do daemon:
  - `QT_QPA_PLATFORM=offscreen` — é app Qt; sem display real aborta com
    core dump tentando o plugin xcb (achado no N1/N3 do G-C, commit
    dcd0611).
  - `XDG_SESSION_TYPE=x11` — com `XDG_SESSION_TYPE=wayland` (o valor que
    o resto do container usa) o binário sai em SILÊNCIO, código 0, sem
    logar nada: ele assume que o compositor Wayland já provê shortcuts
    globais e se recusa a rodar standalone. Com `x11` ele roda normal
    mesmo com `WAYLAND_DISPLAY` real setado (achado preparando o N3 antes
    da F2-01).
  Confirmado manualmente contra o daemon REAL (não um fake dbusmock):
  `doRegister`/`setShortcut`/`getComponent` funcionam e
  `org.kde.kglobalaccel` aparece em `busctl --user list`.
- **N3 e `org.kde.StatusNotifierWatcher` (F2-02, tray)**: ao contrário do
  `kglobalacceld` (daemon real do sistema, sempre precisa estar no ar pra
  PTT funcionar), o watcher da bandeja normalmente vem do `plasmashell` —
  na imagem de teste não tem `plasmashell`, então o barramento privado do
  N3 fica SEM watcher por padrão. Isso é intencional: a SPEC F2-02 manda o
  app fechar quando não acha um watcher, e esse é justamente o cenário que
  `run_n3_wayland.sh` já cobre sem nenhuma mudança (confirmado: sem fake
  nenhum registrado, `RegisterStatusNotifierItem` dá
  `org.freedesktop.DBus.Error.ServiceUnknown`, como esperado).
  Para o caso COM watcher, um teste sobe um FAKE via `python-dbusmock`
  (mesmo padrão de `tests/fakes/dbus_services.fake_dbus_service`, bus_name
  `org.kde.StatusNotifierWatcher`, path `/StatusNotifierWatcher`,
  interface `org.kde.StatusNotifierWatcher`) — SEM precisar mexer no
  `run_n3_wayland.sh`, porque diferente do KGlobalAccel o item se registra
  chamando o método `RegisterStatusNotifierItem(s)` (retorno vazio) uma
  vez, não fica um processo de fundo rodando o tempo todo. Confirmado:
  `mock.AddMethod(IFACE, "RegisterStatusNotifierItem", "s", "", "")` +
  chamar `RegisterStatusNotifierItem("org.jarvis.tray/StatusNotifierItem")`
  aparece em `mock.GetCalls()`.
