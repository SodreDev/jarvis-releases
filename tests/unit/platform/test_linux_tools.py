"""K F2-00: jarvis.platform.linux.tools com ferramentas falsas (fixture fake_tools).

run_tool: sem shell, LC_ALL=C, timeout sempre, None quando a ferramenta falta
ou estoura, código de saída não levanta, e o processo não é registrado como
filho. which: cache por (nome, PATH).
"""
import shutil
import sys
import time

import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.skipif(sys.platform == "win32", reason="ferramentas falsas são scripts bash"),
]

from jarvis.platform.linux import processes as posix_processes  # noqa: E402
from jarvis.platform.linux import tools  # noqa: E402


@pytest.fixture(autouse=True)
def _cache_limpo():
    tools.clear_which_cache()
    yield
    tools.clear_which_cache()


def test_saida_e_argumentos(fake_tools):
    calls = fake_tools({"wpctl": "echo 'Volume: 0.50'"})
    r = tools.run_tool(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    assert r is not None and r.returncode == 0
    assert r.stdout.strip() == "Volume: 0.50"
    assert calls["wpctl"].read_text().splitlines() == ["get-volume @DEFAULT_AUDIO_SINK@"]


def test_lc_all_c(fake_tools, monkeypatch):
    monkeypatch.setenv("LC_ALL", "pt_BR.UTF-8")
    fake_tools({"pactl": 'echo "$LC_ALL"'})
    assert tools.run_tool(["pactl", "info"]).stdout.strip() == "C"


def test_sem_shell(fake_tools, tmp_path):
    fake_tools({"xdg-open": 'printf "%s" "$1"'})
    alvo = tmp_path / "invadido"
    arg = f"; touch {alvo}; $(touch {alvo})"
    r = tools.run_tool(["xdg-open", arg])
    assert r.stdout == arg
    assert not alvo.exists()


def test_input_vai_para_stdin(fake_tools):
    fake_tools({"wl-copy": "cat"})
    assert tools.run_tool(["wl-copy"], input="olá, Jarvis").stdout == "olá, Jarvis"


def test_sem_input_stdin_fechado_nao_trava(fake_tools):
    fake_tools({"wl-paste": "cat"})
    inicio = time.monotonic()
    r = tools.run_tool(["wl-paste"], timeout=2.0)
    assert r is not None and r.stdout == ""
    assert time.monotonic() - inicio < 1.5


def test_codigo_de_saida_nao_levanta(fake_tools):
    fake_tools({"playerctl": "echo 'No players found' >&2; exit 1"})
    r = tools.run_tool(["playerctl", "status"])
    assert r.returncode == 1
    assert "No players found" in r.stderr


def test_ferramenta_ausente_devolve_none():
    assert tools.which("jarvis-ferramenta-que-nao-existe") is None
    assert tools.run_tool(["jarvis-ferramenta-que-nao-existe", "--version"]) is None


def test_argv_vazio_devolve_none():
    assert tools.run_tool([]) is None


def test_timeout_devolve_none(fake_tools):
    fake_tools({"gio": "exec sleep 5"})
    inicio = time.monotonic()
    assert tools.run_tool(["gio", "open", "/tmp"], timeout=0.3) is None
    assert time.monotonic() - inicio < 2.0


def test_which_cacheia_por_nome_e_path(fake_tools, monkeypatch):
    fake_tools({"xclip": "true"})
    reais = []
    original = shutil.which

    def contando(nome, *args, **kwargs):
        reais.append(nome)
        return original(nome, *args, **kwargs)

    monkeypatch.setattr(tools.shutil, "which", contando)
    primeiro = tools.which("xclip")
    assert primeiro is not None and primeiro.endswith("/xclip")
    assert tools.which("xclip") == primeiro
    assert reais == ["xclip"]

    monkeypatch.setenv("PATH", "/nonexistent-jarvis")
    assert tools.which("xclip") is None
    assert reais == ["xclip", "xclip"]


def test_nao_registra_processo_como_filho(fake_tools, monkeypatch):
    def proibido(*args, **kwargs):
        raise AssertionError("run_tool não pode registrar filho")

    monkeypatch.setattr(posix_processes.PosixProcesses, "register_child", proibido)
    fake_tools({"notify-send": "true"})
    assert tools.run_tool(["notify-send", "titulo", "corpo"]).returncode == 0
