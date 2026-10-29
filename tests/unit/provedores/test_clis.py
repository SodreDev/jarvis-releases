"""Codex e OpenCode com executáveis **falsos**: o teste confere o `argv`, o ambiente do filho (sem
as chaves do Jarvis), o `stdin`, a leitura da saída, o cancelamento e as recusas. Nenhuma CLI de
verdade roda, e nada sai da máquina."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from jarvis.provedores.codex import MotorCodexCli, ProvedorCodexCli
from jarvis.provedores.interface import ListagemIndisponivel, ProvedorIndisponivel
from jarvis.provedores.opencode import MotorOpenCodeCli, ProvedorOpenCodeCli
from jarvis.provedores.registro import provedor_registrado
from jarvis.s2.motor import (
    PRAZO_DE_CANCELAMENTO_S,
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    Raciocinio,
    Texto,
)
from jarvis.voz.chaves import VARIAVEL_GROQ, VARIAVEL_OPENAI
from jarvis.voz.interface import nunca_cancelado

SEGREDO = "gsk_chave_de_teste_que_nao_pode_vazar_0123456789"

PROGRAMA = """\
import json, os, sys, time
roteiro = json.load(open(os.environ["FALSO_ROTEIRO"], encoding="utf-8"))
argv = sys.argv[1:]
chave = next((k for k in roteiro if argv[: len(k.split())] == k.split()), "")
passo = roteiro.get(chave, {"saida": [], "codigo": 0})
entrada = sys.stdin.read() if passo.get("ler_entrada") else ""
registro = os.environ["FALSO_REGISTRO"]
with open(registro, "a", encoding="utf-8") as arquivo:
    arquivo.write(json.dumps({"argv": argv, "env": sorted(os.environ), "cwd": os.getcwd(),
                              "entrada": entrada,
                              "config": os.environ.get("OPENCODE_CONFIG_CONTENT", ""),
                              "arquivos": sorted(os.listdir("."))}) + "\\n")
for linha in passo.get("saida", []):
    print(linha if isinstance(linha, str) else json.dumps(linha), flush=True)
    time.sleep(passo.get("pausa", 0))
sys.stderr.write(passo.get("erro", ""))
time.sleep(passo.get("dormir", 0))
sys.exit(passo.get("codigo", 0))
"""


def falso(
    tmp_path: Path, nome: str, roteiro: dict[str, object]
) -> tuple[list[str], dict[str, str]]:
    programa = tmp_path / f"{nome}.py"
    programa.write_text(PROGRAMA, encoding="utf-8")
    (tmp_path / "roteiro.json").write_text(json.dumps(roteiro), encoding="utf-8")
    ambiente = {
        "PATH": os.environ.get("PATH", ""),
        "FALSO_ROTEIRO": str(tmp_path / "roteiro.json"),
        "FALSO_REGISTRO": str(tmp_path / "registro.jsonl"),
        VARIAVEL_GROQ: SEGREDO,
        VARIAVEL_OPENAI: "sk-proj-outra_chave_de_teste_0123456789",
    }
    return [sys.executable, str(programa)], ambiente


def chamadas(tmp_path: Path) -> list[dict[str, object]]:
    arquivo = tmp_path / "registro.jsonl"
    linhas = arquivo.read_text(encoding="utf-8").splitlines() if arquivo.exists() else []
    return [json.loads(linha) for linha in linhas]


def contexto() -> Contexto:
    return Contexto(sistema="persona do Jarvis", mensagens=(Mensagem("dono", "que horas são?"),))


# --- Codex ----------------------------------------------------------------------------------


def test_codex_roda_sem_shell_sem_chaves_e_le_a_mensagem(tmp_path: Path) -> None:
    saida = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "item.completed", "item": {"id": "i1", "type": "reasoning", "text": "pensando"}},
        {"type": "item.completed", "item": {"id": "i2", "type": "agent_message", "text": "Dez."}},
        {"type": "turn.completed", "usage": {"input_tokens": 30, "output_tokens": 2}},
    ]
    comando, ambiente = falso(tmp_path, "codex", {"exec": {"saida": saida, "ler_entrada": True}})
    pasta = tmp_path / "vazia"
    motor = MotorCodexCli(
        pasta_de_trabalho=pasta,
        modelo="gpt-6.1-terra",
        esforco="low",
        comando=comando,
        ambiente=ambiente,
    )

    deltas = list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))

    assert [d.texto for d in deltas if isinstance(d, Texto)] == ["Dez."]
    assert [d.texto for d in deltas if isinstance(d, Raciocinio)] == ["pensando"]
    fim = deltas[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.CONCLUIDO
    assert fim.uso == {"entrada": 30, "saida": 2}
    (chamada,) = chamadas(tmp_path)
    argv = chamada["argv"]
    assert isinstance(argv, list)
    for trecho in (
        ["exec", "--json", "--ephemeral", "--skip-git-repo-check", "--sandbox", "read-only"],
        ["-c", 'approval_policy="never"'],
        ["-c", "features.shell_tool=false"],
        ["-c", 'web_search="disabled"'],
        ["-c", 'model_reasoning_effort="low"'],
        ["-m", "gpt-6.1-terra"],
    ):
        assert any(argv[i : i + len(trecho)] == trecho for i in range(len(argv))), trecho
    assert argv[-1] == "-"
    env = chamada["env"]
    assert isinstance(env, list)
    assert VARIAVEL_GROQ not in env and VARIAVEL_OPENAI not in env
    assert chamada["cwd"] == str(pasta)
    entrada = str(chamada["entrada"])
    assert "persona do Jarvis" in entrada and "que horas são?" in entrada


def test_codex_que_tenta_ferramenta_dele_e_abortado(tmp_path: Path) -> None:
    saida = [{"type": "item.started", "item": {"type": "command_execution", "command": "ls ~"}}]
    comando, ambiente = falso(tmp_path, "codex", {"exec": {"saida": saida, "dormir": 5}})
    motor = MotorCodexCli(pasta_de_trabalho=tmp_path / "v", comando=comando, ambiente=ambiente)
    inicio = time.monotonic()
    fim = list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.ERRO and "ferramenta" in fim.detalhe
    assert time.monotonic() - inicio < 3  # o processo foi morto, não esperado


def test_codex_que_falha_diz_o_login_sem_a_chave(tmp_path: Path) -> None:
    comando, ambiente = falso(
        tmp_path, "codex", {"exec": {"codigo": 1, "erro": f"401 Unauthorized {SEGREDO}"}}
    )
    motor = MotorCodexCli(pasta_de_trabalho=tmp_path / "v", comando=comando, ambiente=ambiente)
    fim = list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.ERRO
    assert "codex login" in fim.detalhe and SEGREDO not in fim.detalhe


def test_codex_sem_o_programa_diz_como_instalar(tmp_path: Path) -> None:
    motor = MotorCodexCli(
        pasta_de_trabalho=tmp_path / "v", comando=(str(tmp_path / "nao-existe"),), ambiente={}
    )
    fim = list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim) and "não está instalado" in fim.detalhe


def test_codex_cancelado_no_meio_morre_no_prazo(tmp_path: Path) -> None:
    saida = [{"type": "thread.started"}]
    comando, ambiente = falso(tmp_path, "codex", {"exec": {"saida": saida, "dormir": 10}})
    motor = MotorCodexCli(pasta_de_trabalho=tmp_path / "v", comando=comando, ambiente=ambiente)
    inicio = time.monotonic()
    cancela_em = inicio + 0.5  # o processo já está rodando (dorme 10 s depois da 1ª linha)

    fim = list(motor.gerar(contexto(), Modo.RAPIDO, lambda: time.monotonic() >= cancela_em))[-1]

    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.CANCELADO
    assert chamadas(tmp_path), "o processo chegou a rodar"
    # Morto e esperado: muito antes dos 10 s; a folga cobre o kill e a espera do processo.
    assert time.monotonic() - cancela_em < PRAZO_DE_CANCELAMENTO_S + 1.0


def test_codex_imagem_vai_por_arquivo_e_some_no_fim(tmp_path: Path) -> None:
    from jarvis.imagem import Imagem

    saida = [{"type": "item.completed", "item": {"type": "agent_message", "text": "um botão"}}]
    comando, ambiente = falso(tmp_path, "codex", {"exec": {"saida": saida}})
    pasta = tmp_path / "v"
    motor = MotorCodexCli(
        pasta_de_trabalho=pasta, aceita_imagem=True, comando=comando, ambiente=ambiente
    )
    imagem = Imagem(id="tela:1", tipo="image/png", dados=b"\x89PNG", largura=2, altura=2)
    com_imagem = Contexto(sistema="p", mensagens=(Mensagem("dono", "e aí?"),), imagens=(imagem,))
    list(motor.gerar(com_imagem, Modo.RAPIDO, nunca_cancelado))
    (chamada,) = chamadas(tmp_path)
    argv = chamada["argv"]
    assert isinstance(argv, list) and "-i" in argv
    assert chamada["arquivos"] == ["tela-0.png"]
    assert list(pasta.iterdir()) == []


def test_codex_lista_pelo_catalogo_e_pergunta_o_login(tmp_path: Path) -> None:
    catalogo = {
        "models": [
            {
                "slug": "gpt-6.1-terra",
                "display_name": "GPT-6.1 Terra",
                "supported_reasoning_efforts": [{"effort": "low"}, {"effort": "ultra"}, "high"],
                "input_modalities": ["text", "image"],
            },
            {"slug": "escondido", "hidden": True},
        ]
    }
    comando, ambiente = falso(
        tmp_path,
        "codex",
        {"debug models": {"saida": [catalogo]}, "login status": {"codigo": 1}},
    )
    registro = provedor_registrado("conversa-codex-cli")
    assert registro is not None
    provedor = ProvedorCodexCli(
        registro=registro, ambiente=ambiente, pasta_de_trabalho=tmp_path / "v", comando=comando
    )
    (modelo,) = provedor.listar()
    assert modelo.id == "gpt-6.1-terra" and modelo.nome == "GPT-6.1 Terra"
    assert modelo.capacidades.esforcos == ("low", "high")
    assert modelo.capacidades.visao is True
    assert "codex login" in provedor.prontidao()


# --- OpenCode -------------------------------------------------------------------------------


def opencode(tmp_path: Path, roteiro: dict[str, object]) -> ProvedorOpenCodeCli:
    comando, ambiente = falso(tmp_path, "opencode", roteiro)
    registro = provedor_registrado("conversa-opencode-cli")
    assert registro is not None
    return ProvedorOpenCodeCli(
        registro=registro, ambiente=ambiente, pasta_de_trabalho=tmp_path / "v", comando=comando
    )


def test_opencode_1x_nega_permissoes_e_para_no_step_finish(tmp_path: Path) -> None:
    saida = [
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "reasoning", "part": {"id": "r1", "type": "reasoning", "text": "hmm"}},
        {"type": "text", "part": {"id": "p1", "type": "text", "text": "São dez."}},
        {"type": "step_finish", "part": {"type": "step-finish", "reason": "stop"}},
    ]
    provedor = opencode(
        tmp_path,
        {"--version": {"saida": ["1.19.5"]}, "run": {"saida": saida, "dormir": 30}},
    )
    motor = provedor.motor("anthropic/claude-sonnet-5-5", "high")
    assert isinstance(motor, MotorOpenCodeCli)
    inicio = time.monotonic()
    deltas = list(motor.gerar(contexto(), Modo.RAPIDO, nunca_cancelado))
    assert time.monotonic() - inicio < 5  # não esperou o processo que fica parado
    assert [d.texto for d in deltas if isinstance(d, Texto)] == ["São dez."]
    assert [d.texto for d in deltas if isinstance(d, Raciocinio)] == ["hmm"]
    assert isinstance(deltas[-1], Fim) and deltas[-1].motivo is MotivoDoFim.CONCLUIDO
    chamada = chamadas(tmp_path)[-1]
    argv = chamada["argv"]
    assert isinstance(argv, list)
    assert argv[:3] == ["run", "--format", "json"]
    assert argv[argv.index("-m") + 1] == "anthropic/claude-sonnet-5-5"
    assert argv[argv.index("--variant") + 1] == "high"
    assert argv[-2] == "--" and "que horas são?" in argv[-1]
    permissao = json.loads(str(chamada["config"]))["permission"]
    assert permissao["bash"] == permissao["edit"] == permissao["*"] == "deny"
    env = chamada["env"]
    assert isinstance(env, list) and VARIAVEL_GROQ not in env


def test_opencode_2x_e_recusado_com_a_frase_do_que_fazer(tmp_path: Path) -> None:
    provedor = opencode(tmp_path, {"--version": {"saida": ["2.2.1"]}})
    with pytest.raises(ProvedorIndisponivel, match=r"2\.x"):
        provedor.motor("x/y")
    with pytest.raises(ListagemIndisponivel, match=r"2\.x"):
        provedor.listar()


def test_opencode_lista_e_sem_texto_reconhecivel_diz_que_nao_entendeu(tmp_path: Path) -> None:
    provedor = opencode(
        tmp_path,
        {
            "--version": {"saida": ["opencode 1.19.5"]},
            "models": {"saida": ["anthropic/claude-sonnet-5-5", "lixo sem barra", "openai/gpt-6"]},
            "run": {"saida": [{"type": "outra-coisa"}]},
        },
    )
    assert [m.id for m in provedor.listar()] == ["anthropic/claude-sonnet-5-5", "openai/gpt-6"]
    fim = list(provedor.motor("openai/gpt-6").gerar(contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.ERRO
    assert "não reconheci" in fim.detalhe


def test_opencode_que_tenta_ferramenta_e_abortado(tmp_path: Path) -> None:
    saida = [{"type": "tool_use", "part": {"type": "tool", "tool": "bash"}}]
    provedor = opencode(
        tmp_path, {"--version": {"saida": ["1.19.5"]}, "run": {"saida": saida, "dormir": 5}}
    )
    fim = list(provedor.motor("x/y").gerar(contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.ERRO and "ferramenta" in fim.detalhe
