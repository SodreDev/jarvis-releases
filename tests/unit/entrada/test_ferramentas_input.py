"""As `input.*` no executor: tier, "sim" do dono por ação, auditoria e o que o modelo enxerga."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.entrada.controle import ControleDeEntrada
from jarvis.entrada.foco import Janela
from jarvis.executor.ferramentas import Confirmacao, ExecutorDeFerramentas, ResultadoDeFerramenta
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from tests.unit.entrada.test_controle import KATE, KONSOLE, BackendFalso, FocoFalso

NUNCA = lambda: False  # noqa: E731


def _executor(
    tmp_path: Path, foco: FocoFalso, backend: BackendFalso | None = None, *, ligada: bool = True
) -> Iterator[tuple[ExecutorDeFerramentas, BackendFalso]]:
    lar = tmp_path / "casa"
    lar.mkdir(exist_ok=True)
    backend = backend or BackendFalso()
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        controle = ControleDeEntrada(backend=backend, foco=foco, dormir=lambda _s: None)
        ex = ExecutorDeFerramentas(pdp=pdp, lar=lar, entrada=controle if ligada else None)
        ex.preparar()
        yield ex, backend


@pytest.fixture
def com_kate(tmp_path: Path) -> Iterator[tuple[ExecutorDeFerramentas, BackendFalso]]:
    yield from _executor(tmp_path, FocoFalso([KATE]))


def _rodar(
    ex: ExecutorDeFerramentas, tool: str, args: dict[str, Any], *, sim: bool = False
) -> tuple[ResultadoDeFerramenta, list[Confirmacao]]:
    perguntas: list[Confirmacao] = []

    def confirmar(p: Confirmacao) -> bool:
        perguntas.append(p)
        return sim

    return ex.executar(tool, args, cancelado=NUNCA, confirmar=confirmar), perguntas


def _auditoria(ex: ExecutorDeFerramentas) -> list[sqlite3.Row]:
    return list(
        ex.pdp.auditoria._con.execute(
            "SELECT d.tool_id, d.veredito, r.resultado FROM audit_log d"
            " LEFT JOIN audit_result r ON r.decision_id = d.decision_id ORDER BY d.seq"
        )
    )


def test_desligada_as_tools_nem_existem_para_o_modelo(tmp_path: Path) -> None:
    for ex, _ in _executor(tmp_path, FocoFalso([KATE]), ligada=False):
        ids = {t["id"] for t in ex.catalogo_para_o_modelo()}
        assert not {i for i in ids if i.startswith("input.")}
        resultado, _ = _rodar(ex, "input.mouse.click", {})
        assert resultado.status == "negado"


def test_ligada_o_modelo_ve_quatro_tools_e_nunca_a_de_confirmacao(
    com_kate: tuple[ExecutorDeFerramentas, BackendFalso],
) -> None:
    ex, _ = com_kate
    ids = {t["id"] for t in ex.catalogo_para_o_modelo()}
    assert {"input.mouse.move", "input.mouse.click", "input.key.type", "input.key.press"} <= ids
    assert "input.acao_sensivel" not in ids
    resultado, perguntas = _rodar(
        ex, "input.acao_sensivel", {"acao": "input.key.press", "detalhe": "enter"}, sim=True
    )
    assert resultado.status == "negado" and perguntas == []


def test_janela_comum_e_moderado_avisa_em_voz_e_nao_pergunta(
    com_kate: tuple[ExecutorDeFerramentas, BackendFalso],
) -> None:
    ex, backend = com_kate
    clique, p1 = _rodar(ex, "input.mouse.click", {"botao": "direito"})
    tecla, p2 = _rodar(ex, "input.key.press", {"tecla": "ctrl+l"})
    assert clique.status == tecla.status == "ok"
    assert clique.aviso == "Cliquei com o botão direito."
    assert tecla.aviso == "Apertei ctrl+l."
    assert p1 == p2 == []
    assert [e[0] for e in backend.eventos] == ["clicar", "pressionar"]


def test_enter_e_perigoso_o_nao_do_dono_impede_o_evento_e_fica_na_auditoria(
    com_kate: tuple[ExecutorDeFerramentas, BackendFalso],
) -> None:
    ex, backend = com_kate
    negado, perguntas = _rodar(ex, "input.key.press", {"tecla": "enter"}, sim=False)
    assert negado.status == "negado" and len(perguntas) == 1
    assert backend.eventos == []

    aceito, _ = _rodar(ex, "input.key.press", {"tecla": "enter"}, sim=True)
    assert aceito.status == "ok" and backend.eventos == [("pressionar", (), "enter")]
    linhas = [r for r in _auditoria(ex) if r["tool_id"] == "input.acao_sensivel"]
    assert [r["veredito"] for r in linhas] == ["confirm", "confirm", "allow"]


def test_terminal_pede_o_sim_e_a_pergunta_nomeia_a_janela(tmp_path: Path) -> None:
    for ex, backend in _executor(tmp_path, FocoFalso([KONSOLE])):
        resultado, perguntas = _rodar(ex, "input.key.type", {"texto": "ls -la"}, sim=True)
        assert resultado.status == "ok"
        assert "ls -la" in perguntas[0].detalhe and "konsole" in perguntas[0].detalhe.lower()
        assert "terminal" in perguntas[0].motivo
        assert backend.eventos == [("digitar", "ls -la")]


def test_foco_desconhecido_e_o_proprio_jarvis_sao_recusa_sem_pergunta(tmp_path: Path) -> None:
    for janela in (None, Janela("jarvis", "Jarvis")):
        for ex, backend in _executor(tmp_path, FocoFalso([janela])):
            resultado, perguntas = _rodar(ex, "input.mouse.click", {}, sim=True)
            assert resultado.status == "erro" and perguntas == []
            assert backend.eventos == []


def test_depois_de_ler_pagina_de_terceiros_a_acao_pede_o_sim(
    com_kate: tuple[ExecutorDeFerramentas, BackendFalso],
) -> None:
    ex, backend = com_kate
    ex.contaminado = True
    negado, perguntas = _rodar(ex, "input.mouse.click", {}, sim=False)
    assert negado.status == "negado" and "terceiros" in perguntas[0].motivo
    assert backend.eventos == []


def test_argumento_a_mais_e_recusado_pelo_schema(
    com_kate: tuple[ExecutorDeFerramentas, BackendFalso],
) -> None:
    ex, backend = com_kate
    for tool, args in (
        ("input.mouse.click", {"x": 10, "y": 10}),
        ("input.key.type", {"texto": "a", "confirmado_pelo_dono": True}),
        ("input.key.press", {"tecla": "a", "modificadores": ["super"]}),
    ):
        resultado, _ = _rodar(ex, tool, args)
        assert resultado.status == "erro", tool
    assert backend.eventos == []
