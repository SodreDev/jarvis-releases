# Handoff — depuração e automação: guarda de contexto, caixa de scripts, e o desenho do CDP/MCP (ADRs 0049–0053)

**Autor:** opus-scripts-guarda · **Data:** 2026-10-29 · **Branch:** master (push para `origin/reescrita`).

O dono pediu dar ao Jarvis capacidade de estudar/depurar no navegador e automatizar com scripts, em camadas: (A) navegador por CDP, (B) executor de scripts isolado, (C) cliente MCP, com (D) um guarda de contexto que compara cada ação proposta com o objetivo da tarefa (ADR-0030), e (E) a viabilidade de interagir com o Claude in Chrome. A camada 3 (apps fora do navegador, AT-SPI) ficou para depois, por decisão dele.

## O que está PRONTO e provado na máquina (contêiner/fakes, sem tocar no navegador/áudio reais)

### D — Guarda de contexto (ADR-0049) — commits `9e83312`, `ad5746b`
- `src/jarvis/politica/guarda.py`: `GuardaDeContexto.julgar(Acao, Objetivo) -> Julgamento` (`permitir`/`pedir_confirmacao`/`barrar`). Ordem: **leitura pura passa** → **lista de negação e regras de sim/permissão** (sem rede) → **cache por (objetivo, forma)** → **Jev só na zona cinza**, prazo 0,8 s, e **falha/sem-classificador pede o sim** (nunca permite na dúvida). A `forma` troca literais e números do script por marcadores (duas chamadas que só diferem nos valores batem no cache). Barrar vira **instrução de correção**; a mesma forma barrada 2× no mesmo objetivo manda "não tente de novo, diga ao dono".
- Tipos de ação: `LEITURA`, `SCRIPT_NA_PAGINA`, `SCRIPT_NA_CAIXA`, `GESTO`, `MCP`. Os três últimos já são julgados e testados — é o que deixa A e C prontos para ligar.
- Trilha: evento `guarda` (`tool_id`, `decisao`, `regra`, `categoria`, `ms`, `cache`, `jev`) — nunca script, URL ou texto de página.
- D20: ao Jev de nuvem vai só o host do alvo, o esqueleto redigido do script e o objetivo; pedido sensível não vai à nuvem.
- Testes: `tests/unit/politica/test_guarda.py` (40). Medição: `tools/medir_guarda.py` → `docs/medicoes/guarda-de-contexto.{md,csv}`.

### B — Caixa de scripts (ADR-0050) — commit `e20d019`
- `src/jarvis/executor/scripts.py`: `CaixaDeScript.rodar(linguagem, codigo, entrada, rede) -> Resultado`. Backend **bubblewrap** (padrão) ou **podman**; sem nenhum, `sem_suporte` honesto. bwrap: `--unshare-all` (sem rede), `/usr` só-leitura, `/caixa` em tmpfs, script por **descritor** (não vira arquivo), `--clearenv`, `--cap-drop ALL`. Limites por `prlimit` (CPU, memória — só Python; o Node usa `--max-old-space-size` porque o V8 morre sob `RLIMIT_AS`) e prazo de parede que mata o grupo. Saída cortada em 64 KiB.
- Capacidade `script.rodar` (catálogo + stub): tier `moderado`, `side_effect: ephemeral`. Ligada no executor (`_corpo`, `_ligada`).
- Testes: `tests/unit/executor/test_scripts.py` (14). Provado: Python e JS, rede bloqueada, `/home` ausente, prazo mata, saída cortada, e o guarda barrando `~/.ssh`/`subprocess` antes da caixa.

### A ligação guarda↔executor (nos commits de B)
- `ExecutorDeFerramentas` ganhou `caixa` e `guarda`. Em `_avaliar`, **antes do PDP**, as ferramentas `guardada(tool_id)` passam pelo guarda: barrar → `negado` causa `guarda_barrou` com a instrução; pedir → vira `exige_o_sim` (o PDP devolve `confirm`, e a máquina do sim da ADR-0048 age); permitir → segue. `FluxoDeAcao._decidir` **não chama o Jev genérico** quando o guarda já julgou (`avaliacao.guarda`). `_acao_do_guarda` monta a `Acao` — hoje só `script.rodar`; **A e C só precisam adicionar os casos aqui**.

## O que está DESENHADO, não implementado (ADRs de proposta) — commit `ce48bfa`

### A — Navegador por CDP (ADR-0051) — FEITO e provado, commits `fdf5695` (Python) + `561ff7f` (extensão)
Tools `browser.console`, `browser.rede`, `browser.avaliar` (JS no **mundo isolado**), `browser.gesto` (clicar/arrastar/digitar/rolar por `Input.*`), via `chrome.debugger` com **recuo** para `chrome.scripting`; Firefox sem CDP (limitação dita). Catálogo (teto `browser` 12→16 no `schemas/manifesto.v1.json`), protocolo (`page.console/network/eval/gesture`), cliente, `CorposDoNavegador` (corpo bloqueia script em banco/e-mail/senha/pagamento, pede o sim fora do objetivo), `_acao_do_guarda` (`avaliar`→`SCRIPT_NA_PAGINA`, `gesto`→`GESTO`). Extensão: `extensao/background.js` anexa/desanexa o `chrome.debugger` (desanexa ao soltar/PARAR), `Runtime.evaluate` em `Page.createIsolatedWorld`, coleta `Log`/`Runtime`/`Network`, despacha `Input.*` (`mouseMoved`+`buttons`); `content.js` devolve o centro do elemento; manifesto ganhou `debugger`/`scripting`. PROVAS: `tests/unit/navegador/background_cdp.test.mjs` (node, debugger simulado) e `tools/harness_navegador.py` **verde em Chromium 155 e Firefox 158 reais** (45/45 cada).

### C — Cliente MCP (ADR-0052) — FEITO e provado, commit `87cd923` (realiza o lado cliente da ADR-0023)
`jarvis.mcp` (fora de executor/policy — abre processo): `config.py` (`~/.config/jarvis/mcp.toml`, padrão vazio/desligado, recusa cara de segredo); `cliente.py` (stdio JSON-RPC: initialize/tools-list/tools-call, prazo, `identidade` pinada por hash); `promocao.py` (tool → `mcp.<servidor>.<tool>` com política NOSSA: tier do dono, risco/egress/confirmação derivados, `trust_input: untrusted`, `input_schema` fechado; recusa proibidas ADR-0010); `gestor.py` (descobre/promove/roteia). Ligado no executor em `preparar()` (entra no catálogo e no PDP; `_ligada`/`_corpo` roteiam; `_acao_do_guarda`→`Tipo.MCP`). `politica.catalogo.de_dados` expõe a `Capacidade` de um manifesto promovido. PROVAS: `tests/unit/mcp/` com `servidor_falso.py` (stdio) ponta a ponta pelo executor/PDP/guarda.

### LIGAÇÃO PENDENTE no app real (`src/jarvis/voz/app.py`, zona da CLI opus-fluxo-voz)
O executor de B/D/A/C já aceita os parâmetros; falta `_montar_ferramentas` passá-los. NÃO editei `voz/app.py` (zona da outra CLI, que estava rodando o verificar.py). As mudanças, para quem a edita:
1. `from jarvis.caixa import CaixaDeScript`, `from jarvis.politica.guarda import GuardaDeContexto`, `from jarvis.mcp import carregar_mcp`, `from jarvis.mcp.gestor import GestorMcp`.
2. No `ExecutorDeFerramentas(...)` de `_montar_ferramentas`: `caixa=CaixaDeScript()`, `guarda=GuardaDeContexto(classificador=(self.detector.classificador if self.detector is not None else None))`, `mcp=GestorMcp(servidores=carregar_mcp(lar=...)) if <ligado> else None`. O `self.detector` já existe nesse ponto (criado antes de `_montar_ferramentas`); é o MESMO classificador do portão. Sem classificador, a zona cinza do guarda pergunta ao dono (seguro). A caixa se autodetecta (bwrap/podman) e degrada honesto. O gestor MCP só se o dono quiser (padrão: arquivo ausente = lista vazia = nada).
Até essa ligação, `script.rodar` não aparece no app e o guarda não roda no app (mas tudo é testado por fakes/harness).

### E — Claude in Chrome: delegar ao Claude Code (ADR-0053 aceita pelo dono → ADR-0054, FEITO)
Viabilidade (ADR-0053): uma extensão **não controla** outra; a integração Chrome é do **Claude Code**. **O dono decidiu (2026-10-29) seguir o caminho A** e manter a licença Apache-2.0. Implementado na ADR-0054 (commit `e032597`, push `origin/reescrita`):
- `delegar.claude_code` (`catalogo/delegar.claude_code.yaml`, stub gerado), corpo em `src/jarvis/delegacao/` (fora de executor/policy: abre processo). `config.py` lê `~/.config/jarvis/delegar.toml` (`[claude_code] ligado = true`; padrão desligado; recusa cara de segredo, chave desconhecida e executável com argumento). `claude_code.py` (`DelegadorClaudeCode`): `checar()` (sem `claude` / `auth status --json` sem login ou login que não é claude.ai / sem host nativo do Claude in Chrome → mensagem clara, sem subir a tarefa) e `delegar()` com o argv documentado `-p <prompt fixo> --chrome --output-format json --permission-mode dontAsk --tools "" --allowedTools mcp__claude-in-chrome__* --strict-mcp-config --setting-sources project --no-session-persistence --disable-slash-commands --max-turns N --append-system-prompt <regras fixas>`; tarefa pela **entrada padrão**; cwd temporário; ambiente por lista de permissão (nenhuma chave); prazo mata o grupo; cancelável; saída cortada; resultado redigido.
- Executor (`executor/ferramentas.py`): `delegacao=` liga a tool; `_recusa_da_delegacao` (já delegou no objetivo → `redelegar`; extensão ligada e nenhum passo `browser.*`/`input.*`/`mcp.*` → `delegar_cedo`); `_exige_o_sim` sempre (moderado + sim pelo código, a frase do que vai delegar em `_detalhe`, o custo na razão); `_acao_do_guarda` → `Tipo.DELEGACAO`; `_delegar` conta `Objetivo.delegacoes`, grava o evento `delegacao` (só códigos) e devolve `para_o_modelo()`; falha vira `DelegacaoFalhou` (status `erro`, causa = código). Em `FONTES_DE_TERCEIROS` (turno contaminado).
- Guarda (`politica/guarda.py`): `_delegacao` barra credencial e site sensível, pede o sim ao enviar/pagar/apagar, fora do objetivo e sem objetivo; zona cinza vai ao Jev com `tarefa_delegada` redigida.
- App (`voz/app.py._delegador`): só com a chave; arquivo inválido desliga com o motivo na tela; `avisar` escreve "Delegando ao Claude Code…".
- Testes: `tests/unit/delegacao/` (26) com o **`claude` falso** `claude_falso.py`; tier na tabela do `test_tiers`. Docs: ADR-0054, emenda da 0053, COMO-TESTAR §0.42.
- **Custo:** consome o limite de uso da conta do dono (inclusive o semanal). **Não provado em máquina real:** `--chrome` em `-p`, `--strict-mcp-config` mantendo o `claude-in-chrome`, `--setting-sources project` não tirando nada da integração, diálogo de permissão por site em `-p`, o socket da extensão com o `TMPDIR` passado — a lista está na ADR-0054.

## Ordem sugerida para continuar
1. Ligar B/D/A/C no app real (`voz/app.py`, as 2–4 linhas acima), coordenado com a CLI que edita voz.
2. O dono provar em máquina real: Brave/KDE com a extensão recarregada (CDP), e um servidor MCP de verdade (`npx chrome-devtools-mcp`) com `mcp.toml` ligado.
3. E (feito, ADR-0054): o dono liga `~/.config/jarvis/delegar.toml` e prova uma delegação real; o resultado (código, turnos, negações) aparece no `--diagnostico`.

## Regras seguidas
Commits só no nome do dono, sem Co-Authored-By; `git push` (sem `--force`, sem tags, sem tocar na `main` do remoto); `git add` só dos meus arquivos (a outra CLI, opus-fluxo-voz, mexe em `src/jarvis/voz/*`, `rede.py`, docs 0046–0048 e seções próprias do COMO-TESTAR). Testes só com fakes/contêiner; nenhuma chave lida; não rodei o `verificar.py` inteiro (só as suítes do que mexi). `TMPDIR=/home/sodre/.cache/jt` para o pytest.

## NÃO provado em máquina real
O Brave/KWin do dono (o harness do navegador é headless em Xvfb; o efeito de um clique sintético no DOM headless não é conferido — só a sequência de `Input.*`, no node); um servidor MCP de verdade com o `npx` do dono (o teste usa servidor falso em processo); o Claude Code real na delegação (E usa um `claude` falso nos testes); e o Windows da caixa de scripts (backend Linux). O guarda, a caixa, as tools de CDP e o cliente MCP foram provados em contêiner/fakes, com bubblewrap de verdade e com os dois navegadores reais no harness em contêiner.
