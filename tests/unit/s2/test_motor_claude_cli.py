"""O adaptador do `claude -p` em stream, contra uma CLI falsa: sem rede, sem conta, sem LLM."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from jarvis.s2.cerebro import Cerebro
from jarvis.s2.motor import (
    PRAZO_DE_CANCELAMENTO_S,
    Contexto,
    Fim,
    Mensagem,
    Modo,
    MotivoDoFim,
    MotorDeConversa,
    Texto,
)
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.voz.interface import Onde, nunca_cancelado

CLI_FALSA = Path(__file__).with_name("cli_falsa.py")
FALA_DO_DONO = "minha senha do banco é 1234, não conta pra ninguém"


@pytest.fixture
def pasta_vazia(tmp_path: Path) -> Path:
    pasta = tmp_path / "vazia"
    pasta.mkdir()
    return pasta


def _motor(pasta: Path, registro: Path, **roteiro: Any) -> MotorClaudeCli:
    ambiente = {
        **os.environ,
        "JARVIS_CLI_FALSA": json.dumps(roteiro),
        "JARVIS_CLI_FALSA_REGISTRO": str(registro),
    }
    return MotorClaudeCli(
        pasta_de_trabalho=pasta, comando=(sys.executable, "-I", str(CLI_FALSA)), ambiente=ambiente
    )


def _contexto(texto: str = FALA_DO_DONO) -> Contexto:
    return Contexto(
        sistema="s",
        mensagens=(
            Mensagem("dono", "oi"),
            Mensagem("jarvis", "Oi, tudo", interrompida=True),
            Mensagem("dono", texto),
        ),
    )


def _registro(caminho: Path) -> list[dict[str, Any]]:
    return [json.loads(linha) for linha in caminho.read_text("utf-8").splitlines()]


def test_cumpre_a_interface_e_declara_nuvem(pasta_vazia: Path) -> None:
    motor = MotorClaudeCli(pasta_de_trabalho=pasta_vazia)
    assert isinstance(motor, MotorDeConversa)
    assert motor.onde is Onde.NUVEM


def test_a_fala_do_dono_vai_por_stdin_e_nunca_no_argv(pasta_vazia: Path, tmp_path: Path) -> None:
    """ADR-0018, regra 2: `argv` é legível por qualquer processo do usuário."""
    registro = tmp_path / "registro.jsonl"
    motor = _motor(pasta_vazia, registro, deltas=["Ok."])
    list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))

    recebido = _registro(registro)[0]
    assert FALA_DO_DONO not in " ".join(recebido["argv"])
    assert FALA_DO_DONO in recebido["stdin"]
    assert "Oi, tudo [interrompido pelo dono aqui]" in recebido["stdin"]


def test_sem_ferramenta_sem_sessao_e_com_o_esforco_do_modo(pasta_vazia: Path) -> None:
    motor = MotorClaudeCli(pasta_de_trabalho=pasta_vazia)
    rapido = motor.argumentos(Modo.RAPIDO)
    assert rapido[rapido.index("--tools") + 1] == ""
    assert "--no-session-persistence" in rapido, "sessão da CLI guarda o gerado, não o tocado"
    assert rapido[rapido.index("--effort") + 1] == "low"
    pensar = motor.argumentos(Modo.PENSAR)
    assert pensar[pensar.index("--effort") + 1] == "high"


def test_o_stream_vira_texto_e_o_pensamento_nao(pasta_vazia: Path, tmp_path: Path) -> None:
    motor = _motor(
        pasta_vazia, tmp_path / "r.jsonl", pensamento=["hmm, 17×3"], deltas=["Cinquenta ", "e um."]
    )
    deltas = list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))

    assert [d for d in deltas if isinstance(d, Texto)] == [Texto("Cinquenta "), Texto("e um.")]
    fim = deltas[-1]
    assert isinstance(fim, Fim)
    assert fim.motivo is MotivoDoFim.CONCLUIDO
    assert fim.uso == {"input_tokens": 12, "output_tokens": 7}
    assert motor.pensamento_descartado == 1
    assert motor.ultimo_codigo == 0


def test_processo_que_sai_sem_fim_vira_erro_com_o_motivo(pasta_vazia: Path, tmp_path: Path) -> None:
    motor = _motor(pasta_vazia, tmp_path / "r.jsonl", deltas=["Oi"], sem_result=True, codigo=3)
    fim = list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))[-1]

    assert isinstance(fim, Fim)
    assert fim.motivo is MotivoDoFim.ERRO
    assert "código 3" in fim.detalhe
    assert "falha simulada" in fim.detalhe


def test_o_prazo_e_nosso_e_mata_o_processo(pasta_vazia: Path, tmp_path: Path) -> None:
    motor = _motor(pasta_vazia, tmp_path / "r.jsonl", deltas=["Oi"], pendurar=True)
    motor.prazo_s = 0.5
    fim = list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))[-1]

    assert isinstance(fim, Fim)
    assert fim.motivo is MotivoDoFim.PRAZO
    assert motor.ultimo_codigo is not None, "processo ficou vivo depois do prazo"


def test_sem_a_pasta_vazia_nao_roda(tmp_path: Path) -> None:
    motor = MotorClaudeCli(pasta_de_trabalho=tmp_path / "nao-existe")
    fim = list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim)
    assert fim.motivo is MotivoDoFim.ERRO
    assert "pasta vazia" in fim.detalhe


def test_sem_o_executavel_diz_isso(pasta_vazia: Path) -> None:
    motor = MotorClaudeCli(pasta_de_trabalho=pasta_vazia, comando=("nao-existe-claude-xyz",))
    fim = list(motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado))[-1]
    assert isinstance(fim, Fim)
    assert "não está nesta máquina" in fim.detalhe


def _cancelar_em(segundos: float, evento: threading.Event, marcas: dict[str, float]) -> None:
    def alvo() -> None:
        time.sleep(segundos)
        marcas["cancelou"] = time.monotonic()
        evento.set()

    threading.Thread(target=alvo, daemon=True).start()


@pytest.mark.parametrize("cancelar_apos_s", [0.15, 0.4])
def test_cancelado_o_processo_morre_no_prazo_e_nada_e_gerado_depois(
    cancelar_apos_s: float, pasta_vazia: Path, tmp_path: Path
) -> None:
    """Regra 9 (c) da ADR-0025: parar de **gerar**, não só de ler, em até 50 ms.

    0,15 s cai antes do primeiro delta (a CLI falsa ainda "pensa"); 0,4 s cai no meio do stream.
    """
    registro = tmp_path / "r.jsonl"
    motor = _motor(
        pasta_vazia,
        registro,
        primeiro_atraso_s=0.3,
        deltas=[f"palavra{i} " for i in range(40)],
        atraso_s=0.02,
    )
    cancelou = threading.Event()
    marcas: dict[str, float] = {}
    _cancelar_em(cancelar_apos_s, cancelou, marcas)

    cerebro = Cerebro(motor=motor)
    resposta = cerebro.responder(
        "conta até quarenta", epoch=0, publicar=lambda _: None, cancelado=cancelou.is_set
    )
    voltou = time.monotonic()

    assert resposta.cancelada
    assert motor.ultimo_codigo is not None, "o processo continuou vivo depois do cancelamento"
    assert voltou - marcas["cancelou"] <= PRAZO_DE_CANCELAMENTO_S
    emitidos_depois = [
        linha
        for linha in _registro(registro)[1:]
        if linha["emitido"] > marcas["cancelou"] + PRAZO_DE_CANCELAMENTO_S
    ]
    assert emitidos_depois == [], "a CLI continuou gerando depois do cancelamento"


def test_desistir_do_iterador_mata_o_processo(pasta_vazia: Path, tmp_path: Path) -> None:
    motor = _motor(pasta_vazia, tmp_path / "r.jsonl", deltas=["a ", "b ", "c "], atraso_s=0.5)
    deltas: Iterator[object] = motor.gerar(_contexto(), Modo.RAPIDO, nunca_cancelado)
    assert isinstance(next(deltas), Texto)
    deltas.close()  # type: ignore[attr-defined]

    assert motor.ultimo_codigo is not None


def test_piso_do_spawn_vem_ligado_por_padrao(tmp_path: Path) -> None:
    """Medido em docs/medicoes/f2-02-piso-do-claude.md: `--safe-mode` tira ~300–400 ms do 1º
    token; a variável de tráfego piorou o p95 e fica desligada (só para medir)."""
    from jarvis.s2.motor import Modo
    from jarvis.s2.motor_claude_cli import VARIAVEL_SEM_TRAFEGO, MotorClaudeCli

    motor = MotorClaudeCli(pasta_de_trabalho=tmp_path, ambiente={"PATH": "/usr/bin"})
    assert "--safe-mode" in motor.argumentos(Modo.RAPIDO)
    assert {"--strict-mcp-config", "--no-session-persistence"} <= set(motor.argumentos(Modo.RAPIDO))
    assert motor.ambiente_do_filho() == {"PATH": "/usr/bin"}

    medindo = MotorClaudeCli(pasta_de_trabalho=tmp_path, ambiente={}, sem_trafego_extra=True)
    assert medindo.ambiente_do_filho() == {VARIAVEL_SEM_TRAFEGO: "1"}
    antes = MotorClaudeCli(pasta_de_trabalho=tmp_path, ambiente={}, modo_seguro=False)
    assert "--safe-mode" not in antes.argumentos(Modo.RAPIDO)
