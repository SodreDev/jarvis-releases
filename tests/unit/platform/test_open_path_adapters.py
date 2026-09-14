"""K F2-06: adapters de open_path e o REGISTRY.

- Windows (W1): StartfileOpenPath faz o mesmo que o oráculo legado de 31bc0ce
  (os.startfile 1× com o mesmo argumento, exceção propagada; notepad literal).
- Linux: xdg-open/gio destacados, código ≠ 0 em 3 s vira OSError, processo que
  continua rodando conta como sucesso; ferramentas falsas via fake_tools (nunca
  o xdg-open de verdade).
- REGISTRY: win32 → StartfileOpenPath; linux-* → XdgOpen → GioOpen.
"""
import subprocess
import sys
import time

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.unavailable import Unavailable
from jarvis.platform.detect import detect
from jarvis.platform.linux import open_path as linux_open_path
from jarvis.platform.linux import tools
from jarvis.platform.windows.open_path import StartfileOpenPath
from tests.golden.legacy_31bc0ce import legacy_open_path_windows, legacy_open_text_file_windows

WIN32 = detect(sys_platform="win32", environ={}, frozen=False)
WAYLAND = detect(sys_platform="linux", environ={"WAYLAND_DISPLAY": "wayland-0"}, frozen=False)
HEADLESS = detect(sys_platform="linux", environ={}, frozen=False)


@pytest.fixture(autouse=True)
def _limpo():
    registry._clear_all()
    tools.clear_which_cache()
    yield
    registry._clear_all()
    tools.clear_which_cache()


# ── Windows: igual ao oráculo legado ────────────────────────────────────────────

def test_windows_open_igual_ao_legado():
    alvo = r"C:\Users\ana\Downloads\relatorio.pdf"
    novo, velho = [], []
    assert StartfileOpenPath(WIN32, startfile_fn=novo.append).open(alvo) is True
    legacy_open_path_windows(velho.append, alvo)
    assert novo == velho == [alvo]


def test_windows_open_propaga_excecao():
    def falha(_alvo):
        raise OSError("arquivo não encontrado")

    with pytest.raises(OSError, match="arquivo não encontrado"):
        StartfileOpenPath(WIN32, startfile_fn=falha).open("x.txt")


def test_windows_open_text_file_igual_ao_legado():
    novo, velho = [], []
    StartfileOpenPath(WIN32, popen_fn=lambda a, **k: novo.append((a, k))).open_text_file(r"C:\temp\longo.txt")
    legacy_open_text_file_windows(lambda a, **k: velho.append((a, k)), r"C:\temp\longo.txt")
    assert novo == velho == [(["notepad.exe", r"C:\temp\longo.txt"], {"close_fds": True})]


# ── Linux ────────────────────────────────────────────────────────────────────────

class _Proc:
    def __init__(self, code=0, roda=False):
        self.code = code
        self.roda = roda
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.roda and timeout is not None:
            raise subprocess.TimeoutExpired("xdg-open", timeout)
        return self.code


def test_linux_codigo_diferente_de_zero_vira_oserror():
    proc = _Proc(code=4)
    with pytest.raises(OSError, match="código 4"):
        linux_open_path.XdgOpen(WAYLAND, popen_fn=lambda a, **k: proc).open("/nao/existe.pdf")
    assert proc.waits == [3.0]


def test_linux_processo_que_continua_rodando_e_sucesso():
    proc = _Proc(roda=True)
    assert linux_open_path.GioOpen(WAYLAND, popen_fn=lambda a, **k: proc).open("/tmp/a.pdf") is True
    for _ in range(50):  # a thread daemon faz o wait() sem timeout
        if None in proc.waits:
            break
        time.sleep(0.01)
    assert proc.waits[0] == 3.0 and None in proc.waits


def test_linux_open_text_file_abre_no_app_padrao():
    chamadas = []

    def popen(argv, **kwargs):
        chamadas.append(argv)
        return _Proc()

    assert linux_open_path.XdgOpen(WAYLAND, popen_fn=popen).open_text_file("/tmp/longo.txt") is True
    assert chamadas == [["xdg-open", "/tmp/longo.txt"]]


def test_linux_nao_registra_filho(monkeypatch):
    from jarvis.platform.linux.processes import PosixProcesses

    def proibido(*args, **kwargs):
        raise AssertionError("open_path não pode registrar filho")

    monkeypatch.setattr(PosixProcesses, "register_child", proibido)
    assert linux_open_path.XdgOpen(WAYLAND, popen_fn=lambda a, **k: _Proc()).open("https://exemplo.com") is True


@pytest.mark.linux_only
@pytest.mark.skipif(sys.platform == "win32", reason="ferramentas falsas são scripts bash")
@pytest.mark.parametrize("cls, ferramenta, prefixo", [
    (linux_open_path.XdgOpen, "xdg-open", ""),
    (linux_open_path.GioOpen, "gio", "open "),
])
def test_linux_ferramenta_falsa_recebe_argumentos(fake_tools, cls, ferramenta, prefixo):
    calls = fake_tools({ferramenta: "exit 0"})
    assert tools.which(ferramenta).startswith(str(calls[ferramenta].parent.parent))  # nunca a real
    assert cls(WAYLAND).open("/tmp/relatório final.pdf") is True
    assert calls[ferramenta].read_text().splitlines() == [f"{prefixo}/tmp/relatório final.pdf"]


@pytest.mark.linux_only
@pytest.mark.skipif(sys.platform == "win32", reason="ferramentas falsas são scripts bash")
def test_linux_ferramenta_falsa_que_falha_levanta(fake_tools):
    fake_tools({"xdg-open": "exit 3"})
    with pytest.raises(OSError):
        linux_open_path.XdgOpen(WAYLAND).open("whatsapp://")


# ── REGISTRY ─────────────────────────────────────────────────────────────────────

def test_registro_win32_startfile():
    inst = registry.resolve(Cap.OPEN_PATH, WIN32)
    assert inst.name == "windows.startfile"


@pytest.mark.linux_only
@pytest.mark.skipif(sys.platform == "win32", reason="ferramentas falsas são scripts bash")
@pytest.mark.parametrize("ctx", [WAYLAND, HEADLESS], ids=["wayland", "headless"])
def test_registro_linux_xdg_open_depois_gio(fake_tools, monkeypatch, tmp_path, ctx):
    assert registry._chain_for(Cap.OPEN_PATH, ctx.kind) == (
        "jarvis.platform.linux.open_path:XdgOpen",
        "jarvis.platform.linux.open_path:GioOpen",
    )
    so_fakes = tmp_path / "fake_tools_bin"

    fake_tools({"xdg-open": "exit 0", "gio": "exit 0"})
    monkeypatch.setenv("PATH", str(so_fakes))
    assert registry.resolve(Cap.OPEN_PATH, ctx).name == "linux.xdg_open"

    (so_fakes / "xdg-open").unlink()
    tools.clear_which_cache()
    registry.refresh(Cap.OPEN_PATH)
    assert registry.resolve(Cap.OPEN_PATH, ctx).name == "linux.gio_open"

    (so_fakes / "gio").unlink()
    tools.clear_which_cache()
    registry.refresh(Cap.OPEN_PATH)
    assert isinstance(registry.resolve(Cap.OPEN_PATH, ctx), Unavailable)
