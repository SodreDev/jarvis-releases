"""ADR-0063: a nota do dono por turno — a leitura da fala é conservadora."""

from __future__ import annotations

import pytest

from jarvis.s2.nota_do_dono import Nota, nota_do_botao, nota_na_fala


@pytest.mark.parametrize(
    "fala",
    [
        "Ficou ótimo, valeu.",
        "boa, Jarvis!",
        "mandou bem nessa",
        "Ficou perfeito, agora abre o outro arquivo",
        "olha, ficou muito bom",
    ],
)
def test_frase_boa_no_comeco_da_fala_e_nota_boa(fala: str) -> None:
    assert nota_na_fala(fala) is Nota.BOA


@pytest.mark.parametrize(
    "fala",
    [
        "Não era isso.",
        "não foi isso que eu pedi, eu queria a planilha",
        "Você errou o nome do arquivo",
        "ficou ruim essa resposta",
        "Jarvis, tá errado",
        "eu não gostei",
    ],
)
def test_frase_ruim_no_comeco_da_fala_e_nota_ruim(fala: str) -> None:
    assert nota_na_fala(fala) is Nota.RUIM


@pytest.mark.parametrize(
    "fala",
    [
        "",
        "abre o navegador",
        "valeu",  # agradecimento, não nota
        "isso mesmo",  # confirmação, não nota
        "sim",
        "não ficou ruim",  # negação de nota: ambígua
        "nem ficou bom nem ficou ruim",
        "ficou bom mas ficou errado",  # as duas notas
        "abre o arquivo do relatório que eu escrevi ontem e diz se ficou bom",  # longe do começo
    ],
)
def test_fala_que_nao_e_nota_ou_e_ambigua_nao_anota(fala: str) -> None:
    assert nota_na_fala(fala) is None


def test_o_botao_da_a_nota_direto() -> None:
    assert nota_do_botao(True) is Nota.BOA and nota_do_botao(False) is Nota.RUIM
