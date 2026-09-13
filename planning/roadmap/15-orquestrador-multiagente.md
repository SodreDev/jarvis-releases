# 15 — Orquestrador multi-agente + sub-agentes + "JARVIS modelo próprio"

> **Status: Fase 3 IMPLEMENTADA** (2026-06-22) — roteador de domínio + escopo de tools.
> Demais fases em DESIGN. Tudo atrás de toggles **OFF**; o orquestrador **envolve** o
> `_pensar_e_agir` (nunca o reescreve) e o comportamento atual é o fallback universal.
>
> **Fase 3 entregue**: `jarvis/agents/{registry,router}.py` (roteador MiniLM por domínio
> documentos/web/midia/sistema/mensageria/visao/jogos) + escopo de tools em
> `_filter_tools_for_text` (manda ~5-9 tools do domínio em vez de 44 → mata o 413) +
> dica de domínio no prompt + toggle visual "Sub-agentes" + casos no `tools/eval_tools.py`
> (roteador 13/13). Bugs do log corrigidos junto: provider do cérebro agora respeita
> "Provider — Chat" da UI (`get_provider('chat')`); 413 re-tenta o primário com payload
> reduzido (passo 0); respostas mais curtas (regra dura de tamanho + chat-fallback 120 tok).
>
> --- design original abaixo ---
> Tudo entrará atrás de toggles **OFF por padrão**; o orquestrador **envolve** o
> `_pensar_e_agir` (nunca o reescreve) e o comportamento atual é o fallback universal.

## Visão (o que o usuário quer)
Tornar o JARVIS um **modelo próprio coerente** que **orquestra sub-agentes** que ele
chama — estilo Claude/Anthropic — usando o **embedding semântico** (MiniLM já carregado)
como roteador barato, mantendo barato/local sempre que possível.

## Princípio central (consenso da pesquisa)
**NÃO** tornar todo turno multi-agente. Multi-agente custa **4–15× tokens** (Anthropic) e
sub-agentes que não compartilham contexto tomam decisões conflitantes (Cognition, "Don't
build multi-agents"). A jogada certa é um **roteador de complexidade** na frente do
`_pensar_e_agir` que escala o esforço por turno, e só vai a multi-agente quando vale.

## Os 4 tiers (roteador de complexidade — Pilar 1)
| Tier | Quando | Execução | Custo |
|---|---|---|---|
| **CHAT** | conversa/pergunta (0 ação) | caminho de chat atual | ~1× |
| **SINGLE** | 1 ação óbvia | fast-path / 1 tool | ~1× |
| **REACT** | sequência num domínio | `_pensar_e_agir` atual (loop) | ~1× |
| **SUPERVISE** | multi-domínio/composto ("faz X e Y e me manda Z") | decompõe → sub-agentes | 4–15× |

Roteador = **MiniLM** (reusa `classifiers.embeddings.get_classifier()._model`, ~5ms, **zero
rede/LLM**), âncoras por tier, `conf < limiar` → **fallback TIER_REACT** (= comportamento de
hoje, nunca regride). Margem top1-top2 baixa → pedir esclarecimento (mesmo truque do
`MEMORY_TRIAGE_MARGIN`).

## Pilares da arquitetura
1. **Roteador de complexidade** — `jarvis/agents/router.py` (clone de `jarvis/memory/router.py`).
   Devolve `{tier, domain, needs_history, needs_memory, is_destructive, conf}`.
2. **Especialistas = TOOL_LAYERS** — `jarvis/agents/registry.py`. Cada sub-agente =
   `(bloco de prompt do domínio + subconjunto de tools via tools_in_layers([layer]) + CORE)`.
   Domínios iniciais espelhando as layers: `pesquisa/web, documentos, sistema, midia,
   mensageria, visao, jogos, memoria`. **Sem processos novos**: o orquestrador "vira" o
   sub-agente trocando *prompt + tools* no mesmo motor `_pensar_e_agir`. **1 nível de
   profundidade** (sub-agente não gera sub-agente).
   - ⭐ **Este pilar, sozinho, resolve o 413 de forma ESTRUTURAL**: manda ~5–8 tools em vez
     de 44, e melhora a seleção (menos distratores → menos "conversa vira tool errada").
3. **Orquestrador / lead** — `jarvis/agents/lead.py`. Só atua em TIER_SUPERVISE: **1 chamada
   barata de planejamento** (Groq/OpenRouter) emite um plano JSON
   `[{especialista, objetivo, formato, deps}]`, persiste o plano na memória (`store.py`),
   roda independentes em paralelo (`ThreadPool` width 2–3, **só nuvem**), dependentes em
   sequência; cada sub-tarefa = `_pensar_e_agir` escopado devolvendo um **resumo curto**
   (não o trace cru). Síntese final na voz do JARVIS via `compaction.py`.
4. **Identidade read-only** — `jarvis/memory/identity.py` (`data/memory/identity.json`:
   persona/human/style). Cabeçalho re-injetado no system do orquestrador **e de cada
   sub-agente** (ID-RAG) — mantém a voz coerente; sub-agente nunca reescreve a persona core.
5. **Memória como estado** — já existe (`jarvis/memory/*`): recuperação por política injeta
   `[Memórias relevantes]` em cada sub-agente; escrita via `ingest_turn` no fim do turno;
   reflexão sleep-time (roadmap/14 Fase 7) consolida episódico→semântico fora do caminho de resposta.

## Local vs nuvem
Roteador + memória + identidade + embeddings = **100% local**. TIER_CHAT/SINGLE → LM Studio
local quando houver. Planejamento + fan-out de sub-agentes = **nuvem (OpenRouter Auto/Groq),
só em SUPERVISE** (único tier onde 4–15× se justifica). Toda chamada herda a cadeia de
fallback + redução de payload no 413 já existentes.

## ⭐ Esclarecimento: o cérebro semântico JÁ é LOCAL e NOSSO
O `MiniLM` (`classifiers/embeddings.py`) **não roda via API** — ele roda **100% local**
na CPU (~90 MB RAM, ~5 ms/query). O "Warning: sending requests to HF Hub" era só a
checagem do cache **no carregamento** (1×), não por consulta. **Corrigido**: agora carrega
`local_files_only=True` (cache-first, **zero rede/warning**; só baixa no 1º uso) e aceita
`JARVIS_EMBED_MODEL` para trocar o modelo. Ou seja: o roteador semântico (intenção +
política de memória + triagem + futuro roteador de complexidade/domínio) já é um **modelo
local que podemos ajustar e melhorar** — exatamente o que você quer. Cabe folgado nos
200–600 MB de RAM que você liberou.

### Escada de "modelo próprio" do roteador (barata → avançada)
1. **Agora — mais exemplos-âncora** (`_INTENT_EXAMPLES`, `router_examples`, `_CATEGORY_ANCHORS`):
   cada frase a mais melhora o acerto. Zero custo, ajuste contínuo com os logs reais.
2. **Destilação `model2vec`/potion** do PRÓPRIO MiniLM: gera um modelo **estático nosso**
   (~30 MB, 100–500× mais rápido, CPU), destilado **offline em ~30s, sem GPU, sem dataset**.
   Vira o roteador do caminho quente; MiniLM fica na memória (recall fino).
3. **SLM local pequeno via LM Studio** (opcional) para roteamento/persona quando quiser mais
   nuance que embeddings — ainda local.
4. **LoRA/fine-tuning** só se as métricas pedirem, e **nunca na persona** (prompt+RAG/ID-RAG
   supera FT em consistência de voz). Gate: harness de eval estável + volume real.

O ponto: já temos a base de um **modelo local treinável**; a "posse" cresce pela escada
acima, medida por `tools/eval_tools.py` (+ um futuro `eval_router.py`). Sem depender de nuvem
para DECIDIR — a nuvem só EXECUTA quando o tier justifica.

## Confiabilidade de roteamento (o "probleminha" dos logs)
- **Fake "está sendo gerada"**: o respondedor de contexto ambiente era usado como fallback e
  fingia execução. **Corrigido** com regra anti-simulação (nunca diz que fez/gerou algo que
  não executou — admite honestamente). Soma-se ao `_CHAT_FALLBACK_SYSTEM` e ao fim do
  "Pronto, Senhor" falso. **Nenhum caminho do cérebro pode mais alucinar execução.**
- **Tool não disparou** (cérebro voltou vazio do Auto Router): o **escopo de tools por domínio
  (Fase 3)** ataca isso na raiz — manda só as ~5-8 tools do domínio "documentos" + um prompt
  focado, o que aumenta muito a chance de o modelo chamar `criar_apresentacao`. Reforço extra
  (Fase 2 do orquestrador): em resposta vazia da nuvem, **re-tentar 1× no Groq real COM tools**
  antes de qualquer fallback conversacional.

## "Modelo próprio": qual caminho
Recomendado: **(a) prompt-orquestração** (persona-core + roteador + sub-agentes com modelos
cheap/locais por tarefa) — melhor custo/manutenção/consistência. **(b) router-as-model**
(model2vec/potion no caminho quente do roteador) só se latência pedir. **(c) fine-tuning/
LoRA**: NÃO agora — para 1 usuário com prompt+RAG funcionando, FT adiciona GPU/dados/risco
sem ganho proporcional; **para PERSONA, prompt+RAG (ID-RAG) supera FT**. FT só entra depois,
com harness de eval + volume real, e nunca na persona.

## Plano em fases (todas atrás de toggle OFF; `py_compile` + eval no CI a cada passo)
0. **Config + eval** — toggles `AGENT_ORCHESTRATOR_ENABLED=False`, `AGENT_COMPLEXITY_THRESHOLD`,
   `AGENT_MAX_SUBAGENTS=2`, `AGENT_SUPERVISE_MIN_CONF`, `IDENTITY_ENABLED=False`. Estender
   `tools/eval_tools.py` com casos `{utterance → tier/domínio esperado}`.
1. **Roteador (log-only)** — `jarvis/agents/router.py`; só **LOGA** o tier previsto junto do
   `[EMBED]`, sem rotear nada. Calibrar âncoras com turnos reais. **Risco zero.**
2. **Wire dos tiers** — `_orquestrar(text)` chamado na entrada texto/voz; CHAT/SINGLE/REACT →
   caminhos de HOJE (saída idêntica), só SUPERVISE é novo. Opt-in e comprovadamente sem regressão.
3. **Especialistas (escopo de tools)** — `registry.py`; fatiar `_TOOL_SYSTEM_PROMPT` em
   `PERSONA_CORE` (persona+proibições+modo-voz+conversa≠comando) + blocos por domínio; threadar
   `only_layers=[...]` no `_filter_tools_for_text`. **(Resolve o 413 estruturalmente.)**
4. **Decomposição (SUPERVISE)** — `lead.py`: `_planejar(text)→plano JSON` (reusa salvage JSON),
   ThreadPool `max_workers=AGENT_MAX_SUBAGENTS`, caps de passos/timeout.
5. **Síntese + higiene de contexto** — coleta digests, compõe na voz; passa o contexto do lead
   por `compaction.mask_tool_outputs/summarize_turns`.
6. **Identidade read-only** (Pilar 4) + telemetria de custo (tier, #sub-agentes, #LLM, ~tokens).
7. **Roteador rápido (opcional)** model2vec/potion no caminho quente; **FT só se métricas pedirem**.

## Riscos & mitigação (resumo)
- **Custo 15×** → gate estrito pelo roteador + `min_conf` + cap de sub-agentes + OFF por padrão.
- **Misrouting** → `conf<limiar`→REACT (nunca o tier mais barato na dúvida); Fase 1 log-only p/ calibrar.
- **Decisões conflitantes** → só paraleliza tarefas `deps==[]`; o resto colapsa em 1 REACT (contexto único).
- **Recursos locais** → paralelo só na nuvem; LM local segue serializado (`_lm_pensar_sem`).
- **413 amplificado** → herda payload-reduce + (melhor) o escopo de tools da Fase 3.
- **Drift de identidade** → bloco persona read-only re-injetado em todo sub-agente.
- **main.py god object** → orquestrador vive em `jarvis/agents/*`, chamado do `_pensar_e_agir`; edições ≤2 funções.

## Ganho mais rápido
A **Fase 3 (escopo de tools por domínio)** é o maior ROI imediato: corta o 413 na raiz,
melhora a precisão de seleção e reduz "conversa vira tool errada" — e é pré-requisito barato
do resto. Pode ser feita **antes** da orquestração completa.

## Fontes (2026)
Anthropic *multi-agent research system* / *writing tools for agents*; Cognition *Don't build
multi-agents*; OpenAI Agents SDK (handoffs); LangGraph (supervisor); vLLM Semantic Router;
Letta (memory blocks read-only); ID-RAG (persona via RAG > FT). (URLs nos outputs da pesquisa.)
