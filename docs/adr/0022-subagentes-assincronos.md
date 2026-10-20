# ADR-0022 — Subagentes assíncronos: a tarefa delegada roda num processo próprio, e cada passo dela passa pelo mesmo PDP

**Data:** 2026-10-16 · **Estado:** proposta; emendada em 2026-10-16 pelas respostas do dono e
pela ADR-0025 (ver "Emenda de 2026-10-16"); aceita como **proposta de trabalho** pelo diretor
em 2026-10-16 (D1), o dono pode revisar · **Decide:** dono
**Pedido:** ideia do dono de 2026-10-15 (memória `b63298d6`, registrada como ideia, não como
decisão): ao pedir uma tarefa longa, o Jarvis **delega**, **continua conversando**, **avisa
quando termina** e deixa o dono **acompanhar**, como um Orchestrator mínimo.

## Contexto

**O que o projeto já decidiu e esta ADR não pode quebrar:**

- P1 — o modelo propõe, o código autoriza: toda chamada de ferramenta passa pelo PDP
  (SPEC §1, ADR-0003). Um subagente que chama ferramenta por fora do PDP é exatamente o que a P1
  proíbe.
- P3 — interromper vence tudo; P5 — hipótese não é compromisso: efeito só com intenção estável
  (SPEC §1).
- §3.3 — `speech_started` incrementa o epoch e cancela a fala; tool de leitura `stale` pode
  terminar; evento de epoch velho é descartado, menos auditoria (ADR-0002,
  `src/jarvis/barramento/epoch.py`).
- §3.4 — o estado de trabalho já tem `tarefas[].estado` com
  `Draft|Planned|AwaitingApproval|Running|Observing|Succeeded|Failed|Cancelled`.
- §3.2 — a lista de tipos de evento é "v0 fechado": tipo novo é emenda à SPEC.
- `s2` é "acordado por evento, nunca em loop cego" (SPEC §2).

**O que os sistemas atuais fazem** (fontes no fim, acesso em 2026-10-16). Os quatro convergem
em seis pontos, e são esses seis que o desenho precisa ter:

| Ponto | Claude Agent SDK | MCP Tasks (extensão) | A2A 1.0.0 | LangGraph |
|---|---|---|---|---|
| id da tarefa | `agentId`/`task_id` gerado pelo runtime | `taskId` com entropia, gerado pelo servidor | `id` gerado pelo servidor, `contextId` agrupa | `thread_id` |
| estados | rodando / parcial / fim | `working`, `input_required`, `completed`, `cancelled`, `failed` | `SUBMITTED`, `WORKING`, `INPUT_REQUIRED`, `AUTH_REQUIRED`, `COMPLETED`, `FAILED`, `CANCELED`, `REJECTED` | checkpoint + `interrupt()` |
| "precisa de entrada" | — | `input_required` + `tasks/update` | `INPUT_REQUIRED` | `interrupt()` + `Command(resume=…)` |
| como o pai sabe | notificação ao terminar; em background por padrão desde o Claude Code v2.1.198 | polling `tasks/get` com `pollIntervalMs`, ou `notifications/tasks` | `GetTask`, streaming ou webhook | carrega o checkpoint |
| cancelar | `stopTask(taskId)` | `tasks/cancel`, cooperativo: "Eventual transition to cancelled is not guaranteed" | `CancelTask`, sem garantia | — |
| contenção | contexto isolado, só a mensagem final volta; teto de profundidade (padrão 3), concorrência (padrão 20) e gasto | sem `tasks/list`, para não vazar ids | — | checkpointer guarda estado e só; fila, retry e teto de concorrência são à parte |

Dois fatos pesam mais que os outros: **cancelamento é cooperativo em todos** (nenhum garante
parar), e **o Claude Agent SDK varre a mensagem final do subagente atrás de padrões de
instrução antes de o pai ler** (Claude Code v2.1.210) — o resultado de um subagente é tratado
como dado suspeito até por quem o escreveu.

## Dois desenhos comparados

**Desenho A — processo `tarefas` local, e cada passo pelo PDP.** Um oitavo processo
supervisionado guarda a fila de tarefas no SQLite e roda cada tarefa num filho. O filho é "um
`s2` sem voz": um motor de raciocínio (atrás de interface, como os motores de voz da ADR-0017)
propõe o próximo passo, e o passo vira `ToolCallRequested` no barramento, com `task_id`, para o
PDP e o executor de sempre.

**Desenho B — delegar a um agente de fora por protocolo.** O Jarvis entrega a tarefa a um
runtime externo (Claude Agent SDK em background, o Orchestrator, ou qualquer servidor com MCP
Tasks ou A2A) e só acompanha o estado por polling ou notificação.

| Critério | A — `tarefas` local | B — agente de fora |
|---|---|---|
| P1 (PDP vê toda chamada) | sim: o passo é `ToolCallRequested` nosso | **não**: as ferramentas do runtime de fora (shell, edição de arquivo) não são manifesto nosso e o PDP não as vê |
| Níveis de acesso (ADR-0009) | valem por construção | valem só se o runtime de fora respeitar; não é verificável por nós |
| Egress | só o que o motor e as tools declaram | objetivo, arquivos e contexto saem para o runtime |
| Cancelar | nós matamos o filho; o PDP para de emitir grant | cooperativo e sem garantia (todas as fontes) |
| Recursão Jarvis→Orchestrator→Jarvis | não existe | precisa do contador de saltos da ADR-0010 |
| Código nosso | fila, estados, supervisão | quase nenhum |
| Termos e fornecedor | o motor é trocável | SDK MIT, mas o uso é regido pelos Commercial Terms da Anthropic e o pacote embute a CLI do Claude Code; risco "dependência de fornecedor" da §10 |

## Decisão

**Desenho A, com o motor de raciocínio do filho trocável — e o B entra só como motor, nunca
como executor.** Quando o motor for um runtime de fora, ele roda sem nenhuma ferramenta (como o
S2 provisório da ADR-0018 já roda) e devolve só o próximo passo proposto; quem executa é o nosso
executor, depois do nosso PDP.

Regras:

1. **Delegar é capacidade tipada do núcleo**, não frase: `tarefas.delegar(modelo, objetivo,
   prazo_s)`, `tarefas.cancelar(task_id)`, `tarefas.estado(task_id?)`. `modelo` é um id de um
   **registro versionado de modelos de tarefa** (ex.: `pesquisa_leitura`), e é o modelo que fixa
   allowlist, motor, teto de passos e teto de tempo. O LLM escolhe o modelo e escreve o
   objetivo; não escreve prompt de sistema nem lista de ferramentas.
2. **A allowlist da tarefa é uma interseção e nunca cresce:** modelo de tarefa ∩ `allowed_tools`
   do turno que delegou ∩ o que o modo de acesso atual permite. Conteúdo lido pela tarefa é
   `third_party` (P6) e não muda nada disso. Profundidade 1 no v1: `tarefas.delegar` não entra em
   allowlist de tarefa nenhuma.
3. **Só nasce de intenção estável** (P5): `FinalTranscript` ou texto digitado, nunca parcial.
   Passo com efeito para em `AwaitingApproval` e a confirmação é a da §5.3, na UI; a tarefa
   espera, a conversa segue.
4. **A tarefa não pertence ao epoch da fala.** `Cancel(barge_in)` cala o "vou fazer isso" que
   estava tocando, e a tarefa continua. Cancelam a tarefa: `tarefas.cancelar`, o botão na UI, o
   botão de privacidade e o kill switch (estes dois cancelam **todas**), e a redução de nível
   (`policy_epoch` cancela chamadas em voo, §5.5). Resultado que chega depois do cancelamento vai
   para a auditoria e não entra no estado de trabalho — a mesma exceção da regra 6 da §3.3.
5. **Durável e sem ressurreição.** A tabela de tarefas guarda estado, passos, `call_id`s e o hash
   do resultado. Se o Jarvis reiniciar com tarefa `Running`, ela vira `Failed(motivo=reinicio)` e
   é anunciada; **não retoma sozinha** (P9: degradar, não improvisar). Retomar é uma delegação
   nova do dono.
6. **O resultado volta como evidência, não como instrução.** O filho devolve `resumo` +
   `evidencia[]` (os `call_id`s que o sustentam). Entra no estado de trabalho da §3.4; o texto é
   `third_party` e passa pela mesma neutralização de conteúdo que imita chamada de ferramenta que
   a saída de MCP já tem (ADR-0010 item 7). Não vira memória durável sozinho (§6.6).
7. **[Substituída em 2026-10-16 pelas regras 11–15 da ADR-0025, por decisão do dono; o texto
   original fica abaixo como histórico.]** **Avisar é na fronteira de turno, e a fala do dono vence.** Um tipo de evento novo,
   `TaskUpdate` (P3), sai **só nas transições de estado**. O `s2` anuncia a conclusão em uma frase
   quando nem o dono nem o Jarvis estão falando; `AwaitingApproval` aparece na UI na hora e é
   falado na próxima fronteira. Com "não perturbe", só a UI.
8. **Tetos:** no máximo **2 tarefas** rodando ao mesmo tempo no v1 **[SUPOSIÇÃO: confirma ou
   derruba a medição de CPU e de SLO-5 com tarefas rodando, no teste de aceite (a)]**; teto de
   passos e de tempo por modelo; teto de gasto por tarefa quando o motor é pago.
9. **Acompanhar sem laço cego.** O `s2` não consulta o estado em polling: quem publica é o
   processo `tarefas`, na transição. A UI ganha uma lista de tarefas com estado, passos e as
   entradas de auditoria de cada uma; por voz, "como está a tarefa?" é `tarefas.estado`.
10. **[Completada em 2026-10-16: o motor é configurável, ver a emenda.]** **Egress da tarefa é a união** do egress das tools da allowlist com o do motor. Motor de nuvem
    faz o objetivo e o que a tarefa lê saírem da máquina: isso é mostrado ao dono na delegação,
    como qualquer egress da §5.3.

**Emendas que esta ADR pede quando aceita:** SPEC §2 (oitavo processo, `tarefas`), §3.2 (tipo
`TaskUpdate`; `ToolCallRequested` ganha `task_id?`), §3.4 (`tarefas[]` ganha `modelo` e
`origem`) e §4 (três capacidades novas no núcleo).

## Emenda de 2026-10-16 (respostas do dono)

O dono respondeu duas das decisões que o roteiro da F2 deixava abertas (D2 e D3) e deu os
requisitos do cérebro (memória `34d72b96`). O que muda aqui, regra por regra:

- **Aviso (regra 7 → ADR-0025, regras 11–15). DECISÃO DO DONO:** o Jarvis recebe a notificação e
  decide sozinho se avisa e como; nunca corta fala; o aviso espera o TTS parar ou a próxima
  mensagem do dono e vai junto com ela; pode virar card. Nesta ADR fica só a parte do produtor:
  o processo `tarefas` publica `Notification` (ADR-0025, regra 11) nas transições `Succeeded`,
  `Failed` e `AwaitingApproval`, além do `TaskUpdate` de estado. A fila, a fronteira e o
  julgamento são da ADR-0025. O "não perturbe" da regra 7 original continua, agora na regra 14 de
  lá.
- **Motor da tarefa (regra 10 e decisão D2 do roteiro). DECISÃO DO DONO:** configurável — local
  ou nuvem, por tarefa e por cenário, com o egress mostrado —, não fixo. Desenho (do planejador):
  1. O motor da tarefa é um motor de conversa da ADR-0025 (regra 6: `gerar(contexto, modo,
     cancelado)`, com `PedidoDeTool`), registrado no mesmo portão dos motores de voz (ADR-0017):
     licença, termos, `onde` e "nuvem só se o dono ligou".
  2. Quem escolhe é a configuração do dono, não o LLM. Ordem de resolução: escolha do dono na
     própria delegação (na UI) → regra do dono por cenário → regra do dono por modelo de tarefa →
     o `motor_padrao` do modelo de tarefa, que é **local** quando existir um motor local
     registrado. O LLM que delega não passa motor; se passar, o PDP ignora e audita.
  3. Motor de nuvem para um modelo de tarefa só se o dono o ligou **para aquele modelo ou
     cenário**; ligar a nuvem para a conversa não liga para as tarefas.
  4. Na delegação, o card mostra o motor, `onde` e o que sai da máquina (o objetivo e o que a
     allowlist deixa a tarefa ler). Trocar o motor de uma tarefa em andamento não existe: é
     cancelar e delegar de novo.
- **Cérebro único (ADR-0025, regra 1):** a tarefa não é outro cérebro conversando com o dono. O
  resultado volta ao cérebro como aviso e evidência (regra 6 desta ADR, sem mudança).
- **Memória (ADR-0026, regra 1):** nenhuma tool `memoria.*` entra em allowlist de tarefa no v1.
- **Ordem:** a fatia mínima desta ADR passa para depois das fatias da ADR-0025 e da M1 da
  ADR-0026 no roteiro da F2 — sem stream e sem fila, a tarefa não tem como avisar do jeito que o
  dono decidiu.

O que **não** mudou: Desenho A, regras 1–6, 8 e 9, a fatia mínima e os testes (a)–(c), (e)–(h).
O teste (d) passa a ser o teste (d) da ADR-0025.

## Alternativas descartadas

- **Desenho B como executor** — morre na P1: o PDP não vê a chamada. Voltaria a ser
  considerado só se o runtime de fora aceitasse um PDP externo obrigatório por chamada (um hook
  autoritativo que nós controlamos), e mesmo assim os níveis de acesso dependeriam de confiar
  nele.
- **Corrotina dentro do `s2`** — mais simples, mas uma tarefa travada ou um vazamento de memória
  derrubaria o raciocínio da conversa; contraria a §2 (cada processo reiniciável sozinho) e não
  dá para matar uma corrotina no meio de uma chamada de sistema.
- **Execução durável com retomada (estilo checkpointer)** — resolve tarefa de horas que
  sobrevive a reinício, mas exige passo idempotente e determinístico em todo modelo de tarefa
  (a própria documentação do LangGraph pede isso). Volta à mesa se o uso mostrar tarefa longa
  o bastante para o reinício ser comum.
- **Profundidade maior que 1** — o Claude Agent SDK permite 3 por padrão e precisa de teto de
  gasto por causa disso. No v1 não há caso de uso que pague o custo de auditar uma árvore.

## Consequências

- Fica mais fácil: tarefa longa não segura o turno; o dono vê cada passo na auditoria, como vê
  os do turno.
- Fica mais caro: um processo novo para supervisionar, um tipo de evento novo, uma tela nova.
- Passa a ser obrigatório testar: o aviso nunca por cima da fala do dono; barge-in não mata
  tarefa; cancelamento e kill switch matam; reinício não reexecuta nada.

## Riscos

| Risco | Controle |
|---|---|
| Aviso fora de hora (fala por cima, interrompe) | ADR-0025 regras 11–15 + teste de aceite (d) de lá |
| Conteúdo lido pela tarefa sequestra o motor | allowlist fixa na criação (regra 2), efeito confirmado (regra 3), resultado é dado (regra 6) |
| Confirmação no automático ("sim, sim") | a confirmação mostra o passo concreto e o destino, como na §5.3; lote só com grant estreito |
| Contenção de CPU piora a voz | teto da regra 8; teste (a) mede SLO-2 e SLO-5 com tarefa rodando |
| Duas tarefas escrevendo no mesmo arquivo | fatia mínima só de leitura; tarefa com escrita fica para depois e precisa de trava por arquivo |
| Motor de nuvem vaza o que a tarefa leu | regra 10 e a emenda: nuvem só ligada pelo dono por modelo ou cenário, egress no card; local por padrão quando existir |

## Fatia mínima (implementar primeiro)

1. Processo `tarefas` com a tabela no SQLite, os estados da §3.4 e o evento `TaskUpdate`.
2. **Um** modelo de tarefa, `pesquisa_leitura`, com allowlist `files.search_in_roots`,
   `files.read_text`, `system.read.status`.
3. **Motor stub determinístico** (um plano roteirizado, como o stub do `s2` do F0-03): prova o
   encanamento — delegar, conversar, avisar, cancelar, reiniciar — sem LLM. O motor de verdade
   entra depois, atrás da mesma interface.
4. `tarefas.delegar`, `tarefas.cancelar` e `tarefas.estado` com manifesto e testes de contrato.
   A UI pode esperar: os testes vão pelo barramento.

## Teste de aceite

- **(a)** Tarefa stub de 60 s com leitura real; 20 turnos de conversa no meio: SLO-2 e SLO-5
  continuam dentro dos alvos da §7, medidos pelo mesmo harness da F1.
- **(b)** Barge-in em 20 pontos durante a tarefa: a tarefa continua em 20/20 e nenhuma fala de
  epoch morto toca.
- **(c)** `tarefas.cancelar`: estado `Cancelled` em até 1 s em 20/20; 0 `ToolResult` posterior
  entra no estado de trabalho (a auditoria registra todos).
- **(d)** [Passa a ser o (d) da ADR-0025, na emenda de 2026-10-16.] 50 conclusões disparadas em instantes aleatórios, com fala do dono simulada: 0 avisos
  sobrepostos à fala do dono; o aviso sai até 2 s depois da fronteira de turno seguinte.
- **(e)** Passo fora da allowlist injetado no plano do stub: negado pelo PDP em 100% dos casos e
  auditado com `task_id`.
- **(f)** Reinício do processo `tarefas` e do Jarvis com tarefa `Running`: vira
  `Failed(motivo=reinicio)`, é anunciada, nada é reexecutado.
- **(g)** Kill switch com 2 tarefas rodando: as duas `Cancelled`.
- **(h)** Varredura do registro de modelos: `tarefas.delegar` não está em allowlist de tarefa.

## Como invalidar esta decisão

- O teste (a) falha com **uma** tarefa rodando, e baixar prioridade do filho não resolve: o
  trabalho pesado do motor tem de sair da máquina, e o desenho volta a ser discutido junto com o
  egress.
- O dono passa a pedir tarefas de horas que precisam sobreviver a reinício: a alternativa de
  execução durável volta.
- Um runtime de fora passa a aceitar PDP externo obrigatório e verificável por chamada: o
  Desenho B como executor pode ser medido contra o A.

## Fontes (acesso em 2026-10-16)

- Claude Agent SDK, "Subagents in the SDK": <https://code.claude.com/docs/en/agent-sdk/sub-agents>
  — background por padrão desde v2.1.198, tetos de profundidade/concorrência/gasto, varredura da
  mensagem final desde v2.1.210.
- Claude Agent SDK para Python, licença MIT e Commercial Terms:
  <https://github.com/anthropics/claude-agent-sdk-python>
- MCP Tasks, extensão `io.modelcontextprotocol/tasks` (SEP-2663, fora do núcleo na revisão
  2026-07-28): <https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks> e
  <https://modelcontextprotocol.io/specification/2026-07-28/changelog>
- A2A 1.0.0, especificação: <https://a2a-protocol.org/latest/specification/>
- LangGraph, execução durável: <https://docs.langchain.com/oss/python/langgraph/durable-execution>;
  limite do checkpointer (fonte secundária):
  <https://hackernoon.com/durable-execution-for-ai-agents-langgraph-dbos-inngest-and-temporal-compared>

## Emenda de 2026-10-20 — memória de trabalho da tarefa (ADR-0034)

O motor `agente` monta o contexto de cada passo da tarefa pelo mesmo orçamento do cérebro: o
resultado mais novo inteiro, os antigos inteiros enquanto couberem e, depois, podados. Os passos
continuam morrendo com a tarefa — só o resumo final fica.

## Emenda de 2026-10-20 — o objetivo da tarefa (ADR-0030, emenda C2)

Cada tarefa nasce com o objetivo dela (a descrição), com critério de pronto, fase e passos: o PDP o
usa nas chamadas da tarefa, e o motor `agente` segue até o critério estar cumprido e conferido,
dentro do teto de passos, do prazo e do cancelar.

