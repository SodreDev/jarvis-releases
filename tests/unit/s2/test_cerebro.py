"""ADR-0025, fatia mínima: um cérebro, a conversa só com o tocado, stream e cancelamento."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

import pytest

from jarvis.barramento import ErroDeContrato, Tipo, validar_bruto
from jarvis.fatiador import fatiar_tudo
from jarvis.s2.cerebro import Cerebro, Conversa, envelope_do_pedaco
from jarvis.s2.motor import (
    PRAZO_DE_CANCELAMENTO_S,
    Contexto,
    Delta,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Pensar,
    Texto,
)
from jarvis.s2.motor_roteirizado import MotorRoteirizado, em_deltas
from jarvis.voz.interface import Cancelado

RESPOSTA = (
    "Depois de quinta vem sexta-feira, e depois de sexta vem o sábado, que é o dia em que "
    "quase todo mundo descansa um pouco mais. Domingo fecha a semana."
)


def _cerebro(**mudancas: Any) -> tuple[Cerebro, MotorRoteirizado]:
    motor = MotorRoteirizado(resposta=RESPOSTA, **mudancas)
    return Cerebro(motor=motor), motor


def test_os_motores_cumprem_a_interface() -> None:
    assert isinstance(MotorRoteirizado(), MotorDeConversa)


def test_cada_pedaco_e_um_response_chunk_valido_na_borda(sessao: str) -> None:
    cerebro, _ = _cerebro()
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.responder("e depois de quinta?", epoch=3, publicar=publicados.append)

    assert resposta.fim is MotivoDoFim.CONCLUIDO
    assert [p["seq"] for p in publicados] == list(range(len(publicados)))
    assert [p["last"] for p in publicados] == [False] * (len(publicados) - 1) + [True]
    assert all("end_reason" not in p for p in publicados[:-1])
    assert publicados[-1]["end_reason"] == "concluido"
    for payload in publicados:
        envelope = envelope_do_pedaco(sessao, payload)
        assert envelope.type is Tipo.RESPONSE_CHUNK
        assert envelope.epoch == 3
    assert " ".join(p["text"] for p in publicados if p["text"]) == " ".join(RESPOSTA.split())


def test_um_pedaco_por_fronteira_e_nao_um_por_token() -> None:
    """Regra 7: o motor manda dezenas de deltas; o barramento vê poucos pedaços."""
    cerebro, _ = _cerebro(caracteres_por_delta=3)
    publicados: list[dict[str, Any]] = []
    cerebro.responder("e depois?", epoch=0, publicar=publicados.append)

    assert len(em_deltas(RESPOSTA, caracteres=3)) > 40
    assert len(publicados) <= 10


@pytest.mark.parametrize(
    ("campo", "valor", "erro"),
    [
        ("epoch", 9, "difere do envelope"),
        ("boundary", "token", "boundary"),
        ("end_reason", "cancelado", "end_reason"),
        ("allowed_tools", ["files.delete"], "allowed_tools"),
    ],
)
def test_a_borda_recusa_pedaco_fora_do_contrato(
    campo: str, valor: object, erro: str, sessao: str
) -> None:
    bruto = envelope_do_pedaco(
        sessao,
        {
            "response_id": "r-1",
            "turn_id": "t-1",
            "epoch": 0,
            "seq": 0,
            "text": "Oi",
            "boundary": "fim",
            "last": True,
        },
    ).para_dict()
    bruto["payload"][campo] = valor

    with pytest.raises(ErroDeContrato, match=erro):
        validar_bruto(bruto)


def test_so_o_s2_publica_pedaco_de_fala(sessao: str) -> None:
    bruto = envelope_do_pedaco(
        sessao,
        {
            "response_id": "r",
            "turn_id": "t",
            "epoch": 0,
            "seq": 0,
            "text": "",
            "boundary": "fim",
            "last": True,
        },
    ).para_dict()
    bruto["source"] = "agentd"
    with pytest.raises(ErroDeContrato, match="só pode vir de"):
        validar_bruto(bruto)


# --- regra 2 e 3: a conversa é nossa e só tem o tocado -----------------------------------
def test_o_motor_recebe_a_conversa_inteira_a_cada_pedido() -> None:
    cerebro, motor = _cerebro()
    primeira = cerebro.responder("que dia vem depois de quinta?", epoch=0, publicar=lambda _: None)
    cerebro.ouvido(primeira.response_id, "Depois de quinta vem sexta-feira", interrompida=True)
    cerebro.responder("e o outro?", epoch=1, publicar=lambda _: None)

    segundo = motor.pedidos[1]
    assert [m.papel for m in segundo.mensagens] == ["dono", "jarvis", "dono"]
    assert segundo.mensagens[1] == Mensagem("jarvis", "Depois de quinta vem sexta-feira", True)
    assert "[interrompido pelo dono aqui]" in segundo.como_texto()
    assert "sábado" not in segundo.como_texto(), "o gerado e não tocado voltou ao modelo (P4)"


def test_resposta_sem_tocado_confirmado_nao_existe_para_o_modelo() -> None:
    cerebro, motor = _cerebro()
    cerebro.responder("oi", epoch=0, publicar=lambda _: None)
    cerebro.responder("oi de novo", epoch=1, publicar=lambda _: None)

    assert [m.papel for m in motor.pedidos[1].mensagens] == ["dono", "dono"]


def test_ouvido_de_resposta_velha_e_ignorado() -> None:
    cerebro, _ = _cerebro()
    velha = cerebro.responder("oi", epoch=0, publicar=lambda _: None)
    cerebro.responder("outra coisa", epoch=1, publicar=lambda _: None)
    cerebro.ouvido(velha.response_id, "Depois de quinta", interrompida=False)

    assert all(m.papel == "dono" for m in cerebro.conversa.turnos)


def test_trocar_o_motor_entre_turnos_nao_perde_a_conversa() -> None:
    """Aceite (h): a conversa sobrevive à troca de motor, porque mora no cérebro."""
    cerebro, _ = _cerebro()
    primeira = cerebro.responder("me fala dois dias", epoch=0, publicar=lambda _: None)
    cerebro.ouvido(primeira.response_id, "Sexta e sábado.", interrompida=False)

    outro = MotorRoteirizado(resposta=lambda ctx: f"Você perguntou: {ctx.mensagens[0].texto}")
    cerebro.motor = outro
    publicados: list[dict[str, Any]] = []
    cerebro.responder("e o outro?", epoch=1, publicar=publicados.append)

    assert "me fala dois dias" in " ".join(p["text"] for p in publicados)
    assert outro.pedidos[0].mensagens[1].texto == "Sexta e sábado."


def test_o_orcamento_de_turnos_e_fixo() -> None:
    conversa = Conversa(maximo=4)
    conversa.turnos += [Mensagem("dono", str(i)) for i in range(10)]
    assert [m.texto for m in conversa.contexto().mensagens] == ["6", "7", "8", "9"]


def test_contexto_que_nao_termina_no_dono_e_recusado() -> None:
    with pytest.raises(ValueError, match="turno do dono"):
        Contexto(sistema="", mensagens=(Mensagem("jarvis", "oi"),))


# --- regra 4: pensar não vira fala ----------------------------------------------------------
class _MotorQuePedePensar:
    nome = "pede-pensar"
    onde = MotorRoteirizado().onde

    def gerar(
        self, contexto: Contexto, modo: Modo, cancelado: Cancelado
    ) -> Generator[Delta, None, None]:
        del contexto, cancelado
        if modo is Modo.RAPIDO:
            yield Pensar("conta difícil")
            yield Fim(MotivoDoFim.CONCLUIDO)
            return
        yield Texto("Cinquenta e um. ")
        yield Fim(MotivoDoFim.CONCLUIDO)


def test_o_sinal_de_pensar_nao_publica_nada_e_fica_na_resposta() -> None:
    cerebro = Cerebro(motor=_MotorQuePedePensar())
    publicados: list[dict[str, Any]] = []

    resposta = cerebro.responder("dezessete vezes três?", epoch=0, publicar=publicados.append)

    assert resposta.pediu_pensar
    assert [p["text"] for p in publicados] == [""], "só o fim vazio, nenhuma fala"
    depois = cerebro.responder(
        "dezessete vezes três?", epoch=0, publicar=publicados.append, modo=Modo.PENSAR
    )
    assert depois.gerado == "Cinquenta e um. "


# --- regra 9: cancelamento ---------------------------------------------------------------
@pytest.mark.parametrize("depois_de", range(1, len(fatiar_tudo(RESPOSTA))))
def test_cancelado_no_meio_nada_mais_daquele_epoch_e_publicado(depois_de: int) -> None:
    cerebro, _ = _cerebro()
    publicados: list[dict[str, Any]] = []
    cancelou = threading.Event()

    def publicar(payload: dict[str, Any]) -> None:
        assert not cancelou.is_set(), "pedaço publicado depois do cancelamento"
        publicados.append(payload)
        if len(publicados) == depois_de:
            cancelou.set()

    resposta = cerebro.responder("e depois?", epoch=0, publicar=publicar, cancelado=cancelou.is_set)

    assert resposta.cancelada
    assert len(publicados) == depois_de
    assert not any(p["last"] for p in publicados), "resposta cancelada não publica o último"
    assert resposta.deltas_depois_do_cancelamento == 0


def test_cancelado_enquanto_o_motor_espera_o_primeiro_token_volta_no_prazo() -> None:
    """Regra 9 (c): do cancelamento ao motor parado em até 50 ms, mesmo esperando a rede."""
    cerebro, _ = _cerebro(primeiro_atraso_s=5.0)
    cancelou = threading.Event()
    marcas: dict[str, float] = {}

    def cancelar_depois() -> None:
        time.sleep(0.05)
        marcas["cancelou"] = time.monotonic()
        cancelou.set()

    threading.Thread(target=cancelar_depois, daemon=True).start()
    publicados: list[dict[str, Any]] = []
    resposta = cerebro.responder(
        "e depois?", epoch=0, publicar=publicados.append, cancelado=cancelou.is_set
    )
    voltou = time.monotonic()

    assert resposta.cancelada
    assert publicados == []
    assert (voltou - marcas["cancelou"]) <= PRAZO_DE_CANCELAMENTO_S


# --- ADR-0026, M1: o histórico persistente só com o tocado -------------------------------
def test_com_historico_o_livro_guarda_o_dono_e_so_o_tocado_do_jarvis() -> None:
    from jarvis.memoryd.cofre import CofreFernet, nova_chave
    from jarvis.memoryd.indice import IndiceEmMemoria
    from jarvis.memoryd.livro import LivroDeMemoria

    livro = LivroDeMemoria.abrir(
        ":memory:", cofre=CofreFernet(nova_chave()), indice=IndiceEmMemoria()
    )
    cerebro = Cerebro(motor=MotorRoteirizado(resposta=RESPOSTA), livro=livro, session_id="s-1")
    primeira = cerebro.responder("e depois de quinta?", epoch=0, publicar=lambda _: None)
    assert cerebro.proveniencia.turno is not None
    cerebro.ouvido(primeira.response_id, "Depois de quinta", interrompida=True, played_ms=640)
    sem_tocar = cerebro.responder("outra coisa", epoch=1, publicar=lambda _: None)
    cerebro.responder("e a última?", epoch=2, publicar=lambda _: None)
    cerebro.ouvido(sem_tocar.response_id, "atrasado", interrompida=False, played_ms=10)

    linhas = livro.con.execute(
        "SELECT papel, played_ms, interrompida FROM turno ORDER BY ordem"
    ).fetchall()
    assert [(r["papel"], r["played_ms"], r["interrompida"]) for r in linhas] == [
        ("dono", None, 0),
        ("jarvis", 640, 1),
        ("dono", None, 0),
        ("dono", None, 0),
    ]
    jarvis = livro.ler_mensagem(
        str(livro.con.execute("SELECT episode_id FROM turno WHERE papel='jarvis'").fetchone()[0])
    )
    assert [t["texto"] for t in jarvis if t["alvo"]] == ["Depois de quinta"]
    assert "sábado" not in str(livro.buscar_historico("sábado")), "gerado e não tocado"
