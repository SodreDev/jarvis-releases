# AUDITORIA & HANDOFF — J.A.R.V.I.S. (sessão 2026-06-22)

Documento de transferência: TUDO o que foi feito, o que está em andamento e os objetivos
restantes. Para continuar o trabalho no Claude app sem perder contexto.

---

## 0. ESTADO DO GIT — ⚠️ LEIA PRIMEIRO

**NADA desta sessão está commitado.** Tudo está no *working tree*. A `VERSION` é `2.7.0`
e o **payload 2.7.0 foi publicado** em `NinjaZinS2/jarvis-releases` (Releases), mas o
**código-fonte não foi commitado** no repo. Último commit real: `ec30af2 bump 2.2.6`.

**Pendência de git (quando quiser):** commitar todo o trabalho desta sessão. Sugestão de
mensagem: *"feat: cérebro agêntico v2 — memória vetorial, discernimento, sub-agentes por
domínio, raciocínio visível + correções (anti-eco, 413, provider, imagem)"*.
Higiene já preparada (do review anterior): `.gitignore` ajustado, `config/apps_cache.json`,
`core/dev_mode/dev_config.json`, `data/img_cache/*` removidos do tracking (`git rm --cached`).

---

## 1. OBJETIVO CENTRAL (o "norte" de tudo)
Transformar o JARVIS de **automação rígida** em um **agente que RACIOCINA e EXECUTA** como
um JARVIS de verdade (estilo OpenHands/Goose/Cline/Hermes/OpenClaw/Claude Cowork), mantendo
a persona, **acertando com modelos baratos via ESTRUTURA** (não modelo caro), tudo
**local-first** quando possível, e **conservador** (toggles OFF por padrão, repo público).

---

## 2. BUGS CORRIGIDOS (todos, sem exceção)
| # | Bug | Correção |
|---|---|---|
| 1 | `LLM bridge falhou: name 'config' is not defined` | `import config as _cfg_bridge` (main.py ~2594) |
| 2 | `[CONTEXTO]`/`_proactive_generate` mandavam id Groq cru (`llama-3.3-70b-versatile`) ao OpenRouter → 400 | usam Groq REAL (`_groq_real` + `_groq_real_model`) |
| 3 | `pesquisa_rapida` mesmo erro 400 (`GROQ_MODELO_CHAT` defasado no tool_registry) | usa Groq real (tool_registry.py ~1473) |
| 4 | Whisper 400 (`invalid content-type`) — swap p/ OpenRouter quebrou áudio | 3 transcrições + 2 visão → `_groq_real` |
| 5 | `set_ui_pref` crash (reload síncrono destruía callback JS) | `root.after(180, ...)` |
| 6 | 404 `qwen3-coder deprecated` | default `openrouter/auto` + cadeia de fallback robusta |
| 7 | **Auto-escuta** (JARVIS ouvia a própria fala como comando) | **Anti-eco**: `_echo_guard_active` + `_tts_ended_at` + gate no wake (descarta durante TTS + 1.2s) |
| 8 | **413** (payload > limite TPM do modelo) | reduz payload (sem histórico/memória, ≤8 tools) + **re-tenta o primário** (passo 0) |
| 9 | **Chat-fallback ALUCINAVA execução** (narrava `abrir_site(...)`) | prompt dedicado `_CHAT_FALLBACK_SYSTEM` (proíbe fingir) |
| 10 | `_responder_contextual_groq` fingia "está sendo gerada" | regra anti-simulação no system |
| 11 | Nuvem (Auto Router) voltava VAZIA → caía em conversa | **re-tenta no Groq real COM tools** antes do fallback |
| 12 | `"Pronto, Senhor"` FALSO quando tudo falhava | mensagem honesta ("não consegui concluir…") |
| 13 | **Provider=groq** apesar de UI=OpenRouter | `_init_llm_clients` usa `config.get_provider("chat")` (respeita "Provider — Chat") |
| 14 | **Imagem 404** (`bytedance-seed/seedream-4.5` inválido) | **Nano Banana** `google/gemini-2.5-flash-image` |
| 15 | "mova esse PDF" → pedia "qual projeto" (atalho IDE sequestrava) | atalho só age com contexto de projeto; senão deixa o cérebro |
| 16 | Respostas longas demais | regra dura de tamanho (≤2 frases) + chat-fallback 120 tok + outcome-first |
| 17 | MiniLM com warning de rede no boot | carrega `local_files_only=True` (offline, cache-first) |

---

## 3. FEATURES IMPLEMENTADAS (e onde estão)

### 3.1 Anti-eco (roadmap/14 build) ✅
`config.WAKE_ANTI_ECHO=True` · `_echo_guard_active()` · stamps `_tts_ended_at`. Barge-in
(interromper TTS com wake word) preservado.

### 3.2 Memória vetorial em RAM — `jarvis/memory/` ✅ (testado)
- `store.py` — **MemoryStore**: MiniLM compartilhado (sem 2º load), numpy+cosseno, 3
  segmentos (episodic/semantic/procedural), `.npy`+`.json` (self-heal), `record_turn` /
  `record_tool_outcome` / `upsert_fact` (ADD/UPDATE estilo Mem0) / `retrieve` / `forget` / `pin`.
- `retrieval.py` — score composto (recência·sim·importância·pinned) + MMR (numpy puro).
- `router.py` — **política de busca por situação** (continuidade/factual/identidade/procedural/hybrid).
- Integração: callback `_on_tool_dispatched` no `dispatch` grava saída de toda tool;
  injeção `[Memórias relevantes]` no `_pensar_e_agir`; `record_turn` no `_exibir_resposta`.
- **Teste**: "refaz o PDF com cores escuras" → policy continuidade → recupera a saída da tool (0.89).

### 3.3 Discernimento de escrita — `jarvis/memory/triage.py` ✅ (testado, F1=1.00)
Cascata **privacidade → regra(regex PT-BR) → embedding**. Descarta efêmero/saudação/pergunta,
**bloqueia segredos** (senha/token/cartão → NUNCA persiste), promove identidade/preferência/
decisão/rotina/correção ao segmento certo. `ingest_turn` aplica a decisão.

### 3.4 Compactação — `jarvis/memory/compaction.py` ✅ (−90% tokens testado)
`mask_tool_outputs` (enxuga saídas de tools, preserva paths/erros verbatim) + `summarize_turns`/
`rolling_summary`. Tools `compactar_conversa` e `resumir_decisoes`.

### 3.5 Tools de memória (tool_registry) ✅
`memoria_buscar`, `memoria_salvar_fato`, `memoria_esquecer` (auto-didáticas, "↳ NÃO confunda
com…"), + `compactar_conversa`, `resumir_decisoes`. Expostas só quando a feature está ON.

### 3.6 Sub-agentes por domínio (roadmap/15 Fase 3) — `jarvis/agents/` ✅ (eval 13/13)
- `registry.py` — domínios = TOOL_LAYERS (documentos/web/midia/sistema/mensageria/visao/jogos)
  com âncoras PT-BR + hint de prompt.
- `router.py` — roteador semântico MiniLM → escolhe domínio → escopo de tools (~5-9 em vez
  de 44 → **mata o 413 estruturalmente** + melhora seleção). Margem baixa → fallback ao filtro atual.

### 3.7 Execução confiável (roadmap/16 / Fase 4) ✅
Auto-correção ancorada (hint de recuperação no ERRO), fim do "Pronto" falso, retry primário no
413, anti-alucinação em TODOS os caminhos de fallback.

### 3.8 Agente que raciocina (roadmap/16) ✅
- **Prompt agêntico** ("AJA COMO AGENTE QUE RACIOCINA"): age por default, infere defaults,
  executa tarefa composta em sequência, resolve referências, fala lidera com o resultado.
- **Memória de artefato** (`self._last_artifact`): captura último arquivo criado e injeta no
  contexto → "esse PDF/aquele/move ele" resolve sem perguntar.
- **Raciocínio VISÍVEL** (`AGENT_REASONING`, OFF): `_gerar_plano()` gera Objetivo→Passos curto,
  mostra na UI ("🧠 pensando", estilo `thinking`), injeta no contexto. **Fala continua curta**.

### 3.9 Harness de avaliação — `tools/eval_tools.py` ✅ (PASS)
BFCL-style offline (só MiniLM, sem custo LLM): discernimento (P/R/F1=1.00), acurácia de
segmento (1.00), **vazamento de segredo (0)**, roteador de domínio (13/13). Rodar no CI antes de release.

### 3.10 UI — toggles visuais (aba Config → 🧠 CÉREBRO) ✅
Checkboxes: **Memória semântica**, **Discernimento**, **Compactação**, **Sub-agentes**,
**Raciocínio visível**. Aplicam ao vivo (`apply_models` → `agent.*` → `_aplicar_prefs_agente`).

### 3.11 (Sessão anterior) Suíte de documentos + v2.7.0 ✅
`documents/{deck_builder,report_builder,sheet_builder,pdf_convert}.py` (spec→render: pptx 25
layouts, pdf via Chromium, xlsx openpyxl, conversão MS Office/LibreOffice). Tools
`criar_apresentacao/criar_relatorio/criar_planilha/exportar_pdf`. OpenRouter (Auto Router +
fallback) + imagem roteada. Release **2.7.0 publicada** (payload). `ARCHITECTURE.md` criado.

---

## 4. CONFIG — TOGGLES (todos OFF por padrão, exceto anti-eco)
```
WAKE_ANTI_ECHO=True · WAKE_ANTI_ECHO_GUARD_SEC=1.2
MEMORY_ENABLED=False · MEMORY_DIR=data/memory · MEMORY_K_DEFAULT=6
MEMORY_RECENCY_DECAY=0.995 · MEMORY_MMR_LAMBDA=0.6 · MEMORY_ROUTER_THRESHOLD=0.50
MEMORY_REFLECTION_ENABLED=False
MEMORY_TRIAGE_ENABLED=False · MEMORY_TRIAGE_EMBED_THRESHOLD=0.45 · MEMORY_TRIAGE_MARGIN=0.08
MEMORY_TRIAGE_LLM_FALLBACK=False · MEMORY_PII_REDACT=True · MEMORY_PRIVATE_MODE=False
MEMORY_COMPACTION_ENABLED=False · MEMORY_COMPACT_AT=0.70
AGENT_SUBAGENTS=False · AGENT_SUBAGENT_THRESHOLD=0.42 · AGENT_SUBAGENT_MARGIN=0.06 · AGENT_SUBAGENT_TOOL_MAX=12
AGENT_REASONING=False · AGENT_REASONING_MIN_WORDS=4
(já existentes: AGENT_TOOL_SELECT_MODE, AGENT_BRAIN_MODE, AGENT_INCLUDE_HISTORY=False, AGENT_STRICT_TOOLS=False, OPENROUTER_MODELS, IMAGE_PROVIDER…)
```
Prefs persistem em `jarvis_prefs.json` → seção `agent` (memory_enabled, memory_triage,
memory_compaction, subagents, reasoning). Provider do cérebro = "Provider — Chat" da UI.

---

## 5. ARQUIVOS (novos / modificados nesta sessão)
**Novos:** `jarvis/memory/{store,retrieval,router,triage,compaction}.py` ·
`jarvis/agents/{__init__,registry,router}.py` · `tools/eval_tools.py` ·
`planning/roadmap/{13,14,15,16}-*.md` · `planning/AUDITORIA-HANDOFF.md` (este) ·
(sessão anterior) `documents/{deck_builder,report_builder,sheet_builder,pdf_convert}.py` ·
`ARCHITECTURE.md` · `core/dev_mode/dev_config.example.json`.
**Modificados:** `main.py` (cérebro, anti-eco, fallback, memória, sub-agentes, raciocínio,
prompt) · `config.py` (toggles + get_provider) · `comandos/tool_registry.py` (tools +
callback + fix model) · `classifiers/embeddings.py` (offline) · `jarvis/memory/__init__.py` ·
`ui/index.html` (toggles + addMessage thinking) · `documents/{design_system,pptx_engine}.py` ·
`README.md` · `VERSION` · `planning/roadmap/00-INDEX.md`.

---

## 6. ROADMAPS / PLANEJAMENTO
- **13 — Cérebro agêntico & tool-calling**: loop, filtro de tools, histórico, paralelo. ✅ base feita.
- **14 — Memória semântica + cognição**: memória RAM + triagem + compactação + reflexão. ✅ Fases 1-4;
  pendente Fase 7 (reflexão offline / heartbeat) + juiz-LLM no triage.
- **15 — Orquestrador multi-agente (4 tiers)**: roteador de complexidade + sub-agentes + supervisor.
  ✅ **Fase 3 feita** (roteador de domínio + escopo de tools). Pendente: tier de COMPLEXIDADE,
  `lead.py` (SUPERVISE/decomposição), identidade read-only.
- **16 — Agente que raciocina** (baseado em projetos reais): prompt agêntico ✅ + last_artifact ✅ +
  raciocínio visível ✅. **Pendente: Fase 3 (defaults + tool de arquivo), Fase 4 (reflexão entre
  passos), Fase 5 (tier SUPERVISE).**

---

## 7. O QUE ESTÁVAMOS FAZENDO / PRÓXIMOS PASSOS (em ordem)
1. **roadmap/16 Fase 3** — *defaults sensatos + TOOL REAL de mover/gerenciar arquivo*
   (hoje só há file-op de IDE). Fecha o caso "mova esse PDF para downloads": destino opcional
   nullable com default (Downloads/Documentos), inferido do `last_artifact`. **← era o próximo.**
2. **roadmap/16 Fase 4** — reflexão curta entre passos (verify "isto resolveu?", orçamento 1-2).
3. **roadmap/16 Fase 5 / roadmap/15 SUPERVISE** — roteador de COMPLEXIDADE (4 tiers) + `lead.py`:
   decompor tarefa composta ("pesquisa + PDF + PowerPoint") em plano JSON, persistir, executar
   por domínio, sintetizar. (Maior esforço; custo 4-15× → só nesse tier.)
4. **roadmap/14 Fase 7** — reflexão offline (heartbeat ocioso) consolida episódico→semântico.
5. **Fase 5 (execução perfeita) restante** — `input_examples` nas tools complexas (Anthropic
   72→90%), coerção de args no dispatch, tags `parallel_safe`/`destructive` + confirmação centralizada.
6. **Identidade read-only** (roadmap/15/16) — `data/memory/identity.json` (persona/human/style)
   re-injetada (ID-RAG) para persona coerente + few-shots de tom.
7. **DOCX** spec→render + refino visual contínuo dos documentos (qualidade de layout do PDF).
8. **Git**: commitar tudo + (opcional) bump de versão + release.

---

## 8. PESQUISAS FEITAS (workflows multi-agente — fundamentam os roadmaps)
- Contexto-antes-de-agir + memória RAM + execução perfeita (→ roadmap/13,14).
- Compactação + taxonomia de discernimento (~50 casos) (→ triage/compaction).
- Orquestrador + sub-agentes + "modelo próprio" (→ roadmap/15).
- **Projetos REAIS**: Open Interpreter, OpenHands, Aider, smolagents, Goose, Cline, Hermes
  (Nous), OpenClaw, Omi, Claude Cowork + Reddit/X (→ roadmap/16). Achados-chave: plan-then-
  execute, separar raciocínio de formatação (Aider +3-7pp), memória de ação/artefato, act-vs-ask
  (agir por default), reflexão/verify, effort-scaling por tier, persona por regras+few-shot.

---

## 9. COMO LIGAR / TESTAR (estado atual)
1. `.\dev.ps1` (dev mode; `.py` refletem na próxima run; `config.py` hot-reload).
2. Aba **Config → 🧠 CÉREBRO**: ligar **Memória semântica**, **Sub-agentes**, **Raciocínio
   visível** (e Discernimento/Compactação se quiser). **Provider — Chat = OpenRouter**.
3. Sempre-ON (sem toggle): anti-eco, prompt agêntico, memória de artefato, correções de fallback.
4. Validar: `.venv\Scripts\python.exe tools\eval_tools.py` (deve dar PASS).
5. Recomendado: ligar `AGENT_INCLUDE_HISTORY` (hoje OFF) p/ "manda pra ele/esse aí" entre turnos.

---

## 10. INVARIANTES / REGRAS DO PROJETO (manter)
- Toggles novos OFF por padrão · edições em `main.py` cirúrgicas (≤2 funções) · `py_compile` a
  cada passo · nunca remover comandos sem confirmação · nunca commitar segredos (tudo gitignored)
  · Groq NÃO gera imagem · acertividade por ESTRUTURA (modelo barato) · `_pensar_e_agir` é o motor
  e o fallback universal (orquestrador ENVOLVE, não reescreve).
</content>
