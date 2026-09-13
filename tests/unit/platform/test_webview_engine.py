"""K — contrato (F1-06): `decide_sandbox` e `QtWebEngine` de
`jarvis/platform/linux/webview_engine.py` (ainda não existe — import
DENTRO de cada teste). `xfail(strict=True, reason="F1-06")`.

Uma função/classe por bloco de teste, uma asserção por passo da ordem
descrita na SPEC F1-06 (`docs/linux-port/SPEC-fase1-boot-linux.md`).
"""
import types

import pytest

pytestmark = [pytest.mark.linux_only, pytest.mark.xfail(strict=True, reason="F1-06")]


def _probe(returncode=0, stderr=""):
    def _fake(cmd, timeout=None):
        return types.SimpleNamespace(returncode=returncode, stderr=stderr)

    return _fake


def _probe_unshare_missing(cmd, timeout=None):
    raise FileNotFoundError("unshare não encontrado")


def _decide(**overrides):
    from jarvis.platform.linux.webview_engine import decide_sandbox

    kwargs = dict(
        environ={},
        read_sysctl=lambda name: None,
        run_probe=_probe(returncode=0, stderr=""),
        euid=1000,
        os_release_id="fedora",
    )
    kwargs.update(overrides)
    return decide_sandbox(**kwargs)


def test_env_var_on_forces_on():
    on, _reason = _decide(environ={"JARVIS_WEBENGINE_SANDBOX": "on"})
    assert on is True


def test_env_var_off_forces_off():
    on, _reason = _decide(environ={"JARVIS_WEBENGINE_SANDBOX": "off"})
    assert on is False


def test_env_var_invalid_falls_back_to_auto():
    # valor inválido não trava em on/off — segue a sonda normal (nos
    # defaults acima, cai no passo 7: sem unshare, apparmor não restringe -> on)
    on, _reason = _decide(environ={"JARVIS_WEBENGINE_SANDBOX": "talvez"}, run_probe=_probe_unshare_missing)
    assert on is True


def test_disable_sandbox_env_flag_off_ambiente():
    on, reason = _decide(environ={"QTWEBENGINE_DISABLE_SANDBOX": "1"})
    assert on is False
    assert reason == "ambiente"


def test_no_sandbox_chromium_flag_off_ambiente():
    on, reason = _decide(environ={"QTWEBENGINE_CHROMIUM_FLAGS": "--foo --no-sandbox"})
    assert on is False
    assert reason == "ambiente"


def test_euid_root_off():
    on, reason = _decide(euid=0)
    assert on is False
    assert reason == "root"


@pytest.mark.parametrize("distro", ["arch", "manjaro", "nixos", "rhel", "pop"])
def test_forced_distro_off(distro):
    on, reason = _decide(os_release_id=distro)
    assert on is False
    assert reason == "forçado pelo pywebview"


def test_userns_sysctl_disabled_off():
    on, _reason = _decide(
        read_sysctl=lambda name: "0" if name == "kernel.unprivileged_userns_clone" else None
    )
    assert on is False


def test_unshare_success_on():
    on, _reason = _decide(run_probe=_probe(returncode=0))
    assert on is True


def test_unshare_failure_off_with_first_stderr_line():
    on, reason = _decide(run_probe=_probe(returncode=1, stderr="permissão negada\nlinha2"))
    assert on is False
    assert reason == "permissão negada"


def test_no_unshare_apparmor_restricts_off():
    on, _reason = _decide(
        run_probe=_probe_unshare_missing,
        read_sysctl=lambda name: "1" if name == "kernel.apparmor_restrict_unprivileged_userns" else None,
    )
    assert on is False


def test_no_unshare_apparmor_allows_on():
    on, _reason = _decide(run_probe=_probe_unshare_missing, read_sysctl=lambda name: None)
    assert on is True


def test_qtwebengine_prepare_env_does_not_overwrite_existing():
    from jarvis.platform.linux.webview_engine import QtWebEngine

    environ = {"QT_API": "ja_definido"}
    QtWebEngine().prepare_env(environ)
    assert environ["QT_API"] == "ja_definido"


def test_qtwebengine_prepare_env_sets_defaults():
    from jarvis.platform.linux.webview_engine import QtWebEngine

    environ = {}
    QtWebEngine().prepare_env(environ)
    assert environ["QT_API"] == "pyside6"
    assert environ["PYWEBVIEW_GUI"] == "qt"
    assert "QT_QPA_PLATFORM" in environ


def test_qtwebengine_start_kwargs():
    from jarvis.platform.linux.webview_engine import QtWebEngine

    assert QtWebEngine().start_kwargs() == {"gui": "qt"}


def test_qtwebengine_sandbox_state_reports_reason():
    from jarvis.platform.linux.webview_engine import QtWebEngine

    engine = QtWebEngine()
    engine.prepare_env({"QTWEBENGINE_DISABLE_SANDBOX": "1"})
    assert engine.sandbox_state() != "n/a"
