"""ADR-0025, regra 7: a fronteira de fala é uma regra só — o mesmo pedaço inteiro ou em stream."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from jarvis.agentd.tts import fatiar
from jarvis.fatiador import (
    PALAVRAS_DO_PRIMEIRO_PEDACO,
    PALAVRAS_POR_PEDACO,
    Corte,
    FatiadorDeFala,
    fatiar_em_deltas,
    fatiar_tudo,
)

RAIZ = Path(__file__).resolve().parents[2]
SEMENTE = 20_261_016


def _textos_do_corpus() -> list[str]:
    textos = []
    for linha in (RAIZ / "corpus" / "turnos" / "rotulos.jsonl").read_text("utf-8").splitlines():
        registro = json.loads(linha)
        textos.append(str(registro.get("texto") or registro.get("text") or ""))
    return [t for t in textos if t]


def _cortar_ao_acaso(texto: str, sorteio: random.Random) -> list[str]:
    cortes = sorted(sorteio.sample(range(1, len(texto)), min(len(texto) - 1, 8)))
    return [texto[a:b] for a, b in zip([0, *cortes], [*cortes, len(texto)], strict=True)]


def test_em_stream_da_o_mesmo_que_inteiro_no_corpus_todo() -> None:
    """O stream entrega pedaço de palavra; o corte tem de sair igual ao do texto inteiro."""
    sorteio = random.Random(SEMENTE)
    textos = _textos_do_corpus()
    assert len(textos) > 400, "o corpus de turnos encolheu: a prova perdeu alcance"
    for texto in textos:
        inteiro = fatiar_tudo(texto)
        aos_poucos = fatiar_em_deltas(_cortar_ao_acaso(texto, sorteio))
        assert aos_poucos == inteiro, texto


def test_o_fatiar_do_tts_e_o_mesmo_fatiador() -> None:
    texto = "Pra dormir melhor, tenta manter um horário fixo pra deitar e acordar, todo dia."
    assert fatiar(texto) == [(p.inicio, p.texto) for p in fatiar_tudo(texto)]


def test_o_primeiro_pedaco_e_curto_e_os_outros_respeitam_o_limite() -> None:
    texto = " ".join(f"palavra{i}" for i in range(30))
    pedacos = fatiar_tudo(texto)
    assert len(pedacos[0].texto.split()) == PALAVRAS_DO_PRIMEIRO_PEDACO
    assert all(len(p.texto.split()) <= PALAVRAS_POR_PEDACO for p in pedacos[1:])
    assert pedacos[0].corte is Corte.LIMITE


def test_pontuacao_corta_antes_do_limite_e_diz_o_tipo() -> None:
    pedacos = fatiar_tudo("Sim. Pode ser, mas depois das três horas da tarde de amanhã")
    assert [p.texto for p in pedacos][:2] == ["Sim.", "Pode ser,"]
    assert [p.corte for p in pedacos][:2] == [Corte.FRASE, Corte.VIRGULA]


def test_numero_com_virgula_nao_e_partido_no_meio_do_stream() -> None:
    """ "3," pode virar "3,5" no próximo delta: palavra só conta quando acaba."""
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar("São 3,") == []
    pedacos = fatiador.alimentar("5 litros ") + fatiador.fechar()
    assert [p.texto for p in pedacos if p.texto] == ["São 3,5 litros"]


def test_a_palavra_so_sai_quando_chega_o_espaco_depois_dela() -> None:
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar("Depois de quint") == []
    assert [p.texto for p in fatiador.alimentar("a vem")] == ["Depois de quinta"]


@pytest.mark.parametrize(
    ("texto", "ultimo"),
    [("Depois de quinta vem sexta.", ""), ("Depois de quinta vem sexta", "vem sexta")],
)
def test_fechar_sempre_devolve_o_ultimo_com_corte_fim(texto: str, ultimo: str) -> None:
    """Se o texto acabou numa pontuação, o último pedaço sai vazio: esperar para saber que era o
    último atrasaria a primeira palavra."""
    fatiador = FatiadorDeFala()
    fatiador.alimentar(texto)
    final = fatiador.fechar()[-1]
    assert final.corte is Corte.FIM
    assert final.texto == ultimo
    assert fatiador.fechar() == []
    with pytest.raises(RuntimeError, match="fechado"):
        fatiador.alimentar("mais")


def test_a_posicao_aponta_para_o_texto_recebido() -> None:
    texto = "  Oi,\n  tudo   bem com você hoje?  "
    for pedaco in fatiar_tudo(texto):
        assert texto[pedaco.inicio :].startswith(pedaco.texto.split()[0])
