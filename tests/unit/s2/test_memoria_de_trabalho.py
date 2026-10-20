"""A memória de trabalho do turno (dono, 2026-10-20, ADR-0034): o que as ferramentas trazem é do
turno — o contexto de cada rodada tem orçamento, e nada passa para a conversa nem para o livro."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from jarvis.executor.ferramentas import ExecutorDeFerramentas, ResultadoDeFerramenta
from jarvis.memoryd.cofre import CofreFernet, nova_chave
from jarvis.memoryd.indice import IndiceEmMemoria
from jarvis.memoryd.livro import LivroDeMemoria
from jarvis.politica.auditoria import LogDeAuditoria
from jarvis.politica.catalogo import carregar_catalogo
from jarvis.politica.modos import Modo
from jarvis.politica.pdp import Pdp
from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import Contexto, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.s2.rascunho import textos_no_contexto
from jarvis.tarefas.gestor import Tarefa
from jarvis.tarefas.motores import MotorDeAgente

MARCA = "TEXTO-DA-PAGINA-QUE-NAO-PASSA-DO-TURNO"


def _pagina(indice: int, tamanho: int = 5000) -> ResultadoDeFerramenta:
    return ResultadoDeFerramenta(
        "web.ler",
        "ok",
        dados={
            "url": f"https://site{indice}.example/a",
            "titulo": f"Página {indice}",
            "texto": "x" * tamanho,
            "truncado": False,
        },
    )


# --- o orçamento ---------------------------------------------------------------------------------
def test_o_mais_novo_vai_inteiro_e_os_antigos_inteiros_enquanto_cabem() -> None:
    feitos = [_pagina(1), _pagina(2), _pagina(3)]
    textos, podados = textos_no_contexto(feitos, orcamento=8000)

    assert podados == 1
    assert textos[2] == feitos[2].para_o_modelo() and textos[1] == feitos[1].para_o_modelo()
    antigo = json.loads(textos[0])
    assert antigo["podado"] is True
    assert antigo["dados"] == {
        "url": "https://site1.example/a",
        "titulo": "Página 1",
        "texto": "[podado: 5000 caracteres]",
        "truncado": False,
    }


def test_o_mais_novo_nunca_e_podado_nem_com_orcamento_zero() -> None:
    feitos = [_pagina(1), _pagina(2)]
    textos, podados = textos_no_contexto(feitos, orcamento=0)
    assert textos[1] == feitos[1].para_o_modelo() and podados == 1
    assert textos_no_contexto([]) == ([], 0)


def test_o_resumo_guarda_o_que_identifica_o_passo_e_cabe_no_limite() -> None:
    lido = ResultadoDeFerramenta(
        "browser.read",
        "ok",
        dados={
            "tab_id": 7,
            "url": "https://loja.example/p",
            "texto": "y" * 3500,
            "links": [{"texto": "a", "href": "https://a.example"}] * 10,
            "tela": {"id": "tela:ab1", "largura": 1280, "altura": 720},
        },
        aviso="Gravei o rascunho nota.",
        acao_id="d-1",
    )
    resumo = json.loads(lido.resumo_para_o_modelo())

    assert resumo["dados"]["texto"] == "[podado: 3500 caracteres]"
    assert resumo["dados"]["links"] == "[podado: 10 itens]"
    assert resumo["dados"]["tela"] == {"id": "tela:ab1", "largura": 1280, "altura": 720}
    assert resumo["dados"]["tab_id"] == 7 and resumo["acao_id"] == "d-1"
    assert "não repita" in resumo["aviso_ao_dono"]
    assert len(lido.resumo_para_o_modelo()) <= 600


# --- no cérebro: orçamento a cada rodada, e o descarte no fim -----------------------------------
@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ExecutorDeFerramentas]:
    lar = tmp_path / "casa"
    (lar / "Documentos").mkdir(parents=True)
    for indice in range(1, 7):
        (lar / "Documentos" / f"pagina{indice}.txt").write_text(
            f"{MARCA} {indice} " + "conteúdo longo " * 900, "utf-8"
        )
    with LogDeAuditoria(tmp_path / "auditoria.sqlite") as auditoria:
        pdp = Pdp(
            catalogo=carregar_catalogo(),
            lar=lar,
            auditoria=auditoria,
            modo=Modo.PADRAO,
            pasta_do_jarvis=tmp_path / "area",
        )
        executor = ExecutorDeFerramentas(pdp=pdp, lar=lar)
        executor.preparar()
        yield executor


def _roteiro() -> MotorRoteirizado:
    def resposta(contexto: Contexto) -> Sequence[Parte]:
        if contexto.turno == "e aí?":
            return ["Nada novo."]
        feitos = sum(1 for m in contexto.mensagens if m.papel == "ferramenta")
        if feitos < 6:
            caminho = f"~/Documentos/pagina{feitos + 1}.txt"
            return [PedidoDeTool("files.read_text", {"path": caminho})]
        return ["Li as seis páginas."]

    return MotorRoteirizado(resposta=resposta)


def test_seis_paginas_grandes_nao_fazem_o_contexto_crescer_sem_fim(
    executor: ExecutorDeFerramentas,
) -> None:
    motor = _roteiro()
    resposta = Cerebro(motor=motor, ferramentas=executor).responder(
        "lê as seis páginas", epoch=0, publicar=lambda _: None
    )

    assert [r.status for r in resposta.ferramentas] == ["ok"] * 6
    tamanhos = [len(c.como_texto()) for c in motor.pedidos]
    assert max(tamanhos) < 30_000, tamanhos  # sem orçamento seriam ~36 mil só de resultados
    ultimo = motor.pedidos[-1]
    assert ultimo.mensagens[-1].texto == resposta.ferramentas[-1].para_o_modelo()  # inteiro
    assert '"podado": true' in ultimo.mensagens[1].texto  # o primeiro passo, podado
    assert resposta.resultados_podados >= 1


def test_nada_do_que_a_ferramenta_trouxe_passa_para_a_conversa_nem_para_o_livro(
    executor: ExecutorDeFerramentas,
) -> None:
    livro = LivroDeMemoria.abrir(
        ":memory:", cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria()
    )
    motor = _roteiro()
    cerebro = Cerebro(motor=motor, ferramentas=executor, livro=livro, session_id="s-1")

    primeira = cerebro.responder("lê as seis páginas", epoch=0, publicar=lambda _: None)
    cerebro.ouvido(primeira.response_id, "Li as seis páginas.", interrompida=False, played_ms=900)
    cerebro.responder("e aí?", epoch=1, publicar=lambda _: None)

    seguinte = motor.pedidos[-1]
    assert [m.papel for m in seguinte.mensagens] == ["dono", "jarvis", "dono"]
    assert MARCA not in seguinte.como_texto()
    assert all(MARCA not in m.texto for m in cerebro.conversa.turnos)
    guardados = livro.turnos_da_sessao("s-1", ultimos=10)
    assert guardados and all(MARCA not in str(t) for t in guardados)


# --- nas tarefas em segundo plano ---------------------------------------------------------------
def test_a_tarefa_tambem_leva_os_passos_antigos_podados() -> None:
    motor = MotorRoteirizado(resposta="Terminei.")
    agente = MotorDeAgente(motor=motor, catalogo=lambda: [])
    tarefa = Tarefa(
        id="t-1",
        descricao="ler sites",
        tool_id="web.ler",
        parametros={"url": "https://a.example"},
        motor="agente",
    )
    feitos = [_pagina(i, 6000) for i in range(1, 6)]

    agente.proximo(tarefa, feitos, lambda: False)

    textos = [m.texto for m in motor.pedidos[0].mensagens if m.papel == "ferramenta"]
    assert len(textos) == 5 and textos[-1] == feitos[-1].para_o_modelo()
    assert any('"podado": true' in t for t in textos[:-1])
