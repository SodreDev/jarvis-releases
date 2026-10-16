"""A CLI do `jarvis-voz`: diagnóstico, modo texto, recusas e a chave que não entra no argv."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.capture import CaptureFixture

from jarvis.voz.chaves import VARIAVEL_GROQ
from jarvis.voz.cli import diagnosticar, main
from jarvis.voz.config import Configuracao, escrever

SEGREDO = "gsk_chave_de_teste_que_nao_pode_vazar_0123456789"


def test_chave_no_argv_impede_subir(capsys: CaptureFixture[str]) -> None:
    codigo = main([f"--asr={SEGREDO}"], ambiente={VARIAVEL_GROQ: SEGREDO})
    erro = capsys.readouterr().err

    assert codigo == 2
    assert SEGREDO not in erro
    assert VARIAVEL_GROQ in erro


def test_diagnostico_lista_motores_chaves_e_o_que_falta(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    assert main(["--diagnostico", "--config", str(tmp_path / "x.toml")], ambiente={}) == 0

    saida = capsys.readouterr().out
    assert "motores registrados" in saida
    assert "asr-whisper-local" in saida and "[local]" in saida
    assert "asr-groq-whisper-large-v3-turbo" in saida and "desligado" in saida
    assert "o que falta para cada motor rodar agora" in saida
    assert "extras opcionais" in saida


def test_diagnostico_nao_le_valor_de_chave(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    main(
        ["--diagnostico", "--config", str(tmp_path / "x.toml")],
        ambiente={VARIAVEL_GROQ: SEGREDO},
    )
    saida = capsys.readouterr().out

    assert SEGREDO not in saida
    assert f"{VARIAVEL_GROQ}: definida" in saida


def test_diagnostico_diz_quando_a_chave_falta(tmp_path: Path, capsys: CaptureFixture[str]) -> None:
    main(["--diagnostico", "--config", str(tmp_path / "x.toml")], ambiente={})
    assert f"{VARIAVEL_GROQ}: AUSENTE" in capsys.readouterr().out


def test_diagnostico_recusa_configuracao_com_segredo(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "x.toml"
    arquivo.write_text(f'asr = "asr-whisper-local"\ngroq_api_key = "{SEGREDO}"\n', encoding="utf-8")

    codigo = diagnosticar(print, caminho=arquivo, ambiente={})

    assert codigo == 2
    saida = capsys.readouterr().out
    assert "RECUSADA" in saida
    assert SEGREDO not in saida


def test_configuracao_invalida_para_o_laco_com_frase(
    tmp_path: Path, capsys: CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "x.toml"
    arquivo.write_text('asr = "motor-inventado"\n', encoding="utf-8")

    codigo = main(["--config", str(arquivo), "--texto"], ambiente={})

    assert codigo == 2
    erro = capsys.readouterr().err
    assert "configuração recusada" in erro
    assert "jarvis-voz config" in erro


def test_modo_texto_roda_com_a_configuracao_do_dono(
    tmp_path: Path, capsys: CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    arquivo = tmp_path / "x.toml"
    escrever(Configuracao(asr="asr-oraculo", tts="tts-parametrico", s2="eco"), arquivo)
    monkeypatch.setattr("sys.stdin", iter(["bom dia\n", "/sair\n"]))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "estado"))

    codigo = main(["--config", str(arquivo), "--texto"], ambiente={})

    assert codigo == 0
    saida = capsys.readouterr().out
    assert "Jarvis: Você disse: bom dia" in saida


def test_opcao_de_linha_vale_so_para_esta_execucao(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: CaptureFixture[str]
) -> None:
    arquivo = tmp_path / "x.toml"
    escrever(Configuracao(asr="asr-oraculo", tts="tts-piper-epitran", s2="eco"), arquivo)
    monkeypatch.setattr("sys.stdin", iter(["/sair\n"]))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "estado"))

    main(["--config", str(arquivo), "--texto", "--tts", "tts-parametrico"], ambiente={})

    assert "parametrico@1" in capsys.readouterr().out
    assert 'tts = "tts-piper-epitran"' in arquivo.read_text(encoding="utf-8"), (
        "a opção de linha reescreveu o arquivo do dono"
    )
