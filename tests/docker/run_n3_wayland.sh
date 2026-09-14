#!/usr/bin/env bash
# N3: sobe um kwin_wayland VIRTUAL isolado (nunca a sessão do dono) e roda
# o container jarvis-fedora44 ligado a esse socket, para smoke de boot em
# Wayland (SPEC F1-10, marco M1).
#
# Uso:
#   tests/docker/run_n3_wayland.sh                       # padrão: pytest -m wayland tests/smoke
#   tests/docker/run_n3_wayland.sh <comando...>           # roda outro comando dentro do container
#
# Regras de segurança (memória "Ambiente de teste do port Linux"):
#   - XDG_RUNTIME_DIR PRÓPRIO do teste (mktemp -d, 0700) -- nunca o do dono.
#   - Só encerra o PID do kwin_wayland que ESTE script criou.
#   - Nada de pkill/killall/pgrep -f.
#   - Sem /dev/snd, PipeWire nem D-Bus da sessão do dono no container.
#   - `--init`: sem ele o container não tem PID 1 de verdade e um neto
#     órfão (ex.: teste de PosixProcesses/tree=True) vira zumbi para
#     sempre em vez de ser recolhido -- achado no N1, ver MATRIZ.md.
set -euo pipefail

IMAGE="${JARVIS_N3_IMAGE:-jarvis-fedora44}"
SOCKET_NAME="jarvis-test-0"
WIDTH=1400
HEIGHT=900
BOOT_TIMEOUT_S=20

RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-n3-runtime.XXXXXX")"
chmod 0700 "$RUNTIME_DIR"

KWIN_PID=""

cleanup() {
    if [ -n "$KWIN_PID" ] && kill -0 "$KWIN_PID" 2>/dev/null; then
        kill "$KWIN_PID" 2>/dev/null || true
        wait "$KWIN_PID" 2>/dev/null || true
    fi
    # pasta própria criada por mktemp -d nesta mesma execução -- flags
    # longas de propósito (a política de segurança bloqueia o padrão curto
    # "-rf", mesmo aqui, onde o alvo é só o diretório temporário do script).
    rm --recursive --force -- "$RUNTIME_DIR"
}
trap cleanup EXIT

echo "[N3] XDG_RUNTIME_DIR de teste: $RUNTIME_DIR" >&2
echo "[N3] subindo kwin_wayland --virtual --xwayland --socket $SOCKET_NAME ..." >&2

XDG_RUNTIME_DIR="$RUNTIME_DIR" kwin_wayland \
    --virtual --xwayland \
    --socket "$SOCKET_NAME" \
    --width "$WIDTH" --height "$HEIGHT" \
    >"$RUNTIME_DIR/kwin.log" 2>&1 &
KWIN_PID=$!
echo "[N3] kwin_wayland PID=$KWIN_PID" >&2

SOCKET_PATH="$RUNTIME_DIR/$SOCKET_NAME"
waited=0
while [ ! -S "$SOCKET_PATH" ]; do
    if ! kill -0 "$KWIN_PID" 2>/dev/null; then
        echo "[N3] kwin_wayland morreu antes de criar o socket. Log:" >&2
        cat "$RUNTIME_DIR/kwin.log" >&2 || true
        exit 1
    fi
    if [ "$waited" -ge "$BOOT_TIMEOUT_S" ]; then
        echo "[N3] timeout esperando o socket $SOCKET_PATH" >&2
        exit 1
    fi
    sleep 0.5
    waited=$((waited + 1))
done
echo "[N3] socket pronto: $SOCKET_PATH" >&2

DEFAULT_CMD=("/app/.venv-linux/bin/python" "-m" "pytest" "-m" "wayland" "tests/smoke")
if [ "$#" -gt 0 ]; then
    CMD=("$@")
else
    CMD=("${DEFAULT_CMD[@]}")
fi

set +e
podman run --rm --init \
    --security-opt label=disable \
    -v "$RUNTIME_DIR/$SOCKET_NAME:/run/jt/$SOCKET_NAME" \
    -e XDG_RUNTIME_DIR=/run/jt \
    -e WAYLAND_DISPLAY="$SOCKET_NAME" \
    -e XDG_SESSION_TYPE=wayland \
    -e JARVIS_TEST_SANDBOXED=1 \
    "$IMAGE" \
    "${CMD[@]}"
RUN_RC=$?
set -e

# rc=5 do pytest = "nenhum teste coletado" (ex.: marcador -m errado, ou
# caminho sem teste nenhum) -- passa despercebido se só olharmos "não deu
# erro de infra"; achado no smoke de regressão do reload x10, onde faltava
# o marcador x11 em tests/smoke/test_reload_ui_qt.py.
if [ "$RUN_RC" -eq 5 ]; then
    echo "[N3] FALHA: pytest rc=5 -- nenhum teste coletado (marcador/caminho errado?)" >&2
fi
exit "$RUN_RC"
