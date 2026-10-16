"""Cartão F1-01, aceite (a) e (c): fonte sem hardware, tempo do relógio injetado."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from jarvis.audio_io import (
    BYTES_POR_QUADRO,
    TAXA_PADRAO,
    VARIAVEL_CI,
    DispositivoIndisponivel,
    DispositivoProibidoEmCI,
    FonteDeArquivo,
    FonteDeAudio,
    FonteDeDispositivo,
    FonteSintetica,
    FormatoNaoSuportado,
    SumidouroDeArquivo,
    gerar,
)
from jarvis.relogio import RelogioFalso


def escrever_wav(
    caminho: Path, amostras: bytes, *, taxa: int = TAXA_PADRAO, canais: int = 1, largura: int = 2
) -> Path:
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(canais)
        arquivo.setsampwidth(largura)
        arquivo.setframerate(taxa)
        arquivo.writeframes(amostras)
    return caminho


def test_as_tres_fontes_cumprem_o_protocolo() -> None:
    relogio = RelogioFalso()
    for fonte in (
        FonteDeArquivo(caminho=Path("x.wav"), relogio=relogio),
        FonteSintetica(relogio=relogio),
        FonteDeDispositivo(relogio=relogio),
    ):
        assert isinstance(fonte, FonteDeAudio)


def test_fonte_de_arquivo_entrega_quadros_de_20_ms_e_completa_o_ultimo(tmp_path: Path) -> None:
    amostras = gerar(semente=3)[: BYTES_POR_QUADRO * 2 + 100]
    caminho = escrever_wav(tmp_path / "a.wav", amostras)
    fonte = FonteDeArquivo(caminho=caminho, relogio=RelogioFalso())

    fonte.abrir()
    quadros = list(fonte.quadros())
    fonte.fechar()

    assert len(quadros) == 3
    assert all(len(q.amostras) == BYTES_POR_QUADRO for q in quadros)
    assert quadros[-1].amostras.endswith(bytes(10))  # o pedaço final foi completado


def test_o_tempo_da_trilha_vem_do_relogio_injetado_e_nao_do_sistema(tmp_path: Path) -> None:
    """Aceite (c): o carimbo anda 20 ms por quadro mesmo sem nenhum `sleep` de verdade."""
    caminho = escrever_wav(tmp_path / "b.wav", gerar(semente=4)[: BYTES_POR_QUADRO * 5])
    relogio = RelogioFalso()
    fonte = FonteDeArquivo(caminho=caminho, relogio=relogio)

    fonte.abrir()
    carimbos = [q.ts_mono_ns for q in fonte.quadros()]
    fonte.fechar()

    assert carimbos == [20_000_000 * (i + 1) for i in range(5)]
    assert relogio.dormidas_ns == [20_000_000] * 5


@pytest.mark.parametrize(
    ("taxa", "canais", "largura"),
    [(8_000, 1, 2), (TAXA_PADRAO, 2, 2), (TAXA_PADRAO, 1, 1)],
)
def test_wav_fora_do_formato_do_caminho_de_captura_e_recusado(
    tmp_path: Path, taxa: int, canais: int, largura: int
) -> None:
    caminho = escrever_wav(
        tmp_path / "ruim.wav", bytes(1600), taxa=taxa, canais=canais, largura=largura
    )
    fonte = FonteDeArquivo(caminho=caminho, relogio=RelogioFalso())

    with pytest.raises(FormatoNaoSuportado):
        fonte.abrir()


def test_fonte_sintetica_e_deterministica_e_diz_a_semente_no_device_id() -> None:
    def trilha_de(semente: int) -> list[bytes]:
        fonte = FonteSintetica(relogio=RelogioFalso(), semente=semente)
        fonte.abrir()
        quadros = [q.amostras for q in fonte.quadros()]
        fonte.fechar()
        return quadros

    assert trilha_de(11) == trilha_de(11)
    assert trilha_de(11) != trilha_de(12)
    assert FonteSintetica(relogio=RelogioFalso(), semente=11).device_id == "sintetico:11"


def test_dispositivo_real_e_proibido_quando_ci_esta_ligado() -> None:
    """Aceite (a): a proibição é do código de produção, não só da fixture."""
    fonte = FonteDeDispositivo(relogio=RelogioFalso())

    with pytest.raises(DispositivoProibidoEmCI, match="CI"):
        fonte.abrir()


def test_fora_do_ci_a_recusa_do_dispositivo_diz_o_que_falta_na_maquina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sem CI, a recusa deixou de ser "não existe backend" e passou a ser sobre a máquina.

    Desde que `jarvis.audio_io.dispositivo` existe (sounddevice/PortAudio), a tentativa é de
    verdade: nesta máquina falta o PortAudio, no CI do dono pode faltar o extra, e com placa
    de som não falta nada. Em qualquer um dos casos, a frase diz **o que fazer** — é isso que
    o teste cobra, não o motivo específico desta máquina.
    """
    monkeypatch.delenv(VARIAVEL_CI, raising=False)
    fonte = FonteDeDispositivo(relogio=RelogioFalso())

    with pytest.raises(DispositivoIndisponivel) as erro:
        fonte.abrir()
    mensagem = str(erro.value)
    assert any(
        pista in mensagem
        for pista in ("uv sync --group dispositivo", "install portaudio", "--diagnostico")
    ), mensagem


def test_sumidouro_de_arquivo_grava_wav_que_a_fonte_de_arquivo_le(tmp_path: Path) -> None:
    amostras = gerar(semente=6)[: BYTES_POR_QUADRO * 4]
    sumidouro = SumidouroDeArquivo(caminho=tmp_path / "saida.wav")
    sumidouro.abrir()
    consumidas = sumidouro.escrever(amostras)
    sumidouro.fechar()

    fonte = FonteDeArquivo(caminho=tmp_path / "saida.wav", relogio=RelogioFalso())
    fonte.abrir()
    lidos = list(fonte.quadros())
    fonte.fechar()

    assert consumidas == len(amostras) // 2 == sumidouro.amostras_consumidas
    assert b"".join(q.amostras for q in lidos) == amostras
