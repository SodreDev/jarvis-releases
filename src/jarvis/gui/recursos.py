"""Onde moram o ícone, o `.desktop` e os textos de licença — no repositório e no pacote.

Um aplicativo instalado não tem repositório em volta. O mesmo código roda de três jeitos —
`uv run jarvis` na árvore, AppImage, `.deb`/`.rpm` — e cada um põe os arquivos num lugar. Em
vez de espalhar `Path(__file__).parents[n]` pelo código, a procura está aqui, numa ordem
declarada, e quem não acha devolve `None` em vez de quebrar a janela: faltar o texto de uma
licença é problema de empacotamento, e o lugar de gritar é o portão (`tools/license_gate.py`),
não a tela do dono no meio de uma conversa.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from jarvis.dados import pasta_de_dados

ID_DO_APLICATIVO: Final = "dev.sodredev.Jarvis"
"""O mesmo nome no `.desktop`, no ícone e no `setDesktopFileName` — é o que faz o KDE casar a
janela com o lançador (ícone na barra de tarefas, "fixar", notificação com o nome certo)."""
NOME: Final = "Jarvis"
PASTA: Final = Path(__file__).resolve().parent / "recursos"
ICONE_SVG: Final = PASTA / "jarvis.svg"


def pasta_de_licencas() -> Path | None:
    """A pasta com os textos de licença que acompanham o artefato (LGPL-3.0, GPL-3.0, BSD-3)."""
    dados = pasta_de_dados()
    for candidata in (
        Path(sys.prefix) / "share" / "licenses" / "jarvis",
        *([dados / "licenses" / "texto"] if dados is not None else []),
    ):
        if candidata.is_dir():
            return candidata
    return None


def frase_de_licenca() -> str:
    """O aviso que a aba de diagnóstico mostra. Obrigação de LGPL, não cortesia (ADR-0019)."""
    pasta = pasta_de_licencas()
    onde = (
        f"Os textos completos estão em {pasta}."
        if pasta
        else ("Os textos completos acompanham o pacote em share/licenses/jarvis.")
    )
    return (
        "J.A.R.V.I.S © SodreDev — Apache-2.0.\n"
        "A janela usa Qt 6 por PySide6 sob a GNU LGPL versão 3: o Qt não foi modificado nem "
        "ligado estaticamente, e as bibliotecas ficam em arquivos próprios, que você pode "
        "substituir por outra compilação compatível.\n" + onde
    )
