# FILA — Fase 1 (executor: Opus 4.8)

Especificação: [SPEC-fase1-boot-linux.md](SPEC-fase1-boot-linux.md) · Arquitetura: [ADR-001](ADR-001-camada-plataforma.md) · Base: `linux-port@1c32e38` · Atualizada em 2026-09-13.

> **Onde esta FILA diverge da SPEC, vale a FILA.** São quatro pontos:
> 1. **F1-13** foi aceita pelo dono com outra implementação: `core/ui_reload.py` / `UiReloadScheduler`. **Não criar `jarvis/webui/reload_guard.py`.**
> 2. **F1-01** entra com o `REGISTRY` vazio.
> 3. As entradas do registro e os testes W6 (hiddenimports) e C1 (allowlist) entram junto com os backends F1-02, F1-06 e F1-14.
> 4. A autoria dos testes segue a coluna "Quem escreve o teste" abaixo.

## Protocolo
1. **Tarefas que movem código do Windows** (F1-02, F1-07, F1-14, F1-15): o **qa** grava os oráculos e testes golden em `tests/golden/` **antes**, e esses testes já passam no código atual. O executor **nunca** edita `tests/golden/`.
2. **Tarefas pequenas** (F1-04, F1-05, F1-09, F1-10) e as demais marcadas "executor": o executor escreve os próprios testes K/AST **no mesmo commit** do código.
3. **Um commit por tarefa**, com a mensagem `port(F1-xx): <resumo>`. Antes do commit, o `.venv-linux` precisa passar em `pytest -m "not slow and not needs_display and not windows_only"`.
4. **W6:** módulo novo carregado pelo registro ou importado pelo `main.py` entra na lista `hidden` do `JARVIS.spec` e no `if False:` do `launcher.py`, no mesmo commit.
5. **Git e localização:**
   - use `git -C /home/sodre/GranaFacil/J.A.R.V.I.S`;
   - nada de push nem reescrita de histórico;
   - localize pelo **trecho-âncora** (as linhas mudam).
6. **Emendas:** arquivo de produção fora da SPEC §3, ou crash novo no smoke → peça emenda ao arquiteto. Área difícil (sandbox, Job Object) → peça detalhe em vez de improvisar.

## Estado e ordem

| # | ID | Estado | Quem escreve o teste | Testes | Arquivos de produção | Depende |
|---|---|---|---|---|---|---|
| — | F1-08 | **FEITO `5c55322`** | executor | `tests/unit/test_windows_subprocess_flags.py` | `main.py`, `comandos/browser_ctrl.py` | — |
| — | extra | **FEITO `df9b245`** | executor | smoke (140 passed) | `comandos/janela_ctrl.py`, `midia_ctrl.py`, `notif_ctrl.py` | — |
| — | F1-11 | **FEITO `5b800fc`** | executor | teste de `core/crash_log.py` (rotação em 5 MB) | `core/crash_log.py`, `main.py` | — |
| — | F1-13 | **FEITO `4173ccb`** (aceito, implementação diferente) | executor | `tests/unit/test_reload_ui.py` | `core/ui_reload.py` (`UiReloadScheduler`: `threading.Timer` de 300 ms, junta os pedidos e recarrega uma vez com o último tema), `main.py` (`reload_ui` retorna na hora; `JarvisApp._request_ui_reload` cria o scheduler sob demanda) | — |
| 1 | F1-01 | **EM ANDAMENTO** | executor | K `tests/unit/platform/test_detect.py` (tabela da SPEC), `test_features.py` (win32 == ALL; wayland == ∅), `test_registry.py` (com registro falso), `test_import_hygiene.py` | `jarvis/platform/{__init__,detect,capabilities,features,registry,protocols,errors}.py`, `common/{base,unavailable}.py`, subpacotes vazios `windows/`, `linux/`, `linux_x11/` e `linux_wayland/`; `REGISTRY` **vazio** | — |
| 2 | G1 | a fazer | **qa (antes)** | C `tests/golden/legacy_1c32e38.py` (oráculos `_appdata_root` e expressão do `storage_path`), `tests/golden/test_paths_windows.py` (quatro funções + `webview_storage_dir`, APPDATA definido/ausente/vazio), `tests/golden/requirements_1c32e38.txt` | — | — |
| 3 | F1-02 | a fazer | executor (K/W6/C1) + qa (golden G1) | K `tests/unit/platform/test_paths_xdg.py`; **W6** `tests/unit/test_pyinstaller_hiddenimports.py`; **C1** `tests/unit/test_platform_checks_allowlist.py` (allowlist congelada neste HEAD); golden G1 verde | `jarvis/platform/windows/paths.py`, `jarvis/platform/linux/{xdg,paths}.py`, entrada `PATHS` no `REGISTRY`, `jarvis/config/paths.py`, `JARVIS.spec`, `launcher.py` | 1, 2 |
| 4 | F1-03 | a fazer | executor (markers) + qa (golden G1; resolve na M1) | `tests/unit/test_requirements_markers.py`; slow `tests/unit/test_requirements_resolve.py` (qa, N1) | `requirements.txt` (pins `pywebview==6.1`, `PySide6==6.9.3` e `QtPy>=2.4,<3` no linux) | 2 |
| 5 | F1-04 | a fazer | executor | K AST `tests/unit/test_main_pynput_guard.py` | `main.py` (âncoras `from pynput import keyboard`, `_SHIFT_KEYS =`, `def _start_keyboard_listener`, `def _start_global_hotkeys`) | 1 |
| 6 | F1-05 | a fazer | executor | K AST `tests/unit/test_main_sounddevice_guard.py` | `main.py` (âncora `import sounddevice as sd` + métodos com `sd.`) | — |
| 7 | F1-06 | a fazer | executor | K `tests/unit/platform/test_webview_engine.py` (`decide_sandbox` passo a passo, com fakes), C `tests/unit/platform/test_webview_windows_noop.py` (`EdgeChromiumEngine`: environ intacto, `start_kwargs() == {}`), K AST `tests/unit/test_main_webview_bootstrap.py`; W6 atualizado | `jarvis/platform/{windows,linux}/webview_engine.py`, entrada `WEBVIEW_ENGINE`, `main.py` (antes de `import webview`; `webview.start(`), `JARVIS.spec`, `launcher.py` | 1 |
| 8 | F1-07 | a fazer | executor (AST) + qa (golden G1) | golden G1 (`webview_storage_dir`) + AST em `test_main_webview_bootstrap.py` | `main.py` (âncoras `_wv_storage = os.path.join(` e `_wv_data = os.path.join(`) | 3 |
| 9 | F1-09 | a fazer | executor | K AST `tests/unit/test_main_feature_gates.py`, `tests/unit/test_gesture_imports.py` | `main.py` (âncoras `self._criar_tray_icon()`, `self._iniciar_verificador_updates()`, `def apply_update_now`, `_iniciar_monitor_notif, daemon=True`, `_chc.start_monitor()`, `def _ativar_gesture`, `def _ativar_eye_control`, `def _calibrar_olhos`), `gesture_interface/main.py`, `gesture_interface/desktop_control/controller.py` | 1 |
| 10 | F1-10 | a fazer | executor (AST) + **qa (smoke)** | K AST `tests/unit/test_main_smoke_hook.py`; qa: `tests/smoke/test_boot_x11.py`, `test_boot_wayland.py`, `test_reload_ui_qt.py` (`JARVIS_SMOKE_RELOADS=10`) | `main.py`. **Até a F1-14**, imprimir `children_alive=n/a` (o `Cap.PROCESSES` ainda não existe); a M1 aceita `n/a` e a M2 exige `0`. | 5–9 |
| — | **M1** | a fazer | qa | N1 (inclui resolve de requirements), N2 e N3 conforme a SPEC §0. Se o smoke de reload falhar (ex.: o reload precisar rodar pelo `root.after`) → **F1-13b**. Crash novo → emenda do arquiteto. | — | 10 |
| 11 | G2 | a fazer | **qa (antes)** | C `tests/golden/test_job_object_windows.py` (oráculo do bloco Job Object com `WinDLL` falso: sequência, `LimitFlags == 0x2800`, `print`, ramos de falha), C `tests/golden/test_windows_env.py` (oráculo `_ler_path_windows` com `winreg` falso) | — | — |
| 12 | F1-14 | a fazer | executor (K/AST) + qa (golden G2) | K `tests/unit/platform/test_processes_posix.py` (`sleep` registrado morre no atexit; `tree=True`; espião proíbe `killpg(os.getpgrp())`), K AST (sem `_JOBOBJECT_*` no `main.py`; `register_child` depois do `Popen` do ffplay), `children_alive=0` no smoke; W6 atualizado | `jarvis/platform/{windows,linux}/processes.py`, entrada `PROCESSES`, `main.py` (âncoras `if _sys_crash.platform == "win32":` e `self._tts_process = proc`), `JARVIS.spec`, `launcher.py` | 1, 11 |
| 13 | F1-15 | a fazer | executor (AST) + qa (golden G2) | golden G2 (env) + AST (`main.py` sem `import winreg`); W6 | `jarvis/platform/windows/env.py`, `main.py` (âncora `import winreg`), `JARVIS.spec`, `launcher.py` | 1, 11 |
| 14 | F1-11b | a fazer | executor | casos novos no teste do `core/crash_log.py`: `FaulthandlerGuard` (teto por sessão, parâmetros injetáveis, `faulthandler.is_enabled()` fica falso + linha-marcador) e `JARVIS_FAULTHANDLER=0` (não abre arquivo) | `core/crash_log.py` | — |
| 15 | F1-12 | a fazer | **tools-lab (antes)** | K `tests/tools/test_clipboard_hist_ctrl_win.py` (`WinDLL` privado falso, protótipos antes da 1ª chamada, `wstring_at` com tamanho, NUL cortado, `finally`, `ctypes.windll` intocado); windows_only no N4 | `comandos/clipboard_hist_ctrl.py` | — |
| — | **M2** | a fazer | qa + revisor | N0–N3 três vezes; `children_alive=0`; `git diff --stat 1c32e38..linux-port` só com arquivos da SPEC §3 (+ `core/ui_reload.py` e `core/crash_log.py`, aceitos); revisão dos diffs | — | 1–15 |
| — | **N4** | dono | dono | `pytest -m "not linux_only and not x11 and not wayland"` no Windows + checklist: boot, tray, Shift+G, F5 ×10, TTS sem janela piscando, sem `msedgewebview2.exe` órfão, clipboard 10 min sem `access violation` | — | antes do merge na `master`; não bloqueia as fases |

## Paralelismo (no máximo 3 CLIs)
- Enquanto o executor fecha a **F1-01**, o qa grava o **G1** e o tools-lab grava o teste da **F1-12**.
- Depois da M1, o qa grava o **G2** enquanto o executor faz a F1-11b ou a F1-12, que não dependem de golden.
- As tarefas 4, 6, 14 e 15 não dependem da camada e podem entrar em qualquer ponto livre.
