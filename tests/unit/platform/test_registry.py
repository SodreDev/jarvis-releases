"""Resolução lazy do registro: cadeia, falhas, probe, cache, threads, refresh."""
import sys
import threading
import types

import pytest

from jarvis.platform import registry
from jarvis.platform.capabilities import Cap
from jarvis.platform.common.base import Probe
from jarvis.platform.common.unavailable import Unavailable
from jarvis.platform.detect import detect
from jarvis.platform.errors import CapabilityUnavailable

CTX = detect(sys_platform="linux", environ={"DISPLAY": ":0"}, frozen=False)  # linux-x11


@pytest.fixture(autouse=True)
def _limpa_registro():
    """Salva/restaura REGISTRY e limpa o cache e os módulos falsos entre testes."""
    salvo = dict(registry.REGISTRY)
    fakes_antes = set(sys.modules)
    registry._clear_all()
    yield
    registry.REGISTRY.clear()
    registry.REGISTRY.update(salvo)
    registry._clear_all()
    for nome in set(sys.modules) - fakes_antes:
        if nome.startswith("fake_plat_"):
            sys.modules.pop(nome, None)


def _instalar_modulo(nome, **attrs):
    mod = types.ModuleType(nome)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[nome] = mod
    return mod


def _make_backend(nome_backend, ok=True, reason=""):
    """Fábrica de classe backend que conta probes e instâncias."""
    contador = {"probe": 0, "init": 0}

    class _B:
        name = nome_backend

        @classmethod
        def probe(cls, ctx):
            contador["probe"] += 1
            return Probe(ok, reason)

        def __init__(self, ctx):
            contador["init"] += 1
            self.ctx = ctx

    _B.contador = contador
    return _B


def test_cadeia_usa_primeiro_que_passa_e_registra_falhas():
    Good = _make_backend("bom")
    _instalar_modulo("fake_plat_a")  # sem a classe → getattr falha
    _instalar_modulo("fake_plat_b", Good=Good)
    registry.REGISTRY[Cap.PATHS] = {
        "linux-x11": ("fake_plat_a:Missing", "fake_plat_b:Good"),
    }
    inst = registry.resolve(Cap.PATHS, CTX)
    assert getattr(inst, "name", None) == "bom"


def test_falha_de_import_registrada_no_tried():
    registry.REGISTRY[Cap.CLIPBOARD] = {"linux-x11": ("fake_plat_inexistente:X",)}
    inst = registry.resolve(Cap.CLIPBOARD, CTX)
    assert isinstance(inst, Unavailable)
    caminho, motivo = inst._tried[0]
    assert caminho == "fake_plat_inexistente:X"
    assert motivo.startswith("import:")


def test_probe_negativo_pula_backend():
    Nao = _make_backend("nao", ok=False, reason="sem suporte")
    Sim = _make_backend("sim")
    _instalar_modulo("fake_plat_nao", B=Nao)
    _instalar_modulo("fake_plat_sim", B=Sim)
    registry.REGISTRY[Cap.VOLUME] = {
        "linux-x11": ("fake_plat_nao:B", "fake_plat_sim:B"),
    }
    inst = registry.resolve(Cap.VOLUME, CTX)
    assert inst.name == "sim"
    assert Nao.contador["init"] == 0  # não instanciou o de probe negativo


def test_ordem_das_chaves_familia_e_curinga():
    Fam = _make_backend("familia")
    _instalar_modulo("fake_plat_fam", B=Fam)
    registry.REGISTRY[Cap.TRAY] = {
        "linux-*": ("fake_plat_fam:B",),
        "*": ("fake_plat_fam:B",),
    }
    # não há chave "linux-x11" exata → usa "linux-*"
    assert registry.resolve(Cap.TRAY, CTX).name == "familia"


def test_nao_mistura_cadeias():
    Exato = _make_backend("exato")
    _instalar_modulo("fake_plat_exato", B=Exato)
    registry.REGISTRY[Cap.SESSION] = {
        "linux-x11": ("fake_plat_falha:Z",),  # existe a chave exata, mas falha
        "*": ("fake_plat_exato:B",),          # NÃO deve cair aqui
    }
    inst = registry.resolve(Cap.SESSION, CTX)
    assert isinstance(inst, Unavailable)  # ficou só na cadeia da chave exata


def test_cache_resolve_uma_vez():
    B = _make_backend("cacheado")
    _instalar_modulo("fake_plat_cache", B=B)
    registry.REGISTRY[Cap.MEDIA] = {"linux-x11": ("fake_plat_cache:B",)}
    a = registry.resolve(Cap.MEDIA, CTX)
    b = registry.resolve(Cap.MEDIA, CTX)
    assert a is b
    assert B.contador["init"] == 1
    assert B.contador["probe"] == 1


def test_dez_threads_mesma_instancia():
    B = _make_backend("thread")
    _instalar_modulo("fake_plat_thread", B=B)
    registry.REGISTRY[Cap.NOTIFIER] = {"linux-x11": ("fake_plat_thread:B",)}

    resultados = []
    barreira = threading.Barrier(10)

    def worker():
        barreira.wait()
        resultados.append(registry.resolve(Cap.NOTIFIER, CTX))

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(resultados) == 10
    assert all(r is resultados[0] for r in resultados)
    assert B.contador["init"] == 1


def test_unavailable_levanta_ao_usar():
    registry.REGISTRY[Cap.HOTKEYS] = {}  # sem cadeia
    inst = registry.resolve(Cap.HOTKEYS, CTX)
    assert isinstance(inst, Unavailable)
    assert registry.has(Cap.HOTKEYS, CTX) is False
    with pytest.raises(CapabilityUnavailable):
        inst.qualquer_metodo()
    with pytest.raises(CapabilityUnavailable):
        _ = inst.qualquer_atributo


def test_refresh_reresolve():
    B = _make_backend("refresh")
    _instalar_modulo("fake_plat_refresh", B=B)
    registry.REGISTRY[Cap.WINDOW_MANAGER] = {"linux-x11": ("fake_plat_refresh:B",)}
    registry.resolve(Cap.WINDOW_MANAGER, CTX)
    assert B.contador["init"] == 1
    registry.refresh(Cap.WINDOW_MANAGER)
    registry.resolve(Cap.WINDOW_MANAGER, CTX)
    assert B.contador["init"] == 2


def test_report_estrutura():
    B = _make_backend("rep")
    _instalar_modulo("fake_plat_rep", B=B)
    # só a entrada falsa: report() não pode sondar backend real (ex.: pynput abre o X de quem testa)
    registry.REGISTRY.clear()
    registry.REGISTRY[Cap.PATHS] = {"linux-x11": ("fake_plat_rep:B",)}
    rep = registry.report(CTX)
    assert rep["kind"] == "linux-x11"
    assert rep["source"] == "display"
    assert rep["capabilities"]["paths"]["backend"] == "rep"
    assert rep["capabilities"]["hotkeys"]["backend"] is None
    assert isinstance(rep["features"], list)
