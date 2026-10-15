"""Cartão F1-02, aceites (d), (e) e (f): o rótulo recusa o que confunde sintético com real."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.corpus.rotulos import (
    ErroDeRotulo,
    contagem,
    escrever_rotulos,
    ler_rotulos,
    split_canonico,
    validar_arquivo,
    validar_rotulo,
)

RAIZ = Path(__file__).resolve().parents[3]
ROTULOS_DO_REPOSITORIO = RAIZ / "corpus" / "turnos" / "rotulos.jsonl"

SINTETICO: dict[str, Any] = {
    "id": "s-0001",
    "arquivo": "audio/s-0001.wav",
    "sha256": "a" * 64,
    "falante": "sintetico",
    "pausa_ms": 420,
    "fim_de_turno": True,
    "texto": "liga o rádio na cozinha",
    "texto_antes": "liga o rádio na cozinha",
    "split": "calibracao",
    "sintetico": True,
    "semente": 7,
    "gerador": "parametrico@1",
    "voz": "parametrico",
    "licenca_voz": "Apache-2.0",
}
REAL: dict[str, Any] = {
    "id": "t-0001",
    "arquivo": "audio/t-0001.wav",
    "sha256": "b" * 64,
    "falante": "dono",
    "pausa_ms": 420,
    "fim_de_turno": True,
    "texto": "liga o rádio",
    "split": "retido",
    "termo": "TERMO-0001",
}


def sem(bruto: dict[str, Any], chave: str) -> dict[str, Any]:
    return {k: v for k, v in bruto.items() if k != chave}


def test_rotulo_sintetico_e_real_validos_passam() -> None:
    assert validar_rotulo(SINTETICO).sintetico
    assert not validar_rotulo(REAL).sintetico


def test_item_com_marca_de_geracao_sem_declarar_sintetico_e_recusado() -> None:
    """Aceite (d)."""
    with pytest.raises(ErroDeRotulo, match="sintetico"):
        validar_rotulo(sem(SINTETICO, "sintetico"))


def test_item_sintetico_com_termo_de_consentimento_e_recusado() -> None:
    """Aceite (e): não se inventa termo para voz de máquina."""
    with pytest.raises(ErroDeRotulo, match="consentimento"):
        validar_rotulo({**SINTETICO, "termo": "TERMO-0001"})


def test_item_real_sem_termo_e_recusado() -> None:
    with pytest.raises(ErroDeRotulo, match="consentimento"):
        validar_rotulo(sem(REAL, "termo"))


def test_split_ausente_e_recusado() -> None:
    """Aceite (f), primeira metade."""
    with pytest.raises(ErroDeRotulo, match="split"):
        validar_rotulo(sem(SINTETICO, "split"))


def test_split_atribuido_fora_da_criacao_e_recusado(tmp_path: Path) -> None:
    """Aceite (f), segunda metade: o split do sintético é função de (semente, ids)."""
    ids = [f"s-{i:04d}" for i in range(1, 11)]
    canonico = split_canonico(ids, 7)
    linhas = [
        {
            **SINTETICO,
            "id": identificador,
            "arquivo": f"audio/{identificador}.wav",
            "split": canonico[identificador],
        }
        for identificador in ids
    ]
    caminho = tmp_path / "rotulos.jsonl"
    caminho.write_text(
        "\n".join(json.dumps(linha, ensure_ascii=False) for linha in linhas) + "\n",
        encoding="utf-8",
    )
    assert validar_arquivo(caminho)[1] == []

    # alguém "escolhe" o split na hora de medir
    trocado = [
        {**linha, "split": "retido" if linha["split"] == "calibracao" else "calibracao"}
        if indice == 3
        else linha
        for indice, linha in enumerate(linhas)
    ]
    caminho.write_text(
        "\n".join(json.dumps(linha, ensure_ascii=False) for linha in trocado) + "\n",
        encoding="utf-8",
    )

    problemas = validar_arquivo(caminho)[1]

    assert len(problemas) == 1
    assert "não é o da criação" in problemas[0]


def test_split_canonico_corta_em_70_30_e_depende_da_semente() -> None:
    ids = [f"s-{i:04d}" for i in range(1, 101)]
    com_7 = split_canonico(ids, 7)

    assert sum(1 for v in com_7.values() if v == "calibracao") == 70
    assert com_7 != split_canonico(ids, 8)
    assert com_7 == split_canonico(reversed(ids), 7)  # não depende da ordem do arquivo


def test_chave_desconhecida_e_recusada_e_nao_ignorada() -> None:
    with pytest.raises(ErroDeRotulo, match="desconhecida"):
        validar_rotulo({**SINTETICO, "qualidade": "boa"})


def test_fim_de_turno_e_continuacao_sao_invariantes_duras() -> None:
    with pytest.raises(ErroDeRotulo, match="não era fim de turno"):
        validar_rotulo({**SINTETICO, "texto_depois": "na cozinha"})
    with pytest.raises(ErroDeRotulo, match="falso corte"):
        validar_rotulo({**SINTETICO, "fim_de_turno": False})


def test_texto_tem_de_ser_a_juncao_das_duas_partes() -> None:
    with pytest.raises(ErroDeRotulo, match="junção"):
        validar_rotulo(
            {
                **SINTETICO,
                "fim_de_turno": False,
                "texto_antes": "abre a pasta",
                "texto_depois": "de fotos",
                "texto": "abre outra coisa",
            }
        )


def test_audio_que_mudou_e_acusado_quando_o_arquivo_existe(tmp_path: Path) -> None:
    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "s-0001.wav").write_bytes(b"outro conteudo")
    caminho = tmp_path / "rotulos.jsonl"
    caminho.write_text(json.dumps(SINTETICO, ensure_ascii=False) + "\n", encoding="utf-8")

    problemas = validar_arquivo(caminho)[1]

    assert len(problemas) == 1 and "mudou" in problemas[0]

    digest = hashlib.sha256(b"outro conteudo").hexdigest()
    caminho.write_text(
        json.dumps({**SINTETICO, "sha256": digest}, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    assert validar_arquivo(caminho)[1] == []


def test_ida_e_volta_do_rotulo_preserva_os_campos(tmp_path: Path) -> None:
    caminho = tmp_path / "r.jsonl"
    rotulos = [validar_rotulo(SINTETICO), validar_rotulo(REAL)]

    escrever_rotulos(caminho, rotulos)

    assert ler_rotulos(caminho) == rotulos


def test_contagem_nunca_soma_sintetico_com_real() -> None:
    numeros = contagem([validar_rotulo(SINTETICO), validar_rotulo(REAL)])

    assert numeros["sintetico"] == 1
    assert numeros["real"] == 1
    assert "sintetico/fim_de_turno" in numeros and "real/fim_de_turno" in numeros


def test_o_corpus_comitado_cumpre_o_cartao() -> None:
    """Aceite (a) e (b) sobre o material que está no repositório."""
    rotulos, problemas = validar_arquivo(ROTULOS_DO_REPOSITORIO)
    numeros = contagem(rotulos)

    assert problemas == []
    assert len(rotulos) >= 500
    assert numeros["sintetico"] == len(rotulos), "todo item do corpus de hoje é sintético"
    assert numeros["sintetico/fim_de_turno"] == numeros["sintetico/meio_de_frase"]
    assert numeros["split/calibracao"] == round(0.7 * len(rotulos))
    assert all(not r.termo for r in rotulos)
    assert all(r.voz and r.licenca_voz and r.gerador for r in rotulos)
