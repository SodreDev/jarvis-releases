"""O card `notificacoes` (ADR-0025): a forma do aviso, validada como qualquer dado de modelo.

Sem fila aqui — ela é do `agentd`. O que se cobra é o contrato do card: campos fechados, `tipo`
e `entrega` de listas fechadas, resumo obrigatório, e o roteiro passando por ele como a IA
passaria, com o selo de demonstração.
"""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.gui.acoes import Modo
from jarvis.gui.componentes import (
    ComponenteNaoAutorizado,
    Vista,
    componente,
    validar_dados,
)
from jarvis.gui.controlador import RoteiroDeDemonstracao
from jarvis.gui.workspace import Workspace

NOTIFICACOES = componente("notificacoes")
BOM: dict[str, str] = {
    "tipo": "precisa_decisao",
    "origem": "tarefa · empacotar",
    "resumo": "Publicar exige a sua ordem",
    "instante": "agora",
    "entrega": "so_card",
    "confianca": "terceiros",
}


def test_o_card_tem_vista_propria_e_e_demonstracao() -> None:
    assert NOTIFICACOES.vista is Vista.NOTIFICACOES
    assert NOTIFICACOES.demonstracao, "sem fila ligada, o card só mostra exemplo — e diz isso"
    assert not NOTIFICACOES.sensivel


def test_aviso_bem_formado_passa_inteiro() -> None:
    assert validar_dados(NOTIFICACOES, {"avisos": [BOM]}) == {"avisos": [BOM]}


@pytest.mark.parametrize(
    ("mudanca", "trecho"),
    [
        ({"tipo": "urgente"}, "tipo"),
        ({"entrega": "gritado"}, "entrega"),
        ({"confianca": "total"}, "confianca"),
        ({"resumo": ""}, "resumo"),
        ({"html": "<b>oi</b>"}, "não autorizado"),
        ({"resumo": 3}, "esperava texto"),
    ],
)
def test_aviso_fora_da_forma_e_recusado(mudanca: dict[str, Any], trecho: str) -> None:
    with pytest.raises(ComponenteNaoAutorizado, match=trecho):
        validar_dados(NOTIFICACOES, {"avisos": [{**BOM, **mudanca}]})


def test_aviso_sem_tipo_e_recusado() -> None:
    sem_tipo = {k: v for k, v in BOM.items() if k != "tipo"}
    with pytest.raises(ComponenteNaoAutorizado, match="todo aviso tem tipo"):
        validar_dados(NOTIFICACOES, {"avisos": [sem_tipo]})


def test_o_formato_antigo_de_itens_nao_passa_mais() -> None:
    with pytest.raises(ComponenteNaoAutorizado, match="campos que este componente não tem"):
        validar_dados(NOTIFICACOES, {"itens": [{"titulo": "x"}]})


@pytest.mark.parametrize("modo", [Modo.ASSISTENTE, Modo.EXECUCAO])
def test_o_roteiro_abre_o_card_pelo_mesmo_caminho_da_ia(modo: Modo) -> None:
    espaco = Workspace()
    resultados = [espaco.propor(p) for p in RoteiroDeDemonstracao().propor(modo)]
    # Componente sensível (console, arquivos) espera o dono: pendente não é recusa.
    recusas = [r.frase() for r in resultados if not (r.aceita or r.pendente)]
    assert not recusas, recusas
    cards = [w for w in espaco.widgets.values() if w.componente == "notificacoes"]
    assert len(cards) == 1
    # O roteiro abre o card **sem dados**: quem os põe é a ponte, com a fila de verdade
    # (ADR-0019, emenda de 2026-10-17). Aviso inventado num card real seria mentira.
    assert "avisos" not in cards[0].dados
