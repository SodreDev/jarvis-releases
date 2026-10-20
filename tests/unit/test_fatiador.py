"""ADR-0025, regra 7: a fronteira de fala é uma regra só — o mesmo pedaço inteiro ou em stream."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from jarvis.agentd.tts import fatiar
from jarvis.fatiador import (
    PALAVRAS_DO_PRIMEIRO_PEDACO,
    PALAVRAS_MINIMAS_POR_PEDACO,
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


def test_lotes_tem_pelo_menos_14_palavras_e_so_o_ultimo_pode_ser_menor() -> None:
    texto = " ".join(f"palavra{i}" for i in range(47))
    pedacos = fatiar_tudo(texto)

    tamanhos = [len(p.texto.split()) for p in pedacos]
    assert tamanhos[:-1] == [PALAVRAS_DO_PRIMEIRO_PEDACO, PALAVRAS_POR_PEDACO]
    assert all(tamanho >= PALAVRAS_MINIMAS_POR_PEDACO for tamanho in tamanhos[:-1])
    assert tamanhos[-1] < PALAVRAS_MINIMAS_POR_PEDACO
    assert pedacos[0].corte is Corte.LIMITE


def test_pontuacao_so_corta_depois_do_minimo_e_antes_do_teto() -> None:
    palavras = ["Sim.", *(f"palavra{i}" for i in range(1, 15)), "chegou,"]
    pedacos = fatiar_tudo(" ".join(palavras))

    assert len(pedacos[0].texto.split()) == 16
    assert pedacos[0].texto.endswith("chegou,")
    assert pedacos[0].corte is Corte.VIRGULA


def test_hifen_e_token_excepcionalmente_longo_continuam_atomicos() -> None:
    longo = "identificador" * 8
    tokens = ["sexta-feira", longo, *(f"palavra{i}" for i in range(36))]

    emitidos = [token for pedaco in fatiar_tudo(" ".join(tokens)) for token in pedaco.texto.split()]

    assert emitidos == tokens
    assert "sexta-feira" in emitidos
    assert longo in emitidos


def test_token_longo_e_hifen_atomicos_em_deltas_de_um_caractere_na_fronteira() -> None:
    longo = "identificador" * 8
    tokens = [*(f"palavra{i}" for i in range(17)), longo, "sexta-feira", "fim."]
    texto = "\t".join(tokens)

    pedacos = fatiar_em_deltas(texto)

    assert pedacos == fatiar_tudo(texto)
    assert [t for p in pedacos for t in p.texto.split()] == tokens
    assert pedacos[0].texto.split()[-1] == longo
    assert pedacos[1].texto.split()[0] == "sexta-feira"


@pytest.mark.parametrize("quantidade", [0, 1, 13, 14, 17, 18, 19, 28, 36, 37, 100])
def test_piso_e_residual_independem_do_tamanho_e_da_pontuacao(quantidade: int) -> None:
    tokens = [f"palavra{i}." for i in range(quantidade)]
    texto = " \n".join(tokens)
    fatiador = FatiadorDeFala()
    antes_do_fim = fatiador.alimentar(texto + " ")
    assert all(len(p.texto.split()) >= 14 for p in antes_do_fim)

    pedacos = [p for p in antes_do_fim + fatiador.fechar() if p.texto]

    assert [t for p in pedacos for t in p.texto.split()] == tokens
    assert all(len(p.texto.split()) >= 14 for p in pedacos[:-1])


def test_lote_menor_espera_o_fim_do_stream() -> None:
    fatiador = FatiadorDeFala()
    texto = " ".join(f"palavra{i}" for i in range(PALAVRAS_MINIMAS_POR_PEDACO - 1))

    assert fatiador.alimentar(texto + " ") == []
    final = [p for p in fatiador.fechar() if p.texto]

    assert [p.texto for p in final] == [texto]
    assert final[0].corte is Corte.FIM


def test_numero_com_virgula_nao_e_partido_no_meio_do_stream() -> None:
    """ "3," pode virar "3,5" no próximo delta: palavra só conta quando acaba."""
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar("São 3,") == []
    pedacos = fatiador.alimentar("5 litros ") + fatiador.fechar()
    assert [p.texto for p in pedacos if p.texto] == ["São 3,5 litros"]


def test_a_palavra_so_sai_quando_chega_o_espaco_depois_dela() -> None:
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar("Depois de quint") == []
    assert fatiador.alimentar("a vem") == []
    assert [p.texto for p in fatiador.fechar() if p.texto] == ["Depois de quinta vem"]


@pytest.mark.parametrize("texto", ["Depois de quinta vem sexta.", "Depois de quinta vem sexta"])
def test_fechar_devolve_o_residual_curto_com_corte_fim(texto: str) -> None:
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar(texto) == []
    final = fatiador.fechar()[-1]
    assert final.corte is Corte.FIM
    assert final.texto == texto
    assert fatiador.fechar() == []
    with pytest.raises(RuntimeError, match="fechado"):
        fatiador.alimentar("mais")


def test_a_posicao_aponta_para_o_texto_recebido() -> None:
    texto = "  Oi,\n  tudo   bem com você hoje?  "
    for pedaco in fatiar_tudo(texto):
        assert texto[pedaco.inicio :].startswith(pedaco.texto.split()[0])


def test_descarregar_solta_o_residual_curto_na_pausa_e_segue_aberto() -> None:
    """A pausa do texto (ferramenta) libera o que chegou, abaixo do piso; o resto continua."""
    fatiador = FatiadorDeFala()
    assert fatiador.alimentar("Deixa eu ver.") == []  # palavra encostada no fim: pode continuar
    pausa = fatiador.descarregar()
    assert [(p.texto, p.corte) for p in pausa] == [("Deixa eu ver.", Corte.PAUSA)]
    assert fatiador.descarregar() == []  # nada pendente, nada sai
    depois = fatiador.alimentar(" Achei a pasta.") + fatiador.fechar()
    assert [(p.texto, p.corte) for p in depois if p.texto] == [("Achei a pasta.", Corte.FIM)]
    assert fatiador.descarregar() == []  # fechado não solta mais nada


def test_descarregar_respeita_o_lote_normal_antes_do_residual() -> None:
    """O lote completo sai pela regra de sempre; só o resto (abaixo do piso) sai como pausa."""
    fatiador = FatiadorDeFala()
    normais = fatiador.alimentar(" ".join(f"p{i}" for i in range(20)))
    pausa = fatiador.descarregar()
    assert [(len(p.texto.split()), p.corte) for p in normais + pausa] == [
        (18, Corte.LIMITE),
        (2, Corte.PAUSA),
    ]
