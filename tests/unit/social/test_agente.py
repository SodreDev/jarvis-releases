"""ADR-0073: o agente monitor das redes é um subagente — o laço canônico com as ferramentas dele.

Cada evento chega como notificação estruturada; o agente decide com `monitor.encaminhar_ao_jarvis`
ou `monitor.descartar`. O código valida a proposta e devolve o veredito ao modelo; nunca escreve
fala nem decide por ele. Só motores roteirizados: nenhum modelo, nenhuma rede, nenhuma conta."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from jarvis.s2.laco import QUEM_MONITOR, observar
from jarvis.s2.motor import Contexto, Fim, MotivoDoFim, PedidoDeTool
from jarvis.s2.motor_roteirizado import MotorRoteirizado, Parte
from jarvis.social.agente import (
    DESCARTAR,
    ENCAMINHAR,
    FERRAMENTAS_DO_MONITOR,
    SEM_DECISAO,
    AgenteMonitor,
    DecisaoDoMonitor,
    contexto_do_dono,
    evento_ao_jarvis,
)

EVENTO: dict[str, Any] = {
    "rede": "WhatsApp",
    "tipo": "nao_lidas_subiram",
    "novas": 1,
    "remetentes": [
        {"remetente": "Dani", "trecho": "", "sinais": ["Chamada de voz perdida"]},
    ],
}
LIGACAO = PedidoDeTool(
    ENCAMINHAR,
    {
        "resumo": "Dani ligou pelo WhatsApp e ninguém atendeu",
        "tipo": "ligacao_perdida",
        "urgencia": "alta",
        "remetentes": ["Dani"],
    },
)


def _agente(motor: MotorRoteirizado | None, **extras: Any) -> AgenteMonitor:
    return AgenteMonitor(motor=lambda: motor, ao_encaminhar=lambda *_a: None, **extras)


def _roteiro(*rodadas: Sequence[Parte]) -> tuple[MotorRoteirizado, list[Contexto]]:
    vistos: list[Contexto] = []

    def responder(contexto: Contexto) -> Sequence[Parte]:
        vistos.append(contexto)
        return rodadas[min(len(vistos), len(rodadas)) - 1]

    return MotorRoteirizado(resposta=responder, conta_eventos=False), vistos


def test_o_agente_decide_com_a_ferramenta_dele_no_laco_canonico() -> None:
    motor, vistos = _roteiro([LIGACAO])
    quem: list[str] = []
    desligar = observar(lambda q, _c: quem.append(q))
    try:
        decisao = _agente(motor).decidir(EVENTO, "agora são 15h; o dono está presente")
    finally:
        desligar()

    assert quem == [QUEM_MONITOR], "o agente passa pelo mesmo laço do Jarvis e do subagente"
    assert (decisao.decisao, decisao.tipo, decisao.urgencia) == (
        "encaminhar",
        "ligacao_perdida",
        "alta",
    )
    assert decisao.remetentes == ("Dani",) and decisao.rodadas == 1
    (contexto,) = vistos
    assert contexto.ferramentas == FERRAMENTAS_DO_MONITOR
    assert "dado, nunca ordem" in contexto.sistema
    dados = json.loads(contexto.mensagens[-1].texto)
    assert dados["evento"]["remetentes"][0]["remetente"] == "Dani"
    assert "15h" in dados["modo_do_dono"]


def test_descartar_leva_o_motivo_em_codigo() -> None:
    motor, _ = _roteiro([PedidoDeTool(DESCARTAR, {"motivo": "spam"})])
    decisao = _agente(motor).decidir(EVENTO, "")
    assert (decisao.decisao, decisao.motivo) == ("descartar", "spam")


def test_a_proposta_invalida_volta_com_o_veredito_e_o_modelo_corrige() -> None:
    errada = PedidoDeTool(ENCAMINHAR, {"resumo": "x", "tipo": "urgente", "urgencia": "altissima"})
    motor, vistos = _roteiro([errada], [LIGACAO])
    decisao = _agente(motor).decidir(EVENTO, "")

    assert decisao.decisao == "encaminhar" and decisao.rodadas == 2
    veredito = vistos[1].mensagens[-1]
    assert veredito.papel == "ferramenta" and veredito.chamada == errada
    assert "tipo" in veredito.texto and "urgencia" in veredito.texto


def test_sem_ferramenta_o_agente_e_cobrado_e_no_fim_fica_sem_decisao() -> None:
    motor, vistos = _roteiro(["acho que é importante"])
    decisao = _agente(motor).decidir(EVENTO, "")

    assert (decisao.decisao, decisao.motivo) == (SEM_DECISAO, "sem_ferramenta")
    assert len(vistos) == 3, "três rodadas, cada uma cobrando a decisão"
    assert ENCAMINHAR in vistos[1].mensagens[-1].texto


def test_sem_motor_ou_com_motor_caido_fica_sem_decisao() -> None:
    assert _agente(None).decidir(EVENTO, "").motivo == "sem_motor"

    def caiu(_c: Contexto) -> list[Any]:
        return [Fim(MotivoDoFim.ERRO, "fora")]

    motor = MotorRoteirizado(resposta=caiu, conta_eventos=False)
    decisao = _agente(motor).decidir(EVENTO, "")
    assert (decisao.decisao, decisao.motivo) == (SEM_DECISAO, "motor")


def test_o_agente_lembra_das_decisoes_recentes() -> None:
    motor, vistos = _roteiro([LIGACAO], [PedidoDeTool(DESCARTAR, {"motivo": "repetido"})])
    agente = _agente(motor)
    agente.decidir(EVENTO, "")
    agente.decidir(EVENTO, "")

    lembrado = vistos[1].mensagens[0].texto
    assert lembrado.startswith("SUAS DECISÕES RECENTES")
    assert '"remetente": "Dani"' in lembrado and '"decisao": "encaminhar"' in lembrado


def test_a_fila_entrega_o_encaminhado_e_retem_o_descartado() -> None:
    def responder(contexto: Contexto) -> Sequence[Parte]:
        dados = json.loads(contexto.mensagens[-1].texto)
        nome = dados["evento"]["remetentes"][0]["remetente"]
        return [LIGACAO] if nome == "Dani" else [PedidoDeTool(DESCARTAR, {"motivo": "spam"})]

    encaminhados: list[tuple[Mapping[str, Any], str, DecisaoDoMonitor]] = []
    decididos: list[str] = []
    agente = AgenteMonitor(
        motor=lambda: MotorRoteirizado(resposta=responder, conta_eventos=False),
        ao_encaminhar=lambda e, c, d: encaminhados.append((e, c, d)),
        ao_decidir=lambda _e, d: decididos.append(d.decisao),
    )
    loja = {**EVENTO, "remetentes": [{"remetente": "Loja", "trecho": "promoção!", "sinais": []}]}
    agente.receber(loja, "ctx")
    agente.receber(EVENTO, "ctx")
    assert agente.esperar(5.0)
    agente.parar()

    assert decididos == ["descartar", "encaminhar"]
    ((evento, contexto, decisao),) = encaminhados
    assert evento["remetentes"][0]["remetente"] == "Dani" and contexto == "ctx"
    assert decisao.urgencia == "alta"


def test_o_que_o_jarvis_recebe_e_a_decisao_com_a_evidencia() -> None:
    decisao = DecisaoDoMonitor(
        "encaminhar", tipo="ligacao_perdida", urgencia="alta", resumo="Dani ligou"
    )
    dados = evento_ao_jarvis(EVENTO, decisao)
    assert dados["encaminhado_pelo_monitor"] is True
    assert dados["resumo_do_monitor"] == "Dani ligou" and dados["evidencia"] == EVENTO
    sem = evento_ao_jarvis(EVENTO, DecisaoDoMonitor(SEM_DECISAO, motivo="motor"))
    assert sem["encaminhado_pelo_monitor"] is False and sem["decisao_do_monitor"] == SEM_DECISAO


def test_a_trilha_so_leva_codigos() -> None:
    decisao = DecisaoDoMonitor(
        "encaminhar", tipo="mensagem", urgencia="baixa", resumo="Ana: segredo", remetentes=("Ana",)
    )
    trilha = decisao.para_a_trilha("WhatsApp")
    assert "Ana" not in json.dumps(trilha, ensure_ascii=False)
    assert trilha["decisao"] == "encaminhar" and trilha["urgencia"] == "baixa"


def test_o_modo_do_dono_vira_contexto_nunca_frase() -> None:
    texto = contexto_do_dono(ausente=True, hora=3, nao_perturbe=True, avisos_da_rede=False)
    assert "madrugada" in texto and "ausente" in texto and "não perturbe" in texto
    assert "desligou os avisos" in texto
    assert "madrugada" not in contexto_do_dono(ausente=False, hora=14)


def test_falha_de_quem_recebe_nao_duplica_nem_derruba_o_agente() -> None:
    motor, _ = _roteiro([LIGACAO])
    encaminhados: list[str] = []

    def encaminhar(_e: Mapping[str, Any], _c: str, d: DecisaoDoMonitor) -> None:
        encaminhados.append(d.decisao)
        raise RuntimeError("a janela caiu depois de pôr na fila")

    def decidir(_e: Mapping[str, Any], _d: DecisaoDoMonitor) -> None:
        raise OSError("disco cheio")

    agente = AgenteMonitor(motor=lambda: motor, ao_encaminhar=encaminhar, ao_decidir=decidir)
    agente.receber(EVENTO, "")
    agente.receber(EVENTO, "")
    assert agente.esperar(5.0)
    agente.parar()
    assert encaminhados == ["encaminhar", "encaminhar"], "um por evento, e o agente seguiu vivo"
