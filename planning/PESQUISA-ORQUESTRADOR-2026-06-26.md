# Pesquisa — Orquestrador eficiente (copilots / workflows) · 2026-06-26

**Origem:** deep-research harness (24 fontes → 119 claims → 25 verificados adversarialmente →
**17 confirmados**, 8 refutados/abstidos). Síntese feita à mão (o passo automático de síntese
bateu o limite de sessão). Fontes primárias = arXiv/ICLR. **Ressalva honesta:** as claims de
**cascata de modelos** (FrugalGPT 2305.05176, RouteLLM) ficaram *abstidas* — não verificadas por
causa do limite, **não confirmadas** aqui (revisitar no reset).

## Manchete

O JARVIS **já tem os ossos**: roteador semântico (OFF), loop maduro, memória em 8 camadas. A
pesquisa aponta o **maior lever de custo+acerto**: **recuperação SEMÂNTICA de tools** (mandar só o
subconjunto certo, não todas). Com **1 ressalva crítica (Gorilla): um retriever RUIM é PIOR que
mandar tudo.** Logo a regra de ouro é **calibrar → só então ligar**. E a **Nila (modelo pequeno)
tem um papel certo: estágio roteador DETERMINÍSTICO**, não gerente autônomo do próprio contexto de
tools — MemTool prova que modelos pequenos falham nisso.

---

## Área 1 — Reduzir custo de API / seleção de tools

| Padrão | Fonte | Número-chave |
|---|---|---|
| Retrieval semântico sobre índice externo (passa só tool relevante) | **RAG-MCP** [2505.03275](https://arxiv.org/abs/2505.03275) | filtrar **triplicou** o acerto (43,1% vs 13,6%); motivação = "prompt bloat" |
| Agente pede tools sob demanda + roteamento hierárquico 2-estágios (req→servidor→tool) | **MCP-Zero** [2506.01056](https://arxiv.org/abs/2506.01056) | **−98% tokens** no APIBank |
| Retriever denso Sentence-BERT (contrastive) | **ToolLLM** [ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/file/28e50ee5b72e90b50e7196fde8ea260e-Paper-Conference.pdf) | NDCG@1 **78** vs ada 49,6 vs BM25 18,5; retriever aprendido ≈ oracle (pass 67,3 vs 66,7 → **perda de acerto ao filtrar ≈ 0**) |
| ⚠ Retriever NÃO-ótimo **degrada** o acerto e induz MAIS erros | **Gorilla** [2305.15334](https://arxiv.org/abs/2305.15334) | −21,5pt TorchHub, −47pt HuggingFace → **qualidade do retriever é o gargalo** |
| Vector DB de tools enriquecidas | **Toolshed** [2410.14594](https://arxiv.org/abs/2410.14594) | — |

**JARVIS hoje:** default = filtro **keyword** (`main.py::_filter_tools_for_text`) — frágil: se nenhuma
keyword bate, manda **todas** as tools → 413 / tool certa não destacada. Roteador semântico MiniLM
**existe** (`jarvis/agents/router.py`) mas **OFF**. `SkillMemory.retrieve_tool_names` (Fase 3) pronta,
**não plugada**.

**Ação:** calibrar roteador+SkillMemory via `tools/eval_tools.py` (gate de qualidade — Gorilla) →
plugar `retrieve_tool_names` no `_filter_tools_for_text` como **default semântico**, com fallback
"manda tudo" **só** em baixa confiança. Atrás de `SKILL_MEMORY_ENABLED`. **Calibrar ANTES de ligar.**

---

## Área 2 — Loop auto-iterativo (chamar tools várias vezes, recuperar de erro)

| Padrão | Fonte | Número-chave |
|---|---|---|
| **DFSDT** (árvore com backtracking) > ReAct | **ToolLLM** [ICLR 2024] | pass **63,8 vs 35,3** (ReAct); maior ganho em multi-tool |
| **ReWOO / Plan-Execute** (planeja tudo antes → menos chamadas ao LLM grande) | [LangChain](https://www.langchain.com/blog/planning-agents) | ReWOO **5x** token-efficiency, +4% HotpotQA vs ReAct |
| **90,8% das retentativas são desperdiçadas** em falhas NÃO-retentáveis (tool alucinada/inexistente) | [TDS](https://towardsdatascience.com/your-react-agent-is-wasting-90-of-its-retries-heres-how-to-stop-it/) | não retente tool inexistente |
| Teto duro de passos + RetryPolicy (backoff exp) | **LangGraph** [docs](https://docs.langchain.com/oss/python/langgraph/fault-tolerance) | `recursion_limit` → erro `GRAPH_RECURSION_LIMIT` |
| Auto-melhora por feedback verbal (sem treinar pesos) | **Reflexion** [2303.11366](https://arxiv.org/abs/2303.11366) | — |

**JARVIS hoje:** **maduro** — `MAX_STEPS`+`STEP_TIMEOUT_S` (orçamento), anti-loop dedup (mesma
tool+args → corta), **auto-correção ancorada** (em erro injeta instrução de recuperação = Reflexion
*dentro* do turno), fallback LM→Groq, atalhos single-step, e "emita TODAS as tool_calls de uma vez"
(sabor ReWOO).

**Ação:** (a) **guard de existência de tool antes de retentar** (mata o 90,8%); (b) **memória de
erro ENTRE turnos** — persistir falhas na camada Erros e injetar no prompt do roteador/loop (Reflexion
*entre sessões* = "aprende com erro" que a Nila já faz no domínio dela); (c) DFSDT é ganho real mas
pesado → **adiar** (dedup+correção já cobrem parte).

---

## Área 3 — Memória como tools

| Padrão | Fonte | Essência |
|---|---|---|
| Ops de memória como **tool calls** (editar working memory, search/evict entre tiers) | **MemGPT** [2310.08560](https://arxiv.org/abs/2310.08560) | paginação OS: core=RAM, archival/recall=disco |
| **Memory blocks** (core sempre visível, sem retrieval) + **sleep-time agent** (consolidação ASSÍNCRONA em background) | **Letta** [docs](https://docs.letta.com/guides/agents/architectures/sleeptime/) | consolida fora do request |
| save / search / forget como tools comuns | [Agent_Memory_Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) | — |

**JARVIS hoje:** `memoria_buscar/salvar_fato/esquecer` + `aprender_sobre` + 8 camadas (inclui Erros,
Meta auto-descritiva). Já é "memória-como-tool".

**Ação:** (a) **core memory block curto** (perfil do Senhor + Meta) sempre visível no prompt — barato,
evita re-buscar; (b) **consolidação em background** (estilo sleep-time) fora do turno — condensa
Aprendizados/Erros sem travar a resposta; (c) falta o loop/Nila **CONSULTAR** a camada Erros.

---

## Área 4 — Contexto curto p/ a Nila orquestrar

| Padrão | Fonte | Implicação p/ a Nila |
|---|---|---|
| ⚠ Modelos pequenos/não-reasoning **FALHAM em podar o próprio contexto de tools** (cresce até o teto) | **MemTool** [2507.21428](https://arxiv.org/html/2507.21428v1) | Nila = **estágio determinístico (Workflow mode)**, NÃO gerente autônomo |
| Roteamento hierárquico 2-estágios (categoria→tool) | **MCP-Zero** | casa com `router.route()→domínio` + `registry.tool_names(domínio)` que já existem |
| Embedder pequeno **task-tuned** > embedder grande genérico | **ToolLLM** | Nila/MiniLM local é a escolha certa p/ o estágio-1 |

**Divisão de trabalho recomendada:**
`Nila/MiniLM (estágio 1, determinístico)` → roteia domínio + recupera ~6-8 tools →
`LLM nuvem (Groq/OpenRouter, estágio 2)` → raciocina e chama as tools. Schemas de tool enxutos no payload.

**Ação:** manter a Nila como **roteador determinístico** (é o `router.py` + SkillMemory). Treino
futuro da Nila = **melhorar o estágio-1** (roteamento/embeddings), **não** torná-la o orquestrador
autônomo do contexto.

---

## Plano priorizado (conservador · toggles OFF · calibrar-antes-de-ligar)

1. **Calibrar** roteador semântico + SkillMemory via `tools/eval_tools.py` (gate de qualidade —
   Gorilla). Sem passar no gate, **não ligar**.
2. **Plugar SkillMemory no `_filter_tools_for_text`** (Fase 3), atrás de `SKILL_MEMORY_ENABLED`, com
   fallback "tudo" em baixa confiança. → resolve o "payload redutor".
3. **Guard de tool inexistente antes de retentar** (mata 90,8% de retry desperdiçado).
4. **Memória de erro entre turnos** (camada Erros consultada pelo loop/roteador).
5. **Core memory block curto** (perfil+Meta) + **consolidação em background**.
6. *(futuro)* DFSDT; treino da Nila no estágio-1; revisitar cascata de modelos (FrugalGPT/RouteLLM,
   ficou abstida).

**Invariantes:** edição direta sem commit · Nila nunca no GitHub · Nila confidencial (não propagar
arquitetura) · config do modelo vem do usuário · CPU 6-8 threads · toggles OFF por padrão.

---

## STATUS de implementação

- **Etapa 1 — CALIBRAÇÃO ✅ (2026-06-26).** Roteador: sweep `thr×margem` (novo `eval_tools.py --calibrate`)
  → `AGENT_SUBAGENT_THRESHOLD=0.45`, `AGENT_SUBAGENT_MARGIN=0.03` → **acc 0.95, 0 misrotas** (era 0.93
  @0.06; margem é o knob, thr não afeta o gold). SkillMemory: `eval_tools.py` ganhou eval de **recall@k
  (gate ≥0.85)** + 5 situações curadas genéricas → **recall@8 0.94→0.97** (34/35; o 1 miss = "lofi pra
  estudar", o MiniLM não liga a música). **Achado:** o top-score NÃO separa conversa (pontua 0.44-0.65 ≈
  pedidos reais) → `SKILL_MEMORY_FLOOR` é só guarda de match nulo, não detector de conversa; escopar
  conversa é inofensivo. Guardrail PASS, toggles OFF.
- **Etapa 2 — WIRE SkillMemory ✅ (2026-06-26).** Bloco semântico em `main.py::_filter_tools_for_text`
  (atrás de `SKILL_MEMORY_ENABLED`, OFF; depois do roteador de domínio e do modo "all"): build lazy do
  índice → `retrieve(text,k)` → `core + top-k` → fallback keyword/all se `top<FLOOR`. Novo
  `SKILL_MEMORY_FLOOR=0.30` no config. Sim de integração: **45 tools → 5-8** com a tool certa presente em
  5/5. Guardrail PASS.
- **Fix CONTEXT-BLOAT / alucinação-após-N-memórias ✅ (2026-06-26, via workflow map+design, 6 agentes).**
  Causa-raiz mapeada: (a) VAZAMENTO — `_pensar_e_agir` nunca grava `_chat_history` → turnos de AÇÃO ficam
  invisíveis aos próximos → "de novo"/"fecha ele"/"esse PDF" alucinam; (b) `compaction.py` com ZERO call
  sites → contexto incha e o 413 trata DESTRUINDO o histórico; (c) roteamento por prosa (regras 1/1b
  corridas); (d) ranking semântico de tools era descartado. **ACHADO:** as prefs do dono têm
  `MEMORY_ENABLED=True` + `MEMORY_COMPACTION_ENABLED=True` (`_aplicar_prefs_agente`) → a memória semântica
  JÁ injeta contexto a cada turno (a FONTE do incho) e a compactação estava morta. **6 mudanças, TODAS
  atrás de toggle OFF/dedicado:** `_CASE_BLOCKS_TEXT` (CASO A/B/C/D + NUNCA-AJA; prepend gated
  `AGENT_CASE_BLOCKS`) · hint semântico de tools no system (`SKILL_MEMORY_HINT`, reusa o ranking da
  SkillMemory — o modelo CONSULTA por significado) · write-back de turnos-com-tool no `_chat_history`
  (`AGENT_TOOL_HISTORY_WRITEBACK`; leitura via `AGENT_INCLUDE_HISTORY`) · compactação no loop vivo +
  413-não-destrutivo (`MEMORY_COMPACT_IN_LOOP` DEDICADO, separado das prefs p/ não ligar sozinho).
  Verificado headless: guardrail PASS, unit de compactação (preserva path/URL/ERRO, libera tokens),
  gating (OFF→byte-idêntico / ON→casos+hint), eval sem regressão. Persona drift (5 defs "Você é JARVIS")
  NÃO tocado (fora de escopo, tarefa separada).
- **Ativação FEITA (2026-06-26, a pedido do dono):** par seguro (`AGENT_CASE_BLOCKS`,
  `MEMORY_COMPACT_IN_LOOP`) + frente A (`SKILL_MEMORY_ENABLED`, `SKILL_MEMORY_HINT`) ligados via
  `credentials/jarvis_prefs.json` (seção `agent`, chaves `case_blocks`/`compact_in_loop`/`skill_memory`/
  `skill_memory_hint`) + mapeados em `config._aplicar_prefs_agente`. **Source defaults seguem OFF**
  (invariante de release intacto; guardrail PASS). ACHADO: as prefs do dono têm `brain_mode=total` → o
  filtro de tools manda TUDO (modo "all"), logo o FILTRO semântico fica inerte e o hint-acoplado-ao-filtro
  não rodaria; por isso DESACOPLEI o hint (computa o próprio `retrieve`) → funciona em QUALQUER modo.
  Verificado: 4 flags True em runtime; hint produz as tools certas. Continuidade
  (`AGENT_TOOL_HISTORY_WRITEBACK`) segue OFF (delicada; `include_history` já está ON, então só falta o
  write-back). NOTA p/ o dono: `brain_mode=total` envia 45 tools/turno (custo alto) — trocar p/ `layered`
  ativaria a redução do filtro semântico (45→~8 tools); decisão dele.
- **Próximo:** etapa 3 (guard de tool inexistente antes de retentar — mata 90,8% retry) · etapa 4
  (memória de erro entre turnos) · etapa 5 (core memory block + consolidação background).
