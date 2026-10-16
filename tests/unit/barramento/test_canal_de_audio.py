"""ADR-0015: o canal de áudio entrega quadro inteiro, filtra epoch morto e descarta o velho."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator

import pytest

from jarvis.audio_io.quadro import BYTES_POR_QUADRO, Quadro, de_int16
from jarvis.barramento.canal_de_audio import (
    CAPACIDADE_PADRAO,
    TAMANHO_CABECALHO,
    Cabecalho,
    CanalDeAnel,
    CanalDeAudio,
    CanalDeConexao,
    CanalDeSocket,
    canal_do_ambiente,
    descrever_formato,
)

FABRICAS: dict[str, Callable[[], CanalDeAudio]] = {
    "anel": lambda: CanalDeAnel.criar(capacidade=8),
    "socket": lambda: CanalDeSocket.par(folga=8),
    "conexao": CanalDeConexao.par,
}


def quadro(indice: int, *, valor: int | None = None) -> Quadro:
    alvo = indice if valor is None else valor
    return Quadro(
        indice=indice,
        amostras=de_int16([alvo % 1000] * 320),
        ts_mono_ns=indice * 20_000_000,
    )


@pytest.fixture(params=list(FABRICAS))
def canal(request: pytest.FixtureRequest) -> Iterator[CanalDeAudio]:
    canal = FABRICAS[request.param]()
    try:
        yield canal
    finally:
        canal.fechar()


def test_as_tres_implementacoes_cumprem_o_protocolo(canal: CanalDeAudio) -> None:
    assert isinstance(canal, CanalDeAudio)
    assert canal.nome


def test_o_quadro_chega_inteiro_e_na_ordem(canal: CanalDeAudio) -> None:
    for i in range(5):
        assert canal.enviar(quadro(i), epoch=1)

    recebidos = []
    while (recebido := canal.receber()) is not None:
        recebidos.append(recebido)

    assert [c.seq for c, _ in recebidos] == [1, 2, 3, 4, 5]
    assert all(len(q.amostras) == BYTES_POR_QUADRO for _, q in recebidos)
    assert [q.valores()[0] for _, q in recebidos] == [0, 1, 2, 3, 4]


def test_o_cabecalho_carrega_epoch_ts_e_amostras(canal: CanalDeAudio) -> None:
    canal.enviar(quadro(7), epoch=3)

    recebido = canal.receber()

    assert recebido is not None
    cabecalho, _ = recebido
    assert cabecalho.epoch == 3
    assert cabecalho.ts_mono_ns == 7 * 20_000_000
    assert cabecalho.amostras == 320


def test_quadro_de_epoch_morto_e_descartado_na_leitura(canal: CanalDeAudio) -> None:
    """§3.3 regra 6, e é por isso que o `epoch` é o primeiro campo do cabeçalho."""
    canal.enviar(quadro(1), epoch=2)
    canal.enviar(quadro(2), epoch=5)

    recebido = canal.receber(epoch_minimo=5)

    assert recebido is not None
    cabecalho, _ = recebido
    assert cabecalho.epoch == 5
    assert canal.descartados == 1


def test_canal_vazio_devolve_none_em_vez_de_bloquear(canal: CanalDeAudio) -> None:
    """Áudio é tempo real: quem lê não pode ficar pendurado esperando quadro."""
    assert canal.receber() is None


def test_o_anel_descarta_o_mais_velho_quando_enche() -> None:
    """Áudio atrasado é áudio inútil: encher descarta o velho, e o descarte é contado."""
    canal = CanalDeAnel.criar(capacidade=4)
    try:
        for i in range(10):
            canal.enviar(quadro(i), epoch=1)

        recebidos = []
        while (recebido := canal.receber()) is not None:
            recebidos.append(recebido[0].seq)

        assert len(recebidos) <= 4, "o anel não guarda mais do que a capacidade"
        assert recebidos == sorted(recebidos), "o que sobra está em ordem"
        assert canal.descartados >= 6
        assert max(recebidos) == 10, "o que sobra é o mais NOVO, não o mais velho"
    finally:
        canal.fechar()


def test_o_selo_do_anel_nao_deixa_passar_quadro_escrito_pela_metade() -> None:
    """O selo nas duas pontas é o que separa "em escrita" de "pronto"."""
    import struct

    from jarvis.barramento.canal_de_audio import FORMATO_SELO, TAMANHO_SELO

    canal = CanalDeAnel.criar(capacidade=4)
    try:
        canal.enviar(quadro(1), epoch=1)
        # Simula escrita interrompida: o selo final fica com o número errado.
        inicio = canal._inicio(1)
        fim = inicio + TAMANHO_SELO + TAMANHO_CABECALHO + BYTES_POR_QUADRO
        struct.pack_into(FORMATO_SELO, canal._visao, fim, 999)

        assert canal.receber() is None, "quadro com selo divergente não pode ser consumido"
        assert canal.descartados == 1
    finally:
        canal.fechar()


def test_o_formato_do_quadro_esta_documentado_para_outra_linguagem() -> None:
    """A ADR-0014 previu `audio-io` em Rust: o formato do canal é dado, não código Python."""
    texto = descrever_formato()

    assert "epoch u32" in texto
    assert "PCM16 little endian" in texto
    assert str(BYTES_POR_QUADRO) in texto
    assert TAMANHO_CABECALHO == 20


def test_o_cabecalho_ida_e_volta_preserva_os_campos() -> None:
    original = Cabecalho(epoch=4, seq=9, ts_mono_ns=123_456_789, amostras=320)

    assert Cabecalho.desempacotar(original.empacotar()) == original


def test_o_canal_do_ambiente_entrega_o_escolhido_pela_adr() -> None:
    escolhido = canal_do_ambiente(capacidade=8)
    try:
        assert isinstance(escolhido, CanalDeAudio)
        assert escolhido.nome == "multiprocessing-connection", (
            "a ADR-0015 escolheu a Connection por portabilidade; trocar é trocar esta linha"
        )
    finally:
        escolhido.fechar()


def test_a_capacidade_padrao_da_folga_de_mais_de_um_segundo() -> None:
    assert CAPACIDADE_PADRAO * 20 >= 1000


QUADROS_ACIMA_DE_QUALQUER_BUFFER = 2000
"""2 000 quadros = 1,3 MB: passa do pipe do kernel (64 KiB) e até do teto de 1 MiB."""


def test_a_conexao_nao_bloqueia_quando_o_buffer_do_sistema_enche() -> None:
    """Achado 1 da revisão F0+F1: enviar sem perguntar por espaço trava o laço de 20 ms.

    O pipe do kernel tem ~64 KiB (≈100 quadros de 20 ms). Com o `agentd` atrasado por GC ou
    por um pico de AEC + ASR, o pipe enche e o `send_bytes` fica **pendurado dentro do tique**
    da captura: o quadro seguinte de 20 ms se perde, o SLO-1 estoura e `descartados` não acusa
    nada, porque o único descarte contado era o de pipe quebrado.
    """
    canal = CanalDeConexao.par()
    terminou = threading.Event()

    def produzir() -> None:
        for i in range(QUADROS_ACIMA_DE_QUALQUER_BUFFER):
            canal.enviar(quadro(i), epoch=1)
        terminou.set()

    linha = threading.Thread(target=produzir, name="produtor-de-quadros", daemon=True)
    linha.start()
    try:
        assert terminou.wait(timeout=5.0), "enviar bloqueou com o buffer do sistema cheio"
        assert canal.descartados > 0, "descarte por fila cheia tem de ser contado"

        seqs = []
        while (recebido := canal.receber()) is not None:
            cabecalho, recebido_quadro = recebido
            assert len(recebido_quadro.amostras) == BYTES_POR_QUADRO, "quadro cortado pela metade"
            seqs.append(cabecalho.seq)
        assert seqs, "o que couber antes de encher tem de chegar"
        assert seqs == sorted(seqs), "o que sobra está em ordem"
    finally:
        # Se bloqueou, drenar é o que solta a linha presa antes de fechar o canal.
        limite = time.monotonic() + 10.0
        while not terminou.is_set() and time.monotonic() < limite:
            if canal.receber() is None:
                time.sleep(0.01)
        linha.join(timeout=5.0)
        canal.fechar()
