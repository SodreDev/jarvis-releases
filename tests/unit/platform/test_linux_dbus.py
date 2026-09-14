"""K F2-00 (N1): jarvis.platform.linux.dbus num D-Bus PRIVADO.

Os testes com serviço usam só a fixture ``private_session_bus`` (dbus-daemon do
próprio teste) e um objeto do python-dbusmock nele. Os demais apontam
``DBUS_SESSION_BUS_ADDRESS`` para um socket inexistente: nenhum teste fala com o
D-Bus do host.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.linux_only,
    pytest.mark.skipif(not sys.platform.startswith("linux"), reason="D-Bus só no Linux"),
]

pytest.importorskip("jeepney")

from jarvis.platform.linux import dbus as jdbus  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

NOME = "org.jarvis.TesteF2"
CAMINHO = "/org/jarvis/TesteF2"
IFACE = "org.jarvis.TesteF2"
MOCK_IFACE = "org.freedesktop.DBus.Mock"


@pytest.fixture(autouse=True)
def _sem_dbus_do_host(monkeypatch, tmp_path):
    """Sem a fixture de barramento privado, qualquer conexão cai num socket que não existe."""
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={tmp_path}/sem-barramento")
    jdbus.reset()
    yield
    jdbus.reset()


@pytest.fixture
def servico_falso(private_session_bus):
    """Objeto dbusmock em NOME/CAMINHO no barramento privado; encerra só o PID dele."""
    dbusmock = pytest.importorskip("dbusmock")
    proc = dbusmock.DBusTestCase.spawn_server(NOME, CAMINHO, IFACE, stdout=subprocess.DEVNULL)
    try:
        yield proc
    finally:
        jdbus.reset()
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _add_method(nome, in_sig, out_sig, codigo):
    jdbus.call(NOME, CAMINHO, MOCK_IFACE, "AddMethod", "sssss", (IFACE, nome, in_sig, out_sig, codigo))


def test_call_devolve_corpo(servico_falso):
    _add_method("Soma", "ii", "i", "ret = args[0] + args[1]")
    assert jdbus.call(NOME, CAMINHO, IFACE, "Soma", "ii", (2, 3)) == (5,)


def test_resposta_de_erro_vira_dbuserror_com_nome(servico_falso):
    with pytest.raises(jdbus.DBusError) as exc:
        jdbus.call(NOME, CAMINHO, IFACE, "NaoExiste")
    assert exc.value.name and exc.value.name.startswith("org.freedesktop.DBus.Error.")


def test_get_property_desembrulha_variante(servico_falso):
    jdbus.call(NOME, CAMINHO, MOCK_IFACE, "AddProperty", "ssv", (IFACE, "version", ("u", 2)))
    assert jdbus.get_property(NOME, CAMINHO, IFACE, "version") == 2


def test_name_has_owner(servico_falso):
    assert jdbus.name_has_owner(NOME) is True
    inicio = time.monotonic()
    assert jdbus.name_has_owner("org.kde.StatusNotifierWatcher") is False
    assert time.monotonic() - inicio <= 1.2


def test_sinal_chega_na_fila(servico_falso):
    regra = jdbus.match_rule(interface=IFACE, member="Mudou", path=CAMINHO)
    with jdbus.subscribe(regra) as fila:
        jdbus.call(NOME, CAMINHO, MOCK_IFACE, "EmitSignal", "sssav", (IFACE, "Mudou", "s", [("s", "oi")]))
        msg = fila.get(timeout=3)
    assert msg is not None
    assert msg.body == ("oi",)


def test_fila_sem_sinal_devolve_none(servico_falso):
    regra = jdbus.match_rule(interface=IFACE, member="NuncaEmitido")
    with jdbus.subscribe(regra) as fila:
        assert fila.get(timeout=0.2) is None


def test_timeout_levanta_timeouterror(servico_falso):
    _add_method("Lento", "", "", "__import__('time').sleep(2)")
    inicio = time.monotonic()
    with pytest.raises(TimeoutError):
        jdbus.call(NOME, CAMINHO, IFACE, "Lento", timeout=0.3)
    assert time.monotonic() - inicio < 1.0


def test_roteador_dedicado_e_separado(servico_falso):
    dedicado = jdbus.open_dedicated_router()
    try:
        assert dedicado is not jdbus.session_router()
        assert jdbus.name_has_owner(NOME, router=dedicado) is True
    finally:
        jdbus.close_router(dedicado)
    assert jdbus.name_has_owner(NOME) is True  # o compartilhado segue vivo


def test_dez_threads_no_roteador_compartilhado(servico_falso):
    resultados = []
    barreira = threading.Barrier(10)

    def worker():
        barreira.wait()
        resultados.append((jdbus.name_has_owner(NOME), jdbus.session_router()))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(resultados) == 10
    assert all(ok for ok, _ in resultados)
    assert len({id(r) for _, r in resultados}) == 1


def test_sonda_sem_barramento_termina_rapido():
    inicio = time.monotonic()
    assert jdbus.name_has_owner("org.freedesktop.portal.Desktop") is False
    assert time.monotonic() - inicio <= 1.2
    with pytest.raises(jdbus.DBusError):
        jdbus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                   "org.freedesktop.Notifications", "GetServerInformation", timeout=1.0)


def test_sem_endereco_nao_adivinha_barramento(monkeypatch):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS")
    assert jdbus.name_has_owner("org.freedesktop.DBus") is False
    with pytest.raises(jdbus.DBusError):
        jdbus.session_router()


def test_importar_modulos_novos_nao_carrega_jeepney():
    snippet = (
        "import sys\n"
        "import jarvis.platform as p\n"
        "p.current()\n"
        "import jarvis.platform.linux.dbus, jarvis.platform.linux.tools, jarvis.platform.linux.app_id\n"
        "ruins = sorted(m for m in sys.modules if m.split('.')[0] == 'jeepney')\n"
        "print('CARREGADOS:' + ','.join(ruins))\n"
        "sys.exit(1 if ruins else 0)\n"
    )
    env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS="unix:path=/nonexistent/jarvis-sem-barramento")
    proc = subprocess.run(
        [sys.executable, "-c", snippet], capture_output=True, text=True, timeout=60, cwd=REPO_ROOT, env=env
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
