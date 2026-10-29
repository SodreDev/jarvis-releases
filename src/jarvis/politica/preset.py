"""O portão do PDP para trocar o preset de modelo ativo (ADR-0056).

`modelo.preset` muda qual modelo responde dali em diante. Ele não liga nuvem nem cria preset — só
escolhe entre os que o dono salvou, de provedores que ele ligou —, mas a escolha é dele. As mesmas
três perguntas do vocabulário (ADR-0044), do código, nunca do modelo:

1. **Há turno do dono como origem?** Sem ele, nega.
2. **A origem é fala ou digitação do dono?** O turno de outra fonte nega.
3. **O turno leu conteúdo de terceiros?** Então o "usa o preset X" pode ter vindo de lá: pede o sim.

Fora disso, o tier decide: moderado roda sem perguntar, o Jarvis diz o preset que ficou ativo e o
dono desfaz com `acao.desfazer`. Tarefa em segundo plano nem chega aqui
(`jarvis.tarefas.gestor.FORA_DA_ALLOWLIST`).
"""

from __future__ import annotations

from typing import Final

from jarvis.politica.memoria import TRUST_DO_DONO, Proveniencia, RegraDeMemoria

FERRAMENTA: Final = "modelo.preset"


def decidir_preset(
    tool_id: str, *, proveniencia: Proveniencia | None, contaminado: bool
) -> RegraDeMemoria | None:
    """O que o PDP decide antes da matriz comum. `None` = siga o tier do manifesto."""
    if tool_id != FERRAMENTA:
        return None
    if proveniencia is None or proveniencia.turno is None:
        return RegraDeMemoria("deny", "trocar o preset sem o turno do dono como origem (ADR-0056)")
    if proveniencia.turno.trust not in TRUST_DO_DONO:
        return RegraDeMemoria(
            "deny", "o turno de origem não é fala nem digitação do dono (ADR-0056)"
        )
    if contaminado:
        return RegraDeMemoria(
            "confirm",
            "este turno leu conteúdo de fora: o pedido de trocar o modelo pode ter vindo dele "
            "(ADR-0056)",
        )
    return None


__all__ = ["FERRAMENTA", "decidir_preset"]
