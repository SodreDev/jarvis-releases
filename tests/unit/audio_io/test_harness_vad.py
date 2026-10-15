"""Cartão F1-05, aceites (a), (c) e (e): o harness mede contra os marcos e checa o gatilho."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from tools.harness_vad import (
    SLO1_MS,
    TOLERANCIA_ANTES_MS,
    avaliar_item,
    main,
    resumo_de_acertos,
    verdade_por_quadro,
)

from jarvis.corpus.rotulos import Rotulo
from jarvis.corpus.sintetico import gerar_corpus
from jarvis.corpus.voz import VozParametrica

RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    gerar_corpus(
        6, semente=99, pasta=tmp_path, voz=VozParametrica(), fracao_ruido=0.0, fracao_eco=0.0
    )
    return tmp_path


def test_a_verdade_por_quadro_sai_dos_marcos_do_rotulo() -> None:
    rotulo = Rotulo(
        id="s-0001",
        arquivo="audio/s-0001.wav",
        sha256="a" * 64,
        falante="sintetico",
        pausa_ms=400,
        fim_de_turno=False,
        texto="abre a pasta de fotos na área de trabalho",
        split="calibracao",
        sintetico=True,
        semente=1,
        gerador="parametrico@1",
        voz="parametrico",
        licenca_voz="Apache-2.0",
        texto_antes="abre a pasta de fotos",
        texto_depois="na área de trabalho",
        inicio_fala_ms=200,
        inicio_pausa_ms=1000,
    )

    verdade = verdade_por_quadro(rotulo, 100)

    assert verdade[:10] == [False] * 10  # silêncio inicial (200 ms)
    assert verdade[10] is True  # 200 ms: começou a falar
    assert verdade[49] is True  # 980 ms: ainda falando
    assert verdade[50] is False  # 1000 ms: pausa
    assert verdade[69] is False  # 1380 ms: fim da pausa (1000 + 400)
    assert verdade[70] is True  # a continuação existe porque há texto_depois


def test_o_harness_publica_acertos_e_piso_onde_mandaram(corpus: Path, tmp_path: Path) -> None:
    saida = tmp_path / "medicoes"

    codigo = main(
        [
            "--corpus",
            str(corpus),
            "--itens",
            "4",
            "--execucoes",
            "2",
            "--vads",
            "energia",
            "--saida",
            str(saida),
        ]
    )

    assert codigo == 0
    md = (saida / "f1-05-vad.md").read_text(encoding="utf-8")
    with (saida / "f1-05-vad-acertos.csv").open(encoding="utf-8") as arquivo:
        acertos = list(csv.DictReader(arquivo))

    assert len(acertos) == 4
    assert {a["vad"] for a in acertos} == {"energia@1"}
    assert "piso de software" in md
    assert "SLO-1 com microfone" in md, "a lacuna de hardware tem de estar escrita"
    assert f"{SLO1_MS:.0f} ms do SLO-1" in md


def test_o_veredito_do_gatilho_da_adr_0014_aparece_no_relatorio(
    corpus: Path, tmp_path: Path
) -> None:
    """Aceite (e): estourar 80 ms p95 não ajusta o SLO, abre o gatilho — e isso é escrito."""
    main(
        [
            "--corpus",
            str(corpus),
            "--itens",
            "3",
            "--execucoes",
            "1",
            "--vads",
            "energia",
            "--saida",
            str(tmp_path),
        ]
    )

    md = (tmp_path / "f1-05-vad.md").read_text(encoding="utf-8")

    assert "Veredito do gatilho da ADR-0014" in md
    assert "D1 não reabre" in md, "o piso de software está muito abaixo de 80 ms"


def test_disparo_antes_da_tolerancia_conta_como_falso_positivo(corpus: Path) -> None:
    """Quem dispara antes da fala não acertou adiantado: errou no silêncio."""
    from tools.harness_vad import ler_wav

    from jarvis.corpus.rotulos import ler_rotulos

    rotulo = ler_rotulos(corpus / "rotulos.jsonl")[0]

    class SempreFalando:
        nome = "sempre@teste"
        falando: bool | None = None
        ultima_probabilidade = 1.0

        def ver(self, _quadro: object) -> bool | None:
            if self.falando is None:
                self.falando = True
                return True
            return None

    acerto = avaliar_item(rotulo, ler_wav(corpus / rotulo.arquivo), SempreFalando())
    resumo = resumo_de_acertos([acerto])["sempre@teste"]

    assert acerto.atraso_ms is not None
    assert acerto.atraso_ms < -TOLERANCIA_ANTES_MS
    assert resumo["cedo"] == 1.0
    assert resumo["recall_inicio"] == 0.0
    assert resumo["precisao_inicio"] == 0.0


def test_o_harness_nao_escreve_na_medicao_publicada(corpus: Path, tmp_path: Path) -> None:
    publicada = RAIZ / "docs" / "medicoes" / "f1-05-vad.md"
    antes = publicada.read_bytes() if publicada.exists() else None

    main(
        [
            "--corpus",
            str(corpus),
            "--itens",
            "2",
            "--execucoes",
            "1",
            "--vads",
            "energia",
            "--saida",
            str(tmp_path),
        ]
    )

    assert (publicada.read_bytes() if publicada.exists() else None) == antes
