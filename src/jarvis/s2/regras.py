"""As regras de comportamento do Jarvis: um bloco curto, do dono, em todo turno (ADR-0047).

Pedido do dono (2026-10-25): "regras estruturadas na memória para o Jarvis agir como o Jarvis
agiria" — conciso, direto, proativo, que faz em vez de pedir ao dono, que resolve a dúvida pelo
contexto antes de perguntar. A persona (`persona.md`) diz quem ele é; estas são as regras que o
**dono** edita sem mexer em código:

- o padrão mora no repositório (`regras.toml`, ao lado deste módulo); o do dono, em
  `~/.config/jarvis/regras.toml` (a pasta do `jarvis-voz.toml`), e vence quando existe;
- o arquivo é TOML com `[[regra]]` (`id`, `texto`, `ligada`); poucas regras fortes: até
  `MAXIMO_DE_REGRAS`, cada uma com até `MAXIMO_DO_TEXTO` caracteres — o bloco vai ao motor em
  **todo** turno, e o dono julga a latência do primeiro token (ADR-0045);
- arquivo do dono quebrado não derruba nada: vale o padrão, e o aviso diz por quê (o
  `--diagnostico` mostra); regra longa demais é cortada, e regra a mais fica de fora, avisando;
- um ambiente **explícito** sem pasta de configuração (o da suíte) usa o padrão: nenhum teste lê a
  pasta do dono.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from jarvis.voz.vocabulario import pasta_do_vocabulario

ARQUIVO_PADRAO: Final = Path(__file__).with_name("regras.toml")
NOME_DO_ARQUIVO: Final = "regras.toml"
MAXIMO_DE_REGRAS: Final = 12
MAXIMO_DO_TEXTO: Final = 220
CABECALHO: Final = "REGRAS DO DONO (valem em todo pedido; na dúvida, vencem o resto):"


class RegrasInvalidas(ValueError):
    """O arquivo não é TOML, ou não traz nenhuma `[[regra]]` com `id` e `texto`."""


@dataclass(frozen=True, slots=True)
class Regra:
    id: str
    texto: str


@dataclass(frozen=True, slots=True)
class Regras:
    regras: tuple[Regra, ...]
    origem: str
    """`padrao` ou o caminho do arquivo do dono."""
    avisos: tuple[str, ...] = ()

    def bloco(self) -> str:
        """O que vai ao prompt de sistema, depois da persona: o cabeçalho e uma linha por regra."""
        if not self.regras:
            return ""
        return "\n".join([CABECALHO, *(f"- {r.texto}" for r in self.regras)])


def ler(arquivo: Path) -> Regras:
    """Lê um arquivo de regras; `RegrasInvalidas` quando ele não serve."""
    try:
        dados = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as erro:
        raise RegrasInvalidas(f"{arquivo.name}: {erro}") from None
    brutas = dados.get("regra")
    if not isinstance(brutas, list):
        raise RegrasInvalidas(f"{arquivo.name}: falta a lista [[regra]]")
    regras: list[Regra] = []
    avisos: list[str] = []
    for bruta in brutas:
        regra = _regra(bruta, avisos)
        if regra is None:
            continue
        if len(regras) == MAXIMO_DE_REGRAS:
            avisos.append(f"mais de {MAXIMO_DE_REGRAS} regras: as de depois ficaram de fora")
            break
        regras.append(regra)
    if not regras:
        raise RegrasInvalidas(f"{arquivo.name}: nenhuma regra ligada com id e texto")
    return Regras(tuple(regras), str(arquivo), tuple(avisos))


def _regra(bruta: Any, avisos: list[str]) -> Regra | None:
    if not isinstance(bruta, Mapping) or bruta.get("ligada", True) is False:
        return None
    identificador, texto = bruta.get("id"), bruta.get("texto")
    if not isinstance(identificador, str) or not isinstance(texto, str) or not texto.strip():
        avisos.append("uma regra sem id ou sem texto ficou de fora")
        return None
    limpo = " ".join(texto.split())
    if len(limpo) > MAXIMO_DO_TEXTO:
        avisos.append(f"a regra «{identificador}» passou de {MAXIMO_DO_TEXTO} caracteres: cortada")
        limpo = limpo[:MAXIMO_DO_TEXTO].rsplit(" ", 1)[0] + "…"
    return Regra(identificador, limpo)


def padrao() -> Regras:
    """As regras do repositório (sempre válidas: o teste confere)."""
    regras = ler(ARQUIVO_PADRAO)
    return Regras(regras.regras, "padrao", regras.avisos)


def arquivo_do_dono(ambiente: Mapping[str, str] | None = None) -> Path | None:
    pasta = pasta_do_vocabulario(ambiente)
    return pasta / NOME_DO_ARQUIVO if pasta is not None else None


def do_dono(ambiente: Mapping[str, str] | None = None) -> Regras:
    """As regras que valem nesta sessão: as do dono, se ele tem o arquivo e ele serve; senão, o
    padrão (com o aviso, quando o do dono não serviu)."""
    arquivo = arquivo_do_dono(ambiente)
    return na_pasta(arquivo.parent) if arquivo is not None else padrao()


def na_pasta(pasta: Path) -> Regras:
    """As regras do arquivo `regras.toml` desta pasta de configuração, ou o padrão."""
    arquivo = pasta / NOME_DO_ARQUIVO
    if not arquivo.is_file():
        return padrao()
    try:
        return ler(arquivo)
    except RegrasInvalidas as erro:
        base = padrao()
        return Regras(base.regras, "padrao", (f"o arquivo do dono não serviu ({erro})",))


def bloco_padrao() -> str:
    return padrao().bloco()


__all__ = [
    "ARQUIVO_PADRAO",
    "CABECALHO",
    "MAXIMO_DE_REGRAS",
    "MAXIMO_DO_TEXTO",
    "Regra",
    "Regras",
    "RegrasInvalidas",
    "arquivo_do_dono",
    "bloco_padrao",
    "do_dono",
    "ler",
    "na_pasta",
    "padrao",
]
