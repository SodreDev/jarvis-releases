"""ADR-0059: «até terminar» e «mais 50» respondem à pergunta do teto, e a nenhuma outra."""

from __future__ import annotations

import pytest

from jarvis.s2.portao import OpcaoDeContinuar, ler_continuacao
from jarvis.voz.resposta import TipoDaResposta, ler_resposta

PERGUNTA = (
    "Posso continuar por mais 50 passos ou até terminar? "
    "Já dei 50 passos em «depurar o teste» e ainda falta."
)


@pytest.mark.parametrize(
    "fala",
    ["até terminar", "Até terminar.", "vai até o fim", "pode, até acabar", "continua até o final"],
)
def test_ate_terminar_em_varias_formas(fala: str) -> None:
    assert ler_continuacao(fala, 50) is OpcaoDeContinuar.ATE_TERMINAR


@pytest.mark.parametrize(
    "fala", ["mais 50", "só mais 50 passos", "mais cinquenta", "pode, mais 50"]
)
def test_mais_um_bloco_em_varias_formas(fala: str) -> None:
    assert ler_continuacao(fala, 50) is OpcaoDeContinuar.MAIS_UM_BLOCO


@pytest.mark.parametrize(
    "fala",
    [
        "não vai até o fim",
        "para até terminar",
        "mais 10",
        "mais 50 reais",
        "mais ²",
        "abre o Spotify até terminar",
        "sim",
        "",
    ],
)
def test_o_resto_nao_escolhe_opcao_nenhuma(fala: str) -> None:
    assert ler_continuacao(fala, 50) is None


def test_o_numero_tem_de_ser_o_do_bloco() -> None:
    assert ler_continuacao("mais 20", 20) is OpcaoDeContinuar.MAIS_UM_BLOCO
    assert ler_continuacao("mais 50", 20) is None


def test_com_a_pergunta_ja_ouvida_repetir_a_opcao_e_resposta() -> None:
    ate = ler_resposta("até terminar", PERGUNTA, continuar_por=50)
    assert (ate.tipo, ate.texto) == (TipoDaResposta.SIM, "até terminar")
    mais = ler_resposta("mais 50", PERGUNTA, continuar_por=50)
    assert (mais.tipo, mais.texto) == (TipoDaResposta.SIM, "sim")


def test_enquanto_a_pergunta_toca_repetir_a_opcao_e_eco() -> None:
    assert ler_resposta("até terminar", PERGUNTA).tipo is TipoDaResposta.ECO
    assert ler_resposta("mais 50 passos", PERGUNTA).tipo is TipoDaResposta.ECO


def test_a_pergunta_de_uma_acao_nao_aceita_as_opcoes() -> None:
    """Em «Posso apagar de vez?», «até terminar» não é um sim."""
    leitura = ler_resposta("até terminar", "Posso apagar de vez?")
    assert leitura.tipo is TipoDaResposta.OUTRA


def test_sim_e_nao_seguem_valendo_na_pergunta_do_teto() -> None:
    assert ler_resposta("continua", PERGUNTA, continuar_por=50).tipo is TipoDaResposta.SIM
    assert ler_resposta("continuar", PERGUNTA, continuar_por=50).tipo is TipoDaResposta.SIM
    assert ler_resposta("não", PERGUNTA, continuar_por=50).tipo is TipoDaResposta.NAO


def test_o_nao_vale_mesmo_enquanto_a_pergunta_toca() -> None:
    """A frase não pode dizer «não»: fala que só repete a pergunta é eco, e o «não» se perderia."""
    assert ler_resposta("não", PERGUNTA).tipo is TipoDaResposta.NAO


def test_o_nao_vale_quando_a_descricao_da_tarefa_traz_a_palavra() -> None:
    pergunta = PERGUNTA.replace("depurar o teste", "não apague nada")
    assert ler_resposta("não", pergunta, continuar_por=50).tipo is TipoDaResposta.NAO
