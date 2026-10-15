"""A tela "sobre" da interface: licença do produto e atribuições obrigatórias (cartão F1-06).

Isto não é enfeite: CC-BY exige atribuição **no produto**, e a tela "sobre" é onde o produto
diz quem são os terceiros. O texto é montado a partir de `licenses/modelos.toml` — a mesma
fonte da porta de licença —, então um modelo CC-BY novo aparece aqui sozinho, e um modelo
removido sai sozinho. Ninguém mantém uma lista à mão para ela envelhecer.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ARQUIVO_MODELOS: Final = Path(__file__).resolve().parents[3] / "licenses" / "modelos.toml"
LICENCAS_COM_ATRIBUICAO: Final[frozenset[str]] = frozenset(
    {"cc-by-4.0", "cc-by-3.0", "cc-by-sa-4.0", "bsd-4-clause", "openrail", "cdla-permissive-2.0"}
)
PROJETO: Final = "J.A.R.V.I.S © SodreDev — licença Apache-2.0"


@dataclass(frozen=True, slots=True)
class Atribuicao:
    """Um item que o produto é obrigado a citar."""

    id: str
    licenca: str
    papel: str

    def linha(self) -> str:
        return f"{self.id} ({self.licenca}) — {self.papel}"


def atribuicoes(arquivo: Path = ARQUIVO_MODELOS) -> list[Atribuicao]:
    """Modelos registrados cuja licença exige atribuição e que não estão barrados."""
    dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    return sorted(
        (
            Atribuicao(
                id=str(modelo["id"]),
                licenca=str(modelo["licenca"]),
                papel=str(modelo.get("papel", "?")),
            )
            for modelo in dados.get("modelo", [])
            if str(modelo["licenca"]).lower() in LICENCAS_COM_ATRIBUICAO
            and str(modelo.get("estado", "candidato")) != "barrado"
        ),
        key=lambda a: a.id,
    )


def texto_sobre(arquivo: Path = ARQUIVO_MODELOS) -> str:
    """O texto que a tela "sobre" mostra. Sem atribuição obrigatória, ainda diz a licença."""
    linhas = [PROJETO, ""]
    itens = atribuicoes(arquivo)
    if itens:
        linhas.append("Componentes de terceiros com atribuição obrigatória:")
        linhas += [f"  • {item.linha()}" for item in itens]
        linhas.append("")
    linhas.append("Licenças completas: docs/licencas.md e NOTICE.")
    return "\n".join(linhas)
