"""Cartão F1-11: a suíte de cancelamento em 20 pontos — o aceite (b) da F1.

Cada ponto da lista de `jarvis.agentd.turno_completo.PONTOS` tem um caso nomeado aqui, e em
todos se confere as **três invariantes**: zero áudio velho tocando, zero entrada no histórico de
algo que não tocou, zero tool disparada depois do `Cancel`.

O que esta suíte **não** prova, e está dito: o áudio já entregue ao **driver**. A invariante é
sobre o nosso sumidouro; a fila do dispositivo é do F1-16.
"""

from __future__ import annotations

import random

import pytest

from jarvis.agentd.turno_completo import (
    NOMES,
    PONTOS,
    Resultado,
    TurnoCompleto,
    regras_cobertas,
    rodar_todos,
)

pytestmark = pytest.mark.cancelamento

SEMENTE_DO_FUZZ = 20_261_015
"""Semente comitada: fuzz que não se reproduz não é regressão, é anedota."""
REPETICOES_DO_FUZZ = 1_000


@pytest.fixture(scope="module")
def turno() -> TurnoCompleto:
    return TurnoCompleto()


@pytest.fixture(scope="module")
def todos(turno: TurnoCompleto) -> list[Resultado]:
    return rodar_todos(turno)


def test_a_lista_tem_vinte_pontos_nomeados_e_com_porque() -> None:
    """Aceite (a): vinte pontos, cada um com nome e motivo no arquivo."""
    assert len(PONTOS) == 20
    assert len(set(NOMES)) == 20, "nome repetido esconderia um ponto não testado"
    assert all(p.porque.strip() for p in PONTOS), "ponto sem porquê não é revisável"


@pytest.mark.parametrize("nome", NOMES)
def test_interromper_em_cada_ponto_nao_deixa_nada_para_tras(
    nome: str, turno: TurnoCompleto
) -> None:
    """Aceite (a), um caso por ponto, com as três invariantes."""
    resultado = turno.rodar(nome)

    assert resultado.sem_audio_velho, (
        f"{nome}: {resultado.amostras_apos_cancel} amostras tocaram depois do Cancel"
    )
    assert resultado.sem_historico_fantasma, (
        f"{nome}: o histórico contém {resultado.texto_nao_tocado[:40]!r}, que não tocou"
    )
    assert resultado.sem_tool_depois, f"{nome}: tool disparada depois do Cancel"


@pytest.mark.parametrize("nome", NOMES)
def test_o_historico_e_sempre_prefixo_do_que_foi_sintetizado(
    nome: str, turno: TurnoCompleto
) -> None:
    """Regra 4 da §3.3: o histórico é o que saiu, nunca o que foi enfileirado."""
    resultado = turno.rodar(nome)

    ouvido = resultado.historico.texto_ouvido
    assert resultado.fala.texto.startswith(ouvido)
    assert len(ouvido) <= len(resultado.fala.texto)


def test_as_seis_regras_da_secao_3_3_sao_exercitadas(todos: list[Resultado]) -> None:
    """Aceite (b): as seis, inclusive a exceção da regra 3."""
    cobertas = regras_cobertas(todos)

    assert cobertas == {1, 2, 3, 4, 5, 6}, (
        f"faltam as regras {sorted({1, 2, 3, 4, 5, 6} - cobertas)}"
    )


def test_a_excecao_da_regra_3_e_respeitada(todos: list[Resultado]) -> None:
    """`ToolResult` de leitura pode chegar; só entra se o `s2` reavaliar no epoch novo."""
    com_tool_em_voo = [r for r in todos if r.ponto == "durante_tool_de_leitura_em_voo"]
    assert com_tool_em_voo, "o ponto da regra 3 tem de existir"
    (resultado,) = com_tool_em_voo

    assert resultado.tool_result_de_leitura_chegou, "leitura em voo pode terminar"
    assert not resultado.tool_result_entrou_no_estado, (
        "mas não entra no estado sem o s2 reavaliar no epoch novo"
    )
    assert resultado.sem_tool_depois, "e nenhuma tool nova é disparada"


def test_a_retomada_nao_ressuscita_o_plano_antigo(todos: list[Resultado]) -> None:
    """Regra 5: "continua" parte do trecho tocado, e o que não tocou não volta."""
    interrompidos = [r for r in todos if r.retomada is not None]

    assert interrompidos, "a maioria dos pontos interrompe de verdade"
    for resultado in interrompidos:
        retomada = resultado.retomada
        assert retomada is not None
        assert not retomada.ressuscita(resultado.fala.texto)
        assert retomada.ouvido == resultado.historico.texto_ouvido


def test_sem_interrupcao_a_resposta_inteira_toca(turno: TurnoCompleto) -> None:
    """O controle: sem Cancel, o histórico tem o texto inteiro e nada é descartado."""
    resultado = turno.rodar(None)

    assert resultado.historico.texto_ouvido == resultado.fala.texto
    assert resultado.retomada is None
    assert resultado.pedacos_descartados == 0


def test_fuzz_com_ponto_aleatorio_nao_viola_as_invariantes(turno: TurnoCompleto) -> None:
    """Aceite (c): n ≥ 1 000, semente comitada, três invariantes em todas as execuções."""
    sorteio = random.Random(SEMENTE_DO_FUZZ)
    falhas: list[str] = []

    for _ in range(REPETICOES_DO_FUZZ):
        nome = sorteio.choice(NOMES)
        resultado = turno.rodar(nome)
        if not resultado.invariantes_ok:
            falhas.append(
                f"{nome}: audio={resultado.sem_audio_velho} "
                f"hist={resultado.sem_historico_fantasma} tool={resultado.sem_tool_depois}"
            )

    assert not falhas, f"{len(falhas)} violação(ões) em {REPETICOES_DO_FUZZ}: {falhas[:5]}"
