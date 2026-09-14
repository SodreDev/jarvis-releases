#!/usr/bin/env bash
# Smoke de regressão de uma (ou das 4) distro(s): build a partir do HEAD
# commitado (git archive -- nunca a working tree, pra não pegar trabalho
# uncommitted de outro agente), import de smoke, N1 (sem display), N2 X11
# (Xvfb, boot + reload x10) e, opcionalmente, N3 Wayland (via
# run_n3_wayland.sh, precisa de kwin_wayland no HOST).
#
# Uso:
#   tests/docker/run_regression.sh                       # só fedora44
#   tests/docker/run_regression.sh fedora44 debian12      # distros escolhidas
#   tests/docker/run_regression.sh all                    # as 4
#   JARVIS_REGRESSION_N3=1 tests/docker/run_regression.sh fedora44   # + N3
#
# N3 é opt-in (`JARVIS_REGRESSION_N3=1`) porque precisa de `kwin_wayland`
# no host e é mais lento -- sem a variável, o comportamento é o mesmo de
# antes (N1 + N2 boot + N2 reload).
#
# Log por distro em /tmp/jarvis-build-<distro>-reg.log. Todo `podman run`
# usa `--init` (sem ele um neto órfão vira zumbi pra sempre em vez de ser
# recolhido -- achado no N1, ver MATRIZ.md). rc=5 do pytest ("nenhum teste
# coletado") conta como FALHA, não sucesso silencioso.
#
# Todo `podman run` usa `--timeout <s>` (mata o CONTAINER, do lado do
# servidor podman) além do `timeout --signal=KILL` do host (mata só o
# cliente `podman run`): sem `--timeout`, um `timeout --signal=KILL` no
# host mata o cliente mas o container continua rodando -- achado real, 7
# containers vazados de sessões de debug anteriores rodando 7-8h. Também
# usa `--name` único, guardado em `$ACTIVE_CONTAINERS`; um `trap` no EXIT
# do script para (`podman stop`, nunca `-a`/pkill) qualquer um que ainda
# esteja rodando.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

ACTIVE_CONTAINERS=()
cleanup_containers() {
    local name
    for name in "${ACTIVE_CONTAINERS[@]:-}"; do
        [ -z "$name" ] && continue
        if podman inspect "$name" >/dev/null 2>&1; then
            podman stop -t 2 "$name" >/dev/null 2>&1 || true
        fi
    done
}
trap cleanup_containers EXIT

if [ "$#" -eq 0 ]; then
    DISTROS=(fedora44)
elif [ "$1" = "all" ]; then
    DISTROS=(fedora44 debian12 ubuntu2404 arch)
else
    DISTROS=("$@")
fi

WITH_N3="${JARVIS_REGRESSION_N3:-0}"
HEAD_SHA="$(git rev-parse HEAD)"
OVERALL_RC=0
declare -A SUMMARY

# rc=5 do pytest = "nenhum teste coletado" (marcador/caminho errado) --
# sem isso vira sucesso silencioso. Ver a lição de test_reload_ui_qt.py
# (faltava o marcador x11).
run_pytest_step() {
    local label="$1"
    local log="$2"
    shift 2
    "$@" >"$log" 2>&1
    local rc=$?
    if [ "$rc" -eq 5 ]; then
        echo "[$label] FALHA: pytest rc=5 -- nenhum teste coletado (marcador/caminho errado?)" | tee -a "$log" >&2
        return 1
    fi
    if [ "$rc" -ne 0 ]; then
        echo "[$label] FALHA: rc=$rc -- ver $log" >&2
        return 1
    fi
    echo "[$label] ok (ver $log)"
    return 0
}

for distro in "${DISTROS[@]}"; do
    LOG="/tmp/jarvis-build-${distro}-reg.log"
    echo "== $distro: inicio $(date -Iseconds), HEAD=$HEAD_SHA ==" > "$LOG"

    CTX="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-ctx-${distro}-reg-XXXXXX")"
    git archive HEAD | tar -x -C "$CTX"

    echo "-- build --" >> "$LOG"
    podman build -f "$CTX/tests/docker/Dockerfile.${distro}" -t "jarvis-${distro}" "$CTX" >> "$LOG" 2>&1
    BUILD_RC=$?
    echo "build_rc=$BUILD_RC" >> "$LOG"

    if [ "$BUILD_RC" -ne 0 ]; then
        echo "== $distro: build falhou, pulando resto ==" >> "$LOG"
        OVERALL_RC=1
        SUMMARY[$distro]="build=FALHOU"
        find "$CTX" -mindepth 1 -delete
        rmdir "$CTX"
        continue
    fi

    echo "-- import jeepney/webview/QtWebEngineWidgets --" >> "$LOG"
    IMPORT_NAME="jarvis-reg-${distro}-import-$$"
    ACTIVE_CONTAINERS+=("$IMPORT_NAME")
    timeout --signal=KILL 120 podman run --rm --init --timeout 100 --name "$IMPORT_NAME" "jarvis-${distro}" \
        python -c "import jeepney, webview, PySide6.QtWebEngineWidgets; print('ok')" >> "$LOG" 2>&1
    IMPORT_RC=$?
    echo "import_rc=$IMPORT_RC" >> "$LOG"
    [ "$IMPORT_RC" -eq 0 ] && IMPORT_STATUS=ok || { IMPORT_STATUS=FALHOU; OVERALL_RC=1; }

    N1_NAME="jarvis-reg-${distro}-n1-$$"
    ACTIVE_CONTAINERS+=("$N1_NAME")
    run_pytest_step "$distro N1" "/tmp/jarvis-reg-${distro}-n1.log" \
        timeout --signal=KILL 600 podman run --rm --init --timeout 580 --name "$N1_NAME" \
        -e JARVIS_TEST_SANDBOXED=0 "jarvis-${distro}" \
        pytest -m "not needs_display and not windows_only and not slow"
    N1_RC=$?
    [ "$N1_RC" -eq 0 ] && N1_STATUS=ok || { N1_STATUS=FALHOU; OVERALL_RC=1; }

    N2BOOT_NAME="jarvis-reg-${distro}-n2boot-$$"
    ACTIVE_CONTAINERS+=("$N2BOOT_NAME")
    run_pytest_step "$distro N2 boot x11" "/tmp/jarvis-reg-${distro}-n2-boot.log" \
        timeout --signal=KILL 150 podman run --rm --init --timeout 130 --name "$N2BOOT_NAME" "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_boot_x11.py
    N2_RC=$?
    [ "$N2_RC" -eq 0 ] && N2_STATUS=ok || { N2_STATUS=FALHOU; OVERALL_RC=1; }

    N2RELOAD_NAME="jarvis-reg-${distro}-n2reload-$$"
    ACTIVE_CONTAINERS+=("$N2RELOAD_NAME")
    run_pytest_step "$distro N2 reload x10" "/tmp/jarvis-reg-${distro}-n2-reload.log" \
        timeout --signal=KILL 150 podman run --rm --init --timeout 130 --name "$N2RELOAD_NAME" "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_reload_ui_qt.py
    RELOAD_RC=$?
    [ "$RELOAD_RC" -eq 0 ] && RELOAD_STATUS=ok || { RELOAD_STATUS=FALHOU; OVERALL_RC=1; }

    N2TRAY_NAME="jarvis-reg-${distro}-n2tray-$$"
    ACTIVE_CONTAINERS+=("$N2TRAY_NAME")
    run_pytest_step "$distro N2 tray" "/tmp/jarvis-reg-${distro}-n2-tray.log" \
        timeout --signal=KILL 150 podman run --rm --init --timeout 130 --name "$N2TRAY_NAME" "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_tray_n2_n3.py
    TRAY_RC=$?
    [ "$TRAY_RC" -eq 0 ] && TRAY_STATUS=ok || { TRAY_STATUS=FALHOU; OVERALL_RC=1; }

    N2AUDIO_NAME="jarvis-reg-${distro}-n2audio-$$"
    ACTIVE_CONTAINERS+=("$N2AUDIO_NAME")
    run_pytest_step "$distro N2 audio" "/tmp/jarvis-reg-${distro}-n2-audio.log" \
        timeout --signal=KILL 150 podman run --rm --init --timeout 130 --name "$N2AUDIO_NAME" "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_audio_exit.py
    AUDIO_RC=$?
    [ "$AUDIO_RC" -eq 0 ] && AUDIO_STATUS=ok || { AUDIO_STATUS=FALHOU; OVERALL_RC=1; }

    N2PTT_NAME="jarvis-reg-${distro}-n2ptt-$$"
    ACTIVE_CONTAINERS+=("$N2PTT_NAME")
    run_pytest_step "$distro N2 PTT pynput" "/tmp/jarvis-reg-${distro}-n2-ptt.log" \
        timeout --signal=KILL 150 podman run --rm --init --timeout 130 --name "$N2PTT_NAME" "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_hotkeys_n2_n3.py
    PTT_RC=$?
    [ "$PTT_RC" -eq 0 ] && PTT_STATUS=ok || { PTT_STATUS=FALHOU; OVERALL_RC=1; }

    N3_STATUS="pulado"
    if [ "$WITH_N3" = "1" ]; then
        # combina boot + tray (com e sem watcher) + áudio + PTT numa única
        # subida de kwin_wayland (mais barato que uma por arquivo).
        run_pytest_step "$distro N3 wayland (boot/tray/audio/PTT)" "/tmp/jarvis-reg-${distro}-n3.log" \
            env JARVIS_N3_IMAGE="jarvis-${distro}" JARVIS_N3_TIMEOUT=280 timeout --signal=KILL 300 \
            "$REPO_ROOT/tests/docker/run_n3_wayland.sh" \
            pytest -m wayland tests/smoke/test_boot_wayland.py tests/smoke/test_tray_n2_n3.py \
            tests/smoke/test_audio_exit.py tests/smoke/test_hotkeys_n2_n3.py
        N3_RC=$?
        [ "$N3_RC" -eq 0 ] && N3_STATUS=ok || { N3_STATUS=FALHOU; OVERALL_RC=1; }
    fi

    SUMMARY[$distro]="build=ok import=$IMPORT_STATUS N1=$N1_STATUS N2boot=$N2_STATUS reload=$RELOAD_STATUS tray=$TRAY_STATUS audio=$AUDIO_STATUS ptt=$PTT_STATUS N3=$N3_STATUS"

    find "$CTX" -mindepth 1 -delete
    rmdir "$CTX"
    echo "== $distro: fim $(date -Iseconds) ==" >> "$LOG"
done

echo "--- resumo ---"
for distro in "${DISTROS[@]}"; do
    echo "[$distro] ${SUMMARY[$distro]:-sem_resultado}"
done

echo "REGRESSAO_TERMINOU overall_rc=$OVERALL_RC"
exit "$OVERALL_RC"
