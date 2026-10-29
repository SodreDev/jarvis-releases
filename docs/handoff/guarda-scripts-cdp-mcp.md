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

### A — Navegador por CDP (ADR-0051, **proposta**)
Tools novas `browser.console`, `browser.rede`, `browser.avaliar` (JS no **mundo isolado**), `browser.gesto` (clicar/arrastar/digitar/rolar por `Input.*`), via `chrome.debugger` com **recuo** para `chrome.scripting`; Firefox sem CDP (limitação dita). Mundo isolado por padrão; cookie/storage/senha nunca; domínio sensível **bloqueado** para script. Mesma concessão/faixa/PARAR da regra 4 (o PARAR desanexa o depurador). **Falta:** o corpo na extensão (`extensao/background.js`: `chrome.debugger.attach`, domínios, recuo) e no cliente, os manifestos no catálogo (subir o teto do namespace `browser` de 12→16 no `schemas/manifesto.v1.json` com justificativa), `_acao_do_guarda` para `browser.avaliar`→`SCRIPT_NA_PAGINA` e `browser.gesto`→`GESTO`, e o `tools/harness_navegador.py` em contêiner (Chromium e Firefox) provando anexar/desanexar, mundo isolado, bloqueio de sensível, recuo, faixa/PARAR.

### C — Cliente MCP (ADR-0052, **proposta**; realiza o lado cliente da ADR-0023)
Config `~/.config/jarvis/mcp.toml` (padrão vazio/desligado); cada tool vira `mcp.<servidor>.<tool>` **promovida** a manifesto nosso (tier/risco/egress são nossos, nunca do servidor — ADR-0010); identidade pinada; saída `untrusted`; roda na caixa de B quando der; passa pelo PDP e pelo **guarda** (toda `mcp.*` é guardada; `Tipo.MCP` já testado). **Falta:** `jarvis.mcp.cliente` (stdio JSON-RPC), o carregador do toml, a promoção, `_acao_do_guarda` para `mcp.*`→`MCP`, e o teste com um **servidor MCP falso** em processo.

### E — Claude in Chrome e outras extensões (ADR-0053, **só viabilidade**)
Uma extensão **não controla** outra (contextos isolados; `management` não dirige; `externally_connectable` é opt-in da outra). A integração Chrome é do **Claude Code** (host nativo `com.anthropic.claude_code_browser_extension`, tools `mcp__claude-in-chrome__*`). **Recomendação:** quando o Jarvis não der conta no navegador, **delegar ao Claude Code** (subagente, ADR-0038) — único caminho que não cruza a fronteira entre extensões nem contorna nada. Não reusar o host nativo da Anthropic, não automatizar a UI dela. **Depende do dono:** querer o caminho (capacidade `perigoso`, só com o sim e o `claude` configurado), aceitar que a delegação manda contexto a outro agente, e confirmar os termos. Nada implementado.

## Ordem sugerida para continuar
1. A, item por item: manifestos + teto do `browser` + `_acao_do_guarda` + corpo na extensão + harness.
2. C: `jarvis.mcp.cliente` + promoção + `_acao_do_guarda` + teste com servidor falso.
3. E (se o dono quiser): a capacidade de delegar ao Claude Code, tier perigoso, com teste.

## Regras seguidas
Commits só no nome do dono, sem Co-Authored-By; `git push` (sem `--force`, sem tags, sem tocar na `main` do remoto); `git add` só dos meus arquivos (a outra CLI, opus-fluxo-voz, mexe em `src/jarvis/voz/*`, `rede.py`, docs 0046–0048 e seções próprias do COMO-TESTAR). Testes só com fakes/contêiner; nenhuma chave lida; não rodei o `verificar.py` inteiro (só as suítes do que mexi). `TMPDIR=/home/sodre/.cache/jt` para o pytest.

## NÃO provado em máquina real
Navegador/CDP real (A é só desenho), MCP real (C é só desenho), Claude in Chrome (E é só viabilidade), e o Windows da caixa de scripts (backend Linux). O guarda e a caixa foram provados em contêiner/fakes e com bubblewrap de verdade nesta máquina.
