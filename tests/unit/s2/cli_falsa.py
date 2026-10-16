"""Uma `claude -p --output-format stream-json` falsa, para testar o adaptador sem rede.

Lê o roteiro de `JARVIS_CLI_FALSA` (JSON), guarda o `argv` e o `stdin` recebidos em
`JARVIS_CLI_FALSA_REGISTRO`, e emite as linhas do stream com os atrasos pedidos. Cada linha
emitida é anotada no registro **antes** de sair: se o adaptador matar o processo, o registro
mostra que nada foi gerado depois.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TextIO


def main() -> int:
    roteiro = json.loads(os.environ["JARVIS_CLI_FALSA"])
    registro_caminho = os.environ["JARVIS_CLI_FALSA_REGISTRO"]
    entrada = sys.stdin.read()
    with Path(registro_caminho).open("w", encoding="utf-8") as registro:
        registro.write(json.dumps({"argv": sys.argv[1:], "stdin": entrada}) + "\n")
        registro.flush()
        time.sleep(float(roteiro.get("primeiro_atraso_s", 0.0)))
        for texto in roteiro.get("pensamento", []):
            _emitir(registro, _delta("thinking_delta", "thinking", texto))
        for texto in roteiro.get("deltas", []):
            _emitir(registro, _delta("text_delta", "text", texto))
            time.sleep(float(roteiro.get("atraso_s", 0.0)))
        if roteiro.get("pendurar"):
            time.sleep(60)
        if roteiro.get("sem_result"):
            sys.stderr.write("falha simulada\n")
            return int(roteiro.get("codigo", 1))
        _emitir(
            registro,
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "result": "".join(roteiro.get("deltas", [])),
                "usage": {"input_tokens": 12, "output_tokens": 7},
            },
        )
    return 0


def _delta(tipo: str, campo: str, texto: str) -> dict[str, object]:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "index": 0, "delta": {"type": tipo, campo: texto}},
    }


def _emitir(registro: TextIO, evento: dict[str, object]) -> None:
    linha = json.dumps(evento)
    registro.write(json.dumps({"emitido": time.monotonic(), "evento": evento}) + "\n")
    registro.flush()
    sys.stdout.write(linha + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
