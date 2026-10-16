"""O S2 provisório (ADR-0018): sem ferramenta, fala por stdin, prazo nosso, cancelável.

Nenhum teste chama a CLI de verdade — ela custa dinheiro, precisa de conta e de rede. O
executável é um parâmetro, e os testes apontam para um roteiro Python que registra o que
recebeu. O que se prova é o **contrato**: o que vai no `argv`, o que vai no `stdin`, o que
acontece quando demora, quando cancela e quando a CLI não existe.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from jarvis.voz.s2_provisorio import (
    FERRAMENTAS_PROIBIDAS,
    PROMPT_DE_SISTEMA,
    GeradorDeResposta,
    RespostaDeEco,
    RespostaIndisponivel,
    RespostaPelaCli,
    gerador_de,
    nomes_de_gerador,
)

FALA = "que horas são agora, Jarvis?"


def cli_falsa(tmp_path: Path, *, corpo: str) -> str:
    """Um executável que faz o papel da CLI e anota o que recebeu."""
    roteiro = tmp_path / "cli_falsa.py"
    roteiro.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys, time\n"
        "from pathlib import Path\n"
        f"anotacao = Path({str(tmp_path / 'recebido.json')!r})\n" + corpo,
        encoding="utf-8",
    )
    roteiro.chmod(roteiro.stat().st_mode | stat.S_IEXEC)
    atalho = tmp_path / "cli_falsa"
    atalho.write_text(f'#!/bin/sh\nexec {sys.executable} {roteiro} "$@"\n', encoding="utf-8")
    atalho.chmod(atalho.stat().st_mode | stat.S_IEXEC)
    return str(atalho)


CORPO_QUE_RESPONDE = (
    "entrada = sys.stdin.read()\n"
    "anotacao.write_text(json.dumps({'argv': sys.argv[1:], 'stdin': entrada}),"
    " encoding='utf-8')\n"
    "print('São quinze e trinta.')\n"
)
CORPO_QUE_DEMORA = (
    "anotacao.write_text(json.dumps({'argv': sys.argv[1:], 'stdin': ''}), encoding='utf-8')\n"
    "time.sleep(30)\n"
)
CORPO_QUE_FALHA = "sys.stderr.write('deu ruim aqui\\n')\nsys.exit(3)\n"


def recebido(tmp_path: Path) -> dict[str, object]:
    return json.loads((tmp_path / "recebido.json").read_text(encoding="utf-8"))


@pytest.fixture
def pasta_vazia(tmp_path: Path) -> Path:
    pasta = tmp_path / "vazia"
    pasta.mkdir()
    return pasta


# --- o eco: o modo sem nuvem ---------------------------------------------------------------


def test_o_eco_responde_sem_processo_nenhum() -> None:
    eco = RespostaDeEco()
    assert isinstance(eco, GeradorDeResposta)
    assert eco.responder("bom dia") == "Você disse: bom dia"
    assert eco.responder("   ") == "Não entendi."


# --- o contrato da CLI ----------------------------------------------------------------------


def test_responde_e_a_fala_vai_por_stdin_nunca_no_argv(tmp_path: Path, pasta_vazia: Path) -> None:
    """`argv` é legível por outro processo do usuário: a transcrição do dono não vai lá."""
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia, executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_RESPONDE)
    )

    assert gerador.responder(FALA) == "São quinze e trinta."

    visto = recebido(tmp_path)
    assert visto["stdin"] == FALA
    assert all(FALA not in str(pedaco) for pedaco in visto["argv"])  # type: ignore[union-attr]
    assert gerador.respostas == 1
    assert gerador.ultimo_ms > 0


def test_o_argv_desliga_ferramenta_e_aprovacao_automatica(
    tmp_path: Path, pasta_vazia: Path
) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia, executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_RESPONDE)
    )
    gerador.responder(FALA)

    argv = [str(pedaco) for pedaco in recebido(tmp_path)["argv"]]  # type: ignore[union-attr]
    assert "--print" in argv
    assert "--permission-mode" in argv and "manual" in argv
    proibidas = argv[argv.index("--disallowed-tools") + 1]
    for ferramenta in ("Bash", "Read", "Write", "Edit", "WebFetch", "Task"):
        assert ferramenta in proibidas
    assert PROMPT_DE_SISTEMA in argv


def test_o_prompt_de_sistema_manda_falar_como_se_fala() -> None:
    """Sem isso o modelo devolve lista com marcador, e marcador no TTS vira "hífen, hífen"."""
    assert "LIDA EM VOZ ALTA" in PROMPT_DE_SISTEMA
    assert "sem listas" in PROMPT_DE_SISTEMA and "sem markdown" in PROMPT_DE_SISTEMA
    assert "não tem ferramentas" in PROMPT_DE_SISTEMA


def test_roda_numa_pasta_vazia_e_recusa_se_ela_nao_existe(tmp_path: Path) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=tmp_path / "nao-existe",
        executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_RESPONDE),
    )
    with pytest.raises(RespostaIndisponivel, match="pasta vazia"):
        gerador.responder(FALA)


def test_a_pasta_de_trabalho_e_mesmo_a_cwd_do_processo(tmp_path: Path, pasta_vazia: Path) -> None:
    """Prova de que o processo não enxerga o repositório: ele lista a própria pasta."""
    corpo = (
        "import os\n"
        "anotacao.write_text(json.dumps({'argv': [], 'stdin': '',"
        " 'cwd': os.getcwd(), 'arquivos': os.listdir('.')}), encoding='utf-8')\n"
        "print('ok')\n"
    )
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia, executavel=cli_falsa(tmp_path, corpo=corpo)
    )
    gerador.responder(FALA)

    visto = recebido(tmp_path)
    assert Path(str(visto["cwd"])).resolve() == pasta_vazia.resolve()
    assert visto["arquivos"] == []


def test_cli_ausente_diz_o_que_fazer(pasta_vazia: Path) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia, executavel="claude-que-nao-existe-aqui"
    )
    with pytest.raises(RespostaIndisponivel, match="--s2 eco"):
        gerador.responder(FALA)


def test_cli_que_falha_vira_frase_e_nao_traceback(tmp_path: Path, pasta_vazia: Path) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia, executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_FALHA)
    )
    with pytest.raises(RespostaIndisponivel) as erro:
        gerador.responder(FALA)
    assert "código 3" in str(erro.value) and "deu ruim" in str(erro.value)


def test_o_prazo_e_nosso_e_o_turno_nao_fica_pendurado(tmp_path: Path, pasta_vazia: Path) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia,
        executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_DEMORA),
        prazo_s=1.0,
    )
    with pytest.raises(RespostaIndisponivel, match="sem responder"):
        gerador.responder(FALA)


def test_cancelado_antes_de_comecar_nao_abre_processo(tmp_path: Path, pasta_vazia: Path) -> None:
    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia,
        executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_RESPONDE),
        cancelado=lambda: True,
    )

    assert gerador.responder(FALA) == ""
    assert gerador.canceladas == 1
    assert not (tmp_path / "recebido.json").exists(), "nem chegou a chamar"


def test_cancelado_durante_a_resposta_mata_o_processo(tmp_path: Path, pasta_vazia: Path) -> None:
    """O dono falou por cima: responder ao turno morto é o que o F1-11 proíbe."""
    chamadas = {"n": 0}

    def cancelado() -> bool:
        chamadas["n"] += 1
        return chamadas["n"] > 2

    gerador = RespostaPelaCli(
        pasta_de_trabalho=pasta_vazia,
        executavel=cli_falsa(tmp_path, corpo=CORPO_QUE_DEMORA),
        cancelado=cancelado,
        prazo_s=20.0,
    )

    assert gerador.responder(FALA) == ""
    assert gerador.canceladas == 1
    assert gerador.ultimo_ms < 5000, "matou o processo em vez de esperar os 30 s dele"


# --- a escolha do gerador --------------------------------------------------------------------


def test_a_fabrica_conhece_os_dois_e_recusa_o_resto(pasta_vazia: Path) -> None:
    assert isinstance(gerador_de("eco", pasta_de_trabalho=pasta_vazia), RespostaDeEco)
    assert isinstance(gerador_de("claude", pasta_de_trabalho=pasta_vazia), RespostaPelaCli)
    with pytest.raises(ValueError, match="não existe"):
        gerador_de("gpt", pasta_de_trabalho=pasta_vazia)
    assert set(nomes_de_gerador()) == {"eco", "claude"}


def test_as_ferramentas_proibidas_cobrem_efeito_e_leitura() -> None:
    assert {"Bash", "Write", "Edit", "Read", "Glob", "Grep"} <= set(FERRAMENTAS_PROIBIDAS)
    assert os.sep not in " ".join(FERRAMENTAS_PROIBIDAS)
