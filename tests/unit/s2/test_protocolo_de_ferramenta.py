"""O protocolo `<<ferramenta>>` do `claude -p` provisório: robusto ao jeito que o modelo escreve.

Cada caso aqui é uma forma real de o modelo propor a mesma coisa; nenhuma pode virar JSON falado
em voz alta, erro para o dono ou espera até o fim da geração.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from jarvis.s2.motor import Delta, PedidoDeTool, Texto
from jarvis.s2.motor_claude_cli import LeitorDoProtocolo

ABRIR = PedidoDeTool("apps.launch", {"nome": "Discord"})
JSON = '{"tool_id": "apps.launch", "args": {"nome": "Discord"}}'


def _ler(*pedacos: str) -> list[Delta]:
    leitor = LeitorDoProtocolo()
    saida: list[Delta] = []
    for pedaco in pedacos:
        saida += leitor.alimentar(pedaco)
    return saida + list(leitor.fechar())


def _fala(deltas: Sequence[Delta]) -> str:
    return "".join(d.texto for d in deltas if isinstance(d, Texto))


def _pedidos(deltas: Sequence[Delta]) -> list[PedidoDeTool]:
    return [d for d in deltas if isinstance(d, PedidoDeTool)]


@pytest.mark.parametrize(
    "texto",
    [
        f"<<ferramenta>> {JSON}",  # sem quebra de linha no fim (o caso real medido)
        f"<<ferramenta>>{JSON}\n",
        f"<<FERRAMENTA>> {JSON}",
        f"<< ferramenta >> {JSON}",
        f"<<ferramenta>>\n{JSON}\n",
        f"```json\n<<ferramenta>> {JSON}\n```",
        f"<<ferramenta>>\n```json\n{JSON}\n```\n",
        '<<ferramenta>> {"tool_id": "apps.launch",\n  "args": {"nome": "Discord"}}',
        '<<ferramenta>> {"tool": "apps.launch", "arguments": {"nome": "Discord"}}',
    ],
)
def test_proposta_em_qualquer_forma_vira_um_pedido_e_nenhuma_fala(texto: str) -> None:
    deltas = _ler(texto)
    assert _pedidos(deltas) == [ABRIR]
    assert _fala(deltas).strip() == "", f"sobrou fala: {_fala(deltas)!r}"


def test_proposta_no_meio_da_linha_nao_vai_para_a_voz() -> None:
    deltas = _ler(f"Vou abrir o Discord. <<ferramenta>> {JSON}")
    assert _fala(deltas).strip() == "Vou abrir o Discord."
    assert _pedidos(deltas) == [ABRIR]


def test_texto_depois_do_json_na_mesma_linha_e_fala_e_nao_erro() -> None:
    deltas = _ler(f"<<ferramenta>> {JSON} e já te aviso.")
    assert _pedidos(deltas) == [ABRIR]
    assert _fala(deltas).strip() == "e já te aviso."


def test_a_proposta_sai_quando_o_objeto_fecha_sem_esperar_o_fim_da_geracao() -> None:
    leitor = LeitorDoProtocolo()
    assert list(leitor.alimentar("<<ferramenta>> ")) == []
    saiu = list(leitor.alimentar(JSON))  # nenhuma quebra de linha, nenhum `fechar()`
    assert saiu == [ABRIR]


def test_marca_partida_em_qualquer_ponto_ainda_e_reconhecida() -> None:
    marca = f"<<ferramenta>> {JSON}"
    for corte in range(1, len(marca)):
        deltas = _ler(marca[:corte], marca[corte:])
        assert _pedidos(deltas) == [ABRIR], corte
        assert _fala(deltas).strip() == "", corte


def test_menor_que_solto_na_fala_nao_trava_nem_some() -> None:
    deltas = _ler("Se 3 < 5 então ", "sim.")
    assert _fala(deltas) == "Se 3 < 5 então sim."


def test_duas_propostas_na_mesma_resposta() -> None:
    deltas = _ler(
        '<<ferramenta>> {"tool_id": "apps.launch", "args": {"nome": "A"}}\n',
        '<<ferramenta>> {"tool_id": "sites.open", "args": {"url": "https://x.org"}}\n',
    )
    assert [p.tool_id for p in _pedidos(deltas)] == ["apps.launch", "sites.open"]


@pytest.mark.parametrize(
    "texto",
    [
        "<<ferramenta>> isto não é json\n",
        '<<ferramenta>> {"tool_id": "apps.launch", "args": {"nome": ',  # nunca fecha
        '<<ferramenta>> {"args": {}}',  # sem tool_id
        '<<ferramenta>> {"tool_id": "x", "args": "texto"}',  # args não é objeto
        "<<ferramenta>> [1, 2]",
    ],
)
def test_proposta_quebrada_vira_malformado_e_nao_derruba_nem_fala(texto: str) -> None:
    deltas = _ler(texto)
    assert [p.tool_id for p in _pedidos(deltas)] == ["(malformado)"]
    assert _fala(deltas).strip() == ""


def test_json_que_nunca_fecha_nao_segura_a_proposta_para_sempre() -> None:
    leitor = LeitorDoProtocolo()
    list(leitor.alimentar('<<ferramenta>> {"a": "'))
    saiu = list(leitor.alimentar("x" * 5000))
    assert [p.tool_id for p in _pedidos(saiu)] == ["(malformado)"]


# --- formas que vazavam para a voz (dono, 2026-10-21; ADR-0038) ------------------------------
@pytest.mark.parametrize(
    "texto",
    [
        JSON,  # o modelo esqueceu a marca
        f"```json\n{JSON}\n```",
        f"<<tool>> {JSON}",
        f"<<tool_call>> {JSON}",
        '{"tool": "apps.launch", "arguments": {"nome": "Discord"}}',
        '<function_calls><invoke name="apps.launch"><parameter name="nome">Discord</parameter>'
        "</invoke></function_calls>",
        f"<tool_call>{JSON}</tool_call>",
    ],
)
def test_proposta_sem_a_marca_ou_no_jeito_nativo_vira_pedido_e_nao_fala(texto: str) -> None:
    deltas = _ler(texto)
    assert _pedidos(deltas) == [ABRIR]
    assert _fala(deltas).strip() == "", f"sobrou fala: {_fala(deltas)!r}"


def test_json_solto_partido_em_qualquer_ponto_nao_vaza() -> None:
    texto = f"Vou abrir. {JSON}"
    for corte in range(1, len(texto)):
        deltas = _ler(texto[:corte], texto[corte:])
        assert _pedidos(deltas) == [ABRIR], corte
        assert _fala(deltas).strip() == "Vou abrir.", corte


def test_bloco_em_xml_que_nao_fecha_nao_e_fala_nem_chamada() -> None:
    deltas = _ler('Certo. <function_calls><invoke name="apps.launch"><parameter name="nome">D')
    assert _fala(deltas).strip() == "Certo."
    assert _pedidos(deltas) == []


def test_chave_comum_entre_chaves_e_fala_e_nao_trava() -> None:
    deltas = _ler("O conjunto {a, b} tem dois ", "elementos.")
    assert _fala(deltas) == "O conjunto {a, b} tem dois elementos."


def test_sem_protocolo_limpa_o_texto_pronto() -> None:
    from jarvis.s2.protocolo import sem_protocolo

    assert (
        sem_protocolo(f"Abri o Discord. <<ferramenta>> {JSON} Pronto.") == "Abri o Discord. Pronto."
    )
    assert sem_protocolo("<<pensar>>plano<</pensar>>Feito.") == "Feito."
