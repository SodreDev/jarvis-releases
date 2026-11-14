# Estudo — executar por CLIs de agente nativas (Claude Code, Codex, opencode, DeepSeek, Gemini, Goose)

*opus-estudo-clis, 2026-11-14. Só leitura: nenhuma CLI foi instalada nem rodada. Os fatos vêm da
documentação oficial e do código-fonte clonado em `../referencias/<nome>` (commit e data na seção
Fontes). O que não foi visto rodando está marcado **[a provar]**.*

## 0. Resumo (para decidir)

- **Pedido do dono (2026-11-14, memória dbb1c726):** o Jarvis executa por CLIs de agente nativas,
  que iteram e raciocinam enquanto executam; permissões em dois modos — **automático** (só pede
  matar processo e apagar arquivo) e **bypass** (nada pede); navegador de verdade; o Jarvis define a
  **tarefa concreta** (passos), não só um objetivo em prompt.
- **O achado que decide a arquitetura:** em todas as CLIs, o modo headless "de linha" (`claude -p`
  simples, `codex exec`, `opencode run`, `gemini -p`, `dsh headless`) **não tem canal para perguntar
  ao Jarvis**. Quando uma regra manda perguntar, essas CLIs aprovam tudo ou negam tudo. O
  **bypass** funciona em qualquer uma. O **automático** (rm/kill perguntam, o resto passa) só
  funciona num modo **bidirecional**:
  - Claude Code: `--permission-prompt-tool`;
  - Codex: `app-server`;
  - opencode: `serve`;
  - DeepSeek Harness: SDK com `approval_requests`;
  - qualquer uma via **ACP**, com `session/request_permission`.
- **O protocolo comum existe: ACP** (Agent Client Protocol, JSON-RPC 2.0 por stdio, como o MCP que
  o Jarvis já fala na ADR-0052). Falam ACP:
  - nativamente: `gemini --acp`, `opencode acp`, `goose acp`, `dsh --profile acp`,
    `codewhale serve --acp`;
  - por adaptador oficial da org agentclientprotocol: `claude-agent-acp` e `codex-acp`.
- **Recomendação, em ordem:**
  1. **Claude Code em `stream-json`**, primeiro. É o que o dono já assina e mandou usar, e 80% do
     processo já existe em `delegacao/claude_code.py`.
  2. **Um servidor MCP do próprio Jarvis**, que entrega a qualquer CLI as ferramentas do navegador
     de verdade (a extensão do Jarvis, por CDP) e a ferramenta de aprovação. Com isso, cada clique
     ainda passa pelo PDP e pelo scanner de injeção do Jarvis.
  3. **Um adaptador ACP genérico**, que liga de uma vez opencode, Gemini, DeepSeek Harness, Goose e
     Codex (via `codex-acp`).
- **DeepSeek:** o "harness" é **oficial** (`deepseek-ai/deepseek-harness`, `dsh`, MIT), mas está em
  *release candidate* e **envia o log da sessão à DeepSeek por padrão**. O caminho mais barato e já
  documentado é o Claude Code apontado ao endpoint compatível com Anthropic da DeepSeek: reaproveita
  o adaptador da fatia 1.

## 1. Como o Jarvis delega hoje (o ponto de partida)

| Peça | Onde | O que faz | Choque com a decisão de hoje |
|---|---|---|---|
| `delegar.claude_code` | `catalogo/delegar.claude_code.yaml`, `src/jarvis/delegacao/claude_code.py`, `config.py` (ADR-0053/0054) | `claude -p --chrome --output-format json --permission-mode dontAsk --tools "" --allowedTools mcp__claude-in-chrome__* --strict-mcp-config --setting-sources project --no-session-persistence --max-turns N`, com a tarefa pela entrada padrão, numa pasta temporária, com ambiente por lista de permissão, prazo e morte do grupo | `dontAsk` + `--tools ""` = **nada executa fora do navegador**. Também pede o sim sempre, é "último recurso" (`delegar_cedo`), devolve um JSON só **no fim** (sem eventos) e roda um tiro só, sem iterar na mesma sessão |
| Provedores `codex`, `opencode` | `src/jarvis/provedores/{codex,opencode}.py` (ADR-0056) | Usam a CLI como **modelo de conversa**: ferramentas da CLI desligadas; se aparecer item de ferramenta, abortam | É o oposto do que o dono quer agora. O processo (`processo.py`: ambiente sem chaves, linhas, prazo) é reaproveitável. O opencode 2.x foi recusado por "saída do run não documentada", mas agora a saída está lida no fonte (§3.2) |
| Tarefas | `src/jarvis/tarefas/gestor.py`, `s2/tarefa_do_pedido.py` (ADR-0022/0038) | Pedido → objetivo → tarefa. Cada passo é proposto pelo motor e passa pelo PDP, com `tarefa_motor` `direto`/`agente` | Ponto natural para um terceiro motor: **`nativo`** |
| Cliente MCP | `src/jarvis/mcp/cliente.py` (ADR-0052) | JSON-RPC por stdio (`TransporteStdio`) | Mesma forma de fio do ACP: o transporte é reaproveitável |
| Servidor MCP do Jarvis | — | **não existe** | Peça que falta para dar o navegador do Jarvis às CLIs (§5) |

## 2. Comparação rápida

| CLI | Versão vista | Licença | Dono | Headless de linha | Bidirecional (aprovação ao Jarvis) | ACP | Login por assinatura |
|---|---|---|---|---|---|---|---|
| Claude Code | 2.1.x (docs) | proprietária (CLI) | Anthropic | `claude -p --output-format stream-json --verbose` | `--permission-prompt-tool mcp__…` ou Agent SDK `can_use_tool` | via `claude-agent-acp` (Apache-2.0) | sim (Pro/Max, `claude auth login`) |
| Codex CLI | 0.169.0 | Apache-2.0 | OpenAI | `codex exec --json` (aprovação fixa em `never`) | `codex app-server` (JSON-RPC, pedidos de aprovação ao cliente) e SDK Python `openai-codex` | via `codex-acp` | sim (ChatGPT, `codex login`) |
| opencode | 2.3.0 (V2) | MIT | Anomaly (ex-sst) | `opencode run --format json` (`ask` → rejeita; `--auto` → aprova) | `opencode serve` (HTTP+SSE, `…/permission/{id}/reply`) | `opencode acp` | provedores do models.dev; chave ou `opencode auth login` |
| DeepSeek Harness | 0.2.2-rc.3 | MIT | **DeepSeek (oficial)** | `dsh --profile headless --json` (sem canal de aprovação) | SDK Python `deepseek-harness-sdk` com `approval_requests=True` | `dsh --profile acp` | chave da API DeepSeek |
| Gemini CLI | 0.68.0 | Apache-2.0 | Google | `gemini -p -o stream-json` (`ask_user` → nega) | só via ACP | `gemini --acp` | sim (conta Google: 1000 req/dia grátis) |
| Goose | 1.59.0 | Apache-2.0 | AAIF / Linux Foundation (ex-Block) | `goose run -t … --output-format stream-json` | via ACP | `goose acp` | provedores; pode usar `claude-agent-acp`/`codex-acp` |
| Codewhale (ex-DeepSeek-TUI) | 0.10.3 | MIT | comunidade, "não afiliado à DeepSeek" | `codewhale exec --output-format stream-json` | `codewhale app-server --http` | `codewhale serve --acp` | chave DeepSeek |

## 3. Cada CLI: como dirigir, eventos, permissões

### 3.1 Claude Code (Anthropic) — fonte: code.claude.com/docs

**Instalar e entrar** (quem tem assinatura):

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude auth login
claude auth status
```

- `claude auth status` sai com JSON por padrão: `loggedIn`, `authMethod` = `claude.ai`; código 0
  quando há login.
- O Jarvis **não** configura login nenhum: usa o `claude` que o dono instalou.

**Dirigir.** A sessão fica viva e recebe novas mensagens pela entrada padrão:

```bash
claude -p --input-format stream-json --output-format stream-json --verbose \
  --include-partial-messages \
  --permission-mode <ver abaixo> --settings <json do modo> \
  --mcp-config <json com o servidor do Jarvis> --strict-mcp-config \
  --permission-prompt-tool mcp__jarvis__aprovar \
  --append-system-prompt <regras fixas> --max-turns N [--model sonnet] [--resume <session_id>]
```

- A tarefa entra como mensagem `user` em JSON pela entrada padrão, nunca no argv — a mesma regra
  da ADR-0054.
- Sem `--input-format stream-json`, `-p "<prompt>"` vale para um tiro só, e a sessão continua
  depois com `--resume <session_id>`.

**Eventos (`stream-json`):**

- `system/init`: modelo, tools, `mcp_servers[{name,status}]`, `mcp_server_errors`;
- `system/api_retry`: `error` = `rate_limit` / `billing_error` / `authentication_failed`;
- `system/permission_denied`;
- `assistant`: blocos `text` e `tool_use`, mais `usage`;
- `user`: `tool_result`;
- `stream_event`: deltas de texto;
- `result`: `subtype` (`success`, `error_max_turns`, `error_during_execution`, …), `is_error`,
  `num_turns`, `total_cost_usd`, `usage`, `modelUsage`, `permission_denials`, `session_id`.
- SIGTERM sai com 143, e SIGINT encerra o turno limpo.

**Permissões:**

- Os modos da CLI são `default`/`manual`, `acceptEdits`, `plan`, `auto` (classificador da
  Anthropic), `dontAsk` e `bypassPermissions` (= `--dangerously-skip-permissions`; recusado como
  root).
- **Cuidado com o nome:** o `auto` do Claude Code é um *classificador*, não o "automático" do dono.

| Modo do dono | Como ligar no Claude Code |
|---|---|
| **bypass** (nada pede) | `--permission-mode bypassPermissions`. A doc diz que só regras `ask` explícitas ainda perguntam; regras `deny` do Jarvis, se houver, continuam valendo |
| **automático** (só matar/apagar pede) | `--settings '{"permissions":{"allow":["Bash","Edit","Write","WebFetch","mcp__jarvis__*"],"ask":["Bash(rm *)","Bash(rmdir *)","Bash(kill *)","Bash(pkill *)","Bash(killall *)","Bash(find * -delete*)","Bash(git clean *)"]}}'` + `--permission-prompt-tool mcp__jarvis__aprovar`. Quem responde o "ask" é o Jarvis, pela ferramenta MCP dele, e pergunta ao dono por voz. **[a provar]** que `ask` vence um `allow` amplo (a doc de avaliação de regras não foi lida até o fim). Alternativa: um hook `PreToolUse` que devolve `permissionDecision: "ask"` ou bloqueia com saída 2 |

**Sessões:**

- `--resume <id>`, `--continue`, `--session-id <uuid>`, `--fork-session`,
  `--no-session-persistence`;
- `claude -p --continue` acha sessões de `-p`;
- o custo de uma sessão retomada vem acumulado.

**Custo:** na assinatura, gasta o limite de uso da conta. O `total_cost_usd` é uma estimativa a
preço de lista, não cobrança. `--max-budget-usd` corta pela mesma estimativa.

**Navegador:**

- `--chrome` exige login `claude.ai`: chave de API ou `setup-token` desligam o Chrome;
- a doc só descreve uso interativo. **[a provar]** em `-p` (mesma pendência da ADR-0054, item 1);
- o servidor MCP chama-se `claude-in-chrome`.

**Agent SDK** (`pip install claude-agent-sdk`):

- traz `query()`, `ClaudeSDKClient`, `ClaudeAgentOptions(permission_mode, allowed_tools,
  can_use_tool, hooks, mcp_servers, cwd, resume, max_turns, …)` e embute um binário próprio;
- **Risco de termos:** a doc diz que terceiros não podem oferecer login claude.ai ou os limites da
  assinatura no produto deles via SDK sem aprovação. Por isso o Jarvis deve dirigir o **`claude`
  que o dono instalou e logou** — o que a decisão do dono pede — e não embutir o SDK com token.
- ACP: `@agentclientprotocol/claude-agent-acp`, construído sobre o SDK, com o mesmo cuidado de
  termos.

### 3.2 opencode (V2, `anomalyco/opencode`, MIT)

**Mudanças da V2 que importam aqui** (`migrate-v1.mdx`):

- o pacote agora é `@opencode/cli`;
- `permission` virou `permissions`, `bash` virou `shell` e `task` virou `subagent`;
- `attach` deu lugar a `--server URL` / `--standalone`;
- o **provedor `opencode.py` do Jarvis foi escrito para a V1**.

**Headless de linha** (`packages/cli/src/commands/commands.ts`):

```bash
opencode run [--standalone] [-s ID|-c] [-m provedor/modelo#variante] [--agent NOME] \
  --format json [--thinking] [--auto] "mensagem"
```

- Eventos NDJSON `{type, timestamp, sessionID, part}`:
  - `step_start`;
  - `text` — no fim do bloco, não por token;
  - `reasoning`;
  - `tool_use` — só ao concluir;
  - `step_finish` — com **`cost` e `tokens`**;
  - `retry`, `error`.
- Com regra `ask`: **sem `--auto` rejeita; com `--auto` aprova** (`run/noninteractive.ts`, ~l.97–112).
  Não há meio-termo, então `run` só serve para o **bypass**: `--auto`, aliases `--yolo` e
  `--dangerously-skip-permissions`.

**Bidirecional** — `OPENCODE_PASSWORD=<aleatória> opencode serve --hostname 127.0.0.1 --port <p>`:

- HTTP Basic com usuário `opencode`; a V2 sempre exige senha.
- Endpoints (`packages/protocol/openapi.json`):
  - `POST /api/session` com `{location:{directory}, agent, model, permissions:[regras]}`;
  - `POST /api/session/{id}/prompt` com `{text, delivery: steer|queue}`;
  - `GET /api/event` (SSE): `permission.asked`, `session.text.delta`,
    `session.tool.{called,progress,success,failed}`, `session.usage.updated`,
    `session.execution.{succeeded,failed,interrupted}`;
  - `POST /api/session/{id}/permission/{requestID}/reply` com `{decision: once|always|reject}`;
  - `POST /api/session/{id}/interrupt`.
- Ou, mais simples: **`opencode acp`** (stdio, com `session/load`/`resume`/`fork`).

**Permissões** (`permissions.mdx`): lista ordenada `{action, resource, effect}`, em que **vale a
última regra que casa**:

```jsonc
// automático
{"permissions":[{"action":"*","resource":"*","effect":"allow"},
  {"action":"shell","resource":"rm *","effect":"ask"},
  {"action":"shell","resource":"kill *","effect":"ask"},
  {"action":"shell","resource":"pkill *","effect":"ask"},
  {"action":"shell","resource":"killall *","effect":"ask"}]}
// bypass
{"permissions":[{"action":"*","resource":"*","effect":"allow"}]}
```

**MCP:** `"mcp":{"servers":{"jarvis":{"type":"local","command":[…]}}}`. A ação de permissão de uma
tool MCP é `jarvis_<tool>`.

**Sessões e custo:** as sessões ficam em SQLite (`-s ID`, `-c`, `session export`). O custo vem no
`step_finish` e em `opencode stats --cost --json`.

**Riscos:**

- **CVE-2026-22812**: servidor V1 sem autenticação, abaixo de 1.0.216;
- **GHSA-632h-h47v-g4x4**: RCE em `/global/upgrade`, corrigida em 1.18.22;
- na V2, `opencode pair --remote` expõe o servidor à internet;
- o servidor deve ficar só em 127.0.0.1, com senha aleatória por processo, nunca o serviço de fundo
  na porta fixa 49374.

### 3.3 Codex CLI (`openai/codex`, Apache-2.0)

**Headless de linha** (`codex-rs/exec/src/cli.rs`):

```bash
codex exec --json [-m modelo] [-C pasta] [--skip-git-repo-check] [--ephemeral] \
  [-s read-only|workspace-write|danger-full-access] [--output-schema f.json] [-o ultima.txt] -
codex exec resume <id|--last> "continuação"
```

- **`exec` fixa `approval_policy = Never`** (`exec/src/lib.rs:632`): com sandbox, o que precisaria
  de aprovação falha.
- `--full-auto` não existe mais. O **bypass** é `--dangerously-bypass-approvals-and-sandbox`
  (`--yolo`).
- Eventos JSONL:
  - `thread.started{thread_id}`;
  - `turn.started`;
  - `item.{started,updated,completed}`, com itens `agent_message`, `reasoning`,
    `command_execution`, `file_change`, `mcp_tool_call`, `web_search`, `todo_list`;
  - `turn.completed{usage{input_tokens, cached_input_tokens, output_tokens,
    reasoning_output_tokens}}`;
  - `turn.failed`, `error`.

**Bidirecional:** `codex app-server` (JSON-RPC por stdio, "experimental"):

- métodos `thread/start`, `turn/start`, `thread/resume`;
- **o servidor pede ao cliente** `item/commandExecution/requestApproval` e
  `item/fileChange/requestApproval`;
- o cliente responde `accept | acceptForSession | decline | cancel`.
- SDK Python `pip install openai-codex`: `Codex(approval_handler=fn)` (o handler padrão aceita
  tudo).
- ACP: `codex-acp`, que sobe o app-server e traduz.

**"Só destrutivo pergunta"** — regras execpolicy em `~/.codex/rules/*.rules`:

```python
prefix_rule(pattern=["rm"], decision="prompt", justification="apaga arquivo")
prefix_rule(pattern=[["kill", "pkill", "killall"]], decision="prompt")
```

- Teste: `codex execpolicy check --rules f.rules rm -rf x`.
- `prompt` só tem efeito no app-server ou no ACP.
- Há ainda uma heurística interna para `rm -f`/`-rf` (`is_dangerous_command.rs`).

**MCP:** `[mcp_servers.jarvis]` em `config.toml`, com `command`/`args` ou `url`, e
`approval_mode = auto|prompt|…` por tool.

**Sessões:** `$CODEX_HOME/sessions`.

**Login:** `codex login` (ChatGPT), `--device-auth` ou `--with-api-key`.

**O Jarvis já tem** `provedores/codex.py` com `exec --json`, que é o lado "modelo".

### 3.4 DeepSeek — o que existe de fato

| Nome | O que é | Dono | Licença / maturidade | Como dirigir |
|---|---|---|---|---|
| **DeepSeek Harness (`dsh`)** | O "harness" oficial, citado em api-docs.deepseek.com/guides/coding_agents | **deepseek-ai** | MIT; **pré-lançamento** 0.2.2-rc.3 (2026-11-13), repo criado em 2026-08 | `dsh --profile headless "tarefa"` / `dsh headless --permission-mode workspace-write --json - < tarefa.txt` (headless **sem canal de aprovação**); `dsh --profile acp`; SDK Python `deepseek-harness-sdk` (`DeepSeekHarness(…, approval_requests=True)` responde `approval/request` por stdio — o que mais encaixa num host Python) |
| **Codewhale** (ex-**DeepSeek-TUI**) | TUI/CLI de comunidade para modelos DeepSeek | comunidade (codewhale-hq; o README diz "not affiliated with DeepSeek") | MIT; 0.10.3, ativo | `codewhale exec --auto --output-format stream-json "…"`; `codewhale serve --acp`; `permissions.toml` (regras `ask` ignoradas em `--auto`) |
| **Claude Code + endpoint da DeepSeek** | Claude Code falando com a API compatível com Anthropic da DeepSeek | doc oficial DeepSeek | — | `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`, `ANTHROPIC_AUTH_TOKEN=<chave DeepSeek>`, `ANTHROPIC_MODEL=deepseek-flash[1m]` (e os `ANTHROPIC_DEFAULT_*_MODEL`); sem Chrome (só com login claude.ai), sem `cache_control`, `deepseek-v4-pro` sem imagem |
| deepseek-agent, DeepSeekCode, deepcode-cli, Deepy… | projetos pequenos | comunidade | variadas | não avaliados |

**Riscos do `dsh`:**

- **`session-log-deepseek` vem ligado** e envia o log da sessão (até 8 MiB por pedido) junto com as
  chamadas à API oficial (`packages/session/session-log-deepseek/README.md:31`). O Jarvis teria de
  forçar `enabled: false`.
- O perfil `sdk-minimal` fixa `danger-full-access`.
- A sandbox é do sistema (bwrap/Landlock), sem regras por comando: o "automático" do dono só sai
  pelo `approval/request` do SDK, com o Jarvis olhando o comando.

### 3.5 Gemini CLI (Google, Apache-2.0)

**Dirigir:**

```bash
gemini -p "<tarefa>" -o stream-json --approval-mode yolo|auto_edit|default --policy <pasta> \
  [-r latest] [--session-id <uuid>]
```

**Eventos:**

- `init{session_id, model}`;
- `message`;
- `tool_use`;
- `tool_result`;
- `error`;
- `result{status, stats{tokens…}}`.

**Política** em TOML (`~/.gemini/policies`), com `decision = allow|deny|ask_user` por
`commandPrefix`:

- **em `-p`, `ask_user` vira negação**: o automático só funciona com `gemini --acp`;
- o bypass é `--yolo`.

**Navegador:** subagente `browser_agent`, desligado por padrão, com `chrome-devtools-mcp`
embutido. `sessionMode existing` se liga a um Chrome com porta de depuração — veja o limite do
Chrome no §5.

**Cota grátis:** 1000 pedidos/dia com conta Google.

### 3.6 Goose (AAIF/Linux Foundation, Apache-2.0)

- `goose run -t "<tarefa>" --output-format stream-json [--max-turns N] [--no-session]`, com
  eventos `message`, `notification`, `error`, `complete{tokens, cost_usd}`.
- `GOOSE_MODE=auto|approve|smart_approve|chat`.
- `goose acp` fala ACP.
- Pode usar `claude-agent-acp`/`codex-acp` como "provedor".
- Relevância **baixa**: o Jarvis já é o orquestrador; o Goose seria um orquestrador a mais.

## 4. ACP — o protocolo comum

Spec: agentclientprotocol.com. É JSON-RPC 2.0 por stdio.

| Direção | Mensagens que o Jarvis usa |
|---|---|
| Jarvis → CLI | `initialize`; `session/new {cwd, mcpServers}` (o Jarvis entrega o **próprio** servidor MCP aqui); `session/prompt {prompt:[blocos]}` (a tarefa); `session/cancel`; `session/load` (retomar); `session/set_mode` |
| CLI → Jarvis (notificação) | `session/update` com: `agent_message_chunk`, `agent_thought_chunk`, `tool_call`, `tool_call_update`, `plan`, `usage_update` (visto no fonte do opencode e do Gemini), `session_info_update` |
| CLI → Jarvis (pedido) | **`session/request_permission {toolCall, options[allow_once\|allow_always\|reject_once\|reject_always]}`** → resposta `{outcome:{outcome:"selected", optionId}}`; e `fs/read_text_file`/`fs/write_text_file` (o cliente pode servir o sistema de arquivos) |

- **Modo bypass:** o Jarvis responde `allow_once` a tudo, na hora. Melhor ainda: configurar a CLI
  para não perguntar (`--yolo`, regra `allow`), para não ter ida e volta.
- **Modo automático:** o Jarvis olha `toolCall.kind` (`delete`, `execute`, …) **e o comando de
  fato**:
  - apagar, matar processo ou um comando composto que contenha isso → pergunta ao dono;
  - o resto → `allow_once`.
  - O `kind` é dica de interface; o comando tem de ser conferido também.
- Python: `pip install agent-client-protocol` (Apache-2.0); ou ~200 linhas sobre o
  `TransporteStdio` da ADR-0052.

## 5. Navegador de verdade

| Caminho | Funciona com | Limite |
|---|---|---|
| `claude --chrome` (Claude in Chrome) | só Claude Code com login claude.ai | **[a provar]** em `-p`; o navegador e a extensão são da Anthropic; o Jarvis não vê nem filtra as páginas |
| `chrome-devtools-mcp` / Playwright MCP numa porta de depuração | qualquer CLI com MCP | **Desde o Chrome 136**, `--remote-debugging-port` é ignorado no perfil padrão (exige outro `--user-data-dir`): **não é o navegador logado do dono**. A porta aberta também dá controle a qualquer processo local |
| **Servidor MCP do Jarvis** expondo `browser.*` da **extensão do Jarvis** (`chrome.debugger`/CDP, ADR-0051) | **qualquer** CLI (Claude, Codex, opencode, Gemini, dsh, Goose) | É código novo, mas reaproveita os corpos que já existem. **Cada clique passa pelo PDP, pelos modos do dono e pelo scanner de injeção (ADR-0065)**, e o texto das páginas volta marcado como dado |

**Recomendação:** o servidor MCP do Jarvis. É o que faz "a extensão funcionar como a do Claude in
Chrome" para **todas** as CLIs e mantém o Jarvis como cérebro. A CLI raciocina e itera, mas o
navegador, a política e a trilha continuam dele.

## 6. A mudança mínima proposta: "Executor de CLI nativo"

```
cérebro (s2) ──TarefaNativa──▶ ExecutorNativo ──▶ Adaptador {claude-stream | acp | codex-app | opencode-http}
     ▲   │                         │  eventos normalizados          │ processo da CLI do dono
     │   └─ confere o critério ◀───┘  (EventoDoExecutor)            │ (pasta, ambiente por lista)
     │       e manda a próxima                                      ▼
     └──── aprovações ◀── servidor MCP do Jarvis (aprovar + browser.* + PDP + scanner)
```

- **`TarefaNativa`** (definida pelo Jarvis, nunca pela CLI):
  - `objetivo`;
  - `passos[]` concretos;
  - `criterio_de_pronto` (o que o Jarvis vai conferir);
  - `limites` (`max_turnos`, `prazo_s`, `max_rodadas`);
  - `cwd`;
  - `modo` (`automatico`|`bypass`);
  - `ferramentas` (que tools do MCP do Jarvis ela vê).
  - Vai como **um** bloco de prompt estruturado, com as regras fixas no system prompt.
- **`EventoDoExecutor`** (comum):
  - `inicio{sessao}`;
  - `texto{delta}`;
  - `pensamento`;
  - `ferramenta{id, nome, tipo, entrada}`;
  - `ferramenta_fim{id, ok, saida_resumida}`;
  - `plano{itens}`;
  - `permissao{id, ferramenta, comando, tipo}`;
  - `uso{tokens_in, tokens_out, custo_usd?}`;
  - `fim{ok, motivo, resumo}`;
  - `erro`.
  - O card de tarefas mostra o progresso, e o uso entra na trilha de consumo (ADR-0061).
- **Não virar mero repasse de prompt.** O laço é do Jarvis:
  1. o Jarvis manda a tarefa;
  2. acompanha os eventos e pode corrigir o rumo no meio (mensagem nova na sessão do
     `stream-json`, `delivery: steer` no opencode, `session/cancel` + novo `session/prompt` no ACP);
  3. no `fim`, **ele mesmo confere** o critério com as próprias ferramentas (lê a aba, o arquivo, o
     estado);
  4. se não bateu, manda "falta X, porque vi Y" **na mesma sessão** (`--resume`/`session/load`),
     até `max_rodadas`;
  5. relata ao dono só o que conferiu (decisão do dono, item 3: "não declarar feito o que não fez").
- **Escolha da CLI:**
  - preset novo com papel `executor` em `presets.toml` (ADR-0056), por exemplo `executor =
    "claude"`, com os campos `cli`, `modelo`, `modo`;
  - `checar()` por CLI (executável, login, versão) degrada com mensagem clara, como o
    `DelegadorClaudeCode.checar` já faz;
  - o Jarvis não troca de CLI sozinho.
- **Onde mora:** `src/jarvis/delegacao/` (já fora de `executor/` por causa do `test_sem_shell`):
  - `nativo.py`: tipos, núcleo e laço de rodadas;
  - `adaptadores/claude.py`;
  - `adaptadores/acp.py`;
  - mais tarde `adaptadores/codex_app.py`.
  - Reaproveita `ambiente_minimo`, `matar_o_grupo`, a pasta temporária e o prazo do
    `claude_code.py`.
  - Também reaproveita o `TransporteStdio` do MCP.
  - A tool `delegar.claude_code` vira `delegar.executar` (o id antigo fica como apelido), e o
    `GestorDeTarefas` ganha `tarefa_motor = "nativo"`.
- **Precisa de ADR nova** (o próximo número livre; outra CLI trabalha em permissões agora). Ela
  substitui pontos da ADR-0054 pela decisão do dono:
  - `dontAsk` + `--tools ""` dão lugar ao modo do dono;
  - o "sim sempre" vira "só destrutivo pergunta no automático";
  - "último recurso" / `delegar_cedo` passa a ser executor normal;
  - "uma delegação, sem iterar" passa a ser sessão com rodadas;
  - ficam: argv fixo, tarefa pela entrada padrão, ambiente por lista sem chaves do Jarvis, prazo,
    trilha só com códigos, o resultado como dado.

## 7. Recomendação priorizada

| # | O quê | Por quê | Esforço | Risco |
|---|---|---|---|---|
| 1 | **Claude Code `stream-json` bidirecional** (adaptador `claude`) | Assinatura do dono; mandato explícito ("a execução vem da CLI do Claude"); 80% do processo já existe e está testado com `claude_falso.py`; eventos e custo documentados | M (3–4 fatias pequenas) | Médio: `ask` vs `allow` e `--chrome` em `-p` **[a provar]**; consome o limite da conta |
| 2 | **Servidor MCP do Jarvis** (`aprovar` + `browser.*` da extensão) | Navegador de verdade e permissões iguais para toda CLI, com PDP e scanner no caminho; tira a dependência do `--chrome` | M | Médio: concorrência com o uso do navegador pelo próprio Jarvis (um dono por aba) |
| 3 | **Adaptador ACP genérico** | Um adaptador para opencode, Gemini, `dsh`, Goose, Codex (`codex-acp`) e Claude (`claude-agent-acp`); permissão bidirecional padronizada | M | Baixo-médio: ACP ainda evolui (métodos `unstable_*`); os adaptadores são pacotes npm |
| 4 | **Preset "DeepSeek"** = adaptador 1 + `ANTHROPIC_BASE_URL` da DeepSeek | Custo por token baixo, sem código novo; a chave vai do chaveiro para o ambiente **só desse processo** | P | Baixo: sem Chrome (o navegador vem pelo item 2) |
| 5 | `dsh` (oficial) via ACP/SDK | Harness nativo do DeepSeek | P (com o item 3) | Médio-alto: rc, log enviado por padrão (forçar `enabled: false`), API mudando |
| 6 | Codex `app-server` direto | Só se o `codex-acp` não bastar (aprovação com `acceptWithExecpolicyAmendment`) | M | Médio: "experimental" |

**Primeiro o Claude Code**, porque é o único que junta as três coisas:

- o dono já paga e mandou;
- o código atual já sobe esse processo com ambiente seguro;
- o modo bidirecional (`--permission-prompt-tool`) é documentado e cabe no servidor MCP do item 2.

O ACP vem em seguida porque, com um adaptador, abre todas as outras.

## 8. Plano em fatias

| Fatia | Entrega | Pronto quando |
|---|---|---|
| **F0 — prova real** (o dono, ~30 min) | Rodar uma vez, em pasta descartável, cada comando do §3 com uma tarefa boba; gravar a saída em `tests/fixtures/clis/<cli>-<modo>.jsonl` | Fixtures reais de `claude` (stream-json com `rm` em `ask` + prompt-tool), `opencode acp`, `gemini --acp`; as quatro pendências **[a provar]** respondidas |
| **F1 — núcleo + adaptador Claude** | `delegacao/nativo.py` (`TarefaNativa`, `EventoDoExecutor`, laço de rodadas) e `adaptadores/claude.py` (stream-json in/out, `--resume`, modos via `--settings`/`--permission-mode`); `claude_falso.py` emitindo stream-json | Testes: argv por modo, eventos normalizados das fixtures, prazo/cancelar, segunda rodada na mesma sessão, `rm` → evento `permissao` |
| **F2 — servidor MCP do Jarvis** | `python -m jarvis.mcp_servidor` (stdio): `aprovar` (responde ao prompt-tool consultando o modo do dono e, se for destrutivo, a voz) e `browser.*` pelos corpos da extensão, com PDP + scanner | Claude falso chama `mcp__jarvis__browser_read` e passa pelo PDP; `rm` no automático pergunta, no bypass não |
| **F3 — cérebro dirige** | `tarefa_motor = "nativo"`, `delegar.executar`; o critério é conferido pelo Jarvis; até `max_rodadas`; card de progresso; trilha (`delegacao` + consumo ADR-0061) | Harness pt-BR (ADR-0064) com casos "abre o contato e manda X" executando sem pedir permissão e relatando só o conferido |
| **F4 — ADR** | ADR nova substituindo pontos da ADR-0054 (§6) | Aceita pelo dono |
| **F5 — ACP genérico** | `adaptadores/acp.py`; presets `opencode`, `gemini`, `codex` (`codex-acp`) | As mesmas provas da F1–F3 com as fixtures da F0 |
| **F6 — DeepSeek** | Preset `deepseek` (Claude + endpoint) e, opcional, `dsh` via ACP com `session-log-deepseek.enabled=false` | Tarefa simples conclui; nenhuma chave no argv nem na trilha |

## 9. Riscos transversais

- **Bypass + navegador + páginas de terceiros = injeção.** Se o navegador vier pelo MCP do Jarvis
  (§5), o scanner da ADR-0065 vê o texto antes da CLI. Pelo `--chrome`, não vê.
- **"Só destrutivo pergunta" por padrão de comando é melhor-esforço.** `bash -c`, `python -c
  'os.remove'`, `find -delete`, `xargs rm` escapam de regra por prefixo. O dono aceitou o risco;
  mesmo assim, o `aprovar` do Jarvis olha o comando inteiro (com o Jev na zona cinza), em vez de
  confiar só na regra da CLI.
- **Segredos:** cada CLI recebe ambiente por lista, sem as chaves do Jarvis. A chave do DeepSeek só
  vai para o processo que precisa dela, nunca no argv.
- **Servidores locais** (opencode `serve`, codex `app-server` em ws): só stdio ou 127.0.0.1 com
  senha aleatória; nunca o `pair --remote`.
- **Termos da assinatura:** dirigir o binário que o dono instalou e logou, não embutir o SDK com o
  login dele num produto distribuído.
- **Versões que andam rápido:** opencode V1→V2 quebrou integrações; `dsh` é rc. Fixar a versão
  mínima por adaptador e degradar com a frase do que fazer, como `provedores/opencode.py` já faz.

## Fontes (acesso em 2026-11-14)

**Código clonado** (`../referencias/`, `git clone --depth 1`):

| Repositório | Commit / data |
|---|---|
| anomalyco/opencode (ex-sst/opencode) | b659188 / 2026-11-14 |
| openai/codex | 65a5410 / 2026-11-14 |
| google-gemini/gemini-cli | 4ed06ed / 2026-11-13 |
| aaif-goose/goose (ex-block/goose) | 2365bc5 / 2026-11-13 |
| deepseek-ai/deepseek-harness | 39163dd / 2026-11-13 |
| codewhale-hq/Codewhale | 981a453 / 2026-11-14 |

**Claude Code:**

- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/permission-modes
- https://code.claude.com/docs/en/permissions
- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/setup
- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/chrome
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/agent-sdk/python
- https://code.claude.com/docs/en/agent-sdk/cost-tracking

**ACP:**

- https://agentclientprotocol.com/protocol/tool-calls
- https://github.com/agentclientprotocol/python-sdk
- https://github.com/agentclientprotocol/claude-agent-acp
- https://github.com/agentclientprotocol/codex-acp

**DeepSeek:**

- https://api-docs.deepseek.com/guides/coding_agents
- https://api-docs.deepseek.com/guides/anthropic_api
- https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code

**opencode, segurança:**

- https://osv.dev/vulnerability/CVE-2026-22812
- https://securitylabs.datadoghq.com/articles/opencode-upgrade-remote-code-execution/

**Releases:**

- https://github.com/openai/codex/releases
- https://github.com/google-gemini/gemini-cli/releases

**Chrome 136, depuração remota:** https://developer.chrome.com/blog/remote-debugging-port
