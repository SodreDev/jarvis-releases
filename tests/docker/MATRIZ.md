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
| Xvfb (N2, X11 virtual) | `xorg-x11-server-Xvfb` | `xvfb` | `xorg-server-xvfb` |
| Toolchain de build (evdev do pynput etc.) | `gcc`, `python3-devel`, `kernel-headers` | `gcc`, `python3-dev`, `build-essential` | `gcc`, `base-devel` |

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
