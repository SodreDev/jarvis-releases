"""O portão do PDP para gravar um nome no vocabulário do dono (ADR-0044).

`vocabulario.aprender` muda como o Jarvis ouve e fala dali em diante: uma correção errada faz o ASR
trocar uma palavra em toda frase, ou o TTS falar um nome de outro jeito. Três perguntas, do código,
nunca do modelo:

1. **Há turno do dono como origem?** Sem ele, nega: a correção não é do dono.
2. **A origem é fala ou digitação do dono?** O turno de outra fonte nega.
3. **O turno leu conteúdo de terceiros** (página, arquivo, memória antiga)? Então a "correção" pode
   ter vindo de lá — uma página que diz "o certo é X" é injeção, não o dono —: pede o sim dele.

Fora disso, o tier decide: moderado roda sem perguntar, o Jarvis diz o que anotou (`aviso_falado`)
e o dono desfaz com `acao.desfazer`. Tarefa em segundo plano nem chega aqui
(`jarvis.tarefas.gestor.FORA_DA_ALLOWLIST`): o vocabulário se aprende na conversa.
"""

from __future__ import annotations

from typing import Final

from jarvis.politica.memoria import TRUST_DO_DONO, Proveniencia, RegraDeMemoria

FERRAMENTA: Final = "vocabulario.aprender"


def decidir_vocabulario(
    tool_id: str, *, proveniencia: Proveniencia | None, contaminado: bool
) -> RegraDeMemoria | None:
    """O que o PDP decide antes da matriz comum. `None` = siga o tier do manifesto."""
    if tool_id != FERRAMENTA:
        return None
    if proveniencia is None or proveniencia.turno is None:
        return RegraDeMemoria("deny", "aprender um nome sem o turno do dono como origem (ADR-0044)")
    if proveniencia.turno.trust not in TRUST_DO_DONO:
        return RegraDeMemoria(
            "deny", "o turno de origem não é fala nem digitação do dono (ADR-0044)"
        )
    if contaminado:
        return RegraDeMemoria(
            "confirm",
            "este turno leu conteúdo de fora: a correção do nome pode ter vindo dele (ADR-0044)",
        )
    return None


__all__ = ["FERRAMENTA", "decidir_vocabulario"]
