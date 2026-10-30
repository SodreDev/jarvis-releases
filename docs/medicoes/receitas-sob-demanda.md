# Receitas sob demanda: o custo por pedido-tipo (2026-10-30)

Medido por `tools/medir_receitas.py` (sem rede, sem modelo). Tokens: multilingual-e5-small. Tempo: escolher o método e montar o bloco, 200 repetições.

**Antes:** o prompt de sistema de todo turno era só persona + regras + catálogo (`docs/medicoes/prompt-do-turno.md`: 15 971 caracteres, 4 705 tokens e5 em 30/10). **Depois:** o mesmo prompt-base em todo turno — as receitas não entram nele — e, só no turno de um assunto com ferramenta, o bloco abaixo.

| pedido | método | famílias | caracteres | tokens | escolha p50 (µs) | p95 (µs) |
|---|---|---|---:|---:|---:|---:|
| abre o canal do Thiago Nigro no YouTube e toca o último vídeo | navegador | navegador | 899 | 269 | 150 | 167 |
| clica no botão de inscrever | conversa | navegador | 899 | 269 | 192 | 208 |
| abre o console da página e vê o erro | conversa | navegador | 899 | 269 | 124 | 138 |
| pesquisa quem ganhou o jogo do Flamengo ontem | web | web | 472 | 141 | 169 | 185 |
| abre o Discord | app | app | 498 | 162 | 168 | 183 |
| aperta enter | entrada_virtual | entrada, app | 696 | 216 | 14 | 15 |
| lembra que eu prefiro café sem açúcar | memoria | memoria | 441 | 130 | 196 | 211 |
| aumenta o volume | sistema | sistema | 289 | 82 | 146 | 159 |
| calcula 15% de 2380 com um script | subagente | delegar, script | 508 | 142 | 186 | 198 |
| usa o preset rápido | conversa | preset | 293 | 87 | 175 | 188 |
| aprende que se escreve Kubernetes | conversa | vocabulario | 258 | 74 | 191 | 205 |
| delega isso para o Claude Code | conversa | delegar | 316 | 87 | 188 | 202 |
| bom dia, tudo bem? | conversa | — | 0 | 0 | 169 | 183 |
| me conta uma piada | conversa | — | 0 | 0 | 169 | 182 |

Média nos turnos com receita: 161 tokens a mais; conversa: 0. Escolher o método e montar o bloco leva no máximo 196 µs (p50) — regras locais; o classificador de decisão só entra no pedido com verbo de ação que as regras não reconheceram, e nunca no turno de conversa.

**Latência do modelo:** não medida — nenhuma chamada a modelo de verdade nesta medição. O que muda para o modelo é só o prefixo de entrada do turno com ferramenta (a tabela).
