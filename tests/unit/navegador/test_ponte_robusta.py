"""A ponte que não prende o Jarvis (dono, 2026-10-30: «o app trava» e «o Jarvis não sabe mais usar
a extensão»): prazo por método, cancelamento com o pedido em voo, a pergunta de versão ao host e à
extensão, e a extensão de antes reconhecida com a frase do que fazer. Host de verdade, extensão
falsa numa thread, socket numa pasta temporária — nenhum navegador do dono."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.navegador.cliente import (
    RECARREGAR,
    ChamadaCancelada,
    ClienteDoNavegador,
    ExtensaoDesatualizada,
    SemResposta,
    TransporteUnix,
    VersaoDaPonte,
)
from jarvis.navegador.estado import sondar
from jarvis.navegador.ferramentas import CorposDoNavegador
from jarvis.navegador.protocolo import (
    PRAZO_CURTO_S,
    PRAZO_PADRAO_S,
    VERSAO_DA_PONTE,
    prazo_do_metodo,
)
from jarvis.navegador.quadro import codificar
from tests.unit.navegador.test_host import Extensao, Navegador

RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture
def curto(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("p")  # caminho de socket Unix tem teto de ~100 caracteres


@pytest.fixture
def navegador(curto: Path) -> Iterator[Callable[[Extensao, float], Navegador]]:
    abertos: list[Navegador] = []

    def abrir(roteiro: Extensao, prazo_s: float = 5.0) -> Navegador:
        nav = Navegador(curto, roteiro, prazo_s)
        nav.abrir()
        abertos.append(nav)
        return nav

    yield abrir
    for nav in abertos:
        nav.fechar()


def _extensao_atual(pedido: dict[str, Any]) -> dict[str, Any]:
    if pedido["method"] == "ponte.versao":
        resultado: dict[str, Any] = {
            "versao": VERSAO_DA_PONTE,
            "manifesto": "0.2.0",
            "permissoes": {"debugger": True, "scripting": True},
        }
        return {"id": pedido["id"], "ok": True, "result": resultado}
    return {"id": pedido["id"], "ok": True, "result": {"abas": []}}


def _extensao_de_antes(pedido: dict[str, Any]) -> dict[str, Any]:
    """A cópia de antes do CDP: não conhece `ponte.versao` nem `page.console`."""
    if pedido["method"] in ("ponte.versao", "page.console"):
        erro = {"codigo": "metodo_invalido", "mensagem": "método não autorizado para a extensão"}
        return {"id": pedido["id"], "ok": False, "error": erro}
    if pedido["method"] == "tabs.current":
        aba = {"id": 3, "url": "https://exemplo.org/", "titulo": "Exemplo"}
        return {"id": pedido["id"], "ok": True, "result": {"aba": aba}}
    return {"id": pedido["id"], "ok": True, "result": {"abas": []}}


def _calada(_pedido: dict[str, Any]) -> None:
    """A extensão travada: recebe e não responde."""
    return None


def test_o_prazo_e_curto_para_consultar_e_longo_para_esperar_a_pagina() -> None:
    assert prazo_do_metodo("tabs.list") == PRAZO_CURTO_S
    assert prazo_do_metodo("page.read") == PRAZO_CURTO_S
    assert prazo_do_metodo("tabs.navigate") == PRAZO_PADRAO_S
    assert prazo_do_metodo("page.readUrl") == PRAZO_PADRAO_S
    transporte = TransporteUnix(Path("/nao/existe"))
    assert transporte.prazo_de("tabs.list") == PRAZO_CURTO_S
    # o pedido longo espera um pouco mais que o host, para ouvir o «tempo_esgotado» dele
    assert transporte.prazo_de("tabs.navigate") > PRAZO_PADRAO_S


def test_a_extensao_travada_nao_prende_o_jarvis_alem_do_prazo_do_metodo(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_calada, 30.0)  # o host esperaria 30 s; o Jarvis não
    cliente = ClienteDoNavegador(TransporteUnix(nav.pasta, prazo_s=0.6))

    comeco = time.monotonic()
    with pytest.raises(SemResposta):
        cliente.abas()
    assert time.monotonic() - comeco < 3.0


def test_cancelar_com_o_pedido_em_voo_larga_a_espera_na_hora(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_calada, 30.0)
    cancelado = threading.Event()
    cliente = ClienteDoNavegador(TransporteUnix(nav.pasta)).sob(None, cancelado.is_set)
    threading.Timer(0.2, cancelado.set).start()

    comeco = time.monotonic()
    with pytest.raises(ChamadaCancelada):
        cliente.navegar(3, "https://exemplo.org/")  # longo: o prazo seria de 30 s
    assert time.monotonic() - comeco < 2.0
    assert nav.chegou.is_set()


def test_o_host_responde_a_propria_versao_sem_ir_a_extensao(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_extensao_atual, 5.0)
    versao = ClienteDoNavegador(TransporteUnix(nav.pasta)).versao()

    assert versao == VersaoDaPonte(
        host=VERSAO_DA_PONTE,
        extensao=VERSAO_DA_PONTE,
        manifesto="0.2.0",
        pid_do_host=versao.pid_do_host,
        host_iniciado_em=versao.host_iniciado_em,
        permissoes={"debugger": True, "scripting": True},
        host_conhece=True,
        extensao_conhece=True,
    )
    assert versao.em_dia and versao.o_que_fazer() == ""
    assert [p["method"] for p in nav.recebidos] == ["ponte.versao"]  # host.versao ficou no host


def test_a_extensao_de_antes_e_reconhecida_e_o_dono_ouve_para_recarregar(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_extensao_de_antes, 5.0)
    cliente = ClienteDoNavegador(TransporteUnix(nav.pasta))

    versao = cliente.versao()
    assert (versao.host, versao.extensao, versao.extensao_conhece) == (VERSAO_DA_PONTE, None, False)
    assert versao.o_que_fazer() == RECARREGAR
    with pytest.raises(ExtensaoDesatualizada) as erro:
        cliente.console(3)
    assert "Recarregar" in erro.value.mensagem


def test_metodo_antigo_que_falha_continua_sendo_falha_da_pagina() -> None:
    """`metodo_invalido` num método que a extensão de antes já conhecia não é versão velha."""

    class Transporte:
        def chamar(self, pedido: Any, navegador: str = "") -> dict[str, Any]:
            erro = {"codigo": "metodo_invalido", "mensagem": "x"}
            return {"id": pedido.id, "ok": False, "error": erro}

    with pytest.raises(Exception) as erro:
        ClienteDoNavegador(Transporte()).abas()
    assert not isinstance(erro.value, ExtensaoDesatualizada)


def test_o_estado_da_ponte_diz_o_que_fazer_com_a_extensao_de_antes(
    navegador: Callable[[Extensao, float], Navegador], tmp_path: Path
) -> None:
    nav = navegador(_extensao_de_antes, 5.0)
    estado = sondar(
        ligado=True,
        principal="brave",
        transporte=TransporteUnix(nav.pasta),
        home=tmp_path,
        raiz_do_sistema=tmp_path,
        conferir_versao=True,
    )

    assert estado.conectado
    assert estado.desatualizada == RECARREGAR
    assert estado.o_que_fazer()[0] == RECARREGAR
    modelo = estado.para_o_modelo()
    assert modelo["versao_em_dia"] is False and modelo["versao_da_extensao"] is None
    assert "Recarregar" in estado.frase()
    assert any("versão da ponte" in linha for linha in estado.linhas())


def test_o_estado_da_ponte_em_dia_nao_pede_nada(
    navegador: Callable[[Extensao, float], Navegador], tmp_path: Path
) -> None:
    nav = navegador(_extensao_atual, 5.0)
    estado = sondar(
        ligado=True,
        principal="brave",
        transporte=TransporteUnix(nav.pasta),
        home=tmp_path,
        raiz_do_sistema=tmp_path,
        conferir_versao=True,
    )
    assert estado.desatualizada == "" and estado.para_o_modelo()["versao_em_dia"] is True


def test_a_ferramenta_com_a_extensao_de_antes_diz_para_recarregar(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_extensao_de_antes, 5.0)
    corpos = CorposDoNavegador(ClienteDoNavegador(TransporteUnix(nav.pasta)))

    def exigir(*_args: object, **_kwargs: object) -> None:
        return None

    with pytest.raises(ValueError, match="extensão desatualizada") as erro:
        corpos.executar(
            "browser.console",
            {"tab_id": 3},
            contaminado=False,
            liberados=frozenset(),
            exigir=exigir,
            cancelado=lambda: False,
        )
    assert "Recarregar" in str(erro.value)


def test_a_ferramenta_cancelada_no_meio_nao_vira_falha(
    navegador: Callable[[Extensao, float], Navegador],
) -> None:
    nav = navegador(_calada, 30.0)
    corpos = CorposDoNavegador(ClienteDoNavegador(TransporteUnix(nav.pasta)))
    cancelado = threading.Event()
    threading.Timer(0.2, cancelado.set).start()

    def exigir(*_args: object, **_kwargs: object) -> None:
        return None

    with pytest.raises(ChamadaCancelada):
        corpos.executar(
            "browser.tabs",
            {},
            contaminado=False,
            liberados=frozenset(),
            exigir=exigir,
            cancelado=cancelado.is_set,
        )


def test_a_versao_da_extensao_e_a_do_python() -> None:
    fundo = (RAIZ / "extensao" / "background.js").read_text(encoding="utf-8")
    achado = re.search(r"const VERSAO_DA_PONTE = (\d+);", fundo)
    assert achado is not None and int(achado.group(1)) == VERSAO_DA_PONTE
    assert 'case "ponte.versao"' in fundo


def test_o_quadro_com_surrogate_solto_nao_derruba_a_ponte() -> None:
    """O Firefox manda o emoji cortado ao meio pelo `slice` como surrogate solto: o quadro passa,
    com `?` no lugar do caractere quebrado."""
    corpo = codificar({"texto": "a\ud83db"}, 1000)
    assert corpo.endswith(b'{"texto":"a?b"}')
