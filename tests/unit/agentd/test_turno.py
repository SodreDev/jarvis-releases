"""Cartão F1-07: dois detectores, a regra de empate em código e `unknown` que não interrompe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.curva_turno import (
    ALVO_SLO9,
    DECISAO_MINIMA,
    Intervalo,
    Ponto,
    aplicar_regra_de_empate,
    escolher_limiar,
    exemplos_de_treino,
    medir_ponto,
    simular,
    treinar,
)

from jarvis.agentd.turno import (
    CONFIANCA_MINIMA,
    Contexto,
    Decisao,
    DetectorDeTurno,
    Previsao,
    Semantico,
    SilencioFixo,
    gravar_pesos,
)
from jarvis.barramento.envelope import Prioridade, Tipo

SESSAO = "0193f0a0-0000-7000-8000-000000000000"


def ponto(
    *, detector: str, limiar: float, falso: int, meio: int, atrasos: tuple[float, ...], fim: int
) -> Ponto:
    return Ponto(
        detector=detector,
        limiar=limiar,
        split="calibracao",
        itens_fim=fim,
        itens_meio=meio,
        falsos_cortes=falso,
        nao_decidiu=fim - len(atrasos),
        atrasos_ms=atrasos,
    )


def test_os_dois_detectores_cumprem_a_interface() -> None:
    assert isinstance(SilencioFixo(), DetectorDeTurno)
    assert isinstance(Semantico(), DetectorDeTurno)


def test_o_controle_so_decide_por_silencio_e_ignora_texto() -> None:
    detector = SilencioFixo(limiar_ms=700.0)
    completo = Contexto(pausa_ms=300.0, texto="abre a pasta de fotos")
    incompleto = Contexto(pausa_ms=800.0, texto="abre a pasta de")

    assert detector.prever(completo).decisao is Decisao.HOLD
    assert detector.prever(incompleto).decisao is Decisao.YIELD, "o controle não lê texto"


def test_unknown_nunca_vira_yield() -> None:
    """Aceite (c): sem confiança, não interrompe."""
    semantico = Semantico(pesos={"pausa_s": 0.0}, vies=0.0, limiar=0.5)

    previsao = semantico.prever(Contexto(pausa_ms=400.0, texto="abre a pasta"))

    assert previsao.p_eot == pytest.approx(0.5)
    assert previsao.decisao is Decisao.UNKNOWN
    assert abs(previsao.p_eot - semantico.limiar) < CONFIANCA_MINIMA


def test_a_vizinhanca_do_limiar_e_unknown_e_fora_dela_decide() -> None:
    semantico = Semantico(pesos={"pausa_s": 10.0}, vies=-5.0, limiar=0.5)

    cedo = semantico.prever(Contexto(pausa_ms=100.0))
    tarde = semantico.prever(Contexto(pausa_ms=900.0))

    assert cedo.decisao is Decisao.HOLD
    assert tarde.decisao is Decisao.YIELD


def test_o_envelope_de_turn_prediction_cumpre_o_contrato() -> None:
    previsao = Previsao(p_eot=0.82, detector="semantico", decisao=Decisao.YIELD)

    envelope = previsao.envelope(session_id=SESSAO, epoch=3)

    assert envelope.type is Tipo.TURN_PREDICTION
    assert envelope.priority is Prioridade.P1
    assert envelope.source == "agentd"
    assert envelope.payload == {"p_eot": 0.82, "detector": "semantico", "decision": "yield"}


def test_tracos_dizem_quando_a_frase_nao_pode_ter_acabado() -> None:
    aberta = Contexto(pausa_ms=500.0, texto="compacta a apresentação do curso antes de").tracos()
    fechada = Contexto(pausa_ms=500.0, texto="compacta a apresentação do curso").tracos()

    assert aberta["termina_em_palavra_aberta"] == 1.0
    assert fechada["termina_em_palavra_aberta"] == 0.0
    assert fechada["comeca_com_verbo"] == 1.0


def test_a_regra_de_empate_mantem_o_controle_quando_os_ics_se_sobrepoem() -> None:
    """Empate dentro do IC → fica o `silencio_fixo` (mais simples e mais explicável)."""
    # Pontos utilizáveis (IC do falso corte dentro do alvo de 3%), que é o que a regra exige
    # antes de comparar.
    falso_fixo = Intervalo(0.020, 0.010, 0.029)
    atraso_fixo = Intervalo(700.0, 650.0, 750.0)
    falso_sem = Intervalo(0.019, 0.012, 0.028)
    atraso_sem = Intervalo(690.0, 640.0, 740.0)

    veredito = aplicar_regra_de_empate(falso_fixo, atraso_fixo, falso_sem, atraso_sem)

    assert not veredito.semantico_entra
    assert "empate" in veredito.motivo


def test_a_regra_de_empate_aceita_o_semantico_quando_ele_e_melhor_fora_do_ic() -> None:
    falso_fixo = Intervalo(0.028, 0.025, 0.030)
    atraso_fixo = Intervalo(700.0, 650.0, 750.0)
    falso_sem = Intervalo(0.012, 0.008, 0.016)  # IC inteiro abaixo, e dentro do alvo
    atraso_sem = Intervalo(690.0, 640.0, 740.0)  # empata no atraso

    veredito = aplicar_regra_de_empate(falso_fixo, atraso_fixo, falso_sem, atraso_sem)

    assert veredito.semantico_entra
    assert "falso corte" in veredito.motivo


def test_a_regra_de_empate_recusa_o_semantico_que_piora_a_outra_dimensao() -> None:
    """Melhor no atraso, pior no falso corte: não entra. A regra exige não ser pior em nenhuma."""
    falso_fixo = Intervalo(0.010, 0.008, 0.012)
    atraso_fixo = Intervalo(700.0, 650.0, 750.0)
    falso_sem = Intervalo(0.025, 0.020, 0.030)
    atraso_sem = Intervalo(200.0, 150.0, 250.0)

    veredito = aplicar_regra_de_empate(falso_fixo, atraso_fixo, falso_sem, atraso_sem)

    assert not veredito.semantico_entra
    assert "pior em falso corte" in veredito.motivo


def test_ponto_inutilizavel_torna_a_comparacao_inconclusiva() -> None:
    """A guarda: quem corta em 60% dos turnos não é candidato, nem com atraso zero.

    Sem ela, a regra "menor atraso" premiaria o detector que cede no instante zero — atraso
    zero por construção, falso corte catastrófico. Foi o que aconteceu na primeira execução
    real da varredura.
    """
    falso_fixo = Intervalo(0.680, 0.573, 0.787)
    atraso_fixo = Intervalo(500.0, 500.0, 500.0)
    falso_sem = Intervalo(0.587, 0.480, 0.693)
    atraso_sem = Intervalo(0.0, 0.0, 0.0)

    veredito = aplicar_regra_de_empate(falso_fixo, atraso_fixo, falso_sem, atraso_sem)

    assert not veredito.semantico_entra
    assert "INCONCLUSIVO" in veredito.motivo
    assert "F1-15" in veredito.motivo


def test_a_monotonia_na_pausa_e_restricao_do_modelo(tmp_path: Path) -> None:
    """Esperar mais nunca pode reduzir `p_eot` — e o corpus sintético ensinaria o contrário."""
    from tools.curva_turno import TRACOS_MONOTONOS

    from jarvis.corpus.rotulos import ler_rotulos
    from jarvis.corpus.sintetico import gerar_corpus
    from jarvis.corpus.voz import VozParametrica

    gerar_corpus(
        12, semente=3, pasta=tmp_path, voz=VozParametrica(), fracao_ruido=0.0, fracao_eco=0.0
    )
    rotulos = ler_rotulos(tmp_path / "rotulos.jsonl")
    textos = {r.id: r.texto_antes for r in rotulos}

    pesos, _, _ = treinar(rotulos, textos, iteracoes=500)

    assert "pausa_s" in TRACOS_MONOTONOS
    assert pesos["pausa_s"] >= 0.0, "o peso da pausa não pode ser negativo"


def test_o_criterio_de_escolha_do_limiar_e_o_declarado() -> None:
    """Menor atraso p50 entre os que têm falso corte ≤ 3%; se nenhum tem, o de menor falso."""
    rapido_e_errado = ponto(
        detector="x", limiar=1.0, falso=10, meio=100, atrasos=(100.0,) * 50, fim=50
    )
    lento_e_certo = ponto(
        detector="x", limiar=2.0, falso=2, meio=100, atrasos=(700.0,) * 50, fim=50
    )
    medio_e_certo = ponto(
        detector="x", limiar=3.0, falso=3, meio=100, atrasos=(400.0,) * 50, fim=50
    )

    escolhido = escolher_limiar([rapido_e_errado, lento_e_certo, medio_e_certo])

    assert escolhido.limiar == 3.0
    assert escolhido.falso_corte <= ALVO_SLO9

    so_ruins = [rapido_e_errado]
    assert escolher_limiar(so_ruins).limiar == 1.0


def test_falso_corte_e_atraso_contam_o_que_as_definicoes_dizem(tmp_path: Path) -> None:
    from jarvis.corpus.rotulos import Rotulo

    fim = Rotulo(
        id="s-1",
        arquivo="audio/s-1.wav",
        sha256="a" * 64,
        falante="sintetico",
        pausa_ms=800,
        fim_de_turno=True,
        texto="abre a pasta de fotos",
        split="retido",
        sintetico=True,
        semente=1,
        gerador="g",
        voz="v",
        licenca_voz="l",
        texto_antes="abre a pasta de fotos",
        inicio_fala_ms=200,
        inicio_pausa_ms=1000,
    )
    meio = Rotulo(
        id="s-2",
        arquivo="audio/s-2.wav",
        sha256="b" * 64,
        falante="sintetico",
        pausa_ms=800,
        fim_de_turno=False,
        texto="abre a pasta de fotos na área de trabalho",
        split="retido",
        sintetico=True,
        semente=1,
        gerador="g",
        voz="v",
        licenca_voz="l",
        texto_antes="abre a pasta de fotos",
        texto_depois="na área de trabalho",
        inicio_fala_ms=200,
        inicio_pausa_ms=1000,
    )
    textos = {"s-1": "abre a pasta de fotos", "s-2": "abre a pasta de fotos"}
    detector = SilencioFixo(limiar_ms=400.0)

    assert simular(detector, fim, textos["s-1"]) == 400.0
    ponto_medido = medir_ponto(detector, 400.0, [fim, meio], textos, split="retido")

    assert ponto_medido.atraso_p50 == 400.0
    assert ponto_medido.falsos_cortes == 1, "cortou quem ia continuar"
    assert ponto_medido.falso_corte == 1.0
    assert ponto_medido.nao_decidiu == 0

    paciente = SilencioFixo(limiar_ms=1200.0)
    sem_decisao = medir_ponto(paciente, 1200.0, [fim, meio], textos, split="retido")
    assert sem_decisao.nao_decidiu == 1, "não decidiu dentro da pausa gravada"
    assert sem_decisao.atrasos_ms == ()
    assert sem_decisao.falsos_cortes == 0


def test_o_treino_e_deterministico_e_os_pesos_sao_dado(tmp_path: Path) -> None:
    from jarvis.corpus.rotulos import ler_rotulos
    from jarvis.corpus.sintetico import gerar_corpus
    from jarvis.corpus.voz import VozParametrica

    gerar_corpus(
        8, semente=5, pasta=tmp_path, voz=VozParametrica(), fracao_ruido=0.0, fracao_eco=0.0
    )
    rotulos = ler_rotulos(tmp_path / "rotulos.jsonl")
    textos = {r.id: r.texto_antes for r in rotulos}

    tracos, alvos = exemplos_de_treino(rotulos, textos)
    primeiro = treinar(rotulos, textos, iteracoes=200)
    segundo = treinar(rotulos, textos, iteracoes=200)

    assert len(tracos) == len(alvos) > len(rotulos), "vários instantes de decisão por item"
    assert primeiro == segundo, "mesmos dados, mesmos pesos"

    arquivo = tmp_path / "pesos.json"
    gravar_pesos(arquivo, pesos=primeiro[0], vies=primeiro[1], treinado_em="2026-10-15", n=10)
    dados = json.loads(arquivo.read_text(encoding="utf-8"))

    assert set(dados["pesos"]) == set(primeiro[0])
    assert "não editar à mão" in dados["descricao"]
    recarregado = Semantico.do_arquivo(arquivo)
    assert recarregado.pesos == primeiro[0]


def test_nunca_ceder_nao_ganha_a_comparacao() -> None:
    """A guarda declarada: limiar que decide pouco não é candidato, mesmo com falso corte zero."""
    nunca_decide = ponto(detector="x", limiar=9.0, falso=0, meio=100, atrasos=(), fim=50)
    decide_e_erra_pouco = ponto(
        detector="x", limiar=5.0, falso=2, meio=100, atrasos=(500.0,) * 40, fim=50
    )

    escolhido = escolher_limiar([nunca_decide, decide_e_erra_pouco])

    assert escolhido.limiar == 5.0
    assert nunca_decide.falso_corte == 0.0, "o vácuo parecia perfeito"
    assert decide_e_erra_pouco.decidiu / decide_e_erra_pouco.itens_fim >= DECISAO_MINIMA


def test_quando_nenhum_limiar_decide_o_suficiente_o_relatorio_nao_finge() -> None:
    """Sem candidato, escolhe-se o que mais decide — e o relatório mostra o não decidiu."""
    pouco = ponto(detector="x", limiar=1.0, falso=0, meio=100, atrasos=(100.0,) * 10, fim=50)
    menos = ponto(detector="x", limiar=2.0, falso=0, meio=100, atrasos=(100.0,) * 5, fim=50)

    escolhido = escolher_limiar([pouco, menos])

    assert escolhido.limiar == 1.0
    assert escolhido.nao_decidiu == 40
