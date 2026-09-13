# 13 — Cérebro agêntico & tool-calling (acerto com modelos baratos)

> **Status**: Em execução incremental (Fase 1). Tudo novo entra atrás de toggle
> **OFF por padrão** (regra do `00-INDEX.md`); o caminho atual continua sendo o default
> até validação. Nada removido — regex/classificador viram *fast-path* opcional com fallback.

## Objetivo

Fazer o JARVIS **pensar nas ferramentas que pode usar** e encadear várias tools enquanto
raciocina, **sem depender de o usuário falar do jeito exato** e **sem depender de um modelo
caro**. A meta é tirar acerto de modelos **gratuitos/baratos** (via OpenRouter) através de
*estrutura* — não de força bruta de modelo.

## Estado atual (verificado, com evidência)

O loop agêntico **já existe** em `main.py:_pensar_e_agir` ([3439-3878]) — é multi-step
(`MAX_STEPS=5`), devolve `role:tool`, tem anti-loop e fallback p/ Groq. E ele roda **antes**
do regex de sistema para comandos gerais (`main.py:8564-8582`). O problema **não** é a
ausência do loop; é o que o estrangula:

| Queixa do usuário | Causa-raiz | Evidência |
|---|---|---|
| "Erra comando / precisa falar exato" | Pré-filtro de tools por **palavra-chave** — modelo só vê ≤10 tools que casaram | `_filter_tools_for_text(max_n=10)` `main.py:3397-3495` |
| "Erra contexto" | Payload de tool-calling vai **sem histórico** (só system + texto atual) | `main.py:3511-3514` |
| "Não chama várias tools enquanto pensa" | Tool_calls paralelos **truncados ao 1º** no modelo local | `main.py:3723-3725`, `3865-3867` |
| "Não pensa direito" | Modelo local **fraco** (Llama-3.2-3B) e sem schema estrito | `config.py:66`; sem `strict` em `tool_registry` |
| Docs feios / 1 formato | Geração interceptada por regex **antes** do LLM + schema JSON fixo | `main.py:8221`, `7851-7891` → ver doc **10** |

Path legado (fallback após o loop não chamar tool): `_detectar_comando_sistema`
(`main.py:8587`), embeddings (`8691`), classificador-tag `[CMD:...]` (`8762`). Fica como
*fast-path*, não é removido.

## Estratégia: acerto com modelo barato = estrutura, não modelo caro

Baseado em pesquisa de projetos efetivos (Anthropic *Advanced tool use*, CodeAct, Gamma,
OpenRouter docs). Os fatores que mais elevam o acerto de modelos pequenos:

1. **Não inflar o conjunto de tools** — *tool overload* derruba o acerto. Em vez de filtro
   por keyword (que esconde a tool certa), usar **camadas/namespaces** e expor só o subconjunto
   relevante por turno; a futuro, *Tool Search / defer_loading* (Anthropic mediu 49%→74% de
   acerto, −85% de tokens).
2. **Strict JSON schema** por tool (`additionalProperties:false`, tudo em `required`) → argumentos
   sempre válidos, aposenta o "salvage" de tool-call malformada.
3. **Descrições + exemplos** (quando usar / quando NÃO usar, 2-3 positivos/negativos) — Anthropic
   mediu 72%→90% em params complexos. Já temos bom padrão em `abrir_app`/`abrir_site`; padronizar.
4. **Histórico no payload** — o modelo precisa do contexto recente para mapear "manda pra ele".
5. **Paralelo real + observação** — parar de truncar ao 1º quando o provider aguenta; manter
   serialização só como fallback do modelo local fraco.
6. **Modelo por tarefa via OpenRouter** (drop-in OpenAI-compatible): modelos **grátis/baratos**
   distintos para *pensar*, *gerar arquivos* e *gerar imagem*. Direto Groq/local fica para
   ack de voz de baixa latência. (Quais modelos exatos = pesquisa dedicada posterior.)
7. **MCP**: tools internas seguem **nativas**; MCP só como **cliente** de servidores externos.
   "Camadas/subcamadas" = registry/namespacing + subset por turno, **não** um gate antes do LLM.

## Fases

### Fase 1 — O cérebro (em execução)
Mudanças cirúrgicas e *flag-gated* (default = comportamento atual):

- **`config.py`** (additive): OpenRouter como 3º provider + roteamento de modelo por tarefa
  (`thinking` / `files` / `image`) com defaults grátis/baratos; toggles novos OFF.
- **`comandos/tool_registry.py`** (additive): `to_openai_tools(strict=...)`; metadados opcionais
  de `layer` (namespace) e `parallel_safe`; helper `select_tools(text, mode=...)`
  (`keyword` | `layered` | `all`).
- **`main.py:_pensar_e_agir`** (cirúrgico): usar `select_tools` conforme flag (default keyword,
  como hoje); injetar histórico recente quando flag ligada; não truncar tool_calls paralelos
  quando o provider é capaz (Groq/OpenRouter) — manter `[:1]` só para o LM local.

Critério de pronto: com a flag de "modo layered + histórico + paralelo" ligada e OpenRouter
configurado, frases livres ("manda pro arthur que cheguei", "abre o spotify e o discord")
resolvem sem palavra-chave exata e com múltiplas tools no mesmo raciocínio.

### Fase 2 — Documentos spec→render (ver doc **10**)
IR tipado + catálogo de componentes/layouts + **design tokens** compartilhados;
backend HTML/CSS→PDF via **Playwright/Chromium** (reusa o que já existe) para PDFs "estilo
Canva"; `.pptx/.docx/.xlsx` via templates-mestre; web data + gráficos + gerador de imagens
(Pollinations, `comandos/image_gen_ctrl.py`) no loop; manifesto de capacidades que o LLM "vê".

**Iteração 1 (PPTX) — em código (2026-06-21):**
- `documents/deck_builder.py` — spec→render com **7 layouts** (capa, secao, topicos,
  duas_colunas, destaque, imagem, fechamento) reusando os primitivos do `pptx_engine`
  + design tokens do `design_system`. `gerar_deck(spec)` + `capability_manifest()`.
- Tool **`criar_apresentacao`** (`tool_registry`) — o LLM compõe a spec (layouts variados +
  `image_prompt` via Pollinations) → geração passa a fluir pelo **cérebro/tool-calling**.
  Camada `documentos` + keywords no `_TOOL_KEYWORDS`.
- Roteamento: flag **`DECK_V2_ENABLED`** (OFF) — quando ON, o atalho regex de "apresentação"
  (`_tentar_atalhos_servico_completo`) NÃO intercepta e deixa o cérebro usar a tool nova.
  Toggle na UI (aba Modelos → "Apresentações novas").
- **Decisões**: backend PDF = Playwright/Chromium; começar por PPTX.
**Iteração 2 (PPTX, qualidade Gamma/Canva) — 2026-06-21:** com base em pesquisa
(Gamma/Beautiful.ai/Tome/Presenton), o `deck_builder` foi reescrito (v2):
- **Grid 12 colunas + escala tipográfica modular + tokens de espaçamento** em `design_system`
  (`GRID`, `TYPE`, `SPACE`, `col_x/span_w`) → alinhamento e hierarquia "designed".
- **15 layouts** (capa, hero, secao, agenda, topicos, duas_colunas, comparativo, kpi, bento,
  timeline, citacao, destaque, imagem, imagem_lateral, fechamento).
- **Cards arredondados** (sombra/borda best-effort), **eyebrow** (kicker), **crop-to-fill**
  de imagens (corrige distorção), **scrim** em full-bleed, **gradiente** de fundo (fallback sólido).
- **Limites de conteúdo** (`CAPS`) clampados em `_normalize` → impedem overflow na origem.
- **Seleção adaptativa** (`pick_layout`) quando o layout falta/for inválido.
- Manifesto + descrição da tool atualizados (regra de variedade; textos curtos).
- **Verificado**: py_compile (main/config/tool_registry/deck_builder/design_system) ✓,
  node --check (bridge) ✓, deck de teste 15 layouts gera .pptx ✓, auditoria strict recursiva
  das 36 tools = nenhum inválido ✓.

**Iteração 3 (texto + imagem) — 2026-06-21** (após pesquisa "muito a fundo", 4 frentes):
- **Truncamento corrigido**: CAPS reequilibradas (só títulos/valores curtos); layout novo
  **`texto`** (corpo médio/grande, fonte por densidade); `topicos` compacta p/ caber em vez
  de cortar; `_text` usa `MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE` (PowerPoint encolhe ao abrir).
- **Roteamento de geração de imagem** (`pptx_engine.gen_image`): 1) modelo de imagem do
  **OpenRouter** (`OPENROUTER_MODELS['image_render']`, default grátis
  `x-ai/grok-imagine-image-quality:free`, via `/chat/completions` modalities=['image','text']),
  2) **Pollinations** com **token (tier Seed) + backoff exponencial** no 429. **Groq NÃO
  gera imagem** (só escreve/realça o prompt). Aspecto por layout (16:9 / 3:4 / 1:1) e throttle
  de concorrência (1 worker no Pollinations grátis) p/ evitar 429.
- Verificado: py_compile ✓, `gen_image` importa ✓, deck renderiza ✓.

**Iteração 4 (fallback + Auto Router + cérebro total + contexto) — 2026-06-21:**
- **Bug corrigido**: `qwen:free` deu 404 (Venice depreciado) e o fallback crashava
  (`self._lm` None). Agora: **default `openrouter/auto`** (sua conta roteia o melhor modelo);
  cadeia de fallback robusta no `_pensar_e_agir` (**modelo específico → openrouter/auto →
  Groq REAL → LM → chat**), com `self._groq_real` separado (Groq real mesmo no modo OpenRouter).
- **Toggle "especificar modelos"** na UI (OFF=Auto Router; ON=campos de modelo, com fallback p/ auto).
- **Provedor de imagem selecionável** (auto | OpenRouter pago | Pollinations); default
  `image_render=bytedance-seed/seedream-4.5` (pago barato, preferência do usuário).
- **Modo "cérebro total"** (`AGENT_BRAIN_MODE=total`, checkbox na UI): pula fast-path de regex,
  todas as tools, histórico ligado → o LLM SEMPRE raciocina sobre o contexto.
- **Contexto adaptativo**: `AGENT_HISTORY_TURNS_CLOUD=20` (mais histórico na nuvem). Esquema
  completo (4→200k-1M) em **roadmap/14**.
- Verificado: py_compile ✓, node ✓, default=auto ✓, deck gera ✓.

**Iteração 5 (blocos + ~25 layouts) — 2026-06-21:**
- **Grid com trilha de LINHAS** (`design_system`: `ROWS`, `row_y`, `cell()`).
- **Registry de BLOCOS** (12 tipos: titulo, texto, bullets, stat, card, imagem, citacao,
  divisor…) + layout **`livre` (COMPOSE)**: o LLM posiciona blocos no grid 12col×6lin
  (`{type,col,span,row,rspan,...}`) → **variedade quase infinita**.
- **8 layouts nomeados novos**: declaracao, processo (passos+setas), matriz (2×2), tabela
  (python-pptx table), equipe (grade+avatar), numerado, executivo (3 colunas), galeria.
  Total: **25 layouts nomeados + compose**.
- **Manifesto**: tabela de **decisão por tipo de conteúdo** + **few-shot** (3 exemplos) +
  spec dos blocos. `pick_layout` cobre blocks→livre, rows→tabela. Schema da tool
  `criar_apresentacao` estendido (blocks/headers/rows/bullets) — strict recursivo válido.
- Verificado: py_compile (6 arquivos) ✓, render de todos os layouts + livre/tabela ✓,
  auditoria strict das 36 tools = nenhum inválido ✓.

**Iteração 6 (PDF multi-formato) — 2026-06-22** (após pesquisa de 3 frentes):
- **`documents/report_builder.py`** — relatórios **spec→HTML→PDF** via o Chromium do
  Playwright (já empacotado). 12 blocos (capa, secao, texto, bullets, kpi, tabela, callout,
  citacao, duas_colunas, imagem, **grafico** matplotlib offline, divisor), CSS com tokens
  (`design_system.tokens_to_css`), @page + capa full-bleed + headers/footers (Página X de Y) +
  outline/bookmarks + skins por `tipo_fonte`. Verificado: renderiza PDF de 115KB end-to-end.
- **`documents/pdf_convert.py`** — fachada NATIVO→PDF: **MS Office COM** (pywin32, fidelidade
  alta) → **LibreOffice headless** (soffice.com + perfil isolado via `Path.as_uri()` + lock) →
  falha graciosa. Conversor detectado na máquina: **COM** (Office instalado).
- **Tools**: `criar_relatorio` (PDF bonito) + `exportar_pdf` (converte .docx/.xlsx/.pptx→PDF).
  Camada `documentos` + keywords. Strict recursivo válido (38 tools).
- Decisão da pesquisa: Chromium só p/ relatório HTML→PDF; arquivos nativos via COM/LibreOffice
  (round-trip HTML perde fidelidade). "Estilo de PDF por tipo" = ramificar o GERADOR, não o conversor.

**Iteração 7 (XLSX) — 2026-06-22:**
- **`documents/sheet_builder.py`** — `gerar_planilha(spec)` spec→XLSX via openpyxl, dirigido
  pelos design tokens: banda de cabeçalho colorida, linhas zebra, freeze panes, **formatos por
  coluna** (moeda/percent/data/número), **formatação condicional** (escala de cor, data bars,
  ícones, maior/menor), **gráficos nativos** (bar/line/pie), **painel de KPIs**, auto-largura,
  e `page_setup`/`print_area` p/ export PDF limpo via `pdf_convert`. `formatos` aceita lista
  `[{coluna,formato}]` (strict-safe) ou dict.
- **Tool `criar_planilha`** (camada documentos + keywords). Verificado: render XLSX ✓,
  strict recursivo válido (**39 tools**).

**Suíte de documentos completa (Fase 2):** `criar_apresentacao` (PPTX, 25 layouts + compose),
`criar_relatorio` (PDF HTML→Chromium), `criar_planilha` (XLSX), `exportar_pdf` (nativo→PDF
COM/LibreOffice). Todas fluem pelo cérebro/tool-calling.

**Pendente (futuro):** DOCX bonito no mesmo padrão (spec→python-docx); ícones embarcados;
auto-fit por medição (PIL); fluxo 2 estágios (outline→fill→validar); roadmap/14 (memória/
orquestrador). Iterar estética com feedback visual.
- Auto-fit por MEDIÇÃO (PIL) + split p/ slide de continuação; ícones embarcados; gráficos
  on-brand; fluxo 2 estágios (outline→fill→validar). Reusar `gen_image` no PDF/XLSX.

### Fase 3 — Code-execution / Programmatic Tool Calling (futuro)
Modelo escreve um bloco que orquestra várias tools num passo (CodeAct: +20% sucesso,
−30% passos), com sandbox. Maior ganho para tarefas multi-step pesadas.

### Fase 4 — Pesquisa de modelos baratos candidatos ✅ (jun/2026)
Picks aplicados em `config.OPENROUTER_MODELS` (free-tier: 20 req/min, 50/dia; 1000/dia após
crédito único de US$10):
- **pensar/tool-calling** → `qwen/qwen3-coder:free` (agêntico, 1M ctx). Alt: `openai/gpt-oss-120b:free`.
- **arquivos/docs** → `qwen/qwen3-next-80b-a3b-instruct:free` (tools + structured_outputs, JSON limpo).
- **imagem/visão** → `google/gemini-2.0-flash-exp:free` (a renderização de imagem continua na Pollinations).
- **fallback pago barato (sem cota)** → `deepseek/deepseek-v4-flash` (~US$0,09/0,18) ou
  `google/gemini-2.5-flash-lite` (~US$0,10/0,40). Baseline free: `meta-llama/llama-3.3-70b-instruct:free`.

Pendente: rotear de fato modelos DIFERENTES por tarefa (hoje OpenRouter usa o "thinking" em todo o
caminho de nuvem) e fallback automático free→pago — fazer junto da Fase 2.

## Decisões tomadas
- Modelo: **estrutura primeiro**; OpenRouter com modelos grátis/baratos por tarefa; pesquisa de
  "melhor modelo barato" fica para a Fase 4.
- Documentos: **ladder completo** spec→render + WeasyPrint/Typst (doc 10).
- Começar pelo **cérebro** (Fase 1), conservador.

## Riscos
- `main.py` é god object frágil e GUI (difícil de testar headless) → edições ≤2 funções,
  flags OFF por padrão, `py_compile` a cada passo.
- Paralelo só é seguro para tools **idempotentes/independentes** (abrir+abrir); marcar
  `parallel_safe=False` em tools com estado (abrir-e-digitar, rename, API rate-limited).
- OpenRouter: 5.5% de fee + hop de confiança; nunca habilitar prompt-logging; manter direto
  Groq/local para latência.

## Histórico
- **2026-06-21**: Diagnóstico completo (5+ agentes) e este plano. Início da Fase 1
  (config OpenRouter + tool_registry strict/camadas + ajustes cirúrgicos em `_pensar_e_agir`),
  tudo atrás de toggles OFF.
- **2026-06-21 (cont.)**: Seleção visual de provider + cérebro na UI (aba **Modelos**) e
  correção do bug "trocar provider não aplicava":
  - `_init_llm_clients()` centraliza a criação dos clients (groq/lmstudio/openrouter),
    idempotente, re-chamado ao trocar de provider.
  - `apply_models` agora **aplica ao vivo** (sem restart): re-lê prefs
    (`_aplicar_prefs_modelos`/`_aplicar_prefs_agente`) e chama `_aplicar_config_recarregado`
    (que passou a incluir `LLM_PROVIDER`/`OPENROUTER_*`/`AGENT_*` e re-inicializa os clients).
  - **OpenRouter fiado de ponta a ponta**: quando selecionado, vira o "cliente de nuvem"
    (`self._groq` ← OpenRouter, model id remapeado) → reusa todo o caminho de nuvem,
    incluindo `_pensar_e_agir`, sem mexer em call-sites. Chave entra pela aba **Setup**
    (`OPENROUTER_API_KEY`). Sem chave → fallback Groq. *(Resolve o "próximo passo #1".)*
  - UI: dropdown Groq/LM Studio/OpenRouter + campos de modelo por tarefa + toggles do
    cérebro (modo de tools, histórico, paralelo). Persistido em `jarvis_prefs.json`
    seções `models`/`agent`.
  - Verificado: `py_compile` (main/config/tool_registry) + `node --check` (bridge) + smoke do config.
  - **Pendente**: **Fase 2** (docs spec→render).
- **2026-06-21 (strict)**: `strict` schema implementado e auditado. `tool_registry._strictify`
  torna QUALQUER tool strict-compliant (todos os campos em `required`, opcionais viram
  nullable) e o `dispatch` descarta `None` (handler usa default) — nenhuma tool com arg
  opcional quebra. Toggle `AGENT_STRICT_TOOLS` (OFF por padrão, UI: aba Modelos → "Schema
  estrito"), fiado em `_pensar_e_agir` via `to_openai_tools(strict=...)`. Verificado: as 35
  tools geram schema válido (ex.: `clima.cidade` → `["string","null"]`).
- **2026-06-21 (Fase 4)**: modelos grátis/baratos reais aplicados em `OPENROUTER_MODELS`
  (ver seção Fase 4).
