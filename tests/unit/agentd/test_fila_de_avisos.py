"""ADR-0025, regras 11–15 e D22: a fila de avisos do `agentd`."""

from __future__ import annotations

import pytest

from jarvis.agentd.fila_de_avisos import PISO_LIVRE_S, TETO_DE_FALA_S, Entrega, FilaDeAvisos
from jarvis.barramento import Envelope, Tipo, Trust, prioridade_canonica, validar
from jarvis.gui.componentes import componente, validar_dados
from tests.fabricas import evento

SESSAO = "01a1c000-0000-7000-8000-000000000004"


def _notificacao(
    notif_id: str,
    tipo: str = "concluida",
    *,
    source: str = "executor",
    trust: Trust = Trust.SYSTEM,
    origem: str = "tarefa · teste",
    resumo: str = "",
) -> Envelope:
    payload = {
        "notif_id": notif_id,
        "origem": origem,
        "tipo": tipo,
        "resumo": resumo or f"resumo de {notif_id}",
    }
    return validar(
        Envelope(
            session_id=SESSAO,
            epoch=0,
            source=source,
            trust=trust,
            priority=prioridade_canonica(Tipo.NOTIFICATION, payload),
            type=Tipo.NOTIFICATION,
            payload=payload,
        )
    )


@pytest.fixture
def fila() -> FilaDeAvisos:
    return FilaDeAvisos(session_id=SESSAO)


def test_nunca_libera_com_o_dono_falando_nem_com_o_tts_tocando(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.dono_falando(True, agora=1.0)
    assert fila.liberar(agora=10.0) is None
    fila.dono_falando(False, agora=10.0)
    fila.tts_tocando(True, agora=10.5)
    assert fila.liberar(agora=30.0) is None
    fila.tts_tocando(False, agora=30.0)
    assert fila.liberar(agora=30.0 + PISO_LIVRE_S - 0.1) is None, "piso livre só após 1,5 s"
    liberacao = fila.liberar(agora=30.0 + PISO_LIVRE_S)
    assert liberacao is not None
    assert liberacao.type is Tipo.NOTIFICATION_RELEASE
    assert liberacao.payload == {"notif_ids": ["n1"], "motivo": "piso_livre"}


def test_audio_activity_tambem_ocupa_o_piso(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.observar(evento(Tipo.AUDIO_ACTIVITY, SESSAO, speech=True), agora=1.0)
    assert fila.liberar(agora=5.0) is None
    fila.observar(evento(Tipo.AUDIO_ACTIVITY, SESSAO, speech=False), agora=5.0)
    assert fila.liberar(agora=6.6) is not None


def test_um_por_vez_e_no_maximo_um_falado_a_cada_dois_minutos(fila: FilaDeAvisos) -> None:
    for i in range(3):
        fila.receber(_notificacao(f"n{i}"), agora=float(i))
    primeira = fila.liberar(agora=10.0)
    assert primeira is not None
    assert primeira.payload["notif_ids"] == ["n0"]
    assert fila.liberar(agora=11.0) is None, "o primeiro ainda não tocou nem foi cortado"
    fila.tocou(["n0"], agora=12.0)
    assert fila.liberar(agora=12.0 + TETO_DE_FALA_S - 1) is None
    segunda = fila.liberar(agora=12.0 + TETO_DE_FALA_S)
    assert segunda is not None
    assert segunda.payload["notif_ids"] == ["n1"]


def test_pedido_de_decisao_sai_primeiro(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("velho"), agora=0.0)
    fila.receber(_notificacao("decidir", tipo="precisa_decisao"), agora=5.0)
    liberacao = fila.liberar(agora=10.0)
    assert liberacao is not None
    assert liberacao.payload["notif_ids"] == ["decidir"]


def test_com_a_mensagem_do_dono_vao_todos_e_o_teto_nao_segura(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n0"), agora=0.0)
    fila.liberar(agora=5.0)
    fila.tocou(["n0"], agora=6.0)
    fila.receber(_notificacao("n1"), agora=7.0)
    fila.receber(_notificacao("n2"), agora=8.0)

    liberacao = fila.mensagem_do_dono("t-9", agora=9.0)
    assert liberacao is not None
    assert liberacao.payload == {
        "notif_ids": ["n1", "n2"],
        "motivo": "mensagem_do_dono",
        "turn_id": "t-9",
    }
    assert fila.mensagem_do_dono("t-10", agora=10.0) is None


def test_cortado_volta_para_a_fila_e_tocado_nao_volta(fila: FilaDeAvisos) -> None:
    """Aceites (e) e regra 15: entregue é o que tocou."""
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.liberar(agora=5.0)
    fila.cortado(["n1"])
    assert fila.avisos["n1"].pendente
    assert fila.mensagem_do_dono("t", agora=6.0) is not None
    fila.tocou(["n1"], agora=7.0)
    assert fila.avisos["n1"].entrega is Entrega.FALADO
    assert fila.mensagem_do_dono("t2", agora=300.0) is None


def test_nao_perturbe_so_card_e_privacidade_nada_em_voz(fila: FilaDeAvisos) -> None:
    """Aceite (f): pedido de decisão com não perturbe — card sempre, voz nunca."""
    fila.nao_perturbe = True
    fila.receber(_notificacao("d", tipo="precisa_decisao"), agora=0.0)
    assert fila.liberar(agora=60.0) is None
    assert fila.mensagem_do_dono("t", agora=61.0) is None
    assert fila.dados_do_card(agora=61.0)["avisos"][0]["entrega"] == "so_card"

    privada = FilaDeAvisos(session_id=SESSAO, privacidade=True)
    privada.receber(_notificacao("n"), agora=0.0)
    assert privada.liberar(agora=60.0) is None
    assert privada.mensagem_do_dono("t", agora=61.0) is None


def test_calado_continua_no_card(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.liberar(agora=5.0)
    fila.decidido("n1", Entrega.CALADO)
    assert fila.dados_do_card(agora=6.0)["avisos"][0]["entrega"] == "calado"
    assert fila.liberar(agora=600.0) is None


def test_notificacao_repetida_nao_duplica(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.receber(_notificacao("n1"), agora=1.0)
    assert len(fila.avisos) == 1


def test_o_card_sai_no_contrato_que_a_janela_valida(fila: FilaDeAvisos) -> None:
    fila.receber(_notificacao("n1"), agora=0.0)
    fila.receber(
        _notificacao(
            "n2",
            "precisa_decisao",
            source="mcp:arquivos",
            trust=Trust.THIRD_PARTY,
            origem="mcp · arquivos",
            resumo="o servidor pede um formulário",
        ),
        agora=100.0,
    )
    dados = fila.dados_do_card(agora=400.0)

    assert validar_dados(componente("notificacoes"), dados) == dados
    assert [a["confianca"] for a in dados["avisos"]] == ["terceiros", "propria"]
    assert [a["instante"] for a in dados["avisos"]] == ["há 5 min", "há 6 min"]


def test_so_notification_entra_na_fila(fila: FilaDeAvisos) -> None:
    with pytest.raises(ValueError, match="Notification"):
        fila.receber(evento(Tipo.CANCEL, SESSAO), agora=0.0)
