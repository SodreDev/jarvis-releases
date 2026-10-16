"""Palavra de ativação por casamento fonético (ADR-0021).

Tudo aqui é texto: nenhum teste abre microfone, transcreve áudio ou fala com a rede. O que se
prova é a parte que o código decide — "a transcrição me chamou?" — com as grafias que o ASR
produz para "jarvis" e com os nomes vizinhos que não podem abrir o microfone sozinhos.

O caso com `epitran` é `skip` onde o grupo `voz` não está instalado (o CI).
"""

from __future__ import annotations

import importlib.util

import pytest

from jarvis.voz.palavra import (
    LIMIAR_MAXIMO,
    LIMIAR_MINIMO,
    LIMIAR_PADRAO,
    PALAVRA_PADRAO,
    DetectorDePalavra,
    PalavraInvalida,
    distancia,
    exigir_limiar,
    exigir_palavra,
    fonetica_simples,
    palavras_de,
    similaridade,
)

sem_epitran = pytest.mark.skipif(
    importlib.util.find_spec("epitran") is None,
    reason="epitran não está instalado (grupo opcional `voz`; o CI não instala)",
)

VARIANTES_QUE_CASAM = ("jarvis", "Jarvis", "járvis", "djarvis", "jarves", "JARVIS")
VIZINHOS_QUE_NAO_CASAM = ("jarbas", "marvin", "charles", "carlos", "travis", "jardim")


# --- as peças -------------------------------------------------------------------------------
def test_distancia_e_similaridade_nos_casos_de_borda() -> None:
    assert distancia("", "") == 0
    assert distancia("abc", "") == 3
    assert distancia("", "ab") == 2
    assert distancia("kitten", "sitting") == 3
    assert similaridade("", "") == 1.0
    assert similaridade("abc", "abc") == 1.0
    assert similaridade("abc", "xyz") == 0.0


def test_fonetica_junta_as_grafias_do_mesmo_som() -> None:
    assert fonetica_simples("jarvis") == fonetica_simples("djarvis") == "Jarvis"
    assert fonetica_simples("járvis") == "Jarvis"
    assert fonetica_simples("jarves") == "Jarvis"  # vogal átona final fecha
    assert fonetica_simples("gente") == fonetica_simples("jenti")
    assert fonetica_simples("chave") == fonetica_simples("xavi")
    assert fonetica_simples("queijo") == fonetica_simples("keijo")
    assert fonetica_simples("hora") == fonetica_simples("ora")
    assert fonetica_simples("casa") == "kaza"
    assert fonetica_simples("água") == "agua"  # `gu` antes de `a` mantém o `u`


def test_gu_e_qu_fora_de_e_i_nao_prendem_o_laco() -> None:
    # Regressão: o primeiro `fonetica_simples` girava para sempre em "quando" e "água" —
    # e o corpus tem "quando o café ficar pronto". Chegar aqui já é a prova.
    assert fonetica_simples("quando") == "kuandu"
    assert fonetica_simples("guarda") == "guarda"
    assert fonetica_simples("guerra") == "geRa"
    assert DetectorDePalavra().achar("abaixa a rádio quando o café ficar pronto") is None


def test_palavras_tira_pontuacao_e_corta_no_teto() -> None:
    assert palavras_de("Jarvis, que horas são?") == ["jarvis", "que", "horas", "são"]
    assert palavras_de("  ...  ") == []
    assert len(palavras_de("a " * 500)) == 64


# --- o detector -----------------------------------------------------------------------------
@pytest.mark.parametrize("variante", VARIANTES_QUE_CASAM)
def test_variantes_do_nome_chamam(variante: str) -> None:
    detector = DetectorDePalavra()
    achado = detector.achar(f"{variante} abre a pasta de fotos")
    assert achado is not None
    assert achado.comando == "abre a pasta de fotos"
    assert achado.similaridade >= LIMIAR_PADRAO


@pytest.mark.parametrize("vizinho", VIZINHOS_QUE_NAO_CASAM)
def test_nomes_vizinhos_nao_chamam(vizinho: str) -> None:
    assert DetectorDePalavra().achar(f"o {vizinho} ligou ontem") is None


def test_frase_comum_do_corpus_nao_chama() -> None:
    assert DetectorDePalavra().achar("duplica o documento do aluguel") is None


def test_nome_partido_pelo_asr_chama_pela_janela_de_duas_palavras() -> None:
    achado = DetectorDePalavra().achar("jar vis que horas são")
    assert achado is not None
    assert achado.ouvido == "jar vis"
    assert achado.comando == "que horas são"


def test_comando_antes_do_nome_vale_igual() -> None:
    achado = DetectorDePalavra().achar("que horas são, jarvis")
    assert achado is not None
    assert achado.depois == ""
    assert achado.antes == "que horas são"
    assert achado.comando == "que horas são"
    assert not achado.so_o_nome


def test_so_o_nome_arma_a_escuta() -> None:
    achado = DetectorDePalavra().achar("Jarvis?")
    assert achado is not None
    assert achado.so_o_nome
    assert achado.comando == ""


def test_empate_fica_com_a_janela_menor() -> None:
    # "jarvis abre": a janela de duas palavras não pode engolir o verbo.
    achado = DetectorDePalavra().achar("jarvis abre")
    assert achado is not None
    assert achado.ouvido == "jarvis"
    assert achado.comando == "abre"


def test_trecho_vazio_nao_chama() -> None:
    assert DetectorDePalavra().achar("") is None
    assert DetectorDePalavra().achar(" ,. ") is None


def test_palavra_escolhida_pelo_dono() -> None:
    detector = DetectorDePalavra(palavra="Sexta")
    assert detector.palavra == "sexta"
    achado = detector.achar("sexta, liga a luz")
    assert achado is not None
    assert achado.comando == "liga a luz"
    assert detector.achar("jarvis, liga a luz") is None


def test_limiar_mais_alto_exige_mais() -> None:
    frouxo = DetectorDePalavra(limiar=0.80)
    estrito = DetectorDePalavra(limiar=1.0)
    assert frouxo.achar("jarvas acende a luz") is not None  # 0,833
    assert estrito.achar("jarvas acende a luz") is None
    assert estrito.achar("jarvis acende a luz") is not None
    assert frouxo.parecenca("jarvas") == pytest.approx(5 / 6)


def test_alvo_e_publico_para_a_tela() -> None:
    assert DetectorDePalavra().alvo == fonetica_simples(PALAVRA_PADRAO)


# --- as recusas que a tela cobra ------------------------------------------------------------
@pytest.mark.parametrize(
    ("bruta", "trecho"),
    [
        ("", "vazia"),
        ("   ", "vazia"),
        ("jar-vis", "pontuação"),
        ("ô jarvis", "mais de uma palavra"),
        ("oi", "curta demais"),
    ],
)
def test_palavra_que_nao_serve_e_recusada_com_motivo(bruta: str, trecho: str) -> None:
    with pytest.raises(PalavraInvalida, match=trecho):
        exigir_palavra(bruta)


def test_palavra_valida_volta_limpa() -> None:
    assert exigir_palavra("  Jarvis ") == "jarvis"
    assert exigir_palavra("Açaí") == "açaí"


@pytest.mark.parametrize("bruto", [0.49, 1.01, -1.0])
def test_limiar_fora_da_faixa_e_recusado(bruto: float) -> None:
    with pytest.raises(PalavraInvalida, match="fora da faixa"):
        exigir_limiar(bruto)


def test_limiar_que_nao_e_numero_e_recusado() -> None:
    with pytest.raises(PalavraInvalida, match="não é número"):
        exigir_limiar("alto")  # type: ignore[arg-type]


def test_limiar_nas_bordas_passa() -> None:
    assert exigir_limiar(LIMIAR_MINIMO) == LIMIAR_MINIMO
    assert exigir_limiar(LIMIAR_MAXIMO) == LIMIAR_MAXIMO
    assert exigir_limiar("0.9") == 0.9  # type: ignore[arg-type]


def test_detector_recusa_na_montagem() -> None:
    with pytest.raises(PalavraInvalida):
        DetectorDePalavra(palavra="ô jarvis")
    with pytest.raises(PalavraInvalida):
        DetectorDePalavra(limiar=0.2)


# --- o fonemizador de verdade, onde existe ---------------------------------------------------
@sem_epitran
def test_epitran_injetado_acha_a_chamada() -> None:
    from jarvis.voz.fonemizador import FonemizadorEpitran

    detector = DetectorDePalavra(fonetica=FonemizadorEpitran(com_tonica=False))
    achado = detector.achar("jarvis, que horas são")
    assert achado is not None
    assert achado.comando == "que horas são"
    assert detector.achar("duplica o documento do aluguel") is None
