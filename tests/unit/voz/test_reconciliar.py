"""Reconciliação por som (ADR-0067): a palavra que o ASR errou volta pelo som e pelo contexto.

Os exemplos do dono (2026-11-14): «mãe» ouvido «ma i», «WhatsApp» ouvido «note pad», uma sigla
ouvida soletrada («gepe madi»). E o outro lado, que pesa mais: palavra comum nunca vira nome.
"""

from __future__ import annotations

import pytest

from jarvis.voz.reconciliar import (
    LEXICO_BASE,
    NOTA_DA_VOZ,
    Candidato,
    Reconciliador,
    som,
)


@pytest.fixture
def reconciliador() -> Reconciliador:
    return Reconciliador.do_contexto(
        termos=[Candidato("GPMad", "termo")],
        apps=["Kdenlive", "Discord"],
        pessoas=["Kauã Ximenes"],
    )


@pytest.mark.parametrize(
    ("ouvido", "esperado"),
    [
        ("Ma i.", "Mãe."),
        ("Abre o contato da minha ma i.", "Abre o contato da minha mãe."),
        ("Liga pra minha ma i", "Liga pra minha mãe"),
        ("Abre o what's app", "Abre o WhatsApp"),
        ("Abre o gepe madi", "Abre o GPMad"),
        ("Pergunta pro gepetê", "Pergunta pro GPT"),
        ("Abre o jemini", "Abre o Gemini"),
        ("Fecha o stim", "Fecha o Steam"),
        ("abre o spot fai", "abre o Spotify"),
        ("Abre o gugou", "Abre o Google"),
        ("Abre o chat GPT.", "Abre o ChatGPT."),
    ],
)
def test_som_quase_igual_troca_sem_perguntar(
    reconciliador: Reconciliador, ouvido: str, esperado: str
) -> None:
    resultado = reconciliador.reconciliar(ouvido)
    assert resultado.texto == esperado
    assert resultado.trocas and all(t.certa for t in resultado.trocas)


@pytest.mark.parametrize(
    "ouvido",
    ["Manda mensagem no note pad pra minha mãe.", "Manda mensagem no what's up."],
)
def test_na_vaga_do_mensageiro_o_som_parecido_vira_palpite_que_o_cerebro_relata(
    reconciliador: Reconciliador, ouvido: str
) -> None:
    resultado = reconciliador.reconciliar(ouvido)
    assert "WhatsApp" in resultado.texto
    (troca,) = resultado.trocas
    assert not troca.certa
    assert "diga em poucas palavras o que entendeu" in resultado.nota()
    assert f"Ouvi «{troca.ouvido}»" in resultado.nota()


@pytest.mark.parametrize(
    "fala",
    [
        "Abre o navegador",
        "Minha mãe",
        "Minha mãe disse que vem amanhã",
        "Abre o Discord",
        "Abre o Kdenlive",
        "Abre o disco",
        "Manda mensagem no grupo",
        "Abre a pasta de downloads",
        "Que horas são?",
        "O que você acha da minha mana?",
        "Me dá a previsão do tempo",
        "Meu pai mandou um oi",
        "Liga pra Ana",
        "Fala pro meu chefe que atraso",
        "Toca no Spotify",
        "Abre o gatinho",
        "Abre o note pad",
        "Manda mensagem pro Kauã Ximenes",
    ],
)
def test_palavra_comum_e_nome_certo_ficam_como_estao(
    reconciliador: Reconciliador, fala: str
) -> None:
    resultado = reconciliador.reconciliar(fala)
    assert resultado.texto == fala
    assert not resultado.trocas


def test_som_parecido_fora_de_vaga_fechada_nao_troca_e_leva_os_candidatos(
    reconciliador: Reconciliador,
) -> None:
    resultado = reconciliador.reconciliar("Abre o ui tube")
    assert resultado.texto == "Abre o ui tube"
    assert resultado.duvidas[0].candidatos[0] == "YouTube"
    assert "«ui tube» pode ser «YouTube»" in resultado.nota()


def test_a_nota_sempre_lembra_que_a_transcricao_pode_estar_errada(
    reconciliador: Reconciliador,
) -> None:
    resultado = reconciliador.reconciliar("Que horas são?")
    assert not resultado.agiu and not resultado.mudou
    assert resultado.nota() == NOTA_DA_VOZ


def test_o_som_soletra_a_sigla_e_le_o_ingles_como_o_brasileiro() -> None:
    assert som("gepe madi") == som("gê pê madi")
    assert som("what's app") == som("uátsápi")
    assert som("ma i") == som("mãe")


def test_o_vocabulario_do_dono_vem_antes_do_lexico_base() -> None:
    proprio = Reconciliador.do_contexto(termos=[Candidato("Mainha", "pessoa")])
    assert proprio.reconciliar("Liga pra minha mai nha").texto == "Liga pra minha Mainha"


def test_sem_candidatos_e_texto_vazio_nao_quebram() -> None:
    assert Reconciliador([]).reconciliar("Abre o jemini").texto == "Abre o jemini"
    assert Reconciliador().reconciliar("").texto == ""
    assert len(LEXICO_BASE) > 30
