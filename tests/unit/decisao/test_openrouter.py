"""O adaptador do Jev (OpenRouter) contra um servidor falso: sem rede, sem chave de verdade."""

from __future__ import annotations

import json

import pytest

from jarvis.decisao.enderecamento import PERGUNTAS
from jarvis.decisao.interface import (
    ClassificadorDeDecisao,
    DecisaoIndisponivel,
    DecisaoRecusada,
    PerguntaNota,
    RespostaEscolha,
    RespostaNota,
    RespostaNoul,
)
from jarvis.decisao.openrouter import REGISTRADO, ClassificadorOpenRouter
from jarvis.voz.chaves import VARIAVEL_OPENROUTER, SegredoAusente
from jarvis.voz.interface import Onde
from jarvis.voz.nuvem import NuvemRealProibidaEmCI
from jarvis.voz.registro import MotorRecusado
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

SEGREDO = "sk-or-v1-chave_de_teste_que_nao_pode_vazar_0123456789"
ESTADO = {"fala": "abre o discord"}


def ambiente() -> dict[str, str]:
    """`CI=1` fica ligado: é o que mantém o teste longe da nuvem de verdade."""
    return {"CI": "1", VARIAVEL_OPENROUTER: SEGREDO}


def resposta_boa() -> bytes:
    return json.dumps(
        {
            "id": "dec-1",
            "model": "typesafe/jev-1.13-20260917",
            "provider": "TypeSafe",
            "answers": {
                "falando_com_o_jarvis": {"noul": 0.93},
                "pedido": {
                    "choice": "acao",
                    "confidence": 0.8,
                    "probabilities": {
                        "ignorar": 0.02,
                        "resposta": 0.05,
                        "sugestao": 0.03,
                        "acao": 0.9,
                    },
                },
            },
            "usage": {"input_tokens": 400, "output_tokens": 0, "cost": 0.000017},
        }
    ).encode()


def classificador(servico: ServicoFalso, **extras: object) -> ClassificadorOpenRouter:
    return ClassificadorOpenRouter(
        base=servico.base,
        nuvem_ligada=[REGISTRADO],
        ambiente=ambiente(),
        **extras,  # type: ignore[arg-type]
    )


def test_satisfaz_a_interface_e_se_declara_de_nuvem() -> None:
    c = ClassificadorOpenRouter()
    assert isinstance(c, ClassificadorDeDecisao)
    assert c.onde is Onde.NUVEM


def test_sem_o_interruptor_do_dono_nada_abre() -> None:
    with pytest.raises(MotorRecusado, match="desligado"):
        ClassificadorOpenRouter(ambiente=ambiente()).abrir()


def test_o_portao_vem_antes_da_chave() -> None:
    with pytest.raises(MotorRecusado):
        ClassificadorOpenRouter(ambiente={}).abrir()


def test_sem_chave_a_recusa_diz_o_nome_e_nunca_o_valor() -> None:
    c = ClassificadorOpenRouter(
        nuvem_ligada=[REGISTRADO], ambiente={"CI": "1"}, base="http://127.0.0.1:9"
    )
    with pytest.raises(SegredoAusente, match=VARIAVEL_OPENROUTER):
        c.abrir()


def test_base_que_nao_e_local_e_proibida_sob_ci() -> None:
    with pytest.raises(NuvemRealProibidaEmCI):
        ClassificadorOpenRouter(nuvem_ligada=[REGISTRADO], ambiente=ambiente()).abrir()


def test_decide_contra_o_servico_falso_e_monta_o_pedido_do_contrato() -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        respostas = classificador(servico).decidir(ESTADO, PERGUNTAS)

        assert respostas["falando_com_o_jarvis"] == RespostaNoul(0.93)
        escolha = respostas["pedido"]
        assert isinstance(escolha, RespostaEscolha) and escolha.escolha == "acao"
        assert escolha.probabilidade_da_escolha == pytest.approx(0.9)
        pedido = servico.pedidos[0]
        assert pedido.caminho == "/decisions"
        corpo = json.loads(pedido.corpo)
        assert corpo["model"] == "typesafe/jev-1.13"
        assert corpo["state"] == ESTADO
        noul = corpo["questions"]["falando_com_o_jarvis"]
        assert noul["type"] == "noul" and set(noul["criteria"]) == {"true", "false"}
        escolhas = corpo["questions"]["pedido"]
        assert escolhas["type"] == "choice"
        assert next(iter(escolhas["criteria"])) == "ignorar", "a opção segura vai primeiro"
        assert pedido.cabecalho("Content-Type") == "application/json"
        assert pedido.cabecalho("User-Agent").startswith("jarvis/")


def test_a_chave_vai_no_cabecalho_e_em_lugar_nenhum_mais() -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=resposta_boa())) as servico:
        classificador(servico).decidir(ESTADO, PERGUNTAS)

        pedido = servico.pedidos[0]
        assert pedido.autorizacao == f"Bearer {SEGREDO}"
        assert SEGREDO not in pedido.caminho
        assert SEGREDO not in pedido.corpo.decode("utf-8", "replace")


def test_nota_e_lida_com_a_escala() -> None:
    corpo = json.dumps(
        {"answers": {"n": {"score": 1.4, "confidence": 0.7, "probabilities": {"0": 0.2, "1": 0.8}}}}
    ).encode()
    with ServicoFalso(roteiro=Roteiro(corpo=corpo)) as servico:
        r = classificador(servico).decidir("x", {"n": PerguntaNota("q", ["baixo", "alto"])})
        assert r["n"] == RespostaNota(1.4, 0.7, {0: 0.2, 1: 0.8})


@pytest.mark.parametrize(
    "corpo",
    [
        b"isto nao e json",
        b"[]",
        b"{}",
        json.dumps({"answers": {"falando_com_o_jarvis": {"noul": 7}}}).encode(),
        json.dumps({"answers": {"falando_com_o_jarvis": {"noul": 0.5}}}).encode(),
        json.dumps(
            {
                "answers": {
                    "falando_com_o_jarvis": {"noul": 0.5},
                    "pedido": {"choice": "inventada", "confidence": 1, "probabilities": {}},
                }
            }
        ).encode(),
    ],
)
def test_resposta_fora_do_formato_vira_indisponivel_e_nao_excecao_solta(corpo: bytes) -> None:
    with ServicoFalso(roteiro=Roteiro(corpo=corpo)) as servico, pytest.raises(DecisaoIndisponivel):
        classificador(servico).decidir(ESTADO, PERGUNTAS)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_servico_fora_ou_limitado_vira_indisponivel(status: int) -> None:
    with ServicoFalso(roteiro=Roteiro(status=status, corpo=b"{}")) as servico:
        with pytest.raises(DecisaoIndisponivel) as erro:
            classificador(servico).decidir(ESTADO, PERGUNTAS)
        assert not isinstance(erro.value, DecisaoRecusada)


@pytest.mark.parametrize("status", [400, 401, 402, 403])
def test_recusa_do_servico_diz_o_motivo_sem_vazar_a_chave(status: int) -> None:
    corpo = json.dumps({"error": {"message": f"Invalid key {SEGREDO}"}}).encode()
    with ServicoFalso(roteiro=Roteiro(status=status, corpo=corpo)) as servico:
        with pytest.raises(DecisaoRecusada) as erro:
            classificador(servico).decidir(ESTADO, PERGUNTAS)
        assert SEGREDO not in str(erro.value)


def test_prazo_nosso_vence_servico_lento() -> None:
    roteiro = Roteiro(corpo=resposta_boa(), atraso_antes_do_cabecalho_s=1.0)
    with ServicoFalso(roteiro=roteiro) as servico, pytest.raises(DecisaoIndisponivel):
        classificador(servico, prazo_s=0.15).decidir(ESTADO, PERGUNTAS)
