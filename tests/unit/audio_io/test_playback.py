"""Cartão F1-03, aceites (a), (b) e (c): cancelar é no mesmo tick e `played_ms` é real."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from jarvis.audio_io import (
    BYTES_POR_QUADRO,
    TAXA_PADRAO,
    Cancelamento,
    FilaDePlayback,
    Pedaco,
    SumidouroDeAudio,
    SumidouroEmMemoria,
    em_pedacos,
    gerar,
)
from jarvis.barramento.envelope import Prioridade, Tipo

SESSAO = "0193f0a0-0000-7000-8000-000000000000"


def audio_de(ms: float) -> bytes:
    """Áudio de TTS falso com a duração pedida (o gerador do F1-01 dá 1,7 s por vez)."""
    alvo = int(TAXA_PADRAO * ms / 1000) * 2
    bruto = gerar(semente=5)
    return (bruto * (alvo // len(bruto) + 1))[:alvo]


@dataclass(slots=True)
class SumidouroSaturado:
    """Dispositivo que aceita só metade do quadro — é o caso que `played_ms` não pode mentir."""

    device_id: str = "saturado:0"
    taxa: int = TAXA_PADRAO
    amostras_consumidas: int = 0
    saida: bytearray = field(default_factory=bytearray, repr=False)

    def abrir(self) -> None:
        return None

    def escrever(self, amostras: bytes) -> int:
        metade = (len(amostras) // 4) * 2
        self.saida.extend(amostras[:metade])
        self.amostras_consumidas += metade // 2
        return metade // 2

    def limpar(self) -> int:
        return 0

    def fechar(self) -> None:
        return None


def montar(sumidouro: SumidouroDeAudio | None = None) -> tuple[FilaDePlayback, SumidouroDeAudio]:
    destino = sumidouro if sumidouro is not None else SumidouroEmMemoria()
    return FilaDePlayback(sumidouro=destino, session_id=SESSAO), destino


def test_cancelar_no_meio_do_pedaco_deixa_played_ms_na_amostra_consumida() -> None:
    """Aceite (a): e o resto do pedaço não aparece em nenhum evento."""
    fila, sumidouro = montar()
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=audio_de(1000)))

    eventos = [e for _ in range(10) for e in fila.tick()]  # 200 ms tocados
    assert eventos == []  # pedaço não terminou: nenhum fato ainda

    cancelamento = fila.cancelar(reason="barge_in")

    assert cancelamento.played_ms == pytest.approx(200, abs=20)
    assert sumidouro.amostras_consumidas == 10 * 320
    assert len(cancelamento.eventos) == 1
    progresso = cancelamento.eventos[0]
    assert progresso.type is Tipo.PLAYBACK_PROGRESS
    assert progresso.payload["played_ms"] == pytest.approx(200, abs=20)
    assert cancelamento.amostras_descartadas == pytest.approx(TAXA_PADRAO * 0.8, abs=320)


def test_fila_de_2_segundos_e_esvaziada_no_mesmo_tick_do_cancel() -> None:
    """Aceite (b): §3.3 regra 2 — esvaziar, não "parar de enfileirar"."""
    fila, sumidouro = montar()
    for pedaco in em_pedacos(audio_de(2000), chunk_id="k", epoch=0, ms_por_pedaco=200.0):
        assert fila.enfileirar(pedaco)
    assert fila.pedacos_na_fila == 10
    fila.tick()
    consumidas_antes = sumidouro.amostras_consumidas

    cancelamento = fila.cancelar(reason="barge_in")

    assert fila.pedacos_na_fila == 0
    assert fila.amostras_enfileiradas == 0
    assert cancelamento.pedacos_descartados == 10
    assert cancelamento.amostras_descartadas == pytest.approx(TAXA_PADRAO * 2, abs=320)
    assert fila.tick() == []  # nada mais toca
    assert sumidouro.amostras_consumidas == consumidas_antes


def test_pedaco_com_epoch_velho_e_descartado_e_nunca_toca() -> None:
    """Aceite (c): §3.3 regra 6."""
    fila, sumidouro = montar()
    fila.epoch_atual = 3

    assert not fila.enfileirar(Pedaco(chunk_id="velho", epoch=2, amostras=audio_de(200)))
    assert fila.descartados_por_epoch == 1
    assert fila.tick() == []
    assert sumidouro.amostras_consumidas == 0

    assert fila.enfileirar(Pedaco(chunk_id="novo", epoch=3, amostras=audio_de(200)))
    fila.tick()
    assert sumidouro.amostras_consumidas == 320


def test_pedaco_enfileirado_antes_do_epoch_novo_nao_toca_depois_dele() -> None:
    """O descarte vale também para o que já estava na fila quando o epoch virou."""
    fila, sumidouro = montar()
    for pedaco in em_pedacos(audio_de(600), chunk_id="k", epoch=0, ms_por_pedaco=200.0):
        fila.enfileirar(pedaco)

    fila.cancelar(reason="barge_in", epoch_novo=1)
    fila.enfileirar(Pedaco(chunk_id="atrasado", epoch=0, amostras=audio_de(200)))

    assert fila.tick() == []
    assert sumidouro.amostras_consumidas == 0
    assert fila.descartados_por_epoch == 1


def test_played_ms_vem_do_sumidouro_e_nao_do_que_foi_oferecido() -> None:
    """Dispositivo que aceita metade do quadro: o progresso acompanha o que saiu."""
    fila, sumidouro = montar(SumidouroSaturado())
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=audio_de(200)))

    for _ in range(10):
        fila.tick()

    # 10 ticks × meio quadro = 100 ms de áudio consumido, não 200 ms.
    assert sumidouro.amostras_consumidas == 10 * 160
    assert fila.played_ms == pytest.approx(100, abs=10)
    assert fila.amostras_enfileiradas == pytest.approx(TAXA_PADRAO * 0.1, abs=160)


def test_fim_de_pedaco_publica_o_fato_uma_vez_so() -> None:
    fila, _ = montar()
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=audio_de(100)))

    eventos = [e for _ in range(6) for e in fila.tick()]

    assert len(eventos) == 1
    assert eventos[0].payload == {"chunk_id": "k-1", "played_ms": 100, "epoch": 0}
    assert eventos[0].priority is Prioridade.P1


def test_progresso_periodico_existe_mas_e_opcional() -> None:
    fila, _ = montar()
    fila.intervalo_de_progresso_ms = 40.0
    fila.enfileirar(Pedaco(chunk_id="k-1", epoch=0, amostras=audio_de(200)))

    eventos = [e for _ in range(10) for e in fila.tick()]

    assert len(eventos) > 1
    assert all(e.payload["chunk_id"] == "k-1" for e in eventos)
    assert [e.payload["played_ms"] for e in eventos] == sorted(
        e.payload["played_ms"] for e in eventos
    )


def test_motivo_de_cancelamento_fora_da_secao_3_2_e_erro() -> None:
    fila, _ = montar()

    with pytest.raises(ValueError, match="não é um dos da"):
        fila.cancelar(reason="porque_eu_quis")


def test_pedacos_cobrem_o_audio_inteiro_sem_sobra() -> None:
    amostras = audio_de(950)
    pedacos = em_pedacos(amostras, chunk_id="k", epoch=2, ms_por_pedaco=200.0)

    assert b"".join(p.amostras for p in pedacos) == amostras
    assert all(p.epoch == 2 for p in pedacos)
    assert [p.chunk_id for p in pedacos][:2] == ["k-1", "k-2"]
    assert len(pedacos[0].amostras) == BYTES_POR_QUADRO * 10


def test_cancelamento_sem_nada_tocando_nao_inventa_evento() -> None:
    fila, _ = montar()

    cancelamento = fila.cancelar(reason="privacy")

    assert cancelamento == Cancelamento()
