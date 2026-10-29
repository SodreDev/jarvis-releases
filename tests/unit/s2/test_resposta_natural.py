"""O «sim» e o «não» naturais, lidos sem rede (dono, 2026-10-29; ADR-0048 emendada).

«Sim, pode seguir», «pode», «vai em frente» respondem à pergunta; «não, não faz», «melhor não»
recusam; o que mistura os dois, ou traz outra coisa no meio, não é resposta clara — nunca vira sim.
"""

from __future__ import annotations

import pytest

from jarvis.s2.portao import RespostaDoDono, resposta_literal
from jarvis.voz.resposta import TipoDaResposta, ler_resposta

SIM, NAO = RespostaDoDono.SIM, RespostaDoDono.NAO


@pytest.mark.parametrize(
    "fala",
    [
        "sim", "Sim, pode seguir.", "pode", "pode sim, por favor", "vai em frente", "manda bala",
        "beleza, manda", "claro, pode fazer", "isso mesmo", "confirmo", "tá bom, pode", "ok",
        "sim por favor, Jarvis", "pode continuar", "prossiga", "autorizo",
    ],
)  # fmt: skip
def test_o_sim_natural(fala: str) -> None:
    assert resposta_literal(fala) is SIM


@pytest.mark.parametrize(
    "fala",
    [
        "não", "não, não faz isso", "melhor não", "deixa pra lá", "não pode", "cancela isso aí",
        "para", "não precisa", "nem pensar", "espera um pouco", "agora não",
    ],
)  # fmt: skip
def test_o_nao_natural(fala: str) -> None:
    assert resposta_literal(fala) is NAO


@pytest.mark.parametrize(
    "fala",
    [
        "não, pode seguir",  # ambígua: não autoriza
        "pode, mas só amanhã",  # uma condição: não é o sim à ação perguntada
        "sim, abre o spotify",  # outro pedido junto
        "abre o spotify",
        "um momento",
        "sim sim sim sim sim sim sim sim sim",  # longa demais para ser uma resposta
    ],
)
def test_o_que_nao_e_resposta_clara_nunca_vira_sim(fala: str) -> None:
    assert resposta_literal(fala) is None


def test_na_voz_a_mesma_leitura_tira_a_palavra_e_o_eco() -> None:
    """O laço de voz e o cérebro leem igual: o «sim» natural chega à voz como sim (e lá passa pelos
    sinais de fala real da ADR-0043); o ambíguo, como outra coisa."""
    pergunta = "Posso apagar de vez? Isso não tem volta."
    assert ler_resposta("Jarvis, sim, pode seguir", pergunta).tipo is TipoDaResposta.SIM
    assert ler_resposta("vai em frente", pergunta).tipo is TipoDaResposta.SIM
    assert ler_resposta("melhor não", pergunta).tipo is TipoDaResposta.NAO
    assert ler_resposta("não, pode seguir", pergunta).tipo is TipoDaResposta.OUTRA
