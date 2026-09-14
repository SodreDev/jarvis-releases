# FILA — Fase 2 (executor: Opus 4.8)

Especificação: [SPEC-fase2.md](SPEC-fase2.md) · Arquitetura: [ADR-001](ADR-001-camada-plataforma.md) · Base: `linux-port@31bc0ce` · 2026-09-14.

## Protocolo
1. **Tarefas que movem código do Windows** (F2-01, F2-02, F2-03, F2-04, F2-06, F2-07, F2-08, F2-09): o **qa grava antes**:
   - o oráculo literal em `tests/golden/legacy_31bc0ce.py`;
   - os testes golden **C** (passam no código atual);
   - os testes **K**, em `xfail(strict=True, reason="F2-xx")`.
2. **Tarefas pequenas ou só-Linux** (F2-00, F2-05, F2-10a, F2-10b, F2-10c): o **executor escreve os testes K/AST no mesmo commit** do código.
3. **Commits:** um por tarefa, mensagem `port(F2-xx): <resumo>`, **commit por pathspec**.
4. **Antes de cada commit**, o `.venv-linux` precisa passar em `pytest -m "not slow and not needs_display and not windows_only"`.
5. **Não editar** `tests/golden/`, `tests/docker/*` nem as fixtures do T0 (são do qa).
6. **W6:** módulo novo de `jarvis.platform.windows`/`common` entra no `JARVIS.spec` e no `if False:` do `launcher.py`, no mesmo commit. As entradas do `REGISTRY` entram só no commit da capacidade.
7. **Git e localização:**
   - use `git -C /home/sodre/GranaFacil/J.A.R.V.I.S`;
   - nada de push nem reescrita de histórico;
   - localize pelo **trecho-âncora** da SPEC.
8. **Emendas e dúvidas:**
   - arquivo fora da SPEC §3 → emenda do arquiteto;
   - dúvidas no portal/KGlobalAccel (flags do `setShortcut`) ou no `run_in_gui_thread` → peça detalhe ao arquiteto, não improvise.
9. **Proibido:** testar hotkeys, tray, áudio ou D-Bus na sessão real do dono ou no D-Bus do host. Só barramento privado, containers e o KWin virtual.
10. **Decisões do dono ainda abertas:** implemente com os **valores recomendados** e mantenha-os em **um único lugar** para trocar depois:
    - `config.PTT_TRIGGER_GLOBAL = "<cmd>+<shift>+g"` (D-F2-1);
    - `APP_ID` em `jarvis/platform/linux/app_id.py` (D-F2-2);
    - `ensure_desktop_entry` (D-F2-3);
    - `jeepney` (D-F2-4).

    A tarefa **não bloqueia** esperando a resposta.

## Estado e ordem

| # | ID | Quem escreve o teste | Testes que precisam passar | Arquivos de produção | Depende |
|---|---|---|---|---|---|
| 0 | **T0** (qa) | qa | fixtures `private_session_bus`, `fake_tools` e `fake_windll` em `tests/conftest.py`/`tests/fakes/`; `python-dbusmock` em requirements-dev (só Linux); imagem N3 com `dbus-run-session` + `kglobalacceld`; esqueleto `tests/golden/legacy_31bc0ce.py` | — (só testes/infra) | — |
| 1 | **F2-00** infra | executor (junto) | K `tests/unit/platform/test_features_derived.py`, `test_linux_dbus.py` (N1), `test_linux_tools.py`; W6/C1 atualizados; win32 continua ALL sem sondar nada | `jarvis/platform/{protocols,registry,features,__init__}.py`, `jarvis/platform/linux/{dbus,tools,app_id}.py`, `requirements.txt` (`jeepney`), `JARVIS.spec`, `launcher.py` | T0 |
| 2 | **F2-10b** sounddevice | executor (junto) | `tests/unit/test_main_sounddevice_guard.py` atualizado | `main.py` | — |
| 3 | **F2-10a** flags | executor (junto) | `tests/unit/test_windows_subprocess_flags.py` atualizado (fachada nos 4 lugares), C1 menor | `main.py`, `comandos/games_ctrl.py`, `core/game_platform_detector.py`, `classifiers/modelo_local.py` | 1 |
| 4 | **G-A** (qa, antes) | qa | C `tests/golden/test_open_path_windows.py`, `test_startfile_callsites.py`, `test_session_windows.py`, `test_restart_windows.py`, `test_clipboard_windows.py`; K (xfail) `tests/unit/platform/test_open_path_linux.py`, `test_session_linux.py`, `test_restart_posix.py`, `test_clipboard_linux.py`; tools-lab: K `tests/tools/test_clipboard_hist_ctrl_platform.py` | — | T0 |
| 5 | **F2-06** open_path | qa (G-A) | golden G-A (open_path + call sites) + K linux; C1 sem `os.startfile`/`notepad.exe` fora do adapter e dos mapas da Fase 4 | `jarvis/platform/{windows,linux}/open_path.py`, `main.py`, `comandos/{executor,games_ctrl,msg_sender,janela_ctrl,tool_registry}.py`, `JARVIS.spec`, `launcher.py` | 1, 4 |
| 6 | **F2-09** restart_self | qa (G-A) | golden restart + K posix; N2 `JARVIS_SMOKE_RESTART=1` (qa roda) | `jarvis/platform/{windows,linux}/processes.py`, `main.py` | 1, 4 |
| 7 | **F2-07** session | qa (G-A) | golden session + K linux (N1, ScreenSaver/Mutter/logind falsos; Xss com lib falsa) | `jarvis/platform/windows/session.py`, `jarvis/platform/linux/session.py`, `jarvis/platform/linux_x11/session.py`, `main.py`, `core/win_locale.py`, `JARVIS.spec`, `launcher.py` | 1, 4 |
| 8 | **F2-04** clipboard | qa (G-A) + tools-lab | golden clipboard + K linux (wl-paste novo/velho, Klipper falso, xclip/xsel) + tools-lab | `jarvis/platform/windows/clipboard.py`, `jarvis/platform/linux_wayland/clipboard.py`, `jarvis/platform/linux_x11/clipboard.py`, `jarvis/platform/linux/clipboard_klipper.py`, `comandos/{system_ctrl,clipboard_hist_ctrl}.py`, `JARVIS.spec`, `launcher.py` | 1, 4 |
| 9 | **F2-05** notifier | executor (junto) | K `tests/unit/platform/test_notifier_linux.py` (N1), K AST `tests/unit/test_main_notifier_gate.py` | `jarvis/platform/linux/notifier.py`, `main.py` | 1 |
| 10 | **G-B** (qa, antes) | qa | C `tests/golden/test_volume_windows.py`, `test_media_windows.py`; K (xfail) `test_volume_linux.py`, `test_media_linux.py` (N1, dois players MPRIS falsos) | — | T0 |
| 11 | **F2-03** volume | qa (G-B) | golden volume + K linux (`fake_tools` wpctl/pactl) | `jarvis/platform/windows/volume.py`, `jarvis/platform/linux/volume.py`, `comandos/system_ctrl.py`, `JARVIS.spec`, `launcher.py` | 1, 10 |
| 12 | **F2-08** media | qa (G-B) | golden media + K linux | `jarvis/platform/windows/media.py`, `jarvis/platform/linux/media.py`, `comandos/midia_ctrl.py`, `JARVIS.spec`, `launcher.py` | 11 |
| 13 | **G-C** (qa, antes) | qa | C `tests/golden/test_hotkeys_windows.py`, `test_tray_windows.py`; K (xfail) `test_hotkeys_portal.py` (N1, portal falso: ordem Register → CreateSession, Response assinado antes, 0/1/2, Activated/Deactivated), `test_hotkeys_kglobalaccel.py` (N1), `test_trigger_convert.py`, `test_tray_qt.py` e `test_qt_gui_thread.py` (N2/N3), `tests/smoke/test_hotkeys_n2_n3.py` | — | T0 |
| 14 | **F2-01** hotkeys (portal → KGlobalAccel) | qa (G-C) | golden hotkeys (inclui a extração literal de `_ptt_iniciar`/`_ptt_finalizar`) + K portal/KGA/convert; N2 `backend=pynput`; N3 `backend=kglobalaccel` + `JARVIS_SMOKE_PTT press` | `jarvis/platform/common/pynput_hotkeys.py`, `jarvis/platform/linux_wayland/hotkeys_portal.py`, `jarvis/platform/linux/{hotkeys_kglobalaccel,desktop_entry}.py`, `main.py`, `config.py` (só `PTT_TRIGGER_GLOBAL`), `JARVIS.spec`, `launcher.py` | 1, 13 |
| 15 | **F2-02** tray | qa (G-C) | golden tray + K `test_qt_gui_thread.py` **primeiro** (se falhar, pare e peça detalhe) + `test_tray_qt.py`; N3 com watcher falso registrado / sem watcher o X fecha o app | `jarvis/platform/windows/tray.py`, `jarvis/platform/linux/{tray_qt,qt_gui}.py`, `main.py`, `JARVIS.spec`, `launcher.py` | 1, 13 |
| 16 | **F2-10c** smoke exit + áudio | executor (junto) + qa (smoke) | K AST `tests/unit/test_main_smoke_exit.py`; qa `tests/smoke/test_audio_exit.py` (N2/N3: `children_alive=0`, sem `FORCED_EXIT`) | `main.py`, `jarvis/platform/{windows,linux}/processes.py` | 6 |
| — | **M1** | qa | SPEC §0 M1 na matriz fedora44/debian12/ubuntu2404/arch | — | 1–16 |
| — | **M2** | qa + revisor | M1 ×3; smoke de áudio; `git diff --stat 31bc0ce..linux-port` ⊆ SPEC §3 (+ `config.py`, só `PTT_TRIGGER_GLOBAL`); revisão Opus 4.7 | — | M1 |
| — | **N-dono** | qa escreve, **dono roda** | checklist Linux na sessão real: portal/PTT, tray, notificação, volume/mic, clipboard, mídia, abrir documento, restart | — | M2 (D-F2-6) |
| — | **N4** | dono | Windows real: `pytest -m "not linux_only and not x11 and not wayland"` + checklist das Fases 1 e 2 (Shift+G, 4 atalhos, tray, volume, mídia, clipboard, restart em dev, abrir PDF/imagem gerados, notepad no texto longo) | — | antes do merge na `master` |

`config.py` entra na lista fechada **só** para a constante `PTT_TRIGGER_GLOBAL` (emenda desta FILA à SPEC §3).

## Paralelismo (no máximo 3 CLIs; o qa já está em `tests/docker/*`)
- **Agora:** qa com T0 (e a matriz de distros); executor com **F2-00**, depois **F2-10b**.
- Depois do T0: o qa grava **G-A** enquanto o executor faz **F2-10a** e **F2-05** (que não precisam de golden). O tools-lab grava o teste do `clipboard_hist_ctrl` em paralelo.
- **G-B** e **G-C** podem ser gravados pelo qa enquanto o executor faz as tarefas 5 a 8.
- **F2-01** (portal) e **F2-02** (tray) ficam por último, porque têm o maior risco e dependem do N3 com KDE montado pelo qa.
