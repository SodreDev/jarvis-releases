"""O aviso falado e o "desfazer" das tools moderadas (dono, 2026-10-18).

Tool `moderada` roda sem perguntar, e em troca duas coisas são **do código**, não do modelo:

1. **o aviso**: depois do efeito, o Jarvis fala a frase que o manifesto declara (`aviso_falado`),
   com os argumentos e o resultado no lugar dos `{campos}`. É o dono sabendo o que aconteceu sem
   ter sido consultado antes. O passo de navegação (`aviso_silencioso`, dono 2026-10-20,
   ADR-0031) é a exceção: a frase fica na auditoria e o resultado vem na resposta final;
2. **o desfazer**: o que dá para voltar atrás fica num registro curto, e `acao.desfazer` o usa.
   Nada é apagado de verdade: arquivo criado pelo Jarvis vai para `lixeira/` na área dele (e
   dali o dono decide), memória é retratada (continua no livro, deixa de valer).

O registro vive na memória do processo: desfazer vale para o que aconteceu **nesta** execução.
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from jarvis.barramento.envelope import uuid7

if TYPE_CHECKING:
    from jarvis.politica.metodo import Escolha
    from jarvis.politica.objetivo import Objetivo

LIMITE_DO_REGISTRO: Final = 20
LIMITE_DO_CAMPO: Final = 80
LIMITE_DO_AVISO: Final = 200
PADRAO_DE_CAMPO: Final = r"\{(\w+)\}"

LIXEIRA: Final = "lixeira"
"""Pasta, dentro da área do Jarvis, para onde vai o que o dono mandou desfazer."""


@dataclass(slots=True)
class Contaminacao:
    """ "Este fluxo já leu conteúdo de terceiros": o turno da conversa tem a sua, e cada tarefa em
    segundo plano tem a dela — uma não contamina a outra."""

    valor: bool = False
    objetivo: Objetivo | None = None
    """O objetivo **deste** fluxo (Lote C, C2): a tarefa em segundo plano tem o dela, que ela segue
    até cumprir; o turno usa o do executor (`ExecutorDeFerramentas.objetivo`)."""
    metodo: Escolha | None = None
    """O método do pedido que a tarefa cumpre (ADR-0035, ADR-0038): o pedido do dono que virou
    tarefa segue fora do que o roteador tirou dele, como seguiria no turno. `None` = nenhum (a
    tarefa que o modelo pediu com `tarefa.iniciar`, como antes)."""


@dataclass(frozen=True, slots=True)
class Desfazer:
    """Como voltar atrás de uma ação moderada."""

    acao_id: str
    tool_id: str
    descricao: str
    """Para o dono ouvir: "o rascunho notas.md"."""
    tipo: str
    """`lixeira` (arquivo novo → `lixeira/`) ou `retratar` (memória)."""
    alvo: str
    """O caminho absoluto do arquivo, ou o id da memória, da tarefa ou do alarme."""
    extra: str = ""
    """O que o desfazer precisa além do alvo: para onde voltar um arquivo movido, o texto que a
    área de transferência tinha."""


@dataclass(slots=True)
class RegistroDeDesfazeres:
    itens: deque[Desfazer] = field(default_factory=lambda: deque(maxlen=LIMITE_DO_REGISTRO))

    def registrar(
        self, tool_id: str, descricao: str, tipo: str, alvo: str, extra: str = ""
    ) -> Desfazer:
        desfazer = Desfazer(f"a-{uuid7()[-8:]}", tool_id, descricao, tipo, alvo, extra)
        self.itens.append(desfazer)
        return desfazer

    def achar(self, acao_id: str = "") -> Desfazer | None:
        """A pedida, ou a última. `None` se não há (ou o id não existe)."""
        if not acao_id:
            return self.itens[-1] if self.itens else None
        return next((d for d in self.itens if d.acao_id == acao_id), None)

    def retirar(self, desfazer: Desfazer) -> None:
        self.itens.remove(desfazer)


class _Campos(dict[str, str]):
    def __missing__(self, chave: str) -> str:
        return ""


def aviso_falado(
    manifesto: Mapping[str, Any], args: Mapping[str, Any], dados: Mapping[str, Any]
) -> str:
    """A frase do manifesto com os campos preenchidos — uma linha, curta, texto puro.

    O que o dono ou um arquivo escreveu entra no meio da frase: é cortado e perde quebra de linha,
    para uma frase de aviso nunca virar um parágrafo falado (nem carregar uma instrução comprida).
    """
    modelo = str(manifesto.get("aviso_falado", ""))
    if not modelo:
        return ""
    campos = _Campos()
    for origem in (args, dados):
        for chave, valor in origem.items():
            texto = " ".join(str(valor).split())
            campos[chave] = (
                texto if len(texto) <= LIMITE_DO_CAMPO else texto[:LIMITE_DO_CAMPO] + "…"
            )
    frase = re.sub(PADRAO_DE_CAMPO, lambda m: campos[m.group(1)], modelo)
    return " ".join(frase.split())[:LIMITE_DO_AVISO]
