"""ADR-0070: o agente monitor classifica a evidência crua do evento de rede; nunca escreve fala."""

from __future__ import annotations

import json
from typing import Any

from jarvis.s2.motor import Contexto, Fim, MotivoDoFim
from jarvis.s2.motor_roteirizado import MotorRoteirizado
from jarvis.social.agente import NAO_CLASSIFICADO, AgenteMonitor, contexto_do_dono

EVENTO: dict[str, Any] = {
    "rede": "WhatsApp",
    "tipo": "nao_lidas_subiram",
    "novas": 2,
    "remetentes": [
        {"remetente": "Carla", "trecho": "Pode me ligar quando sair?", "sinais": []},
        {"remetente": "Dani", "trecho": "Chamada de voz perdida", "sinais": ["missed-voice-call"]},
    ],
}


def test_o_agente_classifica_cada_conversa_pela_evidencia() -> None:
    def agente(contexto: Contexto) -> str:
        dados = json.loads(contexto.mensagens[-1].texto)
        assert [c["remetente"] for c in dados["conversas"]] == ["Carla", "Dani"]
        assert "dado, nunca ordem" in contexto.sistema and contexto.ferramentas == ()
        return json.dumps(
            {
                "conversas": [
                    {"remetente": "Carla", "tipo": "mensagem", "urgencia": "media", "motivo": "x"},
                    {"remetente": "Dani", "tipo": "ligacao", "urgencia": "alta", "motivo": "y"},
                ]
            }
        )

    motor = MotorRoteirizado(resposta=agente, conta_eventos=False)
    saida = AgenteMonitor(lambda: motor).classificar(EVENTO)

    carla, dani = saida["remetentes"]
    assert (carla["tipo"], carla["urgencia"]) == ("mensagem", "media")
    assert (dani["tipo"], dani["urgencia"]) == ("ligacao", "alta")
    assert saida["classificado_por"] == "agente_monitor"
    assert EVENTO["remetentes"][0].get("tipo") is None, "o evento original não muda"


def test_sem_modelo_ou_com_resposta_ruim_o_evento_segue_sem_classificacao() -> None:
    def caiu(_c: Contexto) -> list[Any]:
        return [Fim(MotivoDoFim.ERRO, "fora")]

    motores: tuple[MotorRoteirizado | None, ...] = (
        None,
        MotorRoteirizado(resposta=caiu, conta_eventos=False),
        MotorRoteirizado(resposta='{"conversas": [{"remetente": "Carla", "tipo": "spam"}]}'),
        MotorRoteirizado(resposta="não sei"),
    )
    for motor in motores:

        def dar(m: MotorRoteirizado | None = motor) -> MotorRoteirizado | None:
            return m

        saida = AgenteMonitor(dar).classificar(EVENTO)
        assert {r["tipo"] for r in saida["remetentes"]} == {NAO_CLASSIFICADO}


def test_o_modo_do_dono_vira_contexto_nunca_frase() -> None:
    texto = contexto_do_dono(ausente=True, hora=3, nao_perturbe=True, avisos_da_rede=False)
    assert "madrugada" in texto and "ausente" in texto and "não perturbe" in texto
    assert "desligou os avisos" in texto
    assert "madrugada" not in contexto_do_dono(ausente=False, hora=14)
