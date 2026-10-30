"""O `claude -p` não derruba a rodada por causa da entrada (2026-10-30): o caractere que o UTF-8
não codifica (o surrogate solto de um nome de arquivo ou de um emoji cortado ao meio pelo `slice`
do texto da página) travava a escrita do `stdin` calada, o processo ficava esperando a entrada e o
`TimeoutExpired` subia como exceção — a tarefa caía com "deu um erro aqui dentro"."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from jarvis.s2.motor import Contexto, Fim, Mensagem, Modo, MotivoDoFim, Texto
from jarvis.s2.motor_claude_cli import MotorClaudeCli
from jarvis.voz.interface import nunca_cancelado

CLI_FALSA = Path(__file__).with_name("cli_falsa.py")


def test_entrada_com_surrogate_solto_chega_ao_motor_com_interrogacao(tmp_path: Path) -> None:
    pasta = tmp_path / "vazia"
    pasta.mkdir()
    registro = tmp_path / "registro.jsonl"
    ambiente = {
        **os.environ,
        "JARVIS_CLI_FALSA": json.dumps({"deltas": ["Pronto."]}),
        "JARVIS_CLI_FALSA_REGISTRO": str(registro),
    }
    motor = MotorClaudeCli(
        pasta_de_trabalho=pasta, comando=(sys.executable, "-I", str(CLI_FALSA)), ambiente=ambiente
    )
    contexto = Contexto(
        sistema="s",
        mensagens=(
            Mensagem("dono", "abre o vídeo"),
            Mensagem("ferramenta", '{"titulo": "Vídeo \ud83d novo"}'),
        ),
    )

    deltas = list(motor.gerar(contexto, Modo.RAPIDO, nunca_cancelado))

    fim = deltas[-1]
    assert isinstance(fim, Fim) and fim.motivo is MotivoDoFim.CONCLUIDO, fim
    assert "".join(d.texto for d in deltas if isinstance(d, Texto)) == "Pronto."
    recebido = json.loads(registro.read_text("utf-8").splitlines()[0])["stdin"]
    assert "Vídeo ? novo" in recebido
