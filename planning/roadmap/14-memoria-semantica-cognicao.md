# 14 — Memória semântica/vetorial + orquestrador + cognição humana (design)

> **Status**: DESIGN / futuro. Nenhuma implementação ainda — este doc organiza a visão do
> usuário e o plano fundamentado em pesquisa (Generative Agents, MemGPT/Letta, Mem0,
> Reflexion, LightMem 2026, semantic-router). Tudo entra atrás de toggle OFF (regra do `00-INDEX`).

## Visão (do usuário)

Tornar o JARVIS mais "humano" (não replicar pensamento humano), com:
- **Memória semântica/vetorial** rápida, residente em RAM (~200-500 MB), quase instantânea.
- Um **orquestrador semântico** leve que roda local, decide rota/tool/provider e atua como
  tomador de decisão — permitindo que os submodelos de provedores (pesquisa/geração/imagem/
  busca) sejam **alternativas**, e que esse orquestrador coordene tudo de forma leve.
- **Aprendizado contínuo** (ingerir conteúdo novo) + personalidade/psicologia persistente.
- **Contexto adaptativo**: hoje rende bem com ~4 msgs; com provedores externos dá p/ usar
  200k-1M conforme o limite do modelo carregado, ajustando-se sozinho ao provedor.

## Pilar 1 — Memória vetorial residente em RAM

- **Embedder**: reusar o `all-MiniLM-L6-v2` (384-dim, ~80 MB, ~5 ms) que já está em
  `classifiers/embeddings.py` como QUALIDADE; **adicionar** um embedder ESTÁTICO rápido p/ o
  caminho quente (PT-BR): **model2vec `potion-multilingual-128M`** (256-dim, velocidade
  80-500x, sem torch no inferência). 
- **Índice**: NÃO adicionar vector DB pesado. Manter o padrão que já existe
  (`comandos/memoria_contatos.py` faz matriz `numpy` float32 + cosseno top-k). Até ~100k
  vetores um matmul é <10 ms (100k×384 f32 ≈ 147 MB; f16 ≈ metade). Só migrar p/ `hnswlib`/
  `usearch` acima de ~100-500k vetores.
- **O que guardar (taxonomia CoALA)**: episódica (conversa + resultados de tools, com
  timestamp), semântica (fatos sobre o usuário — padrão Mem0 extract→update p/ não duplicar),
  procedural (rotinas/skills aprendidas), e nós de **resumo/reflexão**.
- **Recuperação**: score composto (Generative Agents) = `a*recência(decay) + b*relevância(cos)
  + c*importância`, depois **MMR** (λ≈0.6) p/ diversidade; filtros de metadado antes.
- **Persistência**: `np.save/np.load` (já usado). Tudo em `jarvis/memory/` (stub já existe).

## Pilar 2 — Orquestrador semântico (router + decisor leve)

- Padrão **semantic-router** (aurelio): pré-computar embeddings de "rotas" e comparar por
  cosseno em <10 ms, 100% local/offline, com limiar de confiança e **fallback p/ LLM**. O
  `_EmbeddingClassifier` de `classifiers/embeddings.py` **já é exatamente esse padrão** —
  generalizar p/ também devolver `{provider, model, tool_layer, needs_history, est_tokens, tom}`.
- Decide: responder direto vs chamar o LLM grande; qual tool/camada; qual provedor/modelo
  (curto/baixa-latência → local/Groq; longo/complexo → nuvem OpenRouter). Casa com o **modo
  "cérebro total"** já implementado (roadmap/13) — o orquestrador é a versão leve que entende
  contexto ANTES de decidir, evitando disparar comando exato fora de contexto.

## Pilar 3 — Contexto adaptativo (4 → 200k-1M)

- Novo `jarvis/llm/context_budget.py`: `resolve_limits(provider, model)` → (max_ctx,
  max_completion, tokenizer): OpenRouter via `GET /api/v1/models` (`top_provider.context_length`,
  cache 24h em `data/memory/model_limits.json`); LM Studio via probe existente; Groq via dict.
- `ContextBudgeter.assemble()` com **orçamento por prioridade**: persona/sistema > identidade/
  preferências > memórias recuperadas (MMR) > resumo rolante > N turnos verbatim. `effective_ctx
  = max_ctx * 0.5`; compacta quando uso > 0.65; conta tokens (tiktoken / chars÷4 + margem).
- Substituir o cap fixo (`HISTORY_LIMIT=21` no `jarvis/llm/client.py` e o cap de
  `_chat_history`) por janela adaptativa: poucos turnos em modelo local 8k → janela grande +
  retrieval em modelo de nuvem 200k-1M. (Hoje já há um passo: histórico maior em nuvem — ver
  `AGENT_HISTORY_TURNS_CLOUD`.) Em loops de tool, **mascarar observações antigas** (resultados
  de tool já consumidos viram placeholder) p/ liberar tokens.

## Pilar 4 — Cognição humana (sem replicar pensamento)

- **Personalidade em 3 camadas**: persona fixa no system prompt (já existe em
  `config.SYSTEM_PROMPT`) + **blocos editáveis** (padrão Letta: `persona` e `human`,
  `read_only` p/ a identidade — anti-drift) + 2-3 few-shots de tom. Re-injetar identidade a
  cada request (ID-RAG) reduz drift (medido +25% consistência).
- **Reflexão/consolidação** (Generative Agents + Letta "sleep-time"): num **heartbeat ocioso**
  (sem mensagem do usuário), sintetizar episódico→semântico, reescrever blocos, dedupe — fora
  do caminho de resposta (mantém latência baixa; LightMem ~83 ms retrieval, ~581 ms e2e).
- **Aprendizado contínuo**: ingerir conteúdo que o usuário compartilha / o JARVIS busca →
  vira memória semântica recuperável. Auto-crítica (Reflexion) salva como nota episódica que
  melhora a próxima tentativa, sem treinar pesos.
- **Edição de memória como TOOLS** (`memoria_append`, `memoria_replace`, `memoria_buscar`) no
  `tool_registry` — o LLM gerencia a própria memória.

## Integração com o que já existe (não reinventar)

- `classifiers/embeddings.py` (MiniLM) → orquestrador + embedder de qualidade.
- `comandos/memoria_contatos.py` (numpy cosseno) → padrão do índice vetorial.
- `jarvis/memory/` (stub) → casa do `MemoryStore`.
- `tool_registry` → memória/edição como tools. `_pensar_e_agir` → orquestrador + reflexão ao redor.
- `config.py` (providers/roteamento) + roadmap/13 (cérebro total, contexto cloud) → base pronta.

## Plano em fases (todas atrás de toggle OFF)

1. **MemoryStore RAM** (numpy + MiniLM): grava (user,assistant) por turno; retrieval composto+MMR;
   injeta "[Memórias relevantes]" no `_pensar_e_agir` (substitui o histórico chato dos últimos N).
2. **context_budget.py**: limites por modelo + orçamento por prioridade + resumo rolante.
3. **Orquestrador**: generalizar o classifier p/ decidir provider/tool/contexto.
4. **Reflexão sleep-time** + blocos de persona/human editáveis + aprendizado contínuo.
5. **potion-multilingual** como embedder rápido do caminho quente.

## Riscos / decisões
- Drift de identidade → blocos `read_only` + re-injeção de identidade; reflexão só escreve em
  memória SEPARADA (nunca muda a identidade core).
- RAM: 100k vetores ×384 f32 ≈ 147 MB (cabe no orçamento). f16 p/ metade.
- Latência: consolidação SEMPRE offline (heartbeat), nunca no caminho de resposta.
- Sem dependências pesadas (sem faiss agora; numpy basta nessa escala).

## Plano de implementação acionável (pesquisa 2026-06-22)

### Problemas observados em uso (logs reais) → o que resolve
| Problema | Causa | Solução |
|---|---|---|
| JARVIS ouve a **própria fala** como comando ("PDF pronto, senhor…") | wake-loop não silencia durante o TTS | **Gate anti-eco**: flag `self._tts_playing`; o wake DESCARTA transcrições enquanto o TTS toca (+ janela de guarda pós-fala) |
| "refaz o **super dev**" vira `sys_dev_refactor` (era o PDF) | classificador regex/embeddings dispara **sem contexto** | **Pré-router de contexto**: abaixo do limiar OU `needs_history/needs_memory` → vai pro loop de raciocínio (sem fast-dispatch) |
| Não lembra do **PDF que gerou** p/ "refaz o PDF com cores escuras" | sem memória episódica de saídas de tools | **MemoryStore**: grava `record_tool_outcome` + `record_turn`; `memoria_buscar` resolve "o PDF/aquele/de novo" |
| `llama-3.3-70b-versatile is not a valid model ID` | id Groq cru indo pro cliente OpenRouter | **CORRIGIDO** (`[CONTEXTO]`/`_proactive` → Groq real). Sistêmico: auxiliares devem usar `self._groq_real` |
| `LLM bridge falhou: name 'config' is not defined` | `config` fora de escopo | **CORRIGIDO** (`import config as _cfg_bridge`) |

### Arquitetura: "entender → (recuperar se preciso) → agir"
Camada de controle barata ANTES do modelo caro (padrão 2026 / semantic-router):
1. **Pré-router** (reusa `classifiers/embeddings.py` `_EmbeddingClassifier`, MiniLM, ~5ms, `temp=0`,
   saída JSON): classifica o turno em `{direct | needs_history | needs_memory | needs_clarification |
   tool_action}` + `confidence` + `is_destructive`. **Limiar ~0.55**; abaixo → escala p/ o LLM;
   margem top1-top2 < 0.08 → **pedir esclarecimento**. Parse-fail → escala (nunca erra calado).
2. **Resolução de contexto**: se `needs_history`, reescreve o turno em query autônoma resolvendo
   correferência/elipse ("abra **minha IDE** no site X", "refaz **o PDF**") via few-shot com o histórico.
3. **Recuperar** (se `needs_memory`): `MemoryStore.retrieve` injeta `[Memórias relevantes]` no system.
4. **Agir**: só então o `_pensar_e_agir` escolhe/chama a tool. (JARVIS já é ReAct multi-step.)

### Memória vetorial em RAM (final, 200–350 MB)
- **Embedder**: manter **all-MiniLM-L6-v2** (384-dim, ~90 MB, ~5 ms, melhor recall p/ PT-BR que
  os estáticos). `model2vec/potion` só na Fase 5, e só no caminho quente do classificador.
- **Índice**: **numpy float32 + cosseno top-k** (padrão de `comandos/memoria_contatos.py`). 10k vetores
  = 15 MB / <2 ms; 100k = 154 MB / <10 ms. `hnswlib` só acima de ~200k (nunca, p/ 1 usuário).
- **3 segmentos** (cada = `.npy` + `.jsonl` + SQLite p/ metadados/filtros/escrita atômica):
  **episódico** (turno + `tools_called` com resultado → lembra "o PDF que gerou"), **semântico**
  (fatos `{subject,predicate,value}` com Mem0 ADD/UPDATE/DELETE/NOOP), **procedural** (rotinas).
- **Retrieval adaptativo por situação** (mini-router de query → 1 de 5 políticas):
  `continuidade`→RECÊNCIA (retorna últimos N, quase 0 custo); `factual`→SIMILARIDADE; `identidade/
  preferência`→PINNED ("minha IDE"); `procedural`→similaridade+success; `aberto`→HÍBRIDO+MMR(0.6).
  Score = `w_r·recência(0.995^Δh) + w_s·cos + w_i·importância + w_p·pinned`, normalizado, com pré-filtro SQLite.

### Execução de tools "quase perfeita" (open source)
- **Strict schema** ON p/ provedores que suportam (`AGENT_STRICT_TOOLS` já existe; flag por-provedor).
- **Coerção+validação de args** no `dispatch` ANTES do handler ('50'→int, enum normalizado); em falha,
  erro **estruturado** `{status:error, tool, args, error, hint}`.
- **Retry com auto-correção ancorada** (Structured Reflection): realimenta o erro estruturado + regra
  no prompt ("status error → corrija args ou use a tool irmã ou peça 1 dado; NÃO repita igual"); **orçamento** de 2 retries.
- **Tags `parallel_safe`/`destructive`** por tool: nunca auto-retry/paraleliza destrutivas
  (`enviar_mensagem`, `controle_sistema` desligar, `encerrar_jarvis`); **gate de confirmação** centralizado.
- **`pedir_clarificacao(pergunta)`** como caminho de 1ª classe (em vez de inventar args).

### Tools auto-didáticas (a definição ensina a situação)
- Template uniforme p/ as ~39 tools: `[JOB 1 frase] + [QUANDO 2-4 gatilhos] + [QUANDO NÃO → tool irmã] +
  [PISTA DE DECISÃO] + exemplos`. Pares a desambiguar: `abrir_app↔abrir_site`,
  `criar_relatorio↔criar_planilha↔criar_apresentacao↔exportar_pdf`, `pesquisa_rapida↔pesquisa_web↔abrir_site`,
  `analisar_tela↔screenshot`, `controle_ambiente↔encerrar_jarvis`.
- **`input_examples`** (Anthropic 72%→90%) nas tools complexas (criar_*); em provedores sem o campo
  nativo, anexar bloco "Exemplos de chamada:" na descrição. Atrás de `AGENT_TOOL_EXAMPLES`.
- **Contrato "DESAMBIGUE ANTES DE EXECUTAR"** no `_TOOL_SYSTEM_PROMPT` + `memoria_buscar` no core
  sempre-visível: referências ("minha IDE/esse site/de novo/aquele") → chamar `memoria_buscar` ANTES da ação.

### Harness de avaliação (obrigatório p/ open source)
`tools/eval_tools.py` estilo **BFCL** (offline, sem GUI): casos `{utterance, expected_tool|null, expected_args}`;
mede acerto de seleção, match de args (tolerante a coerção), detecção de irrelevância (não disparar),
e **perturbações** (paráfrase + tools-distrator irmãs) p/ medir a fragilidade (BFCL: paráfrase derruba
11-19%). Matriz de confusão por tool → cada erro vira bug de descrição. Rodar em CI antes de cada release.

### Ordem de build (tudo atrás de toggle OFF — regra do `00-INDEX`)
1. **Gate anti-eco** no wake (rápido, resolve auto-escuta) + flip de `AGENT_INCLUDE_HISTORY` ON p/ voz.
2. **`jarvis/memory/`** (`store.py` + `retrieval.py` + `router.py`) reusando o MiniLM já carregado;
   hook `record_turn`/`record_tool_outcome` + injeção `[Memórias relevantes]` no `_pensar_e_agir`.
3. **Pré-router de contexto** (generaliza `_EmbeddingClassifier` → `{needs_history, needs_memory,
   is_destructive, conf}`) + resolução de correferência.
4. **Tools de memória** (`memoria_buscar/salvar_fato/esquecer/fixar`) + contrato de desambiguação no prompt.
5. **Execução perfeita** (coerção + retry estruturado + parallel_safe/destructive + confirmação + pedir_clarificacao).
6. **Tools auto-didáticas** (template + input_examples) + **`tools/eval_tools.py`**.
7. **Reflexão offline** (heartbeat ocioso: extrai fatos, consolida, dedupe — nunca no caminho de resposta).
8. Fase 5 opcional: model2vec no classificador; cognição (persona/blocos read-only, aprendizado contínuo).

### Config (novos toggles, OFF)
`MEMORY_ENABLED`, `MEMORY_DIR='data/memory'`, `MEMORY_K_DEFAULT=6`, `MEMORY_RECENCY_DECAY=0.995`,
`MEMORY_MMR_LAMBDA=0.6`, `MEMORY_ROUTER_THRESHOLD=0.35`, `AGENT_ROUTER_THRESHOLD=0.55`,
`AGENT_TOOL_EXAMPLES`, `MEMORY_REFLECTION_ENABLED`, `WAKE_ANTI_ECHO=True`.

## Histórico
- **2026-06-22 (build 4)**: **Fases 4-6** (parcial) + correções do log real. Bug:
  `pesquisa_rapida` mandava id Groq cru ao OpenRouter (400) → agora usa Groq real.
  **Fase 4 (execução confiável)**: chat-fallback com prompt anti-alucinação
  (`_CHAT_FALLBACK_SYSTEM` — proíbe narrar `abrir_site(...)`/fingir execução), retry com
  payload reduzido no 413 (`_reduce_tools_emergencia`), auto-correção ancorada (hint de
  recuperação no resultado de tool com ERRO), e **fim do "Pronto, Senhor" falso** quando tudo
  falha (mensagem honesta). **Tolerância a ASR** (voz errada → usar intenção+contexto+memória,
  nunca inventar ação de ruído). **Fase 6**: `tools/eval_tools.py` (BFCL offline, sem LLM) —
  mede "conversa≠memória" + vazamento de segredo; PASS com P/R/F1=1.00, segmento 1.00, 0 vazamentos.
  Pendente: Fase 5 `input_examples` (adiado — custo de tokens vs 413), coerção de args, tags
  destrutivas. Pesquisa do **orquestrador + sub-agentes** lançada (plano separado).
- **2026-06-22 (build 3)**: **Fase 3** — tools de memória (`memoria_buscar/salvar_fato/esquecer`,
  auto-didáticas, expostas só com memória ON) + regra **CONVERSA ≠ COMANDO** no system prompt
  (não chamar tool à toa / não entender conversa como comando) + **discernimento de escrita**
  (`triage.py`: cascata privacidade→regra→embedding; descarta efêmero/saudação/pergunta, bloqueia
  segredos, promove identidade/preferência/decisão/rotina/correção; testado em 12 casos) +
  **compactação** (`compaction.py`: mascara saídas de tools −90% tokens preservando paths/erros;
  resumo rolante) + tools `compactar_conversa`/`resumir_decisoes`. Toggles `MEMORY_TRIAGE_*`,
  `MEMORY_COMPACTION_*` (OFF) + 3 checkboxes visuais na aba Config → CÉREBRO. Pesquisa de 3
  frentes (tabela de ~50 casos) embasou o triage.
- **2026-06-21**: doc criado a partir da visão do usuário + pesquisa de 4 frentes (memória
  vetorial em RAM, orquestrador semântico, gestão de contexto, cognição/aprendizado). Design;
  implementação posterior, por fases, atrás de toggles.
- **2026-06-22**: **plano de implementação acionável** adicionado (pesquisa de 3 frentes:
  contexto-antes-de-agir, memória RAM concretizada, execução perfeita + tools auto-didáticas).
  Bugs corrigidos no mesmo dia: `[CONTEXTO]`/`_proactive` (id Groq cru → Groq real), bridge
  `config` fora de escopo. Problemas mapeados dos logs reais (eco/auto-escuta, classificador sem
  contexto, sem memória de saídas de tools).
- **2026-06-22 (build)**: **Fase 1 (anti-eco)** e **Fase 2 (MemoryStore)** implementadas e
  testadas. Fase 1: `config.WAKE_ANTI_ECHO` + `_echo_guard_active` + stamps `_tts_ended_at`
  (player/`_stop_tts`) + gate no caminho principal do wake. Fase 2: `jarvis/memory/{store,
  retrieval,router}.py` (MiniLM compartilhado, numpy cosseno, 3 segmentos, recuperação adaptativa
  por situação) + callback `_on_tool_dispatched` no `tool_registry.dispatch` + injeção
  `[Memórias relevantes]` no `_pensar_e_agir` + `record_turn` no `_exibir_resposta`. Config
  `MEMORY_*` (OFF). Teste: "refaz o PDF com cores mais escuras" → policy `continuidade` →
  recupera a saída da tool do PDF (score 0.89); "minha IDE"→identidade; "meu nome"→factual.
  `MEMORY_ROUTER_THRESHOLD` ajustado p/ 0.50 (borderline → hybrid). Próximo: Fase 3.
