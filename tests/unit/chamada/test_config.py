"""`chamada.toml` (ADR-0074): padrões das decisões do dono e recusa do que não presta."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from jarvis.chamada.config import (
    NUNCA_DIZER_PADRAO,
    PODE_DIZER_PADRAO,
    SESSAO_DO_PC,
    WHATSAPP_DO_DONO,
    ConfiguracaoDaChamada,
    ConfiguracaoDaChamadaInvalida,
    gravar,
    ler,
)


def test_padroes_sao_as_decisoes_do_dono_e_seguros(tmp_path: Path) -> None:
    c = ler(tmp_path / "chamada.toml")
    assert (c.duracao_para_aviso_min, c.turnos, c.frases_por_fala) == (5, 30, 5)
    # Sem o nome do chat do dono, o canal do WhatsApp fica desligado: só a sessão do PC.
    assert c.contato_do_dono_whatsapp == "" and c.canais_de_confirmacao == (SESSAO_DO_PC,)
    assert c.palavra_de_coacao == "" and c.fone == "auto" and c.lembrar_interlocutor
    assert (c.retencao_do_recado_dias, c.retencao_da_memoria_dias, c.acao_expira_min) == (
        90,
        90,
        10,
    )
    assert c.pode_dizer == PODE_DIZER_PADRAO and c.nunca_dizer == NUNCA_DIZER_PADRAO


def test_contato_do_dono_liga_o_canal_do_whatsapp() -> None:
    c = ConfiguracaoDaChamada(contato_do_dono_whatsapp="Você")
    assert c.canais_de_confirmacao == (SESSAO_DO_PC, WHATSAPP_DO_DONO)
    assert ConfiguracaoDaChamada(contato_do_dono_whatsapp="   ").canais_de_confirmacao == (
        SESSAO_DO_PC,
    )


@pytest.mark.parametrize(
    ("antigo", "fone"), [("usa_fone = true\n", "sim"), ("usa_fone = false\n", "nao")]
)
def test_arquivo_antigo_continua_valendo(tmp_path: Path, antigo: str, fone: str) -> None:
    caminho = tmp_path / "chamada.toml"
    caminho.write_text(
        antigo + 'canal_de_confirmacao = "sessao_do_pc"\nretencao_do_recado_dias = 30\n'
    )
    c = ler(caminho)
    assert (c.fone, c.retencao_do_recado_dias) == (fone, 30)
    gravar(c, caminho)
    gravado = caminho.read_text()
    assert "usa_fone" not in gravado and "canal_de_confirmacao" not in gravado
    assert ler(caminho) == c


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
        'fone = "talvez"\n',
        "acao_expira_min = 0\n",
        'contato_do_dono_whatsapp = "Você\\nCarlos"\n',
        f'contato_do_dono_whatsapp = "{"x" * 81}"\n',
    ],
)
def test_recusa_o_arquivo_inteiro(tmp_path: Path, texto: str) -> None:
    caminho = tmp_path / "chamada.toml"
    caminho.write_text(texto)
    with pytest.raises(ConfiguracaoDaChamadaInvalida):
        ler(caminho)
