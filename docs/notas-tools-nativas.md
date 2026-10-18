# Tools nativas do assistente de voz — referência e escolhas (2026-10-18)

Pedido do dono: mais tools nativas, seguras e tipadas (nada de shell livre), tomando como
**referência** — só a lista e os contratos, nada de código — as tools do opencode, do Claude Code e
do MCP do Orchestrator.

## O que as três referências oferecem

| Harness | Tools (nome → contrato em uma linha) |
|---|---|
| opencode (`opencode.ai/docs/tools`, lido em 2026-10-18) | `bash` roda comando de shell; `edit` troca texto exato; `write` cria/sobrescreve arquivo; `read` lê com faixa de linhas; `grep` busca por regex; `glob` acha caminhos por padrão; `lsp` consulta servidor de linguagem; `apply_patch` aplica patch; `skill` carrega um `SKILL.md`; `webfetch` lê uma página; `websearch` pesquisa na web (Exa/Parallel); `question` pergunta ao usuário com opções |
| Claude Code | `Bash`, `Read`, `Edit`, `Write`, `Glob`, `Grep`, `WebFetch`, `WebSearch`, `Task` (subagente), `TodoWrite`, `NotebookEdit`; agendamento/lembrete (`ScheduleWakeup`, cron), `PushNotification`, `AskUserQuestion` |
| MCP do Orchestrator (neste repositório vizinho, só leitura) | `shell_exec`/`ssh_exec` (comando), `area_list/read/write` (arquivos da área), `wake_me` (timer que acorda a sessão), `ask_owner`/`decision_*` (perguntar ao dono), `cli_*` (dirigir outras CLIs), `workspace_*` (cards na tela), `ui_*` (dirigir a interface), `retrieve_memory`/`store_memory`/`doc_read` (memória e documentos), `image_generate` |

## O que um assistente **de voz** aproveita — e o que não

Fica de fora, de propósito (proibido pela §4 / `CONTRIBUTING`): `bash`, `shell_exec`, `ssh_exec`,
`cli_send`, `run` — poder que depende do texto que o modelo escreve. Também fora, por serem de
desenvolvedor: `edit`/`apply_patch`/`lsp`/`NotebookEdit`.

Aproveitado, **como contrato tipado do Jarvis**:

| Ideia da referência | Tool do Jarvis | Tier |
|---|---|---|
| `wake_me` / agendamento | `timer.alarm.set/list/cancel` (vira `Notification`) | moderado / livre |
| `webfetch` / `websearch` | `web.ler`, `web.buscar` (só dado público, conteúdo = dado) | livre |
| `PushNotification` | `notify.desktop.send` | livre |
| `read`/`glob`/`grep` | já existiam: `files.read_text/list_dir/search_in_roots` | livre |
| `write` (sem sobrescrever) | `files.write_draft`, `files.create_dir`, `files.copy`, `files.move` | moderado |
| `Task` | `tarefa.iniciar/cancelar/estado` (item 5) | moderado / livre |
| `question` / `ask_owner` | a confirmação na faixa da janela (tier perigoso) | — |
| — (específico de assistente) | `system.*` (hora, estado, volume, brilho), `media.*`, `window.*`, `clipboard.*` | livre; `window.close_app` perigoso; `clipboard.text.write` moderado |

## Decisões

- **Nenhum shell.** O desktop é chamado por `executor/comandos.py`: lista fechada de programas, `argv`
  montado pelo código a partir de argumentos tipados, lançador injetável. Terceira abertura nomeada
  do `test_sem_shell`.
- **Web sem anti-robô e sem vazar.** DuckDuckGo HTML foi tentado e devolve 202 (anti-robô): o padrão é a
  Wikipédia (sem chave, verificado ao vivo); Brave Search entra com `BRAVE_SEARCH_API_KEY` (não
  verificado). A conexão vai ao IP **já conferido** (nada de rede local nem metadados de nuvem).
- **`consulta_publica`** é uma classe de risco nova: sai um pedido para a web pública, sem dado do
  dono (a consulta passa pela redação de segredos), e o resultado é de terceiros. Não é `egress`
  (que sempre confirma).
