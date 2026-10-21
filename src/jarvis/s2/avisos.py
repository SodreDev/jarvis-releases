"""O `s2` diante de avisos liberados: decidir como entregar e dizer em voz (ADR-0025, regra 13).

Decisão do dono: **o Jarvis decide** se avisa e como. O julgamento é do modelo — aqui ele entra
como `julgar`, trocável —, e o código impõe o que a ADR-0025 manda por cima dele:

- `precisa_decisao` **nunca é calado**: a confirmação mora na UI (§5.3), então o card fica e o
  modelo pode, no máximo, não falar (regra 14);
- o texto falado é **montado aqui** a partir do `resumo`, não escrito pelo modelo: é o que deixa
  saber quais pedaços carregam o aviso (`notif_ids`) e, portanto, se ele **tocou** (regra 15);
- resumo que veio de terceiros (`third_party`, resultado de tarefa ou de MCP) é dito **como
  dado de terceiros** — "a tarefa X diz…" —, nunca como fala própria (P6).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from jarvis.agentd.fila_de_avisos import ORIGEM_DO_PEDIDO, Entrega

FALAR: Final = "falar"
Decisao = str
"""`falar`, ou uma `Entrega` final: `so_card` / `calado`."""


@dataclass(frozen=True, slots=True)
class AvisoLiberado:
    notif_id: str
    tipo: str
    origem: str
    resumo: str
    de_terceiros: bool = False


Julgar = Callable[[AvisoLiberado], Decisao]


def falar_sempre(_aviso: AvisoLiberado) -> Decisao:
    """O julgamento padrão enquanto o motor real não decide: avisar."""
    return FALAR


def decidir_entrega(
    avisos: Sequence[AvisoLiberado], *, julgar: Julgar = falar_sempre
) -> Mapping[str, Decisao]:
    decisoes: dict[str, Decisao] = {}
    for aviso in avisos:
        escolha = julgar(aviso)
        if escolha not in (FALAR, str(Entrega.SO_CARD), str(Entrega.CALADO)):
            escolha = str(Entrega.SO_CARD)  # resposta fora do vocabulário: o lado seguro
        if aviso.tipo == "precisa_decisao" and escolha == str(Entrega.CALADO):
            escolha = str(Entrega.SO_CARD)
        decisoes[aviso.notif_id] = escolha
    return decisoes


def frase_do_aviso(aviso: AvisoLiberado) -> str:
    """Uma frase curta, para ouvir: sem lista, sem markdown, terminada em ponto."""
    if aviso.origem.startswith(ORIGEM_DO_PEDIDO) and not aviso.de_terceiros:
        # A tarefa de um pedido do dono (ADR-0038): a frase já é a fala — a resposta, a pergunta
        # "…Posso?" —, montada pelo código ou dita pelo motor da conversa; sem "Aviso:" na frente.
        falado = " ".join(aviso.resumo.split())
        return falado if falado.endswith((".", "!", "?", "…")) else falado + "."
    resumo = aviso.resumo.strip().rstrip(".!?")
    if aviso.de_terceiros:
        texto = f"Aviso de {aviso.origem}: {resumo}"
    elif aviso.tipo == "precisa_decisao":
        texto = f"Preciso da sua decisão: {resumo}"
    else:
        texto = f"Aviso: {resumo}"
    if aviso.tipo == "precisa_decisao":
        texto += ". Está no card para você confirmar"
    return texto + "."
