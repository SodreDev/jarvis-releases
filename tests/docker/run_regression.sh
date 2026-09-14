#!/usr/bin/env bash
# Smoke de regressão de uma (ou das 4) distro(s): build a partir do HEAD
# commitado (git archive -- nunca a working tree, pra não pegar trabalho
# uncommitted de outro agente), import de smoke, N1 (sem display) e N2 X11
# (Xvfb). N3 Wayland fica de fora daqui (precisa de kwin_wayland no HOST,
# ver tests/docker/run_n3_wayland.sh) -- rode-o à parte se precisar.
#
# Uso:
#   tests/docker/run_regression.sh                      # só fedora44
#   tests/docker/run_regression.sh fedora44 debian12     # distros escolhidas
#   tests/docker/run_regression.sh all                   # as 4
#
# Log por distro em /tmp/jarvis-build-<distro>-reg.log. Todo `podman run`
# usa `--init` (sem ele um neto órfão vira zumbi pra sempre em vez de ser
# recolhido -- achado no N1, ver MATRIZ.md).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

if [ "$#" -eq 0 ]; then
    DISTROS=(fedora44)
elif [ "$1" = "all" ]; then
    DISTROS=(fedora44 debian12 ubuntu2404 arch)
else
    DISTROS=("$@")
fi

HEAD_SHA="$(git rev-parse HEAD)"
OVERALL_RC=0

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
        find "$CTX" -mindepth 1 -delete
        rmdir "$CTX"
        continue
    fi

    echo "-- import jeepney/webview/QtWebEngineWidgets --" >> "$LOG"
    timeout --signal=KILL 120 podman run --rm --init "jarvis-${distro}" \
        python -c "import jeepney, webview, PySide6.QtWebEngineWidgets; print('ok')" >> "$LOG" 2>&1
    IMPORT_RC=$?
    echo "import_rc=$IMPORT_RC" >> "$LOG"
    [ "$IMPORT_RC" -ne 0 ] && OVERALL_RC=1

    run_pytest_step "$distro N1" "/tmp/jarvis-reg-${distro}-n1.log" \
        timeout --signal=KILL 600 podman run --rm --init -e JARVIS_TEST_SANDBOXED=0 "jarvis-${distro}" \
        pytest -m "not needs_display and not windows_only and not slow" \
        || OVERALL_RC=1

    run_pytest_step "$distro N2 boot x11" "/tmp/jarvis-reg-${distro}-n2-boot.log" \
        timeout --signal=KILL 150 podman run --rm --init "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_boot_x11.py \
        || OVERALL_RC=1

    run_pytest_step "$distro N2 reload x10" "/tmp/jarvis-reg-${distro}-n2-reload.log" \
        timeout --signal=KILL 150 podman run --rm --init "jarvis-${distro}" \
        xvfb-run -a pytest -m x11 tests/smoke/test_reload_ui_qt.py \
        || OVERALL_RC=1

    find "$CTX" -mindepth 1 -delete
    rmdir "$CTX"
    echo "== $distro: fim $(date -Iseconds) ==" >> "$LOG"
done

echo "REGRESSAO_TERMINOU overall_rc=$OVERALL_RC"
exit "$OVERALL_RC"
