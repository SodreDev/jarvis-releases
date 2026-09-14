"""Fixtures compartilhadas dos testes do Jarvis."""
import os
import shutil
import signal
import subprocess
import sys
import time

import pytest

from tests.fakes.tools import install_fake_tools, prepend_to_path
from tests.fakes.windll import FakeWinDLL, build_fake_ctypes


@pytest.fixture
def fake_platform(monkeypatch):
    """Simula sys.platform. Uso: fake_platform("win32") ou fake_platform("linux")."""

    def _set(platform_name: str):
        monkeypatch.setattr(sys, "platform", platform_name)
        return platform_name

    return _set


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """HOME e diretórios XDG apontando para uma pasta temporária, para nenhum
    teste ler ou escrever nos dados reais do usuário (config, cache, dados)."""
    home = tmp_path / "home"
    config_dir = tmp_path / "config"
    cache_dir = tmp_path / "cache"
    data_dir = tmp_path / "share"
    state_dir = tmp_path / "state"
    for d in (home, config_dir, cache_dir, data_dir, state_dir):
        d.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_dir))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_dir))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_dir))

    return {
        "home": home,
        "config": config_dir,
        "cache": cache_dir,
        "data": data_dir,
        "state": state_dir,
    }


@pytest.fixture
def private_session_bus(request, monkeypatch):
    """Sobe um `dbus-daemon --session` PRIVADO (nunca o D-Bus do host),
    aponta `DBUS_SESSION_BUS_ADDRESS` pra ele e mata só esse PID no fim.
    Regra da SPEC F2: "nenhum teste pode falar com o DBUS_SESSION_BUS_ADDRESS
    do host". Devolve o endereço do barramento (string).

    Também aponta `DBUS_SYSTEM_BUS_ADDRESS` pro MESMO barramento privado
    (F2-07: `LogindSession` em produção fala com o barramento de SISTEMA
    de verdade — `org.freedesktop.login1` mora lá — via
    `DBUS_SYSTEM_BUS_ADDRESS` se definida, senão
    `unix:path=/run/dbus/system_bus_socket`). Sem isso, qualquer teste
    que exercite esse caminho falaria por acidente com o D-Bus de
    SISTEMA de verdade do host.

    Limpeza: o PID impresso por `--print-pid` é guardado num finalizer de
    `request` (roda mesmo se o SETUP da fixture falhar depois de já ter
    subido o daemon, ex. erro no `monkeypatch.setenv`) -- terminate,
    espera curta e kill só se precisar. `--fork` faz o `dbus-daemon`
    desanexar (novo ppid, reparented pro init) DE PROPÓSITO, então o
    finalizer é a única forma de encerrar -- não tem processo-filho
    "natural" pra monitorar. ATENÇÃO: isso não sobrevive a um SIGKILL do
    processo do pytest (achado real: 4 PIDs vazados depois de várias
    rodadas com `timeout --signal=KILL` enquanto um teste travava antes
    de um fix -- finally/finalizer nunca rodam sob SIGKILL, é limitação
    do SO, não da fixture). Prefira SIGTERM (`timeout` sem `--signal`)
    pra matar um pytest travado usando esta fixture.
    """
    if shutil.which("dbus-daemon") is None:
        pytest.skip("dbus-daemon não está instalado neste host/container")

    result = subprocess.run(
        ["dbus-daemon", "--session", "--fork", "--print-address=1", "--print-pid=1"],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    address, pid = lines[0], int(lines[1])

    def _kill_daemon():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(20):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    # addfinalizer (não try/finally em volta do yield): cobre também uma
    # falha DEPOIS de já termos o PID mas ANTES do yield (ex.:
    # monkeypatch.setenv), que um try/finally só em volta do yield não
    # pegaria.
    request.addfinalizer(_kill_daemon)

    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", address)
    monkeypatch.setenv("DBUS_SYSTEM_BUS_ADDRESS", address)
    yield address


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    """Devolve `build(scripts) -> {nome: caminho do .calls}`: cria um
    executável por entrada de `scripts` (nome da ferramenta -> corpo do
    shell script, ex.: `{"wpctl": "echo '0.50'"}`), coloca a pasta na
    FRENTE do PATH (só para este teste) e devolve onde ler os argumentos
    que cada chamada recebeu.
    """
    bin_dir = tmp_path / "fake_tools_bin"
    calls_dir = tmp_path / "fake_tools_calls"

    def _build(scripts: dict[str, str]) -> dict:
        calls_paths = install_fake_tools(bin_dir, calls_dir, scripts)
        monkeypatch.setenv("PATH", prepend_to_path(bin_dir))
        return calls_paths

    return _build


@pytest.fixture
def fake_windll():
    """Devolve `build(dlls, *, last_error=0) -> módulo ctypes falso`.
    `dlls` é `{"kernel32": FakeWinDLL(), "user32": FakeWinDLL(), ...}` —
    ver `tests/fakes/windll.py` (`FakeWinDLL`, `FakeWinFunc`). Só
    `ctypes.WinDLL`/`ctypes.get_last_error` são trocados; o resto do
    `ctypes` continua sendo o real do host.
    """
    return build_fake_ctypes


__all__ = ["FakeWinDLL"]  # reexportado por conveniência (from tests.conftest import FakeWinDLL)
