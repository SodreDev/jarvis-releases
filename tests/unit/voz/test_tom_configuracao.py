"""O tom de voz é do dono (ADR-0058, fatia D): ligado por padrão, desligável, com granularidade
— e desligado, nada é medido nem lido."""

from __future__ import annotations

from pathlib import Path

import pytest
from tools.sinais_de_tom import PERGUNTA, sussurro, voz

from jarvis.voz.config import Configuracao, ConfiguracaoInvalida, escrever, ler
from jarvis.voz.tom import DIMENSOES, Entonacao, Tom, Volume
from tests.unit.voz.test_ruido_no_laco import FORTE, AsrComSinais
from tests.unit.voz.test_tom_no_laco import _app, _eventos, _rodar


def test_o_padrao_mede_tudo_e_os_classificadores_pesados_nao_existem() -> None:
    padrao = Configuracao()
    assert padrao.tom_de_voz and padrao.tom_no_texto and padrao.tom_na_voz
    assert padrao.tom_dimensoes == DIMENSOES


def test_o_arquivo_do_dono_vai_e_volta(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    escolhida = Configuracao(
        tom_de_voz=False, tom_dimensoes=("entonacao", "volume"), tom_no_texto=False
    )
    escrever(escolhida, caminho)
    texto = caminho.read_text(encoding="utf-8")
    assert "tom_de_voz = false" in texto and "Nenhum áudio é gravado" in texto
    lida = ler(caminho)
    assert not lida.tom_de_voz and not lida.tom_no_texto and lida.tom_na_voz
    assert lida.tom_dimensoes == ("volume", "entonacao")  # a ordem é a da linha, não a do arquivo


def test_dimensao_desconhecida_e_erro_e_lista_vazia_cala_o_cerebro(tmp_path: Path) -> None:
    caminho = tmp_path / "jarvis-voz.toml"
    caminho.write_text('tom_dimensoes = ["volume", "humor"]\n', encoding="utf-8")
    with pytest.raises(ConfiguracaoInvalida, match="humor"):
        ler(caminho)
    caminho.write_text("tom_dimensoes = []\n", encoding="utf-8")
    assert ler(caminho).tom_dimensoes == ()
    assert Tom(volume=Volume.GRITO, entonacao=Entonacao.PERGUNTA).linha(()) == ""


def test_desligado_nada_e_medido_nem_lido(tmp_path: Path) -> None:
    asr = AsrComSinais(("Vai chover amanhã de manhã.", FORTE))
    app, linhas = _app(tmp_path, voz(PERGUNTA, 2.0, semente=3), asr)
    app.configuracao = app.configuracao.com(tom_de_voz=False)
    (app.raiz).mkdir(parents=True, exist_ok=True)
    (app.raiz / "tom.json").write_text("arquivo que não pode ser lido", encoding="utf-8")

    _rodar(app)

    assert "Você: Vai chover amanhã de manhã." in linhas  # sem o «?» da entonação
    assert _eventos(app, "tom") == []
    assert app._tom is None
    assert (app.raiz / "tom.json").read_text(encoding="utf-8") == "arquivo que não pode ser lido"


def test_sem_o_ponto_e_sem_a_voz_baixa_quando_o_dono_desliga(tmp_path: Path) -> None:
    asr = AsrComSinais(("Vai chover amanhã de manhã.", FORTE))
    app, linhas = _app(tmp_path / "a", voz(PERGUNTA, 2.0, semente=3), asr)
    app.configuracao = app.configuracao.com(tom_no_texto=False)
    _rodar(app)
    assert "Você: Vai chover amanhã de manhã." in linhas
    assert _eventos(app, "tom")[0]["entonacao"] == "pergunta"  # medido, só não mexe no texto

    baixo = AsrComSinais(("Abre a música baixinho no quarto.", FORTE))
    app, _ = _app(tmp_path / "b", sussurro(2.0, semente=7), baixo)
    app.configuracao = app.configuracao.com(tom_na_voz=False)
    _rodar(app)
    assert app._ganho_da_fala_db == 0.0


def test_o_diagnostico_conta_sem_mostrar_a_voz(tmp_path: Path) -> None:
    from jarvis.voz.cli import _linhas_do_tom
    from jarvis.voz.tom import LinhaDeBase, RepositorioDaLinhaDeBase

    base = LinhaDeBase(turnos=7, nivel_db=-31.4, f0_st=3.21)
    RepositorioDaLinhaDeBase(tmp_path).gravar(base)
    linhas = "\n".join(_linhas_do_tom(Configuracao(), tmp_path))
    assert "7 turno(s), pronta" in linhas and "tom.json" in linhas
    assert "-31" not in linhas and "3.21" not in linhas and "3,21" not in linhas
    assert "DESLIGADO" in "\n".join(_linhas_do_tom(Configuracao(tom_de_voz=False), tmp_path))
