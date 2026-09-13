"""C — caracterização (F1-02/F1-07): prova que o comportamento Windows não
muda. Compara `jarvis/config/paths.py` contra o oráculo literal de
`legacy_1c32e38`. Precisa passar HOJE e continuar passando depois de
F1-02/F1-07 (delegação a `jarvis.platform.paths()`).

Não forçamos `os.name` GLOBAL: `pathlib.Path()` recusa instanciar
`WindowsPath` num host Linux mesmo com `os.name` monkeypatchado (é assim
desde sempre, não é regressão do 3.12) — `WindowsPath()` levanta
`NotImplementedError: cannot instantiate 'WindowsPath' on your system`.
Em vez disso, substituímos só o atributo `os` DENTRO do módulo
`jarvis.config.paths` por um módulo fake com `name="nt"` e o `environ` do
cenário. `pathlib.Path` continua vendo o `os` real (Linux) e funciona
normalmente; só a lógica de `_appdata_root()` enxerga "estou no Windows".
"""
import os
import types

import pytest

import jarvis.platform as jplatform
from jarvis.platform.detect import detect
from jarvis.config import paths as paths_mod
from tests.golden.legacy_1c32e38 import (
    legacy_appdata_root,
    legacy_credentials_dir,
    legacy_logs_dir,
    legacy_user_config_dir,
    legacy_user_data_dir,
)

APPDATA_SCENARIOS = [
    pytest.param("appdata_definido", id="definido"),
    pytest.param(None, id="ausente"),
    pytest.param("", id="vazio"),
]


def _fake_windows_os(monkeypatch, tmp_path, home, scenario):
    """Substitui `paths_mod.os` por um módulo fake com `name="nt"` e o
    `environ` do cenário de APPDATA. Devolve o `environ` usado (para
    alimentar o oráculo)."""
    environ = dict(os.environ)
    environ.pop("APPDATA", None)
    if scenario is None:
        pass  # APPDATA ausente
    elif scenario == "":
        environ["APPDATA"] = ""
    else:
        environ["APPDATA"] = str(tmp_path / scenario)

    fake_os = types.ModuleType("os")
    fake_os.__dict__.update(os.__dict__)
    fake_os.name = "nt"
    fake_os.environ = environ
    monkeypatch.setattr(paths_mod, "os", fake_os)
    # Após F1-02 a escolha do backend vem do contexto da camada, não de os.name:
    # fixamos win32 e o mesmo `os` falso onde o WindowsPaths lê o environ.
    import jarvis.platform.windows.paths as winpaths_mod
    monkeypatch.setattr(winpaths_mod, "os", fake_os)
    jplatform._reset_for_tests(ctx=detect(sys_platform="win32", environ=environ))
    return environ


@pytest.fixture(autouse=True)
def _reset_platform_layer():
    yield
    jplatform._reset_for_tests()


@pytest.mark.parametrize("scenario", APPDATA_SCENARIOS)
def test_appdata_root_matches_oracle(scenario, isolated_home, monkeypatch, tmp_path):
    home = str(isolated_home["home"])
    environ = _fake_windows_os(monkeypatch, tmp_path, home, scenario)

    assert paths_mod._appdata_root() == legacy_appdata_root(environ, home)


@pytest.mark.parametrize("scenario", APPDATA_SCENARIOS)
@pytest.mark.parametrize(
    "real_fn_name, legacy_fn",
    [
        ("user_config_dir", legacy_user_config_dir),
        ("user_data_dir", legacy_user_data_dir),
        ("credentials_dir", legacy_credentials_dir),
        ("logs_dir", legacy_logs_dir),
    ],
)
def test_public_path_functions_match_oracle(
    real_fn_name, legacy_fn, scenario, isolated_home, monkeypatch, tmp_path
):
    home = str(isolated_home["home"])
    environ = _fake_windows_os(monkeypatch, tmp_path, home, scenario)

    real_fn = getattr(paths_mod, real_fn_name)
    assert real_fn() == legacy_fn(environ, home)
