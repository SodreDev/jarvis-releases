# Estudo — OpenJarvis, o núcleo: o que existe, o que presta e o que trazer para o Jarvis

**Data:** 2026-11-12 · **Autor:** CLI opus-estudo-nucleo (pedido do dono) · **Estado:** estudo, não decisão
**Referência estudada:** OpenJarvis (Stanford), Apache-2.0, clone em `../referencias/OpenJarvis`, commit `13706f2`.
**Par deste documento:** `docs/estudos/openjarvis-integracoes.md` (canais, conectores, skills, MCP, voz, front, desktop — outra CLI).

Convenção: `OJ:` = raiz do clone; `OJ/` = `src/openjarvis/`. Todo caminho:linha abaixo é evidência
lida no clone (somente leitura: nada foi instalado, executado ou baixado). Os caminhos do Jarvis
são relativos a este repositório.

---

## 0. Resumo para o dono (uma página)

1. **O OpenJarvis é grande e desigual.** A parte do núcleo que estudei tem ~150 mil linhas de
   Python, ~27,5 mil de Rust e ~7,8 mil funções de teste (662 arquivos). Cerca de 70% do
   aprendizado e das avaliações é infraestrutura de artigo científico (energia por token, GRPO,
   varredura de modelos). O que é produto de verdade é bem menor.
2. **O "roteamento inteligente" é quase todo promessa.** O roteador aprendido é recriado do zero a
   cada chamada e nunca recebe traces (`update_from_traces` não tem chamador). O SDK e o servidor
   nem roteiam. Os roteadores Bandit, GRPO e SFT só existem em Rust e o Python não os chama.
   DSPy e GEPA estão ligados de um jeito em que a nota não depende do candidato, então não otimizam
   nada. O *spec search* é código de pesquisa que roda, mas com gate fraco e LoRA em stub.
3. **A segurança tem boas ideias e implementação frouxa.**
   - O sandbox em contêiner não funciona de ponta a ponta: o Dockerfile chama um módulo que não existe.
   - O `mount_security` deixa passar a `$HOME` inteira.
   - As regex de segredo dão falso positivo em palavras comuns e não conhecem CPF.
   - O `shell_exec` pelo Rust ignora timeout e ambiente limpo.
   - O `http_request` expande `$VARIAVEIS` do ambiente nos cabeçalhos que o modelo escreve, o que vaza chaves.
   - Em vários pontos a falha fica **aberta**.
4. **Em quase tudo que se sobrepõe, o Jarvis já está à frente:**

   | Tema | OpenJarvis | Jarvis |
   |---|---|---|
   | Recuperação de memória | RRF, mapa de ids volátil, contexto injetado como *system* | RRF sobre denso + FTS5 + grafo, com abstinência e proveniência (`src/jarvis/memoryd/`) |
   | Auditoria | Hash encadeado que grava o próprio segredo | Hash encadeado, decisão antes do efeito (`src/jarvis/politica/auditoria.py`) |
   | Isolamento | Docker sem `--cap-drop` | Caixa bwrap com prlimit (`src/jarvis/caixa/scripts.py`) |
   | SSRF | Falha aberta no DNS | IP global, conexão no IP conferido (`src/jarvis/executor/web.py`) |
   | Redação de segredos | Sem `\b`, sem padrão brasileiro | Com `\b`, senha falada e CPF (`memoryd/importacao.py`, `politica/objetivo.py`) |
   | Trilha | Traces com mensagens inteiras em texto puro | Allowlist de metadados (`src/jarvis/trilha.py`) |
   | Delegação ao Claude Code | Sem `permissionMode`, sem retomada, sem stream | Já existe (ADR-0054) |

5. **O que vale trazer** é pouco, barato e concreto. O backlog completo está na §8. Os cinco
   primeiros:
   1. Um **harness de avaliação determinístico em pt-BR** para escolha de ferramenta e decisões do
      Jev, com um gate de regressão por categoria.
   2. **Custo e tokens por turno na trilha.** O Jarvis já recebe o `usage` e já conhece os preços,
      mas não grava nem soma.
   3. Um **guarda de laço** (chamada idêntica e vai-e-volta A-B-A-B) no laço de ferramentas.
   4. **Nota do dono por turno** (👍/👎 ou por voz), que alimenta os itens 1 e 5.
   5. Um **marcador de conteúdo não confiável e um scanner de injeção** como sinal barato para o
      guarda de contexto e para as mensagens de terceiros do social.
6. **Licença:** Apache-2.0, compatível com a do Jarvis (também Apache-2.0). Código copiado ou
   adaptado precisa manter o aviso de copyright ("Copyright 2025 The OpenJarvis Authors"), dizer
   o que mudou e entrar no `NOTICE`. Reimplementar só a ideia não obriga a nada, mas citamos na ADR
   (§7).

---

## 1. Método

- **Quatro leituras paralelas** (Explore/auditoria), cada uma com um bloco do núcleo:
  - núcleo e motor;
  - agentes e ferramentas;
  - segurança, memória e telemetria;
  - aprendizado e avaliações.
- **Conferências pontuais minhas** das afirmações mais fortes:
  - roteador recriado a cada chamada: `OJ/cli/ask.py:1035`;
  - `update_from_traces` sem chamador;
  - repetição sem ferramentas no HTTP 400: `OJ/engine/_openai_compat.py:105-108`;
  - entrypoint do sandbox inexistente: `OJ:deploy/docker/Dockerfile.sandbox:70` × `OJ/sandbox/` (só `__init__`, `mount_security`, `runner`, `wasm_runner`);
  - `sk-` sem borda de palavra: `OJ:rust/crates/openjarvis-security/src/scanner.rs:56`;
  - contexto injetado como SYSTEM: `OJ/tools/storage/context.py:109`;
  - `expandvars` nos cabeçalhos: `OJ/tools/http_request.py:112-115`;
  - métrica do DSPy que ignora a predição: `OJ/learning/agents/dspy_optimizer.py:101-106`.
- **Comparação com o Jarvis feita no código**, não na memória: `src/jarvis/{memoryd,politica,caixa,executor,provedores,s2,tarefas,trilha.py}`,
  `docs/adr/0001…0060`, `tools/medir_*.py` e `docs/medicoes/`.
- **Fora do escopo** (é da outra CLI): `channels`, `connectors`, `skills`, `mcp`, `speech`, `daemon`,
  `frontend`, `desktop`, `a2a`, `operators`, `recipes`, `mining`.

---

## 2. Mapa do núcleo

| Subsistema | Linhas (py) | Testes (`def test_`) | Maturidade | Uma linha |
|---|---:|---:|---|---|
| core (registry, events, config, types) | 3,8 mil | 282 | média | Registry e EventBus bons; `config.py` com 2,5 mil linhas e 60 dataclasses |
| engine | 5,8 mil | 413 | **alta** | OpenAI-compat, Ollama e nuvem, com stream, tool calling e descoberta |
| intelligence | 1,3 mil | 57 | baixa | Catálogo fixo de 78 modelos; a doc cita arquivos que não existem |
| system / sdk / templates | 1,8 mil + 0,7 mil + 0,1 mil | 76 + 5 | média | `QueryOrchestrator` simples; templates sem chamador |
| server (FastAPI) | 11,9 mil | 439 | média | Cerca de 326 rotas, um cliente de nuvem duplicado |
| agents | 24,2 mil | 607 | desigual | Orchestrator e LoopGuard bons; Operative quebrado; *hybrid* com 13,7 mil linhas de experimento |
| tools | 14,4 mil | 820 | média | Pipeline do executor bom; `shell_exec` e `http_request` perigosos |
| workflow / sessions | 0,8 mil + 0,5 mil | 17 + 18 | baixa | DAG sem aresta condicional; sessão que "consolida" apagando |
| security | 4,8 mil | 426 | média-baixa | Muitas camadas, regex fracas, falha aberta |
| sandbox | 0,7 mil | 48 | **não funciona** | O entrypoint do contêiner não existe |
| memory (+ `tools/storage`) | 1,0 mil (+ storage) | 229 | média | Fatos em JSONL; RRF; chunker; injeção como *system* |
| scheduler | 0,9 mil | 65 | baixa | Polling de 60 s em série; horário comparado como string |
| traces / telemetry | 1,0 mil + 4,3 mil | 62 + 304 | média-alta | Telemetria rica (TTFT, ITL, energia); traces em texto puro |
| learning | 14,5 mil | 726 + 113 | **promessa** (fora o `optimize`) | DSPy, GEPA e roteadores desconectados |
| evals / bench | 37,4 mil + 0,6 mil | 597 + 41 | alta como harness | 40 benchmarks, quase todos em inglês e via HF, com juiz em nuvem |
| cli | 17,9 mil | 659 | média | Cerca de 40 comandos; `workflow` é fachada |
| rust/ | 27,5 mil (rs) | ~230 `#[test]` | paralelo | O Python usa só 18 símbolos (segurança, LoopGuard, algumas tools, SQLite/BM25) |

**Sinais gerais de qualidade:**
- No `src` inteiro há poucos TODO (9) e poucos `NotImplementedError` (10). A dívida real aparece de outro jeito:
  - **`except Exception` que engole erro em `logger.debug`**: 202 só no bloco núcleo/motor;
  - **código sem chamador**;
  - **configuração sem efeito**: `merkle_audit`, `ssrf_protection`, `signing_key_path`, `enforce_tool_confirmation` e `local_engine_bypass` são lidas 0 vezes.
- Os testes usam muito mock (cerca de 1.100 `MagicMock`/`patch` só em learning e evals). Por isso não pegam os defeitos de integração descritos abaixo.
- **A documentação diverge do código** em vários pontos:
  - `OJ:docs/architecture/intelligence.md:18,246-252` cita `intelligence/router.py`, que não existe;
  - `learning.md:254-299` documenta módulos Python que só existem em Rust;
  - `security.md:9` diz "opt-in", mas o padrão vem ligado;
  - `agents.md` não fala do Operative.

---

## 3. Subsistema por subsistema

Formato: **o que é → como funciona → qualidade → o Jarvis já tem? → reaproveitar?**

### 3.1 core: registry, EventBus, config, tipos

- **Registry** (`OJ/core/registry.py`, 189 linhas)
  - `RegistryBase[T]` genérico. Cada subclasse guarda seus itens num atributo próprio (l.24-30).
  - Registro com `@register(key)`, `register_value`, `create(key, …)`.
  - São 17 registries tipados (Engine, Model, Agent, Tool, RouterPolicy…).
  - A descoberta acontece por efeito colateral de import. Os módulos opcionais entram com `except (ImportError, OSError)` (`OJ/engine/__init__.py:22-35`).
- **EventBus** (`OJ/core/events.py`, 212 linhas)
  - Pub/sub síncrono e thread-safe. Copia a lista de assinantes sob o lock e chama fora dele. Um assinante que quebra não derruba os outros (l.141-160).
  - Tem 60 `EventType`. O histórico não tem limite (l.140).
- **Config** (`OJ/core/config.py`, 2523 linhas)
  - Carrega em camadas: hardware detectado (chama `nvidia-smi` a cada carga), defaults, TOML (`~/.openjarvis/config.toml`) e perfil de segurança.
  - O overlay recursivo (l.1937-1995) **ignora chave desconhecida em silêncio** e não converte tipos.
  - Escolhe o motor pela GPU e o modelo por faixa de RAM (l.266-355).
- **Formato TOML**: seções `engine`, `intelligence`, `agent`, `security`, `sandbox`, `scheduler`, `traces`, `telemetry` etc. O `configs/openjarvis/config.toml` **não é default de usuário**: é a config de avaliação do GLM-4.7 em 8×A100. O exemplo `full-system-access.toml` libera `shell_exec` e `file_write` sem lista.
- **O Jarvis já tem** um barramento com envelope, epoch e contrato (`src/jarvis/barramento/`, ADR-0002/0007), catálogo de capacidades gerado de manifesto (ADR-0047) e `presets.toml` com validação. O registry e o EventBus do OpenJarvis são mais simples que os nossos.
- **Reaproveitar: não.** A única lição é inversa: o overlay de config deles aceita chave desconhecida calado, e o nosso não deve.

### 3.2 engine: os motores de inferência

- **Contrato** (`OJ/engine/_stubs.py`, 140 linhas)
  - `generate()` devolve `{content, usage, tool_calls, finish_reason}`.
  - `stream_full()` devolve `StreamChunk`.
  - `health()` e `can_serve(model)` são separados.
- **Backends**
  - OpenAI-compat gerado a partir de dados (`openai_compat_engines.py`, 61 linhas): vLLM, SGLang, llama.cpp, MLX, LM Studio…
  - Ollama nativo (`ollama.py`).
  - Nuvem (`cloud.py`, 2116 linhas): OpenAI, Anthropic, Google, OpenRouter, DeepSeek, MiniMax, Codex.
- **Escolha** (`_discovery.py:139-262`)
  - Motor explícito nunca é trocado.
  - Se o default não está saudável, testa os outros em paralelo e prefere um da mesma classe (local ou nuvem).
  - `can_serve` impede usar a nuvem para modelo de provedor sem chave.
  - `MultiEngine` (`multi.py`) nunca manda um modelo local para a nuvem em silêncio.
- **Detalhes bons**
  - HTTP 400 com `tools`: repete sem tools (`_openai_compat.py:105-108`).
  - `estimate_prompt_tokens` = caracteres/4 + 4 por mensagem, e usa `max(reportado, estimado)` (`_base.py:117`).
  - Detector de "contexto estourado" por marcadores (`_base.py:30-49`).
- **Fraco**
  - Não há retry nem backoff, nem circuit breaker.
  - "Saudável" na nuvem só quer dizer "tem chave" (`cloud.py:2071`).
  - Tabela de preços fixa e **duplicada** (`cloud.py:30-71` e `server/savings.py`).
  - `server/cloud_router.py` reimplementa os clientes de nuvem do zero.
- **O Jarvis já tem** isso e mais (`src/jarvis/provedores/`, ADR-0056):
  - presets do dono;
  - portão de licença, termos e interruptor de nuvem;
  - roteamento por capacidade (visão);
  - preço vindo da listagem do provedor (`interface.py:127-129`, `compativel.py:439-455`);
  - `stream_options.include_usage` (`compativel.py:137,188`);
  - a regra "o preset que não pode rodar não troca de provedor sozinho".
- **Reaproveitar (só a ideia):**
  - a repetição sem tools no 400, como fallback **anunciado na trilha** e não silencioso;
  - o detector de contexto estourado, que vira uma mensagem clara em vez de erro cru;
  - o `max(reportado, estimado)`, para o orçamento de 16 000 caracteres não confiar cegamente no provedor.

### 3.3 intelligence e roteamento por traces/custo: o que é real

| Peça | Onde | Real? |
|---|---|---|
| Catálogo de modelos | `OJ/intelligence/model_catalog.py` (78 `ModelSpec` fixos) | Real, estático, envelhece |
| `HeuristicRouter` | `OJ/learning/routing/router.py:139-177` | Real: regras fixas (urgência→menor; código→"coder"; complexidade ≤0,20→menor; ≥0,55→maior) |
| `score_complexity` | `OJ/learning/routing/complexity.py` (281) | Real: soma ponderada de regex **em inglês** + faixas de `max_tokens` |
| `LearnedRouterPolicy` | `OJ/learning/routing/learned_router.py` (236) | **Morto na prática** (detalhes abaixo) |
| Bandit (Thompson/UCB1), GRPO, SFT, TraceDriven | `OJ:rust/crates/openjarvis-learning/` (6,3 mil) | **Só Rust, sem chamador Python** |
| Roteamento no SDK e no servidor | `OJ/sdk.py:293,430`; `OJ/server/routes.py:243-271` | **Não roteia.** O modelo é fixo; o comentário "Resolve model via router" engana; a complexidade só aumenta `max_tokens` |

Por que o `LearnedRouterPolicy` está morto na prática:
- classifica a pergunta por regex em 5 classes e pontua `0,6·sucesso + 0,4·feedback`;
- **ignora custo e latência** (l.104 acumula a latência, l.215-224 não a usa);
- é greedy e não persiste nada;
- é recriado a cada chamada (`OJ/cli/ask.py:1035`, `OJ/agents/executor.py:408`);
- nenhum código chama `observe`/`update_from_traces`.

**Conclusão:** o OpenJarvis **não tem** roteamento por traces nem por custo funcionando. O que dá
para trazer é o **desenho** de um bandit (ver §3.13 e o item B5 do backlog). O código não serve.

### 3.4 system, server, sdk, templates

- **Caminho de uma pergunta**
  1. `SystemBuilder` resolve o motor.
  2. `setup_security` embrulha o motor com os guardrails.
  3. `InstrumentedEngine` publica `INFERENCE_END`/`TELEMETRY_RECORD` (`OJ/system/builder.py:184-200`).
  4. `QueryOrchestrator.ask` (`OJ/system/orchestrator.py:21-96`) injeta memória, detecta intenção por regex (só "good morning" → digest) e roda o agente ou o motor direto.
- **Servidor**
  - Loopback por padrão, autenticação com `compare_digest`, `/v1/chat/completions` compatível com OpenAI.
  - `agent_manager_routes.py` tem 2,6 mil linhas.
- **SDK** (`OJ/sdk.py`, 677): `Jarvis.ask/ask_full/ask_stream`.
- **Templates** (`OJ/templates/agent_templates.py`): **sem chamador**.
- **Reaproveitar: nada.** O Jarvis tem processo próprio, barramento e janela Qt, não precisa de servidor HTTP.

### 3.5 agents

Base comum (`OJ/agents/_stubs.py:44,379`):
- teto de passos `max_turns`, com padrão 10;
- até 2 continuações quando a resposta é cortada por tamanho;
- **nenhum limite de tempo** por execução, exceto no ClaudeCode.

São 22 agentes registrados.

| Agente | O que é de verdade | Veredito |
|---|---|---|
| `orchestrator` (544) | Function-calling OpenAI; executa em paralelo, em threads, as `tool_calls` do mesmo turno; gancho de governança que **falha fechado** (l.118-143). **Não tem subagentes** | Correto e simples; o nosso laço (ADR-0028/0038) já é mais rico |
| `native_react` / `react` (367) | Thought/Action/Observation interpretado por regex; um erro de parse **encerra a execução** (l.290-302) | Inferior |
| `operative` (328) / `monitor_operative` (758) | "Agentes de longa duração" | **Estado quebrado** (detalhes abaixo) |
| Agentes gerenciados (`manager.py` 872, `executor.py` 991, `scheduler.py` 325) | SQLite (`managed_agents`, `agent_tasks`, `agent_checkpoints`…), estado entre ticks = última resposta, 3 tentativas com backoff `min(10·2^n, 300)` s, orçamento de custo checado **depois** do tick, ticks **em série** | O que funciona de verdade; o nosso `GestorDeTarefas` (ADR-0038/0059) cobre o caso com teto e pergunta ao dono |
| `claude_code` (275 + `index.mjs`) | `node index.mjs` com JSON pelo stdin, incluindo `api_key`; `@anthropic-ai/claude-agent-sdk` fixado; `npm install` sob demanda; `maxTurns: 30`; **sem `permissionMode`/`canUseTool`, sem `resume`, sem stream**, bloqueante com 300 s | Nosso `delegacao/claude_code.py` (ADR-0054) já é melhor. A única lição: **fixar e conferir a versão** instalada (l.121-155) |
| `deep_research`, `morning_digest`, `proactive` | Pesquisa com citações, resumo diário por cron | Ideia de produto; a parte de canais é com a outra CLI |
| `hybrid/*` (13,7 mil) | Portes de experimentos de benchmark (minions, conductor, archon…); `hybrid/skillorchestra.py` fica escondido pelo pacote homônimo, é código morto | Ignorar |

Por que o estado do `operative` e do `monitor_operative` está quebrado:
- chamam `save_message(session_id, {dict})`, mas a assinatura é `(session_id, role, content)`. O `TypeError` é engolido em `logger.debug` (`operative.py:299-308`, `monitor_operative.py:727-739`);
- `memory_backend.store/retrieve` não bate com a ABC;
- os eixos `retrieval_strategy` e `task_decomposition` só aparecem como texto no prompt (`monitor_operative.py:206-208`);
- não existe teste.

**`LoopGuard`** (`OJ/agents/loop_guard.py`, 243 linhas, ~150 sem a ponte Rust) é a melhor peça desta pasta:
- bloqueia a chamada idêntica (SHA-256 de nome + argumentos) depois de 3 vezes;
- detecta vai-e-volta de período 2 e 3 (A-B-A-B, A-B-C-A-B-C), em l.221-232;
- avisa uma vez antes de bloquear (l.85-90).

O Jarvis tem algo parecido só para **falhas**: `src/jarvis/s2/recuperacao.py` não repete a mesma
ação idêntica que já falhou. A chamada idêntica que **dá certo** em laço e a oscilação ficam
apenas sob o teto de passos e o prazo. → Backlog B3.

Outras peças pequenas que valem estudo:
- `OJ/agents/errors.py` (116): classifica erro em retentável ou fatal (contexto estourado é fatal) e traz o backoff.
- `monitor_operative.py:519-552`: resume com LLM a saída de ferramenta acima de 2000 caracteres, com corte como fallback.

### 3.6 tools: definição, pipeline e catálogo

- **Definição**: classe `BaseTool` com `spec -> ToolSpec` (schema JSON, `requires_confirmation`, `timeout_seconds` padrão 30, `required_capabilities`) e `@ToolRegistry.register` (`OJ/tools/_stubs.py:120-185`).
  - **Os argumentos não são validados contra o schema**: só `json.loads` e checagem de que é um dict (l.262-277).
- **Pipeline** `ToolExecutor.execute` (`OJ/tools/_stubs.py:251-560`), em ordem:
  1. limite de taxa;
  2. guarda de fronteira (só para ferramenta não local);
  3. RBAC com piso canônico por ferramenta, **desligado por padrão**;
  4. *taint* de sessão;
  5. confirmação (sem callback, **nega**);
  6. execução num pool limitado (`_BoundedToolRunner`, l.31-111: 8 workers, 8 pendentes, contrapressão) com timeout;
  7. varredura de injeção na saída não local, envolvendo o texto em `[UNTRUSTED EXTERNAL CONTENT]` (l.495-530).
- **Defeitos de configuração**
  - `allowed_dirs` vazio quer dizer **sem restrição** (`OJ/core/config.py:1455`).
  - `is_local` está errado em `digest_collect` (lê e-mail e Slack) e no adaptador MCP; nesses casos o scanner de injeção não roda.
- **Bugs graves, para não copiar:**
  - `shell_exec` usa o Rust, que é obrigatório: `sh -c` **sem `env_clear` e sem timeout** (`OJ:rust/crates/openjarvis-tools/src/builtin/shell.rs:39-58`). Um código de saída diferente de zero volta como `success=True` (`OJ/tools/shell_exec.py:154-165`). O próprio teste admite (`OJ:tests/tools/test_shell_exec.py:102`).
  - `http_request` faz `os.path.expandvars` nos cabeçalhos que o modelo escreve (`OJ/tools/http_request.py:112-115`): o cabeçalho `$ANTHROPIC_API_KEY` sai com a chave. Sem cabeçalho, cai no `reqwest` do Rust, que segue redirecionamento e contorna o SSRF por salto feito no Python.
  - As ferramentas `agent_spawn`, `agent_send` e `agent_kill` são **falsas**: gravam num dict e respondem `"delivered": true` (`OJ/tools/agent_tools.py:94-122`).
  - `record_decision` deixa o modelo **se autoaprovar** e gravar "sempre aprovar" (`OJ/tools/proactive_tools.py:251-320`).
  - `repl` e `rlm_repl` usam `exec` no próprio processo com lista de bloqueio, o que não é sandbox.
- **Boas, pequenas:**
  - `code_interpreter.py:35-120`: AST em allowlist (`json`, `math`, `time`) + rlimits (CPU 10 s, AS 512 MB, FSIZE 0).
  - `templates/loader.py:39-166`: `safe_eval_expr`, interpretador de AST sem `eval`.
  - `approval_store.py` (406): níveis de risco + permissão lembrada por impressão digital (`sms_send:contact:+55…`).
- **O Jarvis já tem** um pipeline mais forte: PDP de capacidade tipada (ADR-0003), guarda de contexto (ADR-0049), tabela do sim (ADR-0046), sim por voz (ADR-0048/0057), caixa bwrap (ADR-0050) e níveis de acesso que nenhuma frase muda (ADR-0009). O que falta comparar é a **permissão lembrada** (item B9, decisão do dono).

### 3.7 workflow e sessions

- **Workflow** (796 linhas): DAG em TOML, ordenação topológica e estágios em paralelo (até 4).
  - `WorkflowEdge.condition` nunca é lido.
  - `PARALLEL` cai em "Unknown node type".
  - O nó de condição só produz o texto "true" ou "false", sem desviar o fluxo.
  - A CLI é fachada (`OJ/cli/workflow_cmd.py:20,53-55`).
- **Sessions** (`OJ/sessions/session.py`, 363 linhas): SQLite `sessions` + `session_messages`.
  - Depois de 24 h inativa, a sessão vira uma nova.
  - A "consolidação" acima de 100 mensagens **apaga** a metade antiga e guarda como resumo as 10 primeiras cortadas em 100 caracteres (l.237-266).
  - `ModelSummarization` não chama o modelo.
- **O Jarvis já tem** conversa persistente (`src/jarvis/memoryd/conversa.py`) e tarefas com fila (`src/jarvis/tarefas/`). **Ignorar.**

### 3.8 security: guardrails, scanners, auditoria, file_policy

| Peça | Regras / mecanismo | Onde age | Avaliação |
|---|---|---|---|
| `GuardrailsEngine` (`OJ/security/guardrails.py:160-288`) | SecretScanner + PIIScanner na entrada e na saída do motor; modos warn, redact e block; **padrão redact** (`OJ/core/config.py:1435-1440`) | Embrulha o motor | **O stream não é redigido**, só alerta depois (l.245-288). Se o Rust faltar, `setup_security` **falha aberto** (`OJ/security/__init__.py:44-60`) |
| SecretScanner (`OJ:rust/…/security/src/scanner.rs:52-112`) | `sk-…{20,}` sem `\b`, `sk-ant-`, `AKIA`, `gh[pors]_`, `password="…"` só entre aspas, URIs de banco, `BEGIN (RSA )?PRIVATE KEY`, Slack, Stripe | Motor e argumentos de ferramenta | Falso positivo: "task-management-system-overview" vira chave OpenAI e é **redigida por padrão**. Falso negativo: OpenSSH/EC key, JWT, `AIza`, `hf_`, `KEY=xyz` sem aspas |
| PIIScanner (`scanner.rs:114-162`) | e-mail, SSN, cartões sem Luhn, telefone dos EUA (qualquer número de 10 dígitos, até timestamp), qualquer IPv4 | Idem | **Nada brasileiro** (CPF, CNPJ, telefone BR) |
| Listas de segredo | **Cinco listas divergentes**: `scanner.rs`, `taint.py:53-69`, `credential_stripper.py`, `analytics/redaction.py:28-57` e um dict morto em `scanner.py:25-76` | — | A melhor delas é `analytics/redaction.py` (usa `\b`, JWT, `AIza`, `ya29`) |
| InjectionScanner (`OJ/security/injection_scanner.py:26-104`) | 11 regex ("ignore previous instructions", "you are now", DAN, `; rm`, `<\|im_start\|>`…) | Saída de ferramenta não local, e antes de extrair fato de memória (`OJ/memory/service.py:212-219`) | Nunca bloqueia, só cerca. Sinal barato e útil |
| Taint (`OJ/security/taint.py:37-69`) | `SINK_POLICY`: web e http bloqueiam PII e segredo; file_write e canais bloqueiam segredo | Sessão inteira (taint "grudento") | Ideia boa (rótulo × destino); implementação com muito falso positivo: um e-mail numa página baixada trava a web pelo resto da sessão |
| SSRF (`OJ/security/ssrf.py`, 187) | RFC1918, loopback, link-local, metadata, IPv4 embutido e "disfarçado" (`inet_aton`) | http, browser, web_search, RSS | Python falha fechado, mas o Rust (caminho preferido) **falha aberto** no DNS (`ssrf.rs:156-163`). Não fixa o IP (rebinding). Não bloqueia `100.64/10` |
| RateLimiter | Token bucket, 60 rpm, burst 10 | Antes dos gates do executor | Ok |
| CapabilityPolicy | RBAC com glob por agente e recurso | Executor | **Desligada por padrão** |
| file_policy (`file_policy.rs:7-30`, `file_policy.py:57-75`) | `.env*`, `*.pem/.key/.p12`, `id_rsa`, `.netrc`, `.pgpass`, `.git-credentials`, `shadow`…; segue a cadeia de symlinks | file_read/write, patch, pdf, db | Bom: o detalhe de seguir symlink vale |
| AuditLogger (`OJ/security/audit.py`, 328) | SQLite `security_events`, 0600, cadeia SHA-256 `prev\|ts\|type\|findings\|preview\|action` + `verify_chain` (l.106-147, 214-246) | Assina SECURITY_*, TOOL_CALL_END, CAPABILITY_DENIED | `log()` **grava o texto casado (o próprio segredo)**. Sem HMAC nem âncora: truncar o fim não é detectado |
| `data_boundary_audit.py` (1,9 mil) | Relatório de configuração (`jarvis scan`) | — | Não faz enforcement |

**Comparação com o Jarvis:**

| Tema | Jarvis | Situação |
|---|---|---|
| Segredos | `PADROES_DE_SEGREDO` (`src/jarvis/memoryd/importacao.py:26-90`): `\b`, JWT, `AIza`, chave privada genérica, URL com credencial, `KEY=valor` sem aspas, **senha falada** com dígito obrigatório, conteúdo de `.env` | Já melhor |
| CPF e PII de destino | `src/jarvis/politica/objetivo.py:86` | Já melhor |
| SSRF | `src/jarvis/executor/web.py:97-171`: exige `is_global` em **todos** os IPs resolvidos e conecta no IP conferido (sem rebinding) | Conferi: `::ffff:127.0.0.1`, `100.64.1.1`, `198.18.0.1`, `169.254.169.254` não são globais, e `2130706433`/`0x7f.1` resolvem para 127.0.0.1 e são recusados. Já melhor |
| Auditoria | `src/jarvis/politica/auditoria.py`: duas cadeias, decisão antes do efeito | Já melhor. **Mesma lacuna do OJ:** sem HMAC e sem âncora do último hash fora do banco, então truncar o fim não é detectado → item B14 |

**O que vale trazer:**
- o **scanner de injeção** como sinal (não como bloqueio) e o **marcador de conteúdo não confiável** → B6;
- o **follow de symlink** na política de arquivo (conferir se a nossa já faz) → B13;
- a ideia de **rótulo × destino** do taint, **por dado** e não por sessão. Isso já é quase o que `politica/objetivo.py` faz para PII por domínio.

### 3.9 sandbox e mount_security

- **`ContainerRunner`** (`OJ/sandbox/runner.py`)
  - Roda `docker|podman run --rm --network none -i` com montagens `:ro`.
  - Os segredos vão no JSON pelo stdin.
  - **Não usa** `--cap-drop`, `--read-only`, `--memory`, `--cpus`, `--pids-limit`, `--user`, `no-new-privileges` nem seccomp.
  - O único limite é o timeout de 300 s. `max_concurrent` é guardado e nunca usado.
- **Não funciona**
  - O Dockerfile chama `openjarvis.sandbox.entrypoint`, que não existe.
  - `SandboxedAgent` não é instanciado em lugar nenhum.
  - Vem desligado por padrão.
  - Sem contêiner, `RuntimeError`.
- **`mount_security.py`**
  - Olha só os componentes do caminho montado: montar `$HOME` passa, com `.ssh` e `.aws` dentro.
  - Padrões com `/` (`.config/gcloud`, `.kube/config`) nunca casam.
  - `read_only` é ignorado.
- **`WasmRunner`**: wasmtime com fuel. Não roda comando arbitrário.
- **Comparação:** a caixa do Jarvis (`src/jarvis/caixa/scripts.py`, ADR-0050) usa `bwrap --unshare-all --cap-drop ALL`, `/usr` só-leitura, tmpfs, `--clearenv`, prlimit de CPU, memória, arquivo e processos, e saída redigida. **É superior em tudo. Ignorar.**
- **Útil só como camada extra:** a allowlist de AST de `OJ/tools/code_interpreter.py:35-120` **antes** da caixa, para recusar cedo e com motivo claro. Baixo valor → B16.

### 3.10 memória: fatos, híbrida/RRF, chunking, inject_context

- **Fatos automáticos** (`OJ/memory/`)
  - JSONL com escrita atômica e `flock`, dedupe, teto de 1000 (FIFO).
  - Níveis `auto`, `trusted`, `untrusted` (`store.py:81-92`).
  - Extração por LLM local em thread com fila de 256 (prompt em `extractor.py:20-28`: até 10 fatos de 200 caracteres).
  - **O scanner de injeção roda antes da extração**, e o fato sinalizado vai para quarentena (`service.py:212-245`). É um bom padrão.
- **Documentos** (`OJ/tools/storage/`)
  - SQLite FTS5 com `porter unicode61`. A consulta junta as palavras com **OR**, então qualquer stopword casa, e o stemmer é inglês.
  - BM25 em Rust.
  - O "FAISS" do Rust usa embedding **falso por hash**. O FAISS e o DenseMemory do Python ficam só em memória.
  - Embeddings: `nomic-embed-text` (Ollama) ou MiniLM.
- **RRF** (`OJ/tools/storage/hybrid.py:12-67`)
  - `Σ wᵢ/(k+rankᵢ+1)`, k=60, cada braço busca 3×top_k.
  - A **chave de fusão é o texto bruto**, e o mapa de ids se perde no reinício.
- **Chunking**
  - `chunking.py`: 512 tokens por espaço, overlap 64; **destrói a formatação**.
  - O melhor é `chunk_markdown` (`OJ/tools/storage/dense.py:74-296`): corta em h2/h3 com breadcrumb, respeita cercas de código, teto de 4000 caracteres.
  - `dedupe_chunks` (`dense.py:326-510`): Jaccard de 5-gramas ≥0,7 com union-find.
- **`inject_context`** (`OJ/tools/storage/context.py:109-141`)
  - Orçamento de 2048 "tokens" (contados por espaço).
  - Os fatos levam até metade do orçamento, os mais novos primeiro, **sem relevância para a pergunta**.
  - **Funde tudo na mensagem SYSTEM**, o que eleva dado recuperado e não confiável ao papel de instrução. É o oposto da nossa regra (P6, gate 5).
- **O Jarvis já tem** (`src/jarvis/memoryd/`, ADR-0005/0008/0013, `docs/medicoes/f3-0{1,2}-*.md`):
  - livro-razão SQLite como fonte de verdade e índice trocável e reconstruível (`indice.py`);
  - FTS5 + vetor e5 + grafo com ativação, fundidos por RRF k=60 (`fusao.py`);
  - **abstinência** e parâmetros calibrados em 70/30 (`recuperacao.py`, `parametros.toml`);
  - injeção com orçamento fixo, **rotulada como dado**, proveniência visível e "sensível não vai à nuvem" (`src/jarvis/s2/memoria_do_turno.py`).
- **Reaproveitar:**
  - o padrão "**scan de injeção antes de gravar** + quarentena" para o que vem de terceiros (social, páginas) e pode virar memória → dentro de B6;
  - `chunk_markdown` e `dedupe_chunks` **só quando** o Jarvis ingerir documentos do dono. Hoje o memoryd guarda fala e memórias, não documentos → B15, adiado.

### 3.11 scheduler

- **`OJ/scheduler/`**
  - Tipos `cron` (croniter com fuso IANA, `scheduler.py:310-332`), `interval` e `once`.
  - SQLite `scheduled_tasks` + `task_run_logs`.
  - Uma thread faz polling a cada 60 s e executa **em série, sem timeout** por tarefa.
  - Sem *lease*: dois processos executam a mesma tarefa duas vezes.
  - Horário comparado como **string ISO** (`store.py:104-110`), o que quebra com fusos diferentes.
  - O intervalo deriva (o próximo é calculado depois do fim da execução).
  - `context_mode` é persistido e nunca usado.
- **Agentes gerenciados** (`OJ/agents/scheduler.py:21-48,228-260`): o próximo disparo de cron com fuso e a reconciliação de tarefa travada (timeout → N tentativas → erro) são as partes boas.
- **O Jarvis já tem** `src/jarvis/executor/alarmes.py`: timers e lembretes persistentes; o que venceu com o app fechado dispara ao abrir, marcado como atrasado; a mensagem é dita, nunca executada. **Não tem recorrência** ("todo dia às 8"), e a SPEC (§9, F5) prevê "proatividade só como compromisso criado pelo usuário, com quiet hours e orçamento".
- **Reaproveitar:** só a ideia do próximo disparo com fuso e da reconciliação de travadas, quando a F5 chegar → B10. O scheduler deles não serve.

### 3.12 traces e telemetria (custo e latência)

- **Traces** (`OJ/traces/store.py:16-95`)
  - Tabela `traces` (query, agent, model, engine, result, outcome, **feedback**, tokens, latência, **`messages` inteiras em texto puro**), `trace_steps` e `traces_fts`.
  - Arquivo 0600, **sem redação**.
- **Telemetria** (`OJ/telemetry/store.py:18-72`, `OJ/core/types.py` `TelemetryRecord`), por chamada:
  - tokens (prompt, completion), latência, **TTFT**, `cost_usd`;
  - ITL (média, mediana, percentis), prefill/decode;
  - energia por trilho (CPU, GPU, DRAM via NVML, `energy_nvidia.py:40-44,224`; RAPL `/sys/class/powercap`, `energy_rapl.py:20`; AMD; Apple), tokens/J.
  - Métricas de GPU desligadas por padrão. A mesma store tem uma tabela `mining_stats` (subsistema "Pearl").
- **Envio externo: PostHog**
  - `enabled=False` no código (`OJ/core/config.py:1224`), mas o instalador conta **Enter como consentimento** (`OJ:docs/telemetry.md:9-13`).
  - O host é um IP da AWS via sslip.io, com chave de projeto embutida.
  - O backend tem allowlist de eventos e redação. O front (posthog-js com autocapture e session replay) não passa por esses filtros.
  - Dependência obrigatória no `pyproject.toml`.
- **O Jarvis já tem**:
  - `src/jarvis/trilha.py`: JSONL local, **só metadados**, allowlist por campo, 0700/0600, rotação e retenção, ms por ferramenta, guarda, portão e delegação;
  - `src/jarvis/medicao.py` + `docs/medicoes/`: hardware, n, mediana e p95.
- **O Jarvis não tem, e o OpenJarvis mostra o formato:**
  - **tokens e custo por chamada do motor e do Jev**. O `usage` já chega (`provedores/compativel.py:188`) e o preço já é conhecido (`provedores/interface.py:127-129`), mas nada grava nem soma;
  - **TTFT do motor** na trilha;
  - **nota do dono por turno**.
  - → B2 e B4.
- **Não trazer:**
  - mensagens inteiras no trace (contra a nossa allowlist);
  - PostHog;
  - energia por trilho. Talvez num harness de medição isolado → B17.

### 3.13 learning: DSPy, GEPA, spec search, SFT/GRPO, roteador

| Peça | Arquivo | O que promete | O que é |
|---|---|---|---|
| DSPy | `OJ/learning/agents/dspy_optimizer.py` | Otimizar prompt e few-shot a partir de traces | **Quebrado** (detalhes abaixo) |
| GEPA (lib) | `OJ/learning/agents/gepa_optimizer.py` | Evoluir system_prompt, tools, max_turns, temperatura | **Quebrado**: `assess()` usa o feedback histórico, não roda o candidato (l.54-97), então todo candidato tem o mesmo fitness. A chamada `gepa.GEPAOptimizer(...).optimize(...)` (l.232-246) não parece bater com a API publicada (`gepa.optimize(seed_candidate, trainset, adapter…)`); não verifiquei sem rede. Os testes mockam a lib |
| ACE | `OJ/learning/agents/ace_optimizer.py` | — | Depende de um repositório git fora do PyPI; o extra citado não existe |
| `optimize` (LLMOptimizer + OptimizationEngine) | `OJ/learning/optimize/{llm_optimizer,optimizer,trial_runner,search_space,store}.py` | Laço "LLM propõe config → roda benchmark → LLM analisa" | **Real e executável.** Fronteira de Pareto (`optimizer.py:72-115`), merge a cada 5 trials, persistência SQLite, espaço em TOML (`search_space.py:10-200`). Ressalvas: o "melhor" usa só accuracy; os traces não chegam à análise (l.205) |
| Spec search (~4,2 mil) | `OJ/learning/spec_search/` | Um professor de ponta edita o harness do modelo local | Código de pesquisa que roda (detalhes abaixo) |
| SFT/LoRA, GRPO | `OJ/learning/training/lora.py`, `OJ/intelligence/grpo_trainer.py` | Treinar o modelo local com os traces | Real, **exige GPU grande**; `peft` não está em extra nenhum; full fine-tune é placeholder (`sft_trainer.py:124-130`) |
| `LearningOrchestrator` | `OJ/learning/learning_orchestrator.py` | Laço traces→aprende→avalia | Construído em `OJ/system/builder.py:279,650` (atrás de `training_enabled`); **ninguém chama `.run()`**; o evento `AGENT_LEARNING_STARTED` não tem assinante |

Por que o DSPy está quebrado:
- a métrica ignora a predição e devolve o feedback gravado (l.101-106);
- `dspy.configure`/`dspy.LM` nunca é chamado;
- os few-shot são descartados (l.191-195);
- otimiza um `ChainOfThought("question -> answer")` genérico, não o agente.

O que o spec search é e onde falha:
- **Como funciona:** operações tipadas fechadas (`models.py:44-69`). Diagnose (professor com ~10 ferramentas sobre traces e orçamento em US$) → Plan (tier de risco determinístico, `plan/risk_tier.py`) → Execute com gate (`gate/benchmark_gate.py:89-131`: Δ total > 0 e nenhum cluster cai mais que ε). O benchmark pessoal é sintetizado de traces bons (`optimize/personal/synthesizer.py:59-110`) com juiz LLM.
- **Falhas:**
  - LoRA em stub (`execute/appliers/lora_stub.py:35`);
  - checkpoint sem commit;
  - edits comparados com o snapshot inicial, não com o estado acumulado;
  - sem scorer, aplica **sem gate**;
  - limiar 0 sem teste de significância, então o ruído do juiz aprova edits;
  - o quickstart roda com `MagicMock`.

**Para o Jarvis:**
- **Não copiar** DSPy, GEPA, ACE, spec search nem treino.
- **A ideia que vale**, quando houver harness (B1), é o laço manual e barato do `LLMOptimizer`:
  1. um modelo forte lê as falhas por amostra e propõe **um** edit de prompt;
  2. o harness mede;
  3. o gate decide;
  4. o dono vê o diff (`plan/prompt_diff.py`) e aprova (`risk_tier.py`: edit de prompt = revisão humana).
- Cabe no nosso fluxo de ADR. Nunca contínuo e nunca automático → B12.

### 3.14 evals e bench

- **Evals**
  - 40 benchmarks registrados (`OJ/evals/cli.py:34-158`): GPQA, MMLU-Pro, MATH500, SimpleQA, GAIA, SWE-bench, TerminalBench, τ-bench, LiveCodeBench, ToolCall15… e casos de assistente (email_triage, morning_brief, daily_digest, doc_qa, browser_assistant).
  - 171 TOMLs de execução por modelo.
  - ~25 benchmarks baixam dataset do HF; vários exigem Docker ou navegador. Quase todos são em inglês.
- **Contrato mínimo** (bom e pequeno):
  - `EvalRecord{record_id, problem, reference, category, metadata}` (`OJ/evals/core/types.py:11-70`);
  - `Scorer.score(record, answer) -> (bool|None, meta)`;
  - `DatasetProvider`.
- **Juízes**
  - 23 scorers chamam LLM, com juiz padrão `gpt-5-mini` na nuvem.
  - 18 são determinísticos.
  - O **`ChecklistScorer`** (`scorers/_checklist.py:74-160`) avalia N critérios sim/não numa chamada.
  - O **ToolCall15** (`datasets/toolcall15.py`, `scorers/toolcall15.py:108-160`) usa ferramentas falsas e nota 0/1/2 por cenário: escolha de ferramenta medida **sem juiz**.
- **Runner** (`core/runner.py`, 1,4 mil): ThreadPool, Docker, W&B, Google Sheets, energia. Saída em JSONL por amostra + `.summary.json`. Não serve para nós.
- **Bench** (`OJ/bench/`, ~600): latência com 3 prompts fixos (`time.time()` em vez de `perf_counter`), throughput sequencial, J/token. `bench/_stats.py` (35) faz p50/p95/std sem numpy.
- **O Jarvis já tem** harness de **latência** e de **decisões pontuais**:
  - `tools/medir_guarda.py`, `medir_enderecamento.py`, `medir_prompt.py`, `medir_velocidade.py`, `harness_recuperacao.py`…;
  - `src/jarvis/medicao.py` (percentil por posição, cabeçalho de hardware) cobre o que o `_stats.py` faz.
- **O Jarvis não tem:** uma **suíte de acerto fim a fim** — dado o pedido em pt-BR, o Jev filtrou certo? o cérebro escolheu a ferramenta e os argumentos certos? — com **gate por categoria** que diga se uma mudança de persona, prompt (teto de 16 000) ou preset piorou alguma coisa → B1.

### 3.15 cli

São cerca de 40 comandos (`OJ/cli/__init__.py:98-202`). Os que servem de ideia:
- `eval compare` (diferença entre duas execuções);
- `optimize personal` (benchmark gerado de traces);
- `feedback thumbs/score` (nota do dono);
- `doctor` (diagnóstico; o nosso é `jarvis-voz --diagnostico`).

Do resto:
- `agents` (25 subcomandos), `compose`, `operators`, `pearl`, `mine`, `tunnel`, `gateway` e companhia: não servem.
- `workflow`: é fachada.

### 3.16 rust/

- 17 crates, ~27,5 mil linhas. O módulo PyO3 é **obrigatório** (`OJ/_rust_bridge.py:4`; `bm25.py:13` importa no topo).
- O Python usa só 18 símbolos: scanners, SSRF, CapabilityPolicy, RateLimiter, `is_sensitive_file`, LoopGuard, algumas tools e SQLite/BM25.
- As crates `engine` (2,4 mil), `learning` (6,3 mil), `agents` (1,5 mil), `scheduler`, `traces` e `telemetry` estão expostas e **não são usadas**. Já **divergiram** do Python:
  - cron próprio × croniter;
  - hash do audit com `{:?}` × `.value`, cadeias incompatíveis;
  - SSRF que falha aberto × fechado.
- **Lição:** um segundo caminho de implementação **contorna as proteções do primeiro** (shell sem timeout, http que pula o SSRF por salto). O Jarvis escolheu uma linguagem só no núcleo (ADR-0014) e deve continuar assim. **Ignorar.**
- **Exceção:** os ~60 linhas de Thompson Sampling em `OJ:rust/crates/openjarvis-learning/src/bandit.rs:41-130` servem de referência para portar em Python (B5).

---

## 4. Quadro comparativo: Jarvis × OpenJarvis (só o núcleo)

| Tema | Jarvis hoje | OpenJarvis | Quem está à frente |
|---|---|---|---|
| Provedores e presets | Presets do dono, portão de licença/termos/nuvem, capacidade (visão), preço vindo da listagem (ADR-0056) | Muitos backends, descoberta, fallback local/nuvem, preço em tabela fixa | Jarvis no controle; OJ em número de backends locais |
| Roteamento por custo/qualidade | Por capacidade, decidido pelo dono | **Promessa** (heurística por regex; aprendido morto) | Nenhum. Oportunidade: B5 |
| Telemetria de custo e latência | Latência por etapa na trilha; medições com p95 | Tokens, custo, TTFT, ITL e energia por chamada | **OJ** no formato. Oportunidade: B2 |
| Laço de ferramentas | Teto de passos, prazo, recuperação sem repetir falha, tarefa com pergunta no teto (ADR-0028/0038/0059) | `max_turns` + LoopGuard (repetição e oscilação) | Jarvis, menos a oscilação. Oportunidade: B3 |
| Subagentes | Assíncronos (ADR-0022), delegação ao Claude Code (ADR-0054) | Falsos (`agent_spawn` grava num dict) | Jarvis |
| Política e permissão | PDP tipado, guarda de contexto, tabela do sim, sim por voz, níveis de acesso | RBAC desligado, taint por sessão, confirmação sem callback = nega, permissão lembrada | Jarvis; ver B9 (permissão lembrada) |
| Segredos e PII | Com `\b`, senha falada, CPF por destino | 5 listas divergentes, falso positivo, nada BR | Jarvis |
| SSRF | Todos os IPs globais e conexão no IP conferido | Falha aberta no Rust, rebinding | Jarvis |
| Isolamento | bwrap + prlimit + clearenv | Docker que não sobe | Jarvis |
| Auditoria | 2 cadeias de hash, decisão antes do efeito | 1 cadeia que grava o segredo | Jarvis (os dois sem âncora: B14) |
| Memória | Ledger + índice trocável + grafo + abstinência + proveniência | RRF por texto, injeção como system | Jarvis |
| Agendamento | Lembretes persistentes, sem recorrência | Cron com fuso, mas frágil | Empate fraco; B10 na F5 |
| Avaliação de acerto | Harness de latência e de decisões pontuais | Contrato de eval, ToolCall15, checklist, gate por cluster | **OJ** no desenho. Oportunidade: B1 |
| Otimização de prompt | Manual, por ADR e medição | Laço LLM real (`optimize`); DSPy/GEPA quebrados | Ideia OJ, só manual: B12 |

---

## 5. Armadilhas do OpenJarvis que não devemos repetir

1. **Falha aberta** quando um componente falta: `setup_security`, o audit e o SSRF do Rust. No Jarvis, falha **pede o sim ou nega** (ADR-0049); manter.
2. **Dois caminhos de implementação** (Python e Rust) em que o segundo pula as proteções do primeiro.
3. **Conteúdo recuperado injetado como `system`** (`OJ/tools/storage/context.py:109`).
4. **Variáveis de ambiente expandidas** em texto que o modelo escreveu (`OJ/tools/http_request.py:112-115`).
5. **O modelo se autoaprovando** por ferramenta (`record_decision`).
6. **Configuração sem efeito** e **ferramenta fachada** (`agent_spawn`, CLI `workflow`): a interface mente sobre o que existe.
7. **`except Exception: logger.debug`** escondendo `TypeError` de assinatura (Operative): o defeito vive meses sem teste.
8. **Gate de otimização com limiar 0 e juiz ruidoso**: aceita ruído como melhoria.
9. **Telemetria com "Enter = consentir"** e host em IP cru.
10. **Regex de segredo sem `\b`**, que redige palavras comuns por padrão.

---

## 6. Dependências e custo de adoção

Nada do backlog pede dependência nova obrigatória:
- B10 pode usar `croniter` (MIT), ou um parser de 5 campos nosso;
- B17 usaria `nvidia-ml-py` (BSD), só no harness de medição.

O que **não** trazer em hipótese nenhuma, por peso ou risco:
- `datasets` (HF, puxa pandas e pyarrow);
- `posthog`;
- `python-telegram-bot` como obrigatória;
- `ddgs` (raspagem);
- `dspy`, `gepa`, `peft`;
- a extensão Rust.

---

## 7. Licença e atribuição (Apache-2.0)

- O OpenJarvis é Apache-2.0 (`OJ:LICENSE`, "Copyright 2025 The OpenJarvis Authors"). **Não há arquivo `NOTICE`** no clone, então não há texto de NOTICE a propagar.
- O Jarvis também é Apache-2.0, o que torna as licenças compatíveis.
- **Código copiado ou adaptado** (mesmo parcialmente) — itens marcados **[cópia]** no backlog:
  - **Cabeçalho no arquivo:** "Partes adaptadas de OpenJarvis (`<caminho no clone>`, commit 13706f2), Copyright 2025 The OpenJarvis Authors, Apache-2.0. Alterado: <o que mudou>." Isso cumpre a §4(b) da licença, que exige marcar arquivos modificados, e a §4(c), que exige manter os avisos.
  - **`NOTICE` do Jarvis:** entrada numa seção nova "Código de terceiros", com o mesmo crédito.
  - **Registro por máquina:** se o `tools/license_gate.py` passar a cobrir código de terceiros, um `licenses/codigo-de-terceiros.toml`. Hoje ele cobre modelos e bibliotecas distribuídas; estender é decisão do arquiteto.
- **Ideia reimplementada do zero** — itens marcados **[ideia]**: a licença não exige nada. Por honestidade, a ADR que adotar a ideia cita a origem (arquivo e commit).

---

## 8. Backlog priorizado

**Escalas**
- Valor: A / M / B.
- Risco: B / M / A. É o risco de piorar o Jarvis ou a segurança.
- Esforço: P (≤1 dia) / M (2–4 dias) / G (≥1 semana).

**Ordem:** valor alto e risco baixo primeiro; depois o que destrava outros itens.

### Adotar / adaptar

| # | Item | Ação | Valor | Risco | Esforço | Razão | Origem no clone | Licença |
|---|---|---|---|---|---|---|---|---|
| **B1** | **Harness de acerto em pt-BR**: cenários "pedido → ferramenta e argumentos esperados" e "pedido → decisão do Jev esperada", com ferramentas falsas e nota 0/1/2 por cenário, **sem juiz**. Saída por categoria (navegador, apps, memória, social, sim/não) e **gate de regressão**: total não cai e nenhuma categoria cai mais que ε, com n mínimo e 3 rodadas (mediana), no formato de `src/jarvis/medicao.py` | Adaptar o desenho | **A** | B | M | Hoje toda mudança de persona, prompt (no teto de 16 000), preset ou catálogo é validada à mão ou por latência. É o item que destrava B5 e B12 | `OJ/evals/datasets/toolcall15.py`, `OJ/evals/scorers/toolcall15.py:108-160`, `OJ/evals/core/types.py:11-70`, `OJ/learning/spec_search/gate/{regression,benchmark_gate}.py:89-131` | [ideia]; se copiar o scorer, [cópia] |
| **B2** | **Tokens, custo e TTFT por chamada na trilha**: campos numéricos novos na allowlist de `src/jarvis/trilha.py` (`tokens_entrada`, `tokens_saida`, `custo_usd_estimado`, `ttft_ms`) para o motor do cérebro, o Jev e a delegação. Custo = `usage` × `preco_entrada/saida` do catálogo; sem `usage`, estimativa `max(reportado, caracteres/4)` marcada como estimada. Mais um resumo por dia no `--diagnostico` | Adaptar | **A** | B | P | O dono escolhe preset (ADR-0056) sem ver quanto cada turno custa. Os dados já chegam (`provedores/compativel.py:188`, `interface.py:127-129`) e se perdem | `OJ/core/types.py` (`TelemetryRecord`), `OJ/engine/_base.py:117`, `OJ/engine/cloud.py:274-292` | [ideia] |
| **B3** | **Guarda de laço** no laço de ferramentas e de tarefas: chamada idêntica (hash de ferramenta + argumentos canônicos) com **sucesso** repetida N vezes e oscilação A-B-A-B e A-B-C-A-B-C → um aviso ao motor e depois recusa, reaproveitando o caminho de `src/jarvis/s2/recuperacao.py` | Adaptar | M-A | B | P | O `recuperacao.py` só cobre a repetição de **falha**; o laço de sucesso só para no teto de passos ou no prazo, gastando turnos e dinheiro | `OJ/agents/loop_guard.py:60-232` (~150 linhas úteis) | [cópia] se trouxer a detecção de período; senão [ideia] |
| **B4** | **Nota do dono por turno**: 👍/👎 na janela e frase de voz ("isso ficou ruim"), gravadas na trilha como código + id do turno, nunca o texto | Adotar a ideia | M | B | P | Sem sinal de qualidade não há roteamento por qualidade (B5) nem benchmark pessoal (B12) | `OJ/cli/feedback_cmd.py`, coluna `feedback` em `OJ/traces/store.py` | [ideia] |
| **B5** | **Sugestão de preset por bandit** (Thompson Sampling por classe de pedido, com a classe vinda do Jev e não de regex). Recompensa = nota do dono ou acerto do B1 − peso·custo − peso·latência. **Só sugere ao dono** ("o preset X saiu 40% mais barato e com as mesmas notas em navegador"). Não troca sozinho, porque a ADR-0056 diz que o preset é escolha do dono. Persistência em SQLite; explora só entre presets que passaram no B1 | Adaptar a ideia, portar ~60 linhas | M | M | M | Seria o "roteamento por traces e custo" que o OpenJarvis promete e não entrega, com o dono no comando. Depende de B1, B2 e B4 | `OJ:rust/crates/openjarvis-learning/src/bandit.rs:41-130`, `OJ/learning/routing/heuristic_reward.py:31-53` | [cópia] se portar o bandit linha a linha |
| **B6** | **Conteúdo de terceiros com marcador e scanner de injeção**: as ~11 regex do scanner, **reescritas em pt-BR e inglês**, rodam sobre mensagens do social (WhatsApp, Discord…), páginas e saída de MCP de fora. Um acerto vira **sinal** para o guarda de contexto (ADR-0049) e para a trilha (`categoria=injecao_suspeita`), e põe em **quarentena** o que iria para a memória. Nunca bloqueia sozinho | Adaptar | M | B | P | Barato. Cobre a superfície nova do social (fatias B–E) e o padrão "scan antes de gravar" da memória | `OJ/security/injection_scanner.py:26-104`, `OJ/tools/_stubs.py:495-530`, `OJ/memory/service.py:212-245` | [cópia] das regex; [ideia] do fluxo |
| **B7** | **Resumo de saída grande de ferramenta**: acima de um limiar, resumir com o modelo barato (o mesmo do Jev ou do resumo, ADR-0056) em vez de só cortar no `ORCAMENTO_DE_FERRAMENTAS`; corte como fallback; o resumo vai rotulado como dado | Adaptar | M | M (latência +0,5–1 s) | P | Resultado de navegador e delegação ao Claude Code chega grande; o corte perde o fim. Medir antes e depois com `medir_velocidade.py` | `OJ/agents/monitor_operative.py:519-552` | [ideia] |
| **B8** | **Classificação retentável × fatal** dos erros de provedor (contexto estourado = fatal com mensagem clara; 429/5xx = retentável com backoff curto e limitado), e no HTTP 400 com `tools`, **uma** repetição sem tools **anunciada na trilha** | Adaptar | M | B | P | Hoje o erro de provedor vira `Fim(ERRO)` sem distinção. Melhora a frase ao dono e evita turno perdido por 429 | `OJ/agents/errors.py` (116), `OJ/engine/_base.py:30-49`, `OJ/engine/_openai_compat.py:105-108` | [ideia] |
| **B9** | **Permissão lembrada por impressão digital** ("sempre pode responder a este contato no WhatsApp", "sempre pode fechar o Spotify"), com nível de risco, validade, revogável na janela, **só criada pela voz ou pelo clique do dono**, nunca por ferramenta | Avaliar com o dono | M | **A** (afrouxa confirmação; P13) | M | O dono já pediu menos confirmação (2026-10-18, ADR-0046/0057). É o mecanismo certo se ele quiser ir além da tabela fixa | `OJ/tools/approval_store.py` (406) — **não** copiar `record_decision` | [ideia] |
| **B10** | **Lembrete recorrente** ("todo dia às 8", "toda segunda") em `executor/alarmes.py`: próximo disparo com fuso, reconciliação ao abrir (já existe para o único), quiet hours e teto diário (SPEC F5) | Adaptar | M | B | M | É a base da "proatividade sob contrato" da F5. Evitar os erros do OJ: comparação por string, execução em série, deriva | `OJ/agents/scheduler.py:21-48,228-260`, `OJ/scheduler/scheduler.py:310-332` | [ideia]; `croniter` (MIT) opcional |
| **B11** | **Contrato mínimo de eval** (`registro`, `pontuador`, `resultado`) e **juiz por checklist** sim/não numa chamada, para o que B1 não mede sem juiz (tom da resposta, "respondeu uma vez só", ADR-0046/0058) | Adaptar | M | B | P | Complementa o B1 nas propriedades de fala. O juiz roda num preset do dono, nunca num modelo de nuvem imposto | `OJ/evals/core/types.py:11-70`, `OJ/evals/scorers/_checklist.py:74-160` | [cópia] se o prompt do checklist for traduzido do original |
| **B12** | **Laço manual de melhoria de prompt**: um modelo forte lê as falhas do B1/B11 e propõe **um** edit da persona; o B1 mede; o dono vê o diff e aprova (edit de prompt = risco alto). Rodar sob demanda, nunca contínuo | Adaptar a ideia | M | M | M | Usa o que o `optimize` do OJ tem de real, sem DSPy nem GEPA. Respeita o teto de 16 000 caracteres (o edit tem de caber) | `OJ/learning/optimize/llm_optimizer.py:52-270`, `OJ/learning/spec_search/plan/{risk_tier,prompt_diff}.py` | [ideia] |
| **B13** | **Conferir política de arquivo contra symlink**: o caminho e cada alvo da cadeia de symlinks passam pela lista de sensíveis do Jarvis, mais a lista do OJ (`.netrc`, `.pgpass`, `.git-credentials`, `*.p12/.pfx/.jks`) como casos de teste | Verificar e adaptar | M | B | P | Barato. Fecha uma via clássica (link para `~/.ssh/id_rsa` dentro de pasta liberada) se ainda estiver aberta | `OJ/security/file_policy.py:57-75`, `OJ:rust/…/security/src/file_policy.rs:7-30` | [ideia] (lista de nomes não é obra protegida) |
| **B14** | **Âncora da auditoria**: guardar o último hash e a contagem fora do banco (arquivo 0600 à parte, ou HMAC com chave local) para `verificar_cadeia` detectar **truncamento do fim** | Adotar (lição, não código) | B-M | B | P | O OJ mostra a lacuna e a nossa `politica/auditoria.py` tem a mesma | — (lição do `OJ/security/audit.py`) | — |
| **B15** | **`chunk_markdown` + `dedupe_chunks`** para quando o memoryd ingerir documentos do dono (notas, PDFs) | Adiar | M (futuro) | B | P | Hoje não há ingestão de documentos; trazer só quando houver | `OJ/tools/storage/dense.py:74-296,326-510` | [cópia] |
| **B16** | **AST em allowlist antes da caixa bwrap** para scripts Python: recusa cedo, com motivo legível ao modelo | Opcional | B | B | P | A caixa já isola; isto só melhora a mensagem e economiza um processo | `OJ/tools/code_interpreter.py:35-120` | [ideia] |
| **B17** | **Energia por chamada (RAPL/NVML)** só num harness de medição, para comparar motores locais | Opcional | B | B | P | Curiosidade útil para escolher motor local; fora do caminho da voz | `OJ/telemetry/energy_rapl.py`, `energy_nvidia.py:40-44,224` | [ideia]; `nvidia-ml-py` (BSD) só no harness |

### Ignorar (com a razão)

| Item do OpenJarvis | Por quê |
|---|---|
| Registry/EventBus/config (`OJ/core/`) | O barramento do Jarvis (envelope, epoch, contrato) e o catálogo gerado já são mais ricos. O overlay de config ignora chave desconhecida |
| Engine e clientes de nuvem (`OJ/engine/cloud.py`, `server/cloud_router.py`) | O `provedores/` do Jarvis já cobre, com portão de licença e preset do dono; o OJ tem duplicação e preço fixo desatualizado |
| `HeuristicRouter`, `score_complexity`, `LearnedRouterPolicy` | Regex em inglês, greedy, sem custo, sem persistência, morto em runtime |
| DSPy, GEPA, ACE, spec search, SFT/LoRA/GRPO, `LearningOrchestrator` | Quebrados (fitness independe do candidato), stubs, ou exigem GPU grande; o pouco que vale está em B12 |
| Agentes Operative/MonitorOperative, *hybrid*, `agent_tools`, workflow, sessions | Estado quebrado, fachadas, experimentos de benchmark; o Jarvis tem tarefas, subagentes e conversa persistente |
| `ClaudeCodeAgent` | O nosso (ADR-0054) é melhor; a única lição (fixar e conferir a versão do SDK) cabe numa linha |
| `shell_exec`, `http_request`, `repl` | Bugs de segurança (§3.6) |
| `GuardrailsEngine`, SecretScanner/PIIScanner, as 5 listas de segredo | As nossas listas são melhores e têm padrão brasileiro; a redação cega na entrada e sem stream é pior |
| Sandbox em contêiner, `mount_security`, `WasmRunner` | Não funcionam ou são inferiores ao bwrap |
| RRF/FTS5/FAISS/`inject_context` | O memoryd já é superior; a injeção como system é o oposto da nossa regra |
| `TaskScheduler` | Série, sem timeout, comparação por string; só a ideia entra em B10 |
| Traces com mensagens inteiras | Contra a allowlist da trilha |
| PostHog e analytics, leaderboard | Envio externo; "Enter = consentir" |
| `EvalRunner`, datasets do HF, configs por modelo | Pesados, em inglês, fora do nosso caso; o desenho entra em B1 e B11 |
| `server/` (FastAPI), `sdk.py`, `templates/`, CLI | O Jarvis não é servidor HTTP; o diagnóstico já existe |
| Todo o `rust/` | Caminho paralelo que contorna as proteções; ADR-0014 fixou uma linguagem no núcleo. Exceção: referência do bandit (B5) |

### Ordem sugerida de execução

**B2 → B3 → B4 → B1 → B6 → B8 → B14/B13 → B11 → B7 → B10 → B5 → B12.** B9 só com a decisão do
dono. B15 a B17 ficam para quando houver motivo.

Os quatro primeiros são pequenos e independentes, e dão ao dono **visibilidade** (custo, laço e
nota) antes de qualquer automação. B5 e B12 só fazem sentido com B1, B2 e B4 no lugar.
