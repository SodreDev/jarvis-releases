# Auditoria Profunda — J.A.R.V.I.S (2026-06-23)

> Auditoria multi-agente **com verificação adversarial**. 50 agentes leram o código real
> (checkout principal `B:/GranaFacil/J.A.R.V.I.S`, VERSION 2.7.0), 4 pesquisas web novas,
> e um verificador cético reabriu cada achado crítico. **Dos 36 achados críticos/altos, 20
> foram REFUTADOS** (faixas de linha infladas, queixas que não se sustentam no código). Só os
> **16 confirmados** entraram neste plano. Isto é o oposto de "resumo de resumo": cada item
> abaixo tem `arquivo:linha` real e passou por um cético.

---

## 1. Diagnóstico unificador (a raiz única)

**O JARVIS já tem a arquitetura certa — ela só está DESLIGADA e PRESA dentro do `main.py`.**

Três sintomas que parecem doenças diferentes são a mesma doença:

1. **`main.py` é um god-object de 13.035 linhas.** O "orquestrador" (`_pensar_e_agir`,
   `main.py:3684`, ~636 linhas) é **ReAct reativo puro** — sem camadas, sem plano.
2. **As camadas que resolveriam as queixas JÁ EXISTEM, mas com toggle OFF** por cautela:
   roteador de domínio (`jarvis/agents/registry.py` com 7 domínios + `router.py` MiniLM),
   raciocínio visível (`AGENT_REASONING`), histórico (`AGENT_INCLUDE_HISTORY`),
   memória (`jarvis/memory/*`). Tudo construído e **não cabeado**.
3. **Quando o usuário fala, o motor cai no pior caminho:** keyword-matching em
   `main.py:3567` → "nenhuma keyword bate → devolve **TODAS as 44 tools**" → o modelo barato
   afoga em tokens (**413** no Groq free) → erra a tool → responde "automático" **porque não
   passou por nenhuma camada de raciocínio/domínio/hint**.

Conclusão profissional: **não falta funcionalidade — falta CABEAR (ligar faseado) + EXTRAIR
(`main.py` vira orquestrador) + UNIFICAR (uma fonte de verdade de config e persona).** Tudo
cirúrgico e reversível, mantendo `_pensar_e_agir` como motor/fallback universal.

---

## 2. Mitos × Realidade — suas queixas, conferidas no código

Sendo honesto com você (que é o que você pediu): **duas das suas queixas eram percepção, não
defeito.** Gastar esforço nelas seria desperdício.

| Sua queixa | Veredito | Realidade verificada |
|---|---|---|
| **"provider groq no config vs openrouter na UI não bate"** | 🟡 **Quase falso alarme** | O round-trip **funciona**: UI grava em `jarvis_prefs.json`; `config.get_provider("chat")` (`config.py:387-405`) resolve `chat_provider→llm_provider→LLM_PROVIDER`; `_init_llm_clients` (`main.py:11200`) lê o efetivo. **O que confunde**: o *label* da UI (`main.py:1659`) mostra o `LLM_PROVIDER` global (display-only), não o efetivo por módulo. Bug **cosmético**, não de runtime. |
| **"3 UIs com painéis de config que conflitam"** | 🔴 **Falso alarme** | Existe **UM** editor de config LLM: a modal Stark (`ui/index.html`). Dashboard e IDE **não** têm config LLM. Gesture Interface tem config de **gesto** (domínio separado). Não há conflito de estado a resolver. |
| **"classificador erra"** | ✅ **Real e estrutural** | Confirmado: hoje é flat dispatch que cai em keyword-matching e devolve 44 tools. As camadas existem, estão OFF. |
| **"responde automático, não raciocina"** | ✅ **Real e por design** | `AGENT_REASONING=False` (`config.py:198`) e `AGENT_INCLUDE_HISTORY=False` (`config.py:142`). O código de raciocínio existe (`main.py:3813`), só não está ligado. |
| **"modelo orquestrador de ~10M params"** | ⛔ **Inviável (mas a intenção está certa)** | Ver §4.3. |

> ⚠️ **Risco real:** confundir esses falsos-positivos com bugs e gastar dias onde não há
> defeito. A própria auditoria refutou: provider mismatch, 3 UIs, `_processar_texto` "1935
> linhas" (real: 594), `core/` "35k linhas" (real: 7.580), "main.py estagnado desde 2.6.x"
> (falso). **Priorize os 16 confirmados.**

---

## 3. Os 16 achados CONFIRMADOS (com evidência)

### Monólito / acoplamento (5)
- **`_pensar_e_agir` faz 14 coisas em 636 linhas** (`main.py:3684-4320`): fast-path, filtro de
  tools, contexto ambiental, memória, hints, artefato, plano, histórico, escolha de backend,
  circuit breaker, status, semáforo, tool-call+retry, resposta. Sem separação de responsabilidades.
- **`_chamar_chat` × `_chamar_chat_com_contexto`** (`main.py:9458` / `9565`) — 107+132 linhas
  quase idênticas. Bug corrigido num não aparece no outro.
- **`_lm_chat/_lm_chat_stream` × `_groq_chat/_groq_chat_stream`** (`main.py:3041-3244`) —
  lógica espelhada sem abstração comum.
- **Explosão de estado: 90+ atributos `self._`** sem encapsulamento (`__init__` ~`main.py:2560`).
  Qualquer thread/callback pode corromper; testes unitários exigem mock gigante.
- **System prompt de 140 linhas embutido** (`_TOOL_SYSTEM_PROMPT`, `main.py:3248-3388`).
  Iterar a persona = mexer em código crítico de execução. (Há **3 cópias divergentes** da
  persona: `config.py:723`/`535`, `main.py:3248`/`3211`, `tool_registry.py:1348`.)

### Provider (3) — os resíduos REAIS por trás do falso-alarme
- **A UI permite escolher `openai`/`gemini` que não estão implementados** → quebra se selecionado.
- **`config.py:363` documenta openai/gemini como suportados**, mas não existem.
- **`config_manager.py:57` restringe `LLM_PROVIDER` a `groq/lmstudio`** — ignora `openrouter`
  (que é usado de fato) e os outros. O enum do schema e a realidade divergem.

### Cérebro (3)
- **É ReAct puro, não planejador** — raciocínio reativo, sem plan-then-execute.
- **Raciocínio visível (roadmap 16 Fase 2) DESATIVADO** por padrão — código pronto, toggle OFF.
- **Roteador de domínio (Fase 3) funciona mas está OFF** (`AGENT_SUBAGENTS=False`) — nunca
  influencia a execução; o hint só dispara se `_active_domain` estiver setado, e nada o seta.

### Tools / Memória / Build (5)
- **413 no Groq free** — consequência direta de devolver 44 tools.
- **Memória escala linear** (numpy `vstack`) — limite prático ~10k vetores.
- **Triagem OFF por padrão** → se ligar memória sem triagem, grava TUDO sem filtro.
- **3 dependências proibidas pelos PRINCÍPIOS** em `requirements.txt:60-62`
  (`discord.py`, `instagrapi`, `pywhatkit`) — violam "mensageria só via Chromium" e incham a venv.
- **Nenhuma CI reforça os PRINCÍPIOS** — risco de regressão ao escalar (toggle ligado por
  engano, segredo hardcoded, persona divergindo).

> Higiene à parte (confirmada): `crash_native.log` = **469 MB** no working dir e `VERSION
> 2.7.0` com 48 mudanças não-commitadas. Limpeza, não defeito.

---

## 4. Respostas diretas às suas 5 perguntas

### 4.1 Config (groq × openrouter)
O round-trip funciona; o que existe é **percepção + 2 resíduos reais**. Ações cirúrgicas (risco ~0):
1. UI mostra o provider **EFETIVO** (`config.get_provider('chat')`) ao lado da "escolha do
   usuário", com aviso "reiniciar p/ aplicar" se divergir — fecha a percepção.
2. **Banir `from config import LLM_PROVIDER`** (binding congelado no import-time) — ler sempre
   via função. É a causa nº1 de "um lugar diz groq, outro diz openrouter".
3. Consolidar o default de provider (hoje em **3 lugares**: `config.py`, `core/config_manager`,
   `jarvis/config/defaults`) numa fonte só (`jarvis/config/service.py` reexportando).
4. Tornar `openrouter` cidadão de primeira classe no enum/schema; remover `openai`/`gemini` da
   UI até existirem.

### 4.2 Classificador em CAMADAS + hints
O classificador erra porque **hoje não há camadas** — é flat dispatch → keyword → 44 tools.
A organização em camadas que você pediu **já está construída e desligada**. Plano:
- **CAMADA 0** — regex de alta precisão (`jarvis/intents/patterns.py`, hoje detectado e nunca
  usado no fluxo) → dispatch direto, **zero LLM**.
- **CAMADA 1** — roteador de domínio MiniLM (`jarvis/agents/router.py`) → 1 de 7 domínios +
  **HINT** injetado no prompt ("Foco: mídia/Spotify") → escopa **44→~7 tools**.
- **CAMADA 2/3** — plano curto opcional + tool-call ReAct (o motor atual).
- O "hint" é exatamente o `registry.hint(domain)` que já existe.
- **Maior alavanca barata:** `input_examples`/few-shot nas tools de args sensíveis
  (`criar_alarme HH:MM`, `enviar_mensagem` nome-vs-número, `tocar_musica` música-vs-playlist) —
  ganho documentado **~72%→90%** (Anthropic).

### 4.3 O "modelo orquestrador próprio" — veredito RECONCILIADO (decisão 2026-06-23: sem modelo local por padrão)

**"10 milhões" não é absurdo — depende do PAPEL.** Como **cérebro geral** (decisão + tool-calling)
um modelo de ~10M não serve: está 50-500× abaixo do piso (BFCL: <1B já colapsa multi-turn). MAS
como **roteador + memória semântica** um modelo de ~10M é **perfeito** — é exatamente o que
`potion-base-8M`/`model2vec` faz (~8M params, CPU, 200-600MB RAM, quase instantâneo, "aprende
mais" gravando na memória). **Esse é, quase com certeza, o "milagre dos 10M" do amigo do dono:
um modelo estático de embedding pra rotear/buscar, NÃO um LLM que conversa.**

**DECISÃO DE ARQUITETURA: sem modelo local por padrão** (PRINCÍPIO 2 — roda em quem só tem GPU
integrada; não come a VRAM do dono, que joga). Os três papéis:
- **Cérebro / respondedor = APIs (Groq + OpenRouter)** — baratas, **zero VRAM**, persona +
  decisão + tools. É daqui que vem a resposta. APIs usadas com menos custo/interferência via a
  ESTRUTURA (camadas + escopo de tools).
- **Modelo sempre-ligado = o semântico CPU (~8-32M, `potion`/MiniLM)** — roteia
  (domínio/tier/intenção) + memória/RAG ("Obsidian local"). É o "pensa rápido e aprende".
- **Cérebro local 10B = TOGGLE OPCIONAL (OFF)** pra quem tem GPU e quer 100% offline — o caminho
  já existe (`lmstudio` provider + `_lm_chat`). Nunca default, nunca obrigatório.
- **"Ciente das próprias configs" + persona = ID-RAG** (`jarvis/config/snapshot.py` redatado
  read-only + `SOUL.md`), **não** fine-tuning. LoRA/treino adiado indefinidamente.

Resumo: a visão do dono está certa e cabe — o modelo de ~10M é o **ROTEADOR** (sempre on, CPU,
instantâneo) e o **RESPONDEDOR** é a API (sem VRAM). Os dois juntos dão a "sensação de JARVIS".

### 4.4 Raciocínio de verdade (não automático)
A correção **não é modelo maior** — é cabear o que existe:
1. Ligar `AGENT_REASONING` → plano curto (Goal/Passos, ~120 tokens, 1 chamada barata) aparece
   na UI como "pensando" e **não é falado** (TTS continua telegráfica). Já implementado em
   `main.py:3813`.
2. Ligar `AGENT_INCLUDE_HISTORY` (default p/ nuvem) → resolve "manda pra ele"/"de novo".
3. Few-shots de **tom** no system → mata respostas templated.
Custo: ~1 chamada barata/turno. É a "psicologia do orquestrador" — dar a ele um scratchpad e um
plano **antes** de agir, em vez de reagir.

### 4.5 Consolidação de UI
**Não consolide agora** (effort XL, ganho baixo, risco alto — e não há conflito real). Stark
continua a UI canônica de config (já é). Dashboard/IDE/Gesture são auxiliares/read-only por
natureza — **formalize isso em `ARCHITECTURE.md`** ("quando usar cada superfície"). Única ação
de verdade: o label de provider efetivo da §4.1.

---

## 5. Arquitetura-alvo (em camadas, estendendo `jarvis/`)

`main.py` encolhe para **<2.500 linhas** e vira ORQUESTRADOR (cria o app, monta o pipeline,
delega). **Não reescrever de uma vez** — extrair 1 módulo por PR, com wrapper de compat.

```
jarvis/
  orchestrator/
    pensar_e_agir.py    # extrai main.py:3684 — pensar(text, ctx, injectors). Motor/fallback. Mesma lógica, outra casa.
    pipeline.py         # a "psicologia" em CAMADAS explícitas, top-down com early-exit:
                        #   CAMADA 0  regex (intents/patterns.py)        -> dispatch direto, ZERO LLM
                        #   CAMADA 1  roteador de domínio (agents/router) -> 1 de 7 domínios + hint; escopa tools 44->~7
                        #   CAMADA 2  plano curto opcional (reasoning)    -> UI "pensando" (não falado)
                        #   CAMADA 3  tool-call ReAct (o _pensar_e_agir atual) com budget/dedup em CÓDIGO
                        #   FALLBACK  incerto em qualquer camada          -> comportamento atual (core tools)
    budget.py           # set de (tool, args_hash) + limite duro N calls/turno -> mata loop e 413 na raiz
  agents/               # JÁ EXISTE (registry 7 domínios + router MiniLM). Só CABEAR no pipeline.
  intents/              # JÁ EXISTE (patterns) -> vira CAMADA 0 oficial
  memory/               # JÁ EXISTE (store/triage/retrieval/compaction). Fachada única, opt-in.
  llm/
    client_factory.py   # unifica _lm_chat/_groq_chat e variantes stream: chat(text, system, stream, backend)
  config/
    service.py          # FONTE ÚNICA DA VERDADE. Precedência: defaults < toml < prefs < env < runtime (Pydantic Settings)
    snapshot.py         # snapshot_for_agent() REDATADO (sem *_API_KEY) -> agente "ciente das configs" read-only
  persona/
    SOUL.md             # persona como ARQUIVO (migra as 3 cópias). UMA fonte, versionável.
    loader.py           # compila system prompt: SOUL + few-shots de tom (ID-RAG)
  prompts/orchestrator.md  # _TOOL_SYSTEM_PROMPT externalizado
```

**Princípio:** cada camada é um arquivo testável; só o `pipeline` conhece a ordem; toggles
novos OFF; tudo cai no `_pensar_e_agir` atual quando incerto.

---

## 6. Plano em 4 fases (por ROI / risco)

### Fase 1 — Quick wins (risco ~0, sem tocar o motor) · esforço **S**
- ⚠️ **(revisado 06-23 — NÃO é quick-win)** As 3 deps proibidas têm **imports vivos**
  (`instagrapi` em `comandos/msg_sender.py:930`, paths de `discord` no `main.py`/`comandos/discord_ctrl.py`).
  Remover do `requirements.txt:60-62` sem guardar os call-sites **quebra o build**. Vira tarefa
  própria: guardar/migrar os imports (try/opcional ou backend Chromium
  `jarvis/messaging/backends/discord_web`) **e só então** remover. `pywhatkit` parece sem uso
  (0 imports no grep) — confirmar e remover esse sim.
- UI: label do provider **efetivo** (`get_provider('chat')`) em `main.py:1659`.
- UI: coluna "ATIVO no backend" × "escolha do usuário" + aviso "reiniciar p/ aplicar".
- **Externalizar persona** → `jarvis/persona/SOUL.md` + `jarvis/prompts/orchestrator.md` (mata
  as 3 cópias).
- Decisão consciente sobre o git (commitar a sessão / VERSION 2.7.0) + limpar `crash_native.log`
  (469 MB) do working dir.
- `tools/check_principles.py` + hook pre-commit (toggles OFF, py_compile, zero segredos).

### Fase 2 — Cabear as camadas que já existem (toggle ON faseado + calibragem) · esforço **M**
- **O "payload redutor" tem que ACERTAR, não só cortar** (queixa direta do dono: *"a tool certa
  nem chega"*): hoje `main.py:3567` ou despeja as 44 tools (→ 413) ou, no filtro por keyword,
  **dropa a tool certa**. Trocar por **roteamento semântico** (o modelo ~10M/MiniLM escolhe o
  domínio → top-K por significado, máx 8) — a tool certa **entra** e o payload fica pequeno.
  Mata o 413 **e** o "sumiço da tool certa" de uma vez.
- `input_examples` nas 3-4 tools de args sensíveis (`tool_registry.py`).
- Ligar `AGENT_SUBAGENTS` com threshold/margem **calibrados via `tools/eval_tools.py` no CI**
  (critério `router_acc ≥ 0.80`) → cabeia o roteador, injeta hint, escopa 44→~7.
- Integrar `jarvis/intents/patterns.py` como CAMADA 0.
- Ligar `AGENT_REASONING` (plano na UI, não falado) + `AGENT_INCLUDE_HISTORY` (default nuvem).
- **Budget/dedup em CÓDIGO** (`jarvis/orchestrator/budget.py`), não só no prompt.

### Fase 3 — Extrair o orquestrador de `main.py` (cirúrgico, comportamento idêntico) · esforço **L**
- Mover `_pensar_e_agir` → `jarvis/orchestrator/pensar_e_agir.py` (1 PR).
- Criar `pipeline.py` encadeando as camadas.
- Unificar `_lm_chat/_groq_chat` → `jarvis/llm/client_factory.py`.
- Consolidar `_chamar_chat` + `_chamar_chat_com_contexto`.
- Criar `jarvis/config/service.py` (Pydantic Settings) + `snapshot_for_agent()`. `config.py`
  reexporta p/ compat. Banir imports por valor de símbolos voláteis.
- **Regra:** 1 módulo por PR, wrapper de compat, smoke-test do launcher + `eval_tools` a cada PR.

### Fase 4 — Orquestrador "próprio" real (cérebro = API; modelo ~10M = roteador; local OPCIONAL) + memória 2º cérebro · esforço **L**
- **Cérebro = API (Groq/OpenRouter), sem VRAM, por padrão** (PRINCÍPIO 2). O modelo ~10M
  (`potion`) é o **roteador sempre-on** (CPU, instantâneo), **não** o respondedor.
- Trocar MiniLM por **`potion-base-8M/32M`** em `classifiers/embeddings.py` (drop-in) — roteador instantâneo.
- **ID-RAG** das configs+persona (`snapshot.py` redatado + `SOUL.md`) → agente "ciente de si" sem treino.
- Ligar `jarvis/memory/` opt-in com auto-compaction; Tier 0 JSON default, vetor/SQLite atrás de toggle.
- Protótipo do tier **SUPERVISE** (`jarvis/orchestrator/lead.py`): decompõe tarefa composta →
  plano JSON → sub-agentes → síntese. Só para multi-domínio raro; ReAct continua o default.
- **Cérebro local 10B = toggle OPCIONAL (OFF)** via LM Studio (`_lm_chat` já existe), p/ quem
  tem GPU e quer offline. Nunca default. LoRA/treino adiado indefinidamente.

---

## 7. Top riscos (e mitigação)
- **Big-bang de refatoração** → 1 módulo/PR, wrappers de compat, smoke-test + eval a cada PR.
- **Ligar `AGENT_SUBAGENTS` sem calibrar** → gate por `eval_tools` no CI (`router_acc ≥ 0.80`).
- **Tratar um ~10M como CÉREBRO** → beco sem saída. O ~10M é o **ROTEADOR** (potion/CPU); o
  cérebro é a **API** (Groq/OpenRouter) + ID-RAG. Não treinar/fine-tunar nada agora.
- **Confundir falso-positivo com bug** → priorizar os 16 confirmados.
- **Memória sem compaction** → auto-compaction + tiers opt-in.
- **Release contaminada (2.7.0 working tree suja)** → decidir versionamento antes de qualquer release.

---

## 8. Fundamentação (pesquisa 2025-2026)
- **Orquestrador/tamanho:** 10M < piso de tool-calling (BFCL: <1B colapsa multi-turn). Alternativa
  = potion (model2vec) + LLM barato heterogêneo + scratchpad + ID-RAG. Persona via RAG > FT. (high)
- **Modelo barato confiável por estrutura:** P1 `input_examples` (72→90%); P2 nunca devolver
  catálogo inteiro; P3 validar args + retry com alternativa segura (OpenHands); P4 dedup+budget
  em código (AutoGPT); P5 tiering por complexidade (Anthropic 4-15×; Cognition "don't build
  multi-agents"). (high)
- **Config fonte-única:** Pydantic Settings com precedência declarada
  (defaults<toml<prefs<env<runtime); schema único que GERA a UI; reativo (watch→event_bus);
  `snapshot_for_agent()` redatado read-only. (high)
- **Local-first/persona:** persona = arquivos (SOUL.md/ID-RAG, padrão Hermes/OpenClaw/Letta);
  memória = interface única em camadas + condenser (OpenHands); loop pequeno event-sourced fora
  do main.py (smolagents/OpenHands); modes = persona+allowlist (Cline/Roo). (high)

---

*Gerado por auditoria multi-agente com verificação adversarial. 16 achados confirmados de 36;
20 refutados. Evidência em `arquivo:linha` no checkout real (não no worktree snapshot).*
