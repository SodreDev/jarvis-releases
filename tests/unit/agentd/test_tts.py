"""Cartão F1-09: streaming cancelável no meio da síntese, mapa de texto e licença no produto."""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agentd.tts import (
    PALAVRAS_DO_PRIMEIRO_PEDACO,
    PALAVRAS_MINIMAS_POR_PEDACO,
    MotorDeTts,
    MotorParametrico,
    SintetizadorEmStreaming,
    VozRecusada,
    carregar_voz,
    falar_para,
    fatiar,
)
from jarvis.audio_io.playback import FilaDePlayback, Pedaco
from jarvis.audio_io.sumidouros import SumidouroEmMemoria

SESSAO = "0193f0a0-0000-7000-8000-000000000000"
TEXTO = (
    "Achei três arquivos, o maior é o relatório de junho na pasta de documentos e também "
    "localizei uma planilha antiga com os valores mensais que você pediu para conferir hoje."
)

REGISTRO_CC_BY_SA = """
data_da_verificacao = "2026-10-15"
verificado_por = "teste"

[[modelo]]
id = "rhasspy/piper-voices:pt_BR-compartilha-igual"
papel = "tts"
licenca = "CC-BY-SA-4.0"
estado = "candidato"
fonte = "https://huggingface.co/api/models/rhasspy/piper-voices"
data_de_acesso = "2026-10-15"

[[modelo]]
id = "rhasspy/piper-voices:pt_BR-permissiva"
papel = "tts"
licenca = "MIT"
estado = "candidato"
fonte = "https://huggingface.co/api/models/rhasspy/piper-voices"
data_de_acesso = "2026-10-15"
"""


def sintetizador(**mudancas: object) -> SintetizadorEmStreaming:
    base: dict[str, object] = {
        "motor": MotorParametrico(),
        "session_id": SESSAO,
        "epoch": 1,
    }
    base.update(mudancas)
    return SintetizadorEmStreaming(**base)  # type: ignore[arg-type]


def test_o_motor_parametrico_cumpre_a_interface() -> None:
    assert isinstance(MotorParametrico(), MotorDeTts)


def test_lotes_normais_tem_contexto_e_o_residual_so_sai_no_fim() -> None:
    fatias = [texto for _, texto in fatiar(TEXTO)]

    assert len(fatias[0].split()) >= PALAVRAS_MINIMAS_POR_PEDACO
    assert len(fatias[0].split()) <= PALAVRAS_DO_PRIMEIRO_PEDACO
    assert all(len(fatia.split()) >= PALAVRAS_MINIMAS_POR_PEDACO for fatia in fatias[:-1])
    assert " ".join(fatias).split() == TEXTO.split(), "o texto inteiro é coberto, sem perda"


def test_cancelar_no_meio_da_sintese_nao_escreve_mais_nada(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aceite (b): o pedaço em voo é DESCARTADO, não escrito."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id=SESSAO)
    cancelado = {"valor": False}
    sintese = sintetizador(cancelado=lambda: cancelado["valor"])

    entregues: list[Pedaco] = []

    def enfileirar(pedaco: Pedaco) -> bool:
        entregues.append(pedaco)
        aceito = fila.enfileirar(pedaco)
        if len(entregues) == 1:
            cancelado["valor"] = True  # Cancel chega durante a síntese do segundo pedaço
        return aceito

    fala = falar_para(sintese, TEXTO, enfileirar)

    assert len(entregues) == 1, "nenhum pedaço novo foi entregue depois do Cancel"
    assert fala.cancelada_em == 1
    assert sintese.pedacos_descartados <= 1
    amostras_antes = sumidouro.amostras_consumidas
    fila.cancelar(reason="barge_in")
    for _ in range(10):
        fila.tick()
    assert sumidouro.amostras_consumidas == amostras_antes, "zero amostra nova depois do tick"


def test_pedaco_de_epoch_velho_nunca_toca() -> None:
    """Aceite (b), segunda metade: a fila recusa, e o sintetizador não insiste."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id=SESSAO, epoch_atual=5)
    sintese = sintetizador(epoch=4)  # síntese de um turno que já morreu

    fala = falar_para(sintese, TEXTO, fila.enfileirar)

    assert fala.pedacos == ()
    assert fila.descartados_por_epoch > 0
    fila.tick()
    assert sumidouro.amostras_consumidas == 0


def test_played_ms_nunca_passa_das_amostras_sintetizadas() -> None:
    """Aceite (c): a invariante que impede o histórico de inventar áudio."""
    sumidouro = SumidouroEmMemoria()
    fila = FilaDePlayback(sumidouro=sumidouro, session_id=SESSAO)
    sintese = sintetizador()

    fala = falar_para(sintese, TEXTO, fila.enfileirar)
    for _ in range(500):
        fila.tick()
        tocadas = sumidouro.amostras_consumidas
        assert tocadas <= fala.amostras_sintetizadas, "tocou mais do que existe"
        assert fila.played_ms * 16 <= fala.amostras_sintetizadas + 320


def test_o_mapa_de_texto_e_sempre_prefixo_do_texto() -> None:
    fala = sintetizador().falar(TEXTO)
    total = fala.amostras_sintetizadas

    for fracao in (0.0, 0.1, 0.25, 0.5, 0.75, 0.99, 1.0):
        prefixo = fala.texto_ate(int(total * fracao))
        assert TEXTO.startswith(prefixo), f"{prefixo!r} não é prefixo"
    assert fala.texto_ate(total) == TEXTO
    assert fala.texto_ate(0) == ""
    assert fala.texto_ate(-10) == ""


def test_o_mapa_cobre_o_texto_sem_perder_espaco() -> None:
    """Juntar pedaços perderia o espaço entre eles; o corte é no texto original."""
    fala = sintetizador().falar(TEXTO)
    meio = fala.amostras_sintetizadas // 2

    prefixo = fala.texto_ate(meio)

    assert prefixo in TEXTO
    assert TEXTO[: len(prefixo)] == prefixo


# --- licença no carregamento (aceite (d)) ---------------------------------------------
def test_voz_cc_by_sa_nao_carrega(tmp_path: Path) -> None:
    """Aceite (d): ShareAlike numa voz contaminaria o áudio que o produto distribui."""
    registro = tmp_path / "modelos.toml"
    registro.write_text(REGISTRO_CC_BY_SA, encoding="utf-8")

    with pytest.raises(VozRecusada, match="CC-BY-SA"):
        carregar_voz("rhasspy/piper-voices:pt_BR-compartilha-igual", registro=registro)

    assert carregar_voz("rhasspy/piper-voices:pt_BR-permissiva", registro=registro) == "MIT"


def test_voz_nao_registrada_nao_carrega() -> None:
    with pytest.raises(VozRecusada, match="não está em licenses"):
        carregar_voz("alguem/voz-misteriosa")


def test_voz_barrada_no_registro_nao_carrega() -> None:
    """XTTS-v2 está barrado desde a ADR-0011: qualquer tentativa de usar falha aqui."""
    with pytest.raises(VozRecusada, match="barrada"):
        carregar_voz("coqui/XTTS-v2")


def test_a_voz_do_corpus_carrega_e_declara_a_licenca() -> None:
    assert carregar_voz("rhasspy/piper-voices:pt_BR-faber-medium") == "MIT"


def test_sem_texto_nao_ha_pedaco() -> None:
    fala = sintetizador().falar("   ")

    assert fala.pedacos == ()
    assert fala.amostras_sintetizadas == 0
    assert fala.texto_ate(100) == ""
