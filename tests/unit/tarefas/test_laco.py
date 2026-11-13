"""ADR-0062: a guarda de laço da tarefa — repetir sem avançar avisa, e depois do aviso para."""

from __future__ import annotations

from typing import Any

from jarvis.executor.ferramentas import ResultadoDeFerramenta
from jarvis.s2.motor import PedidoDeTool
from jarvis.tarefas.laco import (
    AcaoDoLaco,
    GuardaDeLaco,
    Laco,
    TipoDeLaco,
    campos_na_trilha,
    marca_do_passo,
)

SEGREDO = "a senha do cofre é 9876"


def _ok(tool_id: str, **dados: Any) -> ResultadoDeFerramenta:
    return ResultadoDeFerramenta(tool_id=tool_id, status="ok", dados=dados)


def _passo(
    guarda: GuardaDeLaco, tool_id: str, args: dict[str, Any] | None = None, **dados: Any
) -> Laco | None:
    return guarda.observar(PedidoDeTool(tool_id, args or {}), _ok(tool_id, **dados))


def test_a_mesma_acao_com_o_mesmo_resultado_tres_vezes_avisa_e_a_quarta_para() -> None:
    guarda = GuardaDeLaco()
    assert _passo(guarda, "browser.read", texto="igual") is None
    assert _passo(guarda, "browser.read", texto="igual") is None
    aviso = _passo(guarda, "browser.read", texto="igual")
    assert aviso == Laco(TipoDeLaco.IDENTICA, 1, ("browser.read",), AcaoDoLaco.AVISO)
    parada = _passo(guarda, "browser.read", texto="igual")
    assert parada is not None and parada.acao is AcaoDoLaco.PARADA


def test_rolar_e_ler_com_texto_novo_a_cada_volta_nao_e_laco() -> None:
    """O falso positivo que comparar só o nome da ferramenta daria: ler página longa. Rolar
    devolve sempre o mesmo «ok», mas a leitura depois traz texto novo."""
    guarda = GuardaDeLaco()
    for pagina in range(12):
        assert _passo(guarda, "browser.scroll", {"direcao": "baixo"}, ok=True) is None
        assert _passo(guarda, "browser.read", texto=f"trecho {pagina}") is None


def test_a_mesma_ferramenta_com_argumentos_diferentes_nao_e_laco() -> None:
    guarda = GuardaDeLaco()
    for consulta in ("hotel em Recife", "pousada em Olinda", "hostel em Recife", "voo Recife"):
        assert _passo(guarda, "web.buscar", {"q": consulta}, resultados=[]) is None


def test_vai_e_volta_de_periodo_dois_e_tres() -> None:
    guarda = GuardaDeLaco()
    assert _passo(guarda, "browser.tabs", abas=1) is None
    assert _passo(guarda, "browser.navigate", {"url": "a"}, ok=True) is None
    assert _passo(guarda, "browser.tabs", abas=1) is None
    laco = _passo(guarda, "browser.navigate", {"url": "a"}, ok=True)
    assert laco is not None and laco.tipo is TipoDeLaco.CICLO and laco.periodo == 2
    assert laco.ferramentas == ("browser.tabs", "browser.navigate")

    tres = GuardaDeLaco()
    sequencia = [("window.list", {}), ("window.focus_app", {"app": "x"}), ("browser.read", {})]
    achados = [_passo(tres, t, a, r=1) for t, a in sequencia * 2]
    assert achados[:-1] == [None] * 5
    assert achados[-1] is not None and achados[-1].periodo == 3


def test_o_ciclo_mais_longo_cai_nos_passos_sem_nada_novo() -> None:
    guarda = GuardaDeLaco()
    ciclo = [
        ("browser.tabs", {}),
        ("browser.navigate", {"url": "a"}),
        ("browser.read", {}),
        ("browser.navigate", {"url": "b"}),
    ]
    achados = [_passo(guarda, t, a, r=1) for t, a in ciclo * 3]
    primeiro = next(a for a in achados if a is not None)
    assert achados.index(primeiro) == 9, "4 passos novos e 6 sem nada novo"
    assert primeiro.tipo is TipoDeLaco.SEM_NOVIDADE and primeiro.periodo == 6
    assert primeiro.ferramentas == ("browser.tabs", "browser.navigate", "browser.read")
    assert "6 passos sem nada novo" in primeiro.linha_na_tela()


def test_mudar_de_caminho_depois_do_aviso_segue_a_tarefa() -> None:
    guarda = GuardaDeLaco()
    for _ in range(3):
        laco = _passo(guarda, "browser.read", texto="igual")
    assert laco is not None and laco.acao is AcaoDoLaco.AVISO
    assert _passo(guarda, "browser.scroll", {"direcao": "baixo"}, ok=True) is None
    assert _passo(guarda, "browser.read", texto="novo") is None


def test_a_marca_muda_com_o_resultado_e_nao_guarda_o_texto() -> None:
    pedido = PedidoDeTool("files.read_text", {"caminho": "notas.txt"})
    uma = marca_do_passo(pedido, _ok("files.read_text", texto=SEGREDO))
    outra = marca_do_passo(pedido, _ok("files.read_text", texto="outra coisa"))
    assert uma != outra and len(uma) == 16 and SEGREDO not in uma
    falhou = ResultadoDeFerramenta("files.read_text", "erro", motivo="sem permissão")
    assert marca_do_passo(pedido, falhou) != uma


def test_nota_linha_e_trilha_dizem_o_laco_sem_argumento_nem_resultado() -> None:
    laco = Laco(TipoDeLaco.CICLO, 2, ("browser.tabs", "browser.navigate"), AcaoDoLaco.AVISO)
    nota = laco.nota_ao_motor()
    assert "LAÇO" in nota and "browser.tabs → browser.navigate" in nota and "termine" in nota
    assert "avisei" in laco.linha_na_tela()
    assert campos_na_trilha(laco, 7) == {
        "tool_id": "browser.navigate",
        "categoria": "ciclo",
        "decisao": "aviso",
        "periodo": 2,
        "passo": 7,
    }
