"""C/K (F1-15): `winreg` do PATH → `jarvis.platform.windows.env`.

`xfail(strict=True, reason="F1-15")`: `refresh_path_from_registry` ainda
não existe (import feito DENTRO do teste, para a coleta não quebrar).
`winreg` é falso — Linux não tem esse módulo.
"""
import pytest

from tests.golden.legacy_1c32e38 import legacy_refresh_path

_SCOPE_LM = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
_SCOPE_CU = r"Environment"


class _FakeKey:
    def __init__(self, values: dict):
        self._values = values

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeWinreg:
    """Substituto mínimo de `winreg`: `data` mapeia `(hive, scope) ->
    {"Path": "..."}`. Um hive ausente de `data` faz `OpenKey` levantar
    `OSError`, como a chave de registro que não existe."""

    HKEY_LOCAL_MACHINE = "HKLM"
    HKEY_CURRENT_USER = "HKCU"

    def __init__(self, data: dict):
        self._data = data

    def OpenKey(self, hive, scope):
        key = (hive, scope)
        if key not in self._data:
            raise OSError(f"[FakeWinreg] chave inexistente: {key!r}")
        return _FakeKey(self._data[key])

    def QueryValueEx(self, key: _FakeKey, name: str):
        return key._values[name], 1  # tipo REG_SZ arbitrário


def test_refresh_path_matches_oracle_both_hives_present():
    from jarvis.platform.windows.env import refresh_path_from_registry

    fake = FakeWinreg(
        {
            (FakeWinreg.HKEY_LOCAL_MACHINE, _SCOPE_LM): {"Path": r"C:\lm1;C:\lm2"},
            (FakeWinreg.HKEY_CURRENT_USER, _SCOPE_CU): {"Path": r"C:\cu1"},
        }
    )
    environ = {"PATH": r"C:\existente"}

    oracle = legacy_refresh_path(environ, fake)
    result = refresh_path_from_registry(environ=environ, winreg_mod=fake)
    assert set(result) == oracle
    assert "" not in set(result)


def test_refresh_path_matches_oracle_one_hive_missing():
    from jarvis.platform.windows.env import refresh_path_from_registry

    fake = FakeWinreg(
        {
            (FakeWinreg.HKEY_LOCAL_MACHINE, _SCOPE_LM): {"Path": r"C:\lm1"},
            # HKCU ausente -> OpenKey levanta OSError, tratado como no original
        }
    )
    environ = {"PATH": r"C:\existente;;C:\outro"}  # ";;" gera entrada vazia

    oracle = legacy_refresh_path(environ, fake)
    result = refresh_path_from_registry(environ=environ, winreg_mod=fake)
    assert set(result) == oracle
    assert "" not in set(result)
