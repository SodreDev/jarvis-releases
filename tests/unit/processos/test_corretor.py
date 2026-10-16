"""Corretor em processo, com canais de verdade mas sem lançar os sete processos.

Aqui ficam as propriedades do roteamento e da fronteira de confiança; o teste que lança os
processos de verdade é `tests/integration/test_sete_processos.py`.
"""

from __future__ import annotations

from multiprocessing.connection import Client, Pipe
from pathlib import Path

import pytest

from jarvis.barramento import DonoDoEpoch, LogDeEventos, Tipo, Trust
from jarvis.barramento.corretor import ASSINATURAS, Assinante, Corretor
from jarvis.barramento.ipc import Canal, endereco
from tests.fabricas import evento


@pytest.fixture
def corretor(tmp_path: Path, sessao: str) -> Corretor:
    log = LogDeEventos(tmp_path / "eventos.sqlite")
    return Corretor(
        raiz=tmp_path,
        session_id=sessao,
        log=log,
        dono=DonoDoEpoch(session_id=sessao),
    )


def ligar(corretor: Corretor, nome: str) -> Canal:
    """Liga um assinante falso ao corretor e devolve a ponta do teste."""
    nossa, dele = Pipe(duplex=True)
    corretor.assinantes.append(Assinante(nome=nome, canal=Canal(dele, nome=nome)))
    return Canal(nossa, nome=f"teste:{nome}")


def test_roteia_so_para_quem_assinou_o_tipo(corretor: Corretor, sessao: str) -> None:
    executor = ligar(corretor, "executor")
    ui = ligar(corretor, "ui")
    memoryd = ligar(corretor, "memoryd")

    corretor.publicar(evento(Tipo.POLICY_DECISION, sessao, verdict="confirm"))
    corretor._drenar()

    assert ASSINATURAS["PolicyDecision"] == ("executor", "ui")
    for canal in (executor, ui):
        quadro = canal.receber(timeout=1.0)
        assert quadro is not None
        assert quadro["evento"]["type"] == "PolicyDecision"
    assert memoryd.receber(timeout=0.2) is None


def test_processo_nao_publica_no_lugar_de_outro(corretor: Corretor, sessao: str) -> None:
    """Um processo comprometido não se passa pelo `policy` para fabricar um `allow`."""
    s2 = Assinante(nome="s2", canal=Canal(Pipe(duplex=True)[1], nome="s2"))
    corretor.assinantes.append(s2)

    corretor._receber_publicacao(
        s2, {"publicar": evento(Tipo.POLICY_DECISION, sessao, verdict="allow").para_dict()}
    )

    assert corretor.recusados == ["s2 tentou publicar como 'policy'"]
    assert list(corretor.log.ler()) == []


def test_trust_vem_da_fronteira_do_processo_nao_do_quadro(corretor: Corretor, sessao: str) -> None:
    audio = Assinante(nome="audio-io", canal=Canal(Pipe(duplex=True)[1], nome="audio-io"))
    corretor.assinantes.append(audio)
    bruto = evento(Tipo.AUDIO_ACTIVITY, sessao, speech=True).para_dict()
    bruto["trust"] = str(Trust.SYSTEM)

    corretor._receber_publicacao(audio, {"publicar": bruto})

    registros = list(corretor.log.ler())
    assert len(registros) == 1
    assert registros[0].envelope.trust is Trust.USER_VOICE


def test_quadro_invalido_e_recusado_com_nome_de_quem_tentou(
    corretor: Corretor, sessao: str
) -> None:
    s2 = Assinante(nome="s2", canal=Canal(Pipe(duplex=True)[1], nome="s2"))
    corretor.assinantes.append(s2)

    corretor._receber_publicacao(s2, {"oi": "tudo bem?"})
    bruto = evento(Tipo.STATE_REVISION, sessao).para_dict()
    bruto["type"] = "FaleAgora"
    corretor._receber_publicacao(s2, {"publicar": bruto})

    assert len(corretor.recusados) == 2
    assert "quadro sem 'publicar'" in corretor.recusados[0]
    assert "tipo desconhecido" in corretor.recusados[1]


def test_evento_de_epoch_morto_vai_ao_log_mas_nao_e_entregue(
    corretor: Corretor, sessao: str
) -> None:
    """Aceite (c) no corretor: fala de epoch morto não chega a ninguém — e fica auditada."""
    s2 = ligar(corretor, "s2")
    corretor.dono.fala_comecou()  # epoch 0 morre, atual passa a 1

    corretor.publicar(evento(Tipo.FINAL_TRANSCRIPT, sessao, epoch=0, text="pedido antigo"))
    corretor._drenar()

    assert s2.receber(timeout=0.2) is None
    assert [r.envelope.epoch for r in corretor.log.ler()] == [0]


def test_cancel_esvazia_a_fila_do_epoch_morto(corretor: Corretor, sessao: str) -> None:
    s2 = ligar(corretor, "s2")
    corretor.publicar(evento(Tipo.PARTIAL_TRANSCRIPT, sessao, epoch=0, text="liga o"))
    cancelamento = corretor.dono.fala_comecou()
    corretor.publicar(cancelamento)

    corretor._drenar()

    recebidos = []
    while (quadro := s2.receber(timeout=0.2)) is not None:
        recebidos.append(quadro["evento"]["type"])
    assert recebidos == ["Cancel"]


# --- achado 6 da revisão F0+F1: o cursor do handshake vinha do cliente, sem conferência ----
def test_cursor_acima_do_maior_seq_repoe_do_comeco_e_fica_registrado(
    corretor: Corretor, sessao: str
) -> None:
    """Achado 6: `desde_seq` grande demais fazia a reposição entregar NADA, em silêncio.

    `_repor` filtra `registro.seq <= cursor`. Com o cursor acima de tudo que existe — cursor
    corrompido no disco do `executor`, ou um processo pedindo alto de propósito —, nenhum
    evento era reposto: o `PolicyDecision` que esperava consumo nunca chegava, o `ToolCall`
    ficava em voo para sempre e não havia linha de erro em lugar nenhum.
    """
    corretor.publicar(evento(Tipo.POLICY_DECISION, sessao, verdict="confirm"))
    nossa, dele = Pipe(duplex=True)
    corretor._novos.put(
        Assinante(nome="executor", canal=Canal(dele, nome="executor"), cursor_pedido=2**31)
    )

    corretor._admitir_novos()

    reposto = Canal(nossa, nome="teste:executor").receber(timeout=1.0)
    assert reposto is not None, "cursor impossível não pode engolir a reposição"
    assert reposto["evento"]["type"] == "PolicyDecision"
    assert any("desde_seq" in linha for linha in corretor.recusados), corretor.recusados
    assert [a.cursor for a in corretor.assinantes if a.nome == "executor"] == [1]


def test_cursor_dentro_do_log_continua_valendo(corretor: Corretor, sessao: str) -> None:
    """O clamp não pode virar "reponha sempre tudo": cursor legítimo segue respeitado."""
    corretor.publicar(evento(Tipo.POLICY_DECISION, sessao, verdict="confirm"))
    nossa, dele = Pipe(duplex=True)
    corretor._novos.put(
        Assinante(nome="executor", canal=Canal(dele, nome="executor"), cursor_pedido=1)
    )

    corretor._admitir_novos()

    assert Canal(nossa, nome="teste:executor").receber(timeout=0.2) is None
    assert corretor.recusados == []


def test_desde_seq_ilegivel_nao_derruba_a_thread_de_aceitacao(
    corretor: Corretor, sessao: str
) -> None:
    """Mesma linha do achado 6: `int(primeiro.get("desde_seq"))` levantava na thread de aceitação.

    Um handshake com `desde_seq` que não é número matava a thread — e, morta, ela não responde
    mais nenhum `accept`: nenhum processo conseguiria conectar ao barramento pelo resto da
    sessão. O erro aparecia como "ninguém conecta", não como "handshake inválido".
    """
    import threading

    from jarvis.barramento.ipc import ler_chave

    def ligar_cru(pedido: dict[str, object], onde: list[Canal]) -> None:
        """Conecta como um processo de verdade conectaria, com o `desde_seq` que eu quiser.

        Em linha própria porque o `Client` do `multiprocessing` só volta depois do desafio
        HMAC, que o servidor responde dentro do `accept`: se a aceitação estiver morta, isto
        fica pendurado — e é justamente o que a espera com prazo transforma em falha de teste
        em vez de suíte travada.
        """
        alvo, familia = endereco(corretor.raiz)
        canal = Canal(Client(alvo, family=familia, authkey=ler_chave(corretor.raiz)))
        canal.enviar(pedido)
        onde.append(canal)

    corretor.abrir()
    abertos: list[Canal] = []
    try:
        primeiro = threading.Thread(
            target=ligar_cru, args=({"registro": "ui", "desde_seq": "muito"}, abertos), daemon=True
        )
        primeiro.start()
        primeiro.join(timeout=10.0)
        assert abertos, "o handshake ilegível nem completou a conexão"
        ack = abertos[0].receber(timeout=5.0)

        assert ack is not None, "a aceitação morreu antes de responder o ack"
        assert ack["ack"] == "ui"

        # A prova de que a aceitação continua de pé: outro processo ainda entra depois dela.
        segundo = threading.Thread(
            target=ligar_cru, args=({"registro": "executor", "desde_seq": 0}, abertos), daemon=True
        )
        segundo.start()
        segundo.join(timeout=10.0)

        assert len(abertos) == 2, "ninguém mais conecta: a thread de aceitação morreu"
        assert abertos[1].receber(timeout=5.0) is not None

        corretor._admitir_novos()
        assert any("desde_seq" in linha for linha in corretor.recusados), corretor.recusados
    finally:
        for canal in abertos:
            canal.fechar()
        corretor.fechar()
