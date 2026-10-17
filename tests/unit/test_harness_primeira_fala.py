"""Fumaça do harness da primeira fala: roda sem rede e **nunca** escreve em `docs/medicoes`.

A armadilha conhecida do projeto: teste de fumaça que publica na pasta oficial troca o número
medido por um de brinquedo. Aqui a saída vai para `tmp_path`, e o teste confere.
"""

from __future__ import annotations

import csv
from pathlib import Path

from tools.harness_primeira_fala import NOME, PASTA_SAIDA, main


def test_o_harness_publica_os_tres_trechos_sem_rede(tmp_path: Path) -> None:
    oficial = PASTA_SAIDA / f"{NOME}.csv"
    antes = oficial.read_bytes() if oficial.exists() else None

    codigo = main(
        [
            "--motores",
            "roteirizado",
            "--tts",
            "parametrico",
            "--itens",
            "3",
            "--saida",
            str(tmp_path),
            "--pasta-vazia",
            str(tmp_path / "vazia"),
        ]
    )

    assert codigo == 0
    linhas = list(csv.DictReader((tmp_path / f"{NOME}.csv").open(encoding="utf-8")))
    assert len(linhas) == 3
    for linha in linhas:
        montagem = float(linha["montagem_ms"])
        fronteira = float(linha["primeira_fronteira_ms"])
        audio = float(linha["primeiro_audio_ms"])
        assert 0 <= montagem <= fronteira <= audio, linha
        assert linha["fim"] == "concluido"
    texto = (tmp_path / f"{NOME}.md").read_text(encoding="utf-8")
    assert "Piso de software" in texto
    assert "O que não foi medido" in texto
    depois = oficial.read_bytes() if oficial.exists() else None
    assert depois == antes, "o teste escreveu na medição publicada"
