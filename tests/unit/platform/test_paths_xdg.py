"""K — contrato (F1-02 e F1-07): descrevem `WindowsPaths` e `XdgPaths`
ANTES de existirem (`jarvis/platform/{windows,linux}/paths.py`,
`jarvis/platform/linux/xdg.py`). `xfail(strict=True)` — o executor remove
o `xfail` no commit que implementa cada peça (SPEC F1-02 e F1-07).

Import é feito DENTRO de cada teste (não no topo do módulo): os módulos
ainda não existem, e um `ImportError` no topo quebraria a coleta do
arquivo inteiro em vez de contar como falha esperada do teste.
"""
import ntpath
import os
import stat

import pytest

from tests.golden.legacy_1c32e38 import legacy_webview_storage

pytestmark = pytest.mark.linux_only


# ── F1-02: XdgPaths — padrões, variável relativa ignorada, permissões, logs ──


@pytest.mark.xfail(strict=True, reason="F1-02")
def test_xdg_paths_defaults_without_env(isolated_home, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    from jarvis.platform.linux.xdg import XdgPaths

    p = XdgPaths()
    home = isolated_home["home"]
    assert p.user_config_dir() == home / ".config" / "jarvis"
    assert p.user_data_dir() == home / ".local" / "share" / "jarvis"
    assert p.logs_dir() == home / ".local" / "state" / "jarvis" / "logs"


@pytest.mark.xfail(strict=True, reason="F1-02")
def test_xdg_paths_relative_value_is_ignored(isolated_home, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "relativo/nao/absoluto")
    from jarvis.platform.linux.xdg import XdgPaths

    p = XdgPaths()
    assert p.user_config_dir() == isolated_home["home"] / ".config" / "jarvis"


@pytest.mark.xfail(strict=True, reason="F1-02")
def test_xdg_paths_created_dirs_are_mode_0700(isolated_home):
    from jarvis.platform.linux.xdg import XdgPaths

    p = XdgPaths()
    created = p.user_config_dir()
    mode = stat.S_IMODE(os.stat(created).st_mode)
    assert mode == 0o700


@pytest.mark.xfail(strict=True, reason="F1-02")
def test_xdg_paths_logs_in_xdg_state_home(isolated_home):
    from jarvis.platform.linux.xdg import XdgPaths

    p = XdgPaths()
    assert p.logs_dir() == isolated_home["state"] / "jarvis" / "logs"


@pytest.mark.xfail(strict=True, reason="F1-02")
def test_xdg_paths_webview_storage_dir(isolated_home):
    from jarvis.platform.linux.xdg import XdgPaths

    p = XdgPaths()
    assert p.webview_storage_dir() == isolated_home["data"] / "jarvis" / "webview_data"


# ── F1-07: WindowsPaths.webview_storage_dir() == oráculo (ntpath) ──


APPDATA_SCENARIOS = [
    pytest.param("C:\\Users\\ana\\AppData\\Roaming", id="definido"),
    pytest.param(None, id="ausente"),
    pytest.param("", id="vazio"),
]


@pytest.mark.xfail(strict=True, reason="F1-07")
@pytest.mark.parametrize("appdata_value", APPDATA_SCENARIOS)
def test_windows_paths_webview_storage_matches_oracle(appdata_value, isolated_home):
    from jarvis.platform.windows.paths import WindowsPaths

    home = str(isolated_home["home"])
    environ = {} if appdata_value is None else {"APPDATA": appdata_value}

    result = WindowsPaths(environ=environ, home=home, path_module=ntpath).webview_storage_dir()
    assert result == legacy_webview_storage(environ, home)
