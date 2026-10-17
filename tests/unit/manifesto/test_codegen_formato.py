"""O stub gerado é exatamente o que o `ruff format` deixaria — o `conferir` compara byte a byte.

Os stubs da F0 tinham zero ou um argumento, e o caso de dois ou mais (vírgula final que faz o
formatador expandir a tupla) só apareceu com as tools `memoria.*` da ADR-0026.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from jarvis.manifesto.codegen import _conjunto

RUFF = shutil.which("ruff")


def _formatado(codigo: str) -> str:
    assert RUFF is not None
    saida = subprocess.run(
        [RUFF, "format", "--stdin-filename", "stub.py", "-"],
        input=codigo,
        capture_output=True,
        text=True,
        check=True,
    )
    return saida.stdout


@pytest.mark.skipif(RUFF is None, reason="ruff fora do PATH")
@pytest.mark.parametrize(
    "valores",
    [
        [],
        ["um"],
        ["alvo_id", "escopo"],
        ["destino", "origem", "relacao", "ate", "desde"],
        [f"argumento_comprido_{i}" for i in range(4)],
        [f"argumento_muito_comprido_numero_{i}" for i in range(6)],
    ],
)
def test_o_conjunto_gerado_ja_esta_no_formato_do_ruff(valores: list[str]) -> None:
    linha = _conjunto("PERMITIDOS", valores) + "\n"
    codigo = "from typing import Final\n\n" + linha
    assert _formatado(codigo) == codigo
