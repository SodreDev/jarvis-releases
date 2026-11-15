"""O pedido que o Jarvis FORMULA para um subagente (ADR-0069; dono, 2026-11-15: «o Jarvis não
repassa o meu prompt literal: ele formula o pedido, espera o subagente trazer o resultado e só
então me responde»).

Delegar era copiar a fala do dono para o subagente («manda pra minha mãe que eu te amo» ia igual
ao Claude Code). Um assistente pessoal entrega outra coisa: o **objetivo** nas palavras dele, o
**contexto** que só ele tem (memória, conversa, o que já tentou), os **passos** concretos, o
**critério de pronto** e **o que devolver**. Aqui ficam:

- `PedidoFormulado` e `do_args`: os campos que a ferramenta de delegar exige;
- `texto`: o pedido montado em seções, que é o que o subagente recebe;
- `copia_do_dono` e `recusa`: o pedido que é só a fala do dono (o objetivo igual a ela, ou um
  passo que a repete) volta ao motor como erro, com a instrução de formular — nunca é enviado.

Só funções puras: quem chama (o executor, a tarefa do pedido) decide o que fazer com a recusa.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Final

SEMELHANCA_DE_COPIA: Final = 0.8
"""A partir daqui (razão do `SequenceMatcher` no texto normalizado) é a fala do dono repetida."""
COBERTURA_DE_COPIA: Final = 0.85
"""Fração das palavras do texto que já estavam na fala do dono, com o texto do tamanho dela ou
menor: é a fala recortada, não um pedido formulado."""
PALAVRAS_MINIMAS: Final = 3
"""Fala curta demais («abre o YouTube») não serve de régua: um objetivo formulado sempre a
contém. Abaixo disto só a igualdade conta como cópia."""
RECUSA_DE_COPIA: Final = (
    "o pedido ao subagente é a fala do dono copiada: FORMULE você mesmo — `tarefa` com o "
    "objetivo nas suas palavras (o que conseguir, onde, para quê), `contexto` com o que você sabe "
    "e ele não (memória, conversa, o que já tentou e falhou), `passos` concretos (o que abrir, "
    "ler, procurar, conferir), `pronto_quando` (como saber que acabou) e `devolver` (o que trazer "
    "de volta). Depois espere o resultado e só então responda ao dono com o que voltou"
)
_PONTUACAO: Final = re.compile(r"[^\w\s]", re.UNICODE)


@dataclass(frozen=True, slots=True)
class PedidoFormulado:
    """O que o subagente recebe: tudo escrito pelo Jarvis, nada copiado da fala do dono."""

    objetivo: str
    passos: tuple[str, ...]
    pronto_quando: str
    devolver: str
    contexto: str = ""
    site: str = ""


def do_args(args: Mapping[str, Any]) -> PedidoFormulado:
    """Os argumentos da `delegar.claude_code` (já validados pelo contrato) como pedido."""
    bruto = args.get("passos") or ()
    passos = tuple(str(p).strip() for p in bruto if str(p).strip())
    return PedidoFormulado(
        objetivo=str(args.get("tarefa", "")).strip(),
        passos=passos,
        pronto_quando=str(args.get("pronto_quando", "")).strip(),
        devolver=str(args.get("devolver", "")).strip(),
        contexto=str(args.get("contexto", "")).strip(),
        site=str(args.get("site", "")).strip(),
    )


def texto(pedido: PedidoFormulado) -> str:
    """O pedido em seções, na ordem em que o subagente precisa dele."""
    linhas = [f"OBJETIVO: {pedido.objetivo}"]
    if pedido.contexto:
        linhas.append(f"CONTEXTO: {pedido.contexto}")
    if pedido.site:
        linhas.append(f"COMECE POR: {pedido.site}")
    if pedido.passos:
        linhas.append("PASSOS:")
        linhas.extend(f"{n}. {passo}" for n, passo in enumerate(pedido.passos, 1))
    if pedido.pronto_quando:
        linhas.append(f"PRONTO QUANDO: {pedido.pronto_quando}")
    if pedido.devolver:
        linhas.append(f"DEVOLVA: {pedido.devolver}")
    return "\n".join(linhas)


def normal(frase: str) -> str:
    """Minúsculas, sem acento, sem pontuação e com um espaço só: a régua da comparação."""
    base = unicodedata.normalize("NFKD", frase.casefold())
    sem_acento = "".join(c for c in base if not unicodedata.combining(c))
    return " ".join(_PONTUACAO.sub(" ", sem_acento).split())


def copia_do_dono(enviado: str, fala: str) -> bool:
    """O texto que iria ao subagente é a fala do dono (igual, quase igual ou recortada dela)?"""
    a, b = normal(enviado), normal(fala)
    if not a or not b:
        return False
    if a == b:
        return True
    palavras_a, palavras_b = a.split(), b.split()
    if len(palavras_b) < PALAVRAS_MINIMAS:
        return False
    if SequenceMatcher(None, a, b).ratio() >= SEMELHANCA_DE_COPIA:
        return True
    da_fala = set(palavras_b)
    cobertas = sum(1 for p in palavras_a if p in da_fala) / len(palavras_a)
    return cobertas >= COBERTURA_DE_COPIA and len(palavras_a) <= len(palavras_b)


def recusa(pedido: PedidoFormulado, fala_do_dono: str) -> str:
    """Vazio = o pedido foi formulado; senão, o porquê da recusa com a instrução ao motor."""
    if not fala_do_dono.strip():
        return ""
    candidatos: Sequence[str] = (pedido.objetivo, *pedido.passos)
    if any(copia_do_dono(c, fala_do_dono) for c in candidatos):
        return RECUSA_DE_COPIA
    return ""


__all__ = [
    "RECUSA_DE_COPIA",
    "PedidoFormulado",
    "copia_do_dono",
    "do_args",
    "normal",
    "recusa",
    "texto",
]
