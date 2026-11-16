"""A ORIENTAÇÃO de uma tarefa de navegador (ADR-0066; revista pelas ADR-0070 e ADR-0072).

O que vai ao subagente que tem ferramenta de navegador é o que um agente precisa para trabalhar
numa página — ler antes de agir, escolher o alvo pelo que está nela, reler para conferir, depurar
no erro —, as TRAVAS do envio (que valem sempre) e o jeito de o dono escrever, das memórias fixas
dele. O caminho, o contato e a mensagem são decisão do modelo.

Até a ADR-0071 uma regex tirava da fala do dono o contato e a mensagem e os dava ao subagente como
«dica». A ADR-0072 (dono, 2026-11-16: «a fala do STT não vira parâmetro») tirou isso: a transcrição
é só a mensagem do usuário, que o modelo lê; quem decide o nome a procurar e o texto a digitar é
ele, com a memória à mão.

Nada aqui executa: é texto para as notas da rodada.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

TENTATIVAS_POR_PASSO: Final = 3
"""Quantas vezes a orientação manda reler e tentar o mesmo passo antes de dizer que falhou."""
TONS_NO_ROTEIRO: Final = 3
"""Quantas instruções de tom das memórias fixas vão na orientação."""


@dataclass(frozen=True, slots=True)
class Contato:
    """Uma memória fixa útil ao envio: o contato (nome e o que o dono escreveu sobre ele, «minha
    mãe») ou uma instrução de tom (`tipo="instrucao"`: como o dono escreve)."""

    nome: str
    texto: str = ""
    tipo: str = "contato"


ORIENTACAO: Final = (
    "COMO TRABALHAR NO NAVEGADOR (orientação, não roteiro: o caminho é você quem escolhe): veja "
    "as abas antes de abrir outra; LEIA A PÁGINA antes de agir (browser.inspecionar dá o mapa dos "
    "elementos, com papel, rótulo, estado e `ref`) e escolha o alvo pelo que está nela, nunca por "
    "palpite; aja pelo `ref`, um passo por vez, e releia depois de uma ação que muda a página; se "
    "um passo falhar, releia e depure (outro rótulo, outro `ref`, rolar, fechar o aviso por cima) "
    f"antes de tentar de novo — até {TENTATIVAS_POR_PASSO} vezes por passo; só diga que ficou "
    "feito quando uma leitura confirmar."
)
TRAVAS_DO_ENVIO: Final = (
    "SE FOR UM ENVIO DE MENSAGEM pedido pelo dono: é pedido direto, execute sem perguntar (lista "
    "permitida e modo ausente são só da resposta autônoma). Redija a mensagem em nome dele, em "
    "primeira pessoa e no tom dele com essa pessoa, sem copiar a fala dele (só vai palavra por "
    "palavra o que ele ditou como texto). TRAVAS (valem sempre): antes de digitar, o cabeçalho da "
    "conversa aberta TEM de mostrar o contato certo — nunca digite na conversa errada; depois de "
    "enviar, leia a conversa e só diga que mandou se a última mensagem for a sua."
)


def _ferramentas(ids: Iterable[str]) -> list[str]:
    return sorted(i for i in ids if i.startswith("browser."))


def roteiro(ids: Iterable[str], contatos: Sequence[Contato] = ()) -> str:
    """A orientação para as notas da tarefa, ou vazio quando não há ferramenta de navegador."""
    if not _ferramentas(ids):
        return ""
    tom = [c.texto or c.nome for c in contatos if c.tipo == "instrucao"][:TONS_NO_ROTEIRO]
    jeito = (
        " O jeito de o dono escrever, das memórias dele: "
        + "; ".join(f"«{_curto(t)}»" for t in tom)
        + "."
        if tom
        else ""
    )
    return f"{ORIENTACAO}\n{TRAVAS_DO_ENVIO}{jeito}"


def _curto(texto: str, limite: int = 200) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= limite else texto[:limite] + "…"


__all__ = ["ORIENTACAO", "TENTATIVAS_POR_PASSO", "TRAVAS_DO_ENVIO", "Contato", "roteiro"]
