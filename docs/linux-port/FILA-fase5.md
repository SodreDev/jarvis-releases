# FILA — Fase 5 (AppImage), executor: Opus 4.8

Especificação: [SPEC-fase5-appimage.md](SPEC-fase5-appimage.md) · Base: `linux-port@ab4404c` · 2026-09-14.

## Protocolo
1. **Tarefas que tocam caminho do Windows** (F5-02, F5-06, F5-07): o **qa grava antes** o oráculo em `tests/golden/legacy_ab4404c.py` + os golden **C** (passam no código atual) + os **K** em `xfail(strict=True)`.
2. **Tarefas só-Linux ou de packaging:** o **executor escreve os K junto**, no mesmo commit.
3. **Commits:** um por tarefa, mensagem `port(F5-xx): …`, **commit por pathspec**.
4. **Antes de cada commit**, o `.venv-linux` precisa passar em `pytest -m "not slow and not needs_display and not windows_only"`.
5. **Proibido:**
   - editar `JARVIS.spec`, `tools/make_release.py`, `tests/golden/` e `tests/docker/*`;
   - instalar qualquer coisa no host do dono;
   - rodar o AppImage fora de container, KWin virtual ou sandbox;
   - **publicar release**.
6. **Decisões D-F5 abertas:** usar a recomendação da SPEC §8, com os valores num lugar só:
   - `APP_ID` em `jarvis/platform/linux/app_id.py`;
   - `JARVIS_UPDATE_REPO=NinjaZinS2/jarvis-releases`, `JARVIS_UPDATE_CHANNEL=latest-pre` e `JARVIS_BUILD_TAG=v<VERSION>-linux.<N>` no `build_appimage.sh`. O canal pré-release no `jarvis-releases` foi **decidido pelo dono** (D-F5-1).
   - lista de `excludes` do Núcleo no `JARVIS-linux.spec`.
7. **Git e emendas:**
   - `git -C /home/sodre/GranaFacil/J.A.R.V.I.S`, sem push;
   - arquivo fora da SPEC §3 → emenda do arquiteto.

## Ordem

| # | ID | Quem escreve o teste | Testes / verificação | Arquivos de produção | Depende |
|---|---|---|---|---|---|
| 0 | **T0** (qa) | qa | `tests/docker/Dockerfile.appimage-build` (manylinux_2_28 + cp312 + libs de build do Qt + PortAudio + appimagetool/type2-runtime **fixados por sha256**); `Dockerfile.appimage-bare` (debian:stable-slim + coluna SISTEMA da §5); `build_appimage.sh` (wrapper podman); `run_appimage_smoke.sh`; marker `appimage` no `pytest.ini`; C `tests/golden/test_windows_spec_frozen.py` (hash do `JARVIS.spec`) | — | — |
| 1 | **F5-01** inventário de pesados | qa (N1) + executor (emendas de guard, se precisar) | AST dos imports de `torch`/`kokoro`/`easyocr`/`rembg`/`mediapipe`/`transformers`/`sentence_transformers`/`spacy`; venv Núcleo (sem esses pacotes) → import dos módulos do boot + smoke N2 verde; relatório para o arquiteto | — (emenda se aparecer import de topo) | T0 |
| 2 | **G5** (qa, antes) | qa | C `tests/golden/test_runtime_root_windows.py`, `test_playwright_path_windows.py`, `test_launcher_windows.py`; K (xfail) `tests/unit/platform/test_runtime_root_linux.py`, `tests/unit/test_main_data_root.py`, `tests/unit/test_playwright_path_linux_frozen.py`, `tests/unit/test_launcher_linux.py` | — | T0 |
| 3 | **F5-02** runtime_root/XDG | qa (G5) | golden + K acima | `jarvis/platform/protocols.py`, `jarvis/platform/{windows,linux}/paths.py`, `main.py` (`_data`), `config.py` (base do `creds_path`), `jarvis/config/paths.py` (`project_root`), `updater/check_update.py` (`_base_dir`), `rthook_errlog.py`; C1 allowlist (`rthook_errlog.py`) | 2 |
| 4 | **F5-03** host_env | executor (junto) | K `tests/unit/platform/test_host_env.py` | `jarvis/platform/protocols.py`, `jarvis/platform/{windows,linux}/processes.py`, `jarvis/platform/linux/{tools,open_path,notifier,clipboard_klipper,volume,media}.py`, `jarvis/platform/linux_wayland/clipboard.py`, `jarvis/platform/linux_x11/clipboard.py` | — |
| 5 | **F5-04** restart no AppImage | executor (junto) | K `tests/unit/platform/test_restart_appimage.py` | `jarvis/platform/linux/processes.py` | 4 |
| 6 | **F5-05** desktop entry | executor (junto) | K `tests/unit/platform/test_desktop_entry_appimage.py` | `jarvis/platform/linux/desktop_entry.py` | — |
| 7 | **F5-06** Playwright em XDG | qa (G5) | golden Windows + K linux frozen | `jarvis/browser/playwright_setup.py` | 2 |
| 8 | **F5-07** live-source | qa (G5) | golden Windows + K linux; C1 allowlist (`launcher.py`) | `launcher.py` | 2 |
| 9 | **F5-08** rthook Linux | executor (junto) | K `tests/unit/test_rthook_linux.py` | `packaging/linux/rthook_linux.py` | — |
| 10 | **F5-09** spec Linux | executor (K) + qa (hash C do T0) | K `tests/unit/test_linux_spec_hidden.py`; C hash do `JARVIS.spec` inalterado | `packaging/linux/JARVIS-linux.spec` | 1, 3, 8, 9 |
| 11 | **F5-10** AppDir/appimagetool | executor (K) + qa (B) | K `tests/unit/test_packaging_linux_files.py`; **B**: build verde, sem `GLIBC_2.29+`, nenhuma lib PROIBIDO EMBUTIR, `appstreamcli`/`desktop-file-validate` sem erro, `SHA256SUMS-linux.txt` | `packaging/linux/{build_appimage.sh,AppRun,make_icons.py,io.github.ninjazins2.Jarvis.desktop,io.github.ninjazins2.Jarvis.metainfo.xml}`, `.gitignore` | 10 |
| — | **1º build + tamanho** | qa | `run_appimage_smoke.sh fedora44 N2` (boot) + relatório de tamanho → arquiteto confirma meta/teto (§6, D-F5-3) | — | 11 |
| 12 | **F5-11** updater AppImage | executor (junto) | K `tests/unit/platform/test_appimage_update.py`:<br>- API `/releases` falsa: pré-release Linux mais nova/igual/antiga, release Windows normal mais nova ignorada, tag fora do esquema ignorada;<br>- chave `(version_tuple(base), N)`;<br>- nunca chama `/releases/latest`.<br><br>K `tests/unit/test_windows_updater_ignores_linux.py`: `check_for_update` com `_http_get` falso e assets Linux → `asset is None`, `installer is None`; `version_tuple("2.7.0-linux.3") == (2, 7, 0)`.<br><br>AST `tests/unit/test_main_update_branches.py`: ramo win32 idêntico; `self_update_payload` falso com `APPIMAGE`. | `jarvis/platform/linux/appimage_update.py`, `main.py` (âncoras `_iniciar_verificador_updates`, `def apply_update_now`) | 4, 5 |
| 13 | **F5-12** release Linux | executor (junto) | K `tests/unit/test_make_release_linux.py`:<br>- segredo falso aborta;<br>- `SHA256SUMS-linux.txt` confere;<br>- nomes de asset fora dos padrões do updater Windows;<br>- tag no esquema `v<VERSION>-linux.<N>`;<br>- os comandos impressos têm `--prerelease` **e** `--latest=false`;<br>- nenhuma publicação é executada (espião em `subprocess`). | `tools/make_release_linux.py` | 11 |
| 14 | **F5-13** smoke do AppImage (M1) | qa | `tests/smoke/test_appimage_{boot,tray,audio,ptt,restart,host_env,update,readonly}.py` em fedora44/debian12/ubuntu2404/arch + `appimage-bare` (N2-AI), fedora44 N3-AI e sandbox Debian 13 | — | 11, 12 |
| — | **M2** | qa + revisor | M1 ×3; `sha256sum -c`; scan limpo; `git diff --stat ab4404c..linux-port` ⊆ SPEC §3; hash do `JARVIS.spec`; revisão Opus 4.7 | — | 14, 13 |
| — | **N-dono** | dono | Plasma real: duplo clique (FUSE), menu (opt-in), tray, PTT, áudio, aviso de update, checklist N-dono da Fase 2 dentro do AppImage | — | M2 |
| — | **Release** | dono (D-F5-6) | comandos impressos pela F5-12 | — | N-dono (+ N4 para a versão Windows do mesmo tag) |

## Paralelismo (no máximo 3 CLIs)
- **Agora:** qa com **T0**; executor com **F5-03** → **F5-04** → **F5-05** → **F5-08** (nenhuma depende de golden nem do container de build).
- Depois do T0: o qa faz a **F5-01** e grava o **G5**; o executor segue com a **F5-02**, a **F5-06** e a **F5-07**.
- **F5-09/F5-10** esperam a F5-01, porque a lista de `excludes` do Núcleo depende do inventário.
- **F5-11** e **F5-12** podem correr em paralelo com o 1º build.
