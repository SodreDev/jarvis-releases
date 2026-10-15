"""Cartão F1-02, aceites (a), (b) e (c): o gerador é determinístico e o plano é o declarado.

Tudo aqui roda com a voz **paramétrica** (sem modelo, sem rede, sem espeak-ng), que é o que o
CI tem. O corpus comitado foi gerado com a voz piper-ONNX, e isso está declarado em cada
rótulo (`gerador`, `voz`, `licenca_voz`) e em `docs/notas-executor-F1.md`.
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from jarvis.audio_io.quadro import TAXA_PADRAO, como_int16
from jarvis.corpus.rotulos import Rotulo, validar_arquivo
from jarvis.corpus.sintetico import (
    DOMINIOS,
    FAIXA_PAUSA_FIM_MS,
    FAIXA_PAUSA_MEIO_MS,
    gerar_corpus,
    planejar,
    regenerar_e_comparar,
)
from jarvis.corpus.voz import VozParametrica


def gerar(
    pasta: Path, *, n: int = 8, semente: int = 42, ruido: float = 0.0, eco: float = 0.0
) -> list[Rotulo]:
    return gerar_corpus(
        n,
        semente=semente,
        pasta=pasta,
        voz=VozParametrica(),
        fracao_ruido=ruido,
        fracao_eco=eco,
    )


def test_mesma_semente_gera_o_mesmo_audio_byte_a_byte(tmp_path: Path) -> None:
    """Aceite (c)."""
    primeira = gerar(tmp_path / "a")
    segunda = gerar(tmp_path / "b")

    assert [r.sha256 for r in primeira] == [r.sha256 for r in segunda]
    assert [r.para_dict() for r in primeira] == [r.para_dict() for r in segunda]


def test_semente_diferente_gera_outro_corpus(tmp_path: Path) -> None:
    primeira = gerar(tmp_path / "a", semente=42)
    outra = gerar(tmp_path / "b", semente=43)

    assert [r.sha256 for r in primeira] != [r.sha256 for r in outra]


def test_os_rotulos_gerados_passam_na_validacao(tmp_path: Path) -> None:
    """Aceite (b): o que o gerador escreve é o que o verificador aceita."""
    gerar(tmp_path)

    rotulos, problemas = validar_arquivo(tmp_path / "rotulos.jsonl")

    assert problemas == []
    assert all(r.sintetico and r.falante == "sintetico" and not r.termo for r in rotulos)


def test_regeneracao_a_partir_do_rotulo_confere_e_acusa_arquivo_trocado(tmp_path: Path) -> None:
    gerar(tmp_path)

    assert regenerar_e_comparar(tmp_path, voz=VozParametrica()) == []

    alvo = tmp_path / "audio" / "s-0001.wav"
    alvo.write_bytes(alvo.read_bytes()[:-200])  # alguém cortou o fim do áudio
    problemas = validar_arquivo(tmp_path / "rotulos.jsonl")[1]

    assert any("s-0001" in p for p in problemas)


def test_o_plano_e_metade_fim_de_turno_e_as_faixas_sao_as_declaradas() -> None:
    """Aceite (a): proporção declarada, e a pausa cai na faixa que o README publica."""
    itens = planejar(500, semente=20_261_015)

    fins = [i for i in itens if i.fim_de_turno]
    meios = [i for i in itens if not i.fim_de_turno]
    assert len(fins) == len(meios) == 250
    assert all(FAIXA_PAUSA_FIM_MS[0] <= i.pausa_ms <= FAIXA_PAUSA_FIM_MS[1] for i in fins)
    assert all(FAIXA_PAUSA_MEIO_MS[0] <= i.pausa_ms <= FAIXA_PAUSA_MEIO_MS[1] for i in meios)
    assert all(not i.texto_depois for i in fins)
    assert all(i.texto_depois for i in meios)


def test_o_prefixo_e_ambiguo_de_proposito() -> None:
    """O mesmo começo aparece como enunciado completo e como prefixo de um maior."""
    itens = planejar(500, semente=20_261_015)

    completos = {i.texto_antes for i in itens if i.fim_de_turno}
    prefixos = {i.texto_antes for i in itens if not i.fim_de_turno}

    # 87 dos 90 enunciados completos também aparecem como prefixo de um maior.
    assert len(completos & prefixos) >= 0.8 * len(completos)


def test_as_faixas_de_pausa_se_sobrepoem_senao_o_limiar_fixo_acertaria_tudo() -> None:
    assert FAIXA_PAUSA_MEIO_MS[0] < FAIXA_PAUSA_FIM_MS[1]
    assert FAIXA_PAUSA_FIM_MS[0] > FAIXA_PAUSA_MEIO_MS[0]


def test_o_vocabulario_cobre_os_tres_dominios_do_v1() -> None:
    assert {d.nome for d in DOMINIOS} == {"arquivos", "midia", "calendario"}
    assert all(len(d.prefixos()) >= 25 for d in DOMINIOS)


def test_a_pausa_do_audio_tem_a_duracao_que_o_rotulo_diz(tmp_path: Path) -> None:
    """O número do rótulo é o silêncio que está no arquivo, não uma intenção."""
    rotulos = gerar(tmp_path, n=6)

    for rotulo in rotulos:
        with wave.open(str(tmp_path / rotulo.arquivo)) as arquivo:
            valores = como_int16(arquivo.readframes(arquivo.getnframes()))
        maior_silencio = 0
        corrente = 0
        for valor in valores:
            corrente = corrente + 1 if valor == 0 else 0
            maior_silencio = max(maior_silencio, corrente)
        silencio_ms = 1000.0 * maior_silencio / TAXA_PADRAO

        assert silencio_ms == pytest.approx(rotulo.pausa_ms, abs=30.0), rotulo.id
