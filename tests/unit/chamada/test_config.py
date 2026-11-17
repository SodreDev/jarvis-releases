"""`chamada.toml` (ADR-0074): padrões das decisões do dono e recusa do que não presta."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from jarvis.chamada.config import (
    ConfiguracaoDaChamada,
    ConfiguracaoDaChamadaInvalida,
    gravar,
    ler,
)


def test_padroes_sao_as_decisoes_do_dono_e_seguros(tmp_path: Path) -> None:
    c = ler(tmp_path / "chamada.toml")
    assert (c.duracao_para_aviso_min, c.turnos, c.frases_por_fala) == (5, 30, 5)
    assert c.canal_de_confirmacao == "sessao_do_pc"
    assert c.palavra_de_coacao == "" and c.usa_fone is False and c.lembrar_interlocutor


def test_grava_privado_e_volta_igual(tmp_path: Path) -> None:
    caminho = tmp_path / "chamada.toml"
    c = ConfiguracaoDaChamada(turnos=12, pode_dizer='em reunião até as "15h"')
    gravar(c, caminho)
    assert ler(caminho) == c
    assert stat.S_IMODE(caminho.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "texto",
    [
        "turnos = 0\n",
        'turnos = "30"\n',
        "desconhecido = 1\n",
        'canal_de_confirmacao = "whatsapp"\n',
        "usa_fone = 1\n",
    ],
)
def test_recusa_o_arquivo_inteiro(tmp_path: Path, texto: str) -> None:
    caminho = tmp_path / "chamada.toml"
    caminho.write_text(texto)
    with pytest.raises(ConfiguracaoDaChamadaInvalida):
        ler(caminho)
