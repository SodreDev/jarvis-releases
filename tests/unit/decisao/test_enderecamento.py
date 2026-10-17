"""O detector de endereçamento com o classificador de mentira: limiares, histerese e a regra de
ouro (na dúvida, não age)."""

from __future__ import annotations

import pytest

from jarvis.decisao.enderecamento import (
    PERGUNTAS,
    DetectorDeEnderecamento,
    Intencao,
    Limiares,
    Motivo,
)
from jarvis.decisao.fake import ClassificadorFalso, endereco
from jarvis.decisao.interface import PerguntaEscolha, PerguntaNoul, RespostaNoul


class Relogio:
    def __init__(self) -> None:
        self.agora = 100.0

    def __call__(self) -> float:
        return self.agora


def detector(p: float, intencao: str = "resposta", **extras: object) -> DetectorDeEnderecamento:
    relogio = Relogio()
    return DetectorDeEnderecamento(
        classificador=ClassificadorFalso(roteiro=endereco(p, intencao), **extras),  # type: ignore[arg-type]
        relogio=relogio,
    )


def test_as_perguntas_sao_fechadas_e_a_opcao_segura_vem_primeiro() -> None:
    assert isinstance(PERGUNTAS["falando_com_o_jarvis"], PerguntaNoul)
    pedido = PERGUNTAS["pedido"]
    assert isinstance(pedido, PerguntaEscolha)
    assert list(pedido.opcoes) == ["ignorar", "resposta", "sugestao", "acao"]


@pytest.mark.parametrize("intencao", ["resposta", "sugestao", "acao"])
def test_fala_endereçada_com_certeza_age_e_diz_a_intencao(intencao: str) -> None:
    d = detector(0.95, intencao).avaliar("abre o discord")
    assert d.agir and d.motivo is Motivo.ENDERECADA and d.intencao is Intencao(intencao)


def test_falar_sozinho_ou_com_outra_pessoa_nao_age() -> None:
    d = detector(0.05, "ignorar").avaliar("amor, onde deixei a chave do carro?")
    assert not d.agir and d.motivo is Motivo.NAO_ERA_COMIGO


def test_no_meio_do_caminho_e_incerto_e_nao_age() -> None:
    d = detector(0.55).avaliar("hum, será que chove amanhã")
    assert not d.agir and d.motivo is Motivo.INCERTO


def test_endereçada_mas_intencao_ignorar_nao_age() -> None:
    d = detector(0.9, "ignorar").avaliar("tá, tá")
    assert not d.agir and d.motivo is Motivo.NAO_ERA_COMIGO


def test_intencao_sem_clareza_nao_age() -> None:
    d = detector(
        0.95,
        "acao",
    ).avaliar("isso aí")
    assert d.agir  # controle: com 0,9 de certeza da intenção age
    fraco = DetectorDeEnderecamento(
        classificador=ClassificadorFalso(roteiro=endereco(0.95, "acao", 0.3))
    ).avaliar("isso aí")
    assert not fraco.agir and fraco.motivo is Motivo.SEM_INTENCAO


def test_histerese_conversa_em_andamento_aceita_menos_certeza() -> None:
    relogio = Relogio()
    classificador = ClassificadorFalso(roteiro=endereco(0.9))
    det = DetectorDeEnderecamento(classificador=classificador, relogio=relogio)
    assert det.avaliar("jarvis, que horas são").agir
    classificador.roteiro = endereco(0.65)  # entre permanecer (0,55) e entrar (0,80)
    estava_em_conversa = det.em_conversa
    assert estava_em_conversa and det.avaliar("e em Lisboa?").agir

    relogio.agora += 60.0  # a conversa esfriou
    esfriou = not det.em_conversa
    assert esfriou
    d = det.avaliar("e em Lisboa?")
    assert not d.agir and d.motivo is Motivo.INCERTO


def test_o_estado_enviado_e_so_a_fala_e_dois_sinais_locais() -> None:
    classificador = ClassificadorFalso(roteiro=endereco(0.9))
    det = DetectorDeEnderecamento(classificador=classificador)
    det.avaliar("  abre o discord ", jarvis_perguntou=True)
    estado, _ = classificador.chamadas[0]
    assert estado == {
        "fala": "abre o discord",
        "o_assistente_acabou_de_fazer_uma_pergunta": "sim",
        "ja_estavamos_conversando": "não",
    }


def test_classificador_fora_do_ar_nao_age_e_diz_por_que() -> None:
    d = detector(0.99, falhar_com="503 do serviço").avaliar("abre o discord")
    assert not d.agir and d.motivo is Motivo.FORA_DO_AR and "503" in d.detalhe


def test_resposta_com_tipo_trocado_nao_age() -> None:
    def torta(_e: object, _p: object) -> dict[str, RespostaNoul]:
        return {"falando_com_o_jarvis": RespostaNoul(0.99), "pedido": RespostaNoul(0.99)}

    det = DetectorDeEnderecamento(classificador=ClassificadorFalso(roteiro=torta))
    assert not det.avaliar("abre").agir


def test_resposta_sem_uma_das_perguntas_nao_age() -> None:
    det = DetectorDeEnderecamento(
        classificador=ClassificadorFalso(
            roteiro=lambda _e, _p: {"falando_com_o_jarvis": RespostaNoul(0.9)}
        )
    )
    assert not det.avaliar("abre").agir


def test_a_frase_da_tela_nunca_repete_a_fala() -> None:
    d = detector(0.95, "acao").avaliar("minha senha é 1234")
    assert ("1234" not in d.frase() and "ação" not in d.frase()) or "acao" in d.frase()
    assert "1234" not in d.frase()


def test_limiares_incoerentes_sao_recusados() -> None:
    with pytest.raises(ValueError):
        Limiares(entrar=0.5, permanecer=0.6)


def test_o_resumo_conta_o_que_aconteceu() -> None:
    det = detector(0.95)
    det.avaliar("a")
    det.avaliar("b")
    assert "2 consulta(s)" in det.resumo() and "endereçadas 2" in det.resumo()
