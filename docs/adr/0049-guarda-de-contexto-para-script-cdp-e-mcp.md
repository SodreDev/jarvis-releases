# ADR-0049 — Guarda de contexto: toda ação de script, CDP e MCP é comparada com o objetivo antes de rodar (e o mapa das camadas de depuração e automação)

**Data:** 2026-10-29 · **Estado:** aceita (pedido do dono) · **Decide:** dono (as camadas, o que barra, o que vai à nuvem), arquiteto (onde o guarda mora, a ordem das regras, o cache, o prazo)
**Pedido:** dono, 2026-10-29 — "dar ao Jarvis capacidade de estudar/depurar no navegador e automatizar com scripts. Camadas aprovadas: (1) NAVEGADOR e (2) EXECUTOR DE SCRIPTS isolado; a camada 3 (apps fora do navegador: AT-SPI/mouse virtual) fica para DEPOIS. Integrar TAMBÉM servidores MCP. […] GUARDA DE CONTEXTO COM O JEV (peça central): toda ação de script/CDP/MCP proposta pelo modelo passa por um classificador que compara a AÇÃO (script/ação + alvo/URL) com o OBJETIVO/FASE da tarefa em curso (ADR-0030) e devolve permitir / barrar / pedir-confirmação com motivo curto; se barrar, o motivo volta ao modelo como instrução de correção e o evento é registrado. […] PRECISA SER OTIMIZADO: regra determinística rápida antes, cache por (objetivo, forma da ação), chamada ao Jev só na zona cinza, timeout curto com fail-safe seguro, e meça latência p50/p95 antes/depois." Relaciona: ADR-0004 (classificador não autoriza), ADR-0010/0023 (MCP), ADR-0027 (regra 4: PDP por ação), ADR-0029 (o Jev), ADR-0030 (objetivo e fase), ADR-0038 (tarefa do pedido).

## Contexto

1. **O que existe.** Toda ferramenta passa por catálogo → contrato → método (ADR-0035) → **PDP** (ADR-0003/0009; autoridade) → **portão** (o Jev da ADR-0029, `jarvis.s2.portao`) → objetivo (ADR-0030) → autorização explícita → efeito, com o risco dinâmico do navegador (`jarvis.navegador.risco`) no corpo de `browser.click/type/acionar`. O portão pergunta ao Jev **em toda ferramenta** quando está ligado (p50 563 ms e p95 617 ms na medição de 2026-10-17 da ADR-0029) e **não existe** quando o dono não ligou o classificador — que é a configuração dele hoje (escuta por palavra, sem endereçamento; ADR-0048).
2. **O que entra agora** dá ao modelo poder cujo efeito depende de **texto que ele escreve**: JavaScript na página (CDP/`chrome.scripting`), Python/JS num executor, e as ferramentas de servidores MCP de fora. É o que a SPEC §4 chama de canivete suíço e o lint recusa pelo nome (`*.exec`, `*.eval`, `shell.*`). O que torna essas capacidades aceitáveis é a **cerca** de cada uma — mundo isolado e domínios sensíveis bloqueados (A), caixa de areia sem rede e sem os arquivos do dono (B), política nossa por ferramenta (C) — e, por cima de todas, **um guarda que compara a ação com o objetivo** antes de ela rodar.
3. **A referência do dono** é o modo automático do Claude Code: as listas de ferramentas seguras e as regras do usuário rodam antes, então a maior parte das ações nunca chega ao classificador; só o que tem consequência real vai a ele; ele barra categorias de risco (exfiltração, escalada de escopo para fora do diretório da sessão, código baixado, credenciais) e, quando barra, o modelo é redirecionado a outro caminho; se insiste, vira pergunta ao usuário. O classificador vê as mensagens do usuário e as chamadas de ferramenta, **não** a saída das ferramentas (fontes no fim).

## Decisão

### 1. Onde o guarda mora e em que ordem

`jarvis.politica.guarda.GuardaDeContexto` (código puro; a única saída é a consulta ao classificador injetado). O executor o chama em `ExecutorDeFerramentas._avaliar`, **depois** do catálogo, do contrato e do método e **antes** do PDP, para as ferramentas **guardadas** (a lista é do código, `guarda.GUARDADAS`, e as `mcp.*` são todas guardadas). Assim todo caminho passa por ele — o turno, a tarefa do pedido (ADR-0038), o caminho rápido (ADR-0045) e a repetição depois do "sim" — sem um segundo ponto de entrada.

- **barrar** → a chamada volta ao modelo como `negado`, `causa="guarda_barrou"`, com a **instrução de correção** no motivo; nada chega ao PDP, nenhum grant é aberto.
- **pedir confirmação** → o motivo vira o `exige_o_sim` do pedido ao PDP, que devolve `confirm` — e a máquina que já existe faz o resto: pendência do turno, a tarefa parada esperando, o "sim" de uso único que casa ferramenta e argumentos (ADR-0048). O guarda nunca abre uma via de confirmação própria.
- **permitir** → segue ao PDP como antes. O guarda **nunca** autoriza o que o PDP nega nem troca o `confirm` dele (ADR-0004).

Para não pagar o Jev duas vezes, o **portão** não consulta o Jev numa ferramenta que o guarda já julgou: a avaliação leva o veredito do guarda, e o `FluxoDeAcao._decidir` o usa no lugar da classificação genérica (a trilha diz `guarda` no campo `jev` do evento `portao`).

### 2. As regras, da mais barata para a mais cara

Cada ação vira uma **forma**: a ferramenta, o host do alvo (a aba, a URL do argumento, o servidor MCP), as **categorias** que a análise estática do script achou e o **esqueleto** do script (literais de texto e números trocados por marcadores, espaços colapsados) — duas chamadas que só diferem nos valores têm a mesma forma.

1. **Leitura pura passa direto** (`browser.console`, `browser.rede`, ferramenta MCP que o dono marcou `leitura`): permitir sem olhar mais nada. O PDP e o tier continuam valendo.
2. **Lista de negação** (barra sem o Jev; a regra diz a categoria):
   - `credenciais`: `document.cookie`, `localStorage`, `sessionStorage`, `indexedDB`, `caches`, `navigator.credentials`, `chrome.cookies`, o valor de campo de senha;
   - `exfiltrar`: `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, imagem/iframe montado com URL, `postMessage` para fora, e a URL de destino fora do objetivo levando dado do dono (o `leva_dado_do_dono` da ADR-0030);
   - `baixar_executar`: `eval`, `new Function`, `import()`, `importScripts`, `<script>` criado, download forçado; no executor, `subprocess`, `os.system`, `pip install`, `curl … | sh`;
   - `enviar`: `submit()`/`requestSubmit()` e clique por script em mensageiro, e-mail ou pagamento — enviar é com `browser.acionar`/`browser.click`, que pedem o sim (ADR-0030 §3);
   - `fora_do_dominio`: navegação por script (`location`, `window.open`, `history.pushState`) para host fora do objetivo;
   - `dominio_sensivel`: script em aba de banco, gerenciador de senhas, e-mail ou pagamento (`jarvis.navegador.risco.categoria`) — **bloqueado** para script, decisão do dono;
   - `ofuscado`: escapes, `fromCharCode` e base64 em quantidade que ninguém escreve para ler a página.
3. **Pede o sim por regra** (sem o Jev): `browser.avaliar` no mundo **principal** da página (o padrão é o isolado); `script.rodar` com rede; gesto CDP numa aba fora do objetivo ou de categoria sensível; ferramenta MCP que o dono marcou `perigoso`.
4. **Permite por regra** (sem o Jev): script que só **lê** o DOM (seletores, texto, atributos, caixas, estilos, contagens, `JSON.stringify`, `return`) e não tem nenhuma escrita, navegação, rede ou armazenamento; `script.rodar` sem rede e sem categoria (a caixa de areia é a cerca: o resultado volta como dado); rolar; gesto CDP dentro do objetivo num elemento sem risco (o risco dinâmico do clique roda depois, no corpo, como hoje).
5. **Cache** por `(objetivo, forma)`: o veredito do Jev para a mesma forma no mesmo objetivo é reusado; LRU de 256 entradas, esvaziado quando o objetivo muda. Falha do classificador **não** entra no cache.
6. **Zona cinza → Jev**, uma chamada com duas perguntas fechadas: `acao` (barrar, pedir_confirmacao, permitir — a segura primeiro, porque a primeira opção atrai) e `categoria` (fora_do_objetivo, exfiltrar, baixar_executar, credenciais, enviar, nenhuma), que compõe a instrução. Limiares: permitir só com p ≥ 0,75; barrar com p ≥ 0,60; o resto pede o sim.
7. **Prazo curto e falha segura**: o guarda dá ao Jev 0,8 s (o p95 medido é 617 ms); prazo, rede, formato estranho ou classificador ausente → **pedir confirmação**. Falha nunca permite.

### 3. O que vai ao Jev (D20)

Só o necessário: o objetivo como o portão já manda (critério de pronto, fase, estado, passos `ferramenta:status`; o texto do pedido só ao classificador local), a ferramenta, o **host** do alvo (nunca caminho nem consulta da URL), as categorias achadas e o **esqueleto** do script passado pelo `redigir` do projeto e cortado em 600 caracteres. Nunca: conteúdo da página, saída de ferramenta, resultado de script, cookie, valor de campo, chave. Conteúdo vindo de MCP, de página ou de script é **dado**, nunca ordem — o guarda não o lê.

### 4. A instrução de volta

O motivo do `negado` é curto e diz o que fazer no lugar: "Barrei: o script lê cookies (credenciais). Isso foge do objetivo «ver por que o botão de login não responde»: leia o que precisa pelo DOM visível (browser.inspecionar, browser.read), sem cookie, storage nem senha." Cada categoria tem a sua alternativa (`guarda.ALTERNATIVAS`). A mesma forma barrada duas vezes no mesmo objetivo muda a instrução para "não tente de novo: diga ao dono o que não dá para fazer", que é o freio do laço (o modo automático também para de insistir e passa ao usuário).

### 5. Registro

Evento `guarda` na trilha (`jarvis.trilha`, só metadados): `tool_id`, `decisao`, `regra` (código), `categoria`, `ms`, `cache` (sim/não) e `jev` (a escolha e o p, quando houve consulta). Nunca o script, a URL ou o motivo com texto de página (o achado 2 da auditoria dos Lotes B e C).

### 6. Medição

`tools/medir_guarda.py` roda o guarda de verdade sobre um roteiro de ações de uma sessão de depuração (leituras, scripts dentro do objetivo que se repetem, gestos, e os cenários fora do eixo) em dois desenhos: **antes** — o Jev em toda ação, como o portão faz — e **depois** — regras, cache e o Jev só na zona cinza. O Jev é o classificador falso com a latência medida na ADR-0029 (sem chave, sem rede, sem custo); o tempo das regras e do cache é o real. Resultado em `docs/medicoes/guarda-de-contexto.md`, gerado pela ferramenta junto com o CSV das amostras.

### 7. As camadas que o guarda protege (cada uma na sua ADR)

| camada | ADR | o que é | a cerca própria |
|---|---|---|---|
| D. guarda de contexto | esta | regras → cache → Jev na zona cinza | falha pede o sim; o PDP decide |
| B. executor de scripts | ADR-0050 | `script.rodar`: Python ou JS escritos pelo Jarvis | bubblewrap (ou podman) sem rede, sem a casa do dono, pasta descartável, tempo, CPU, memória e saída limitados |
| A. navegador por CDP | ADR-0051 | console, rede, avaliar JS, gestos e tela pelo `chrome.debugger`; Firefox por script injetado | mundo isolado por padrão, nada de cookie/senha/storage, domínio sensível bloqueado, faixa «Jarvis no controle» e PARAR |
| C. cliente MCP | ADR-0052 | servidores que o dono listar em `~/.config/jarvis/mcp.toml` (vazio = desligado) | tier nosso por ferramenta, identidade pinada, saída `untrusted`, o mesmo guarda |
| E. extensões de terceiros | ADR-0053 | o Claude in Chrome e outras: viabilidade e termos | nada que viole termo ou contorne proteção |

A camada 3 (apps fora do navegador: AT-SPI, mouse virtual) fica para depois, por decisão do dono.

### 8. Tiers no PDP

| ferramenta | tier | confirmação do manifesto | o guarda |
|---|---|---|---|
| `browser.console`, `browser.rede` | livre | never | leitura pura: passa |
| `browser.avaliar` | moderado | never | regras → cache → Jev; mundo principal pede o sim; domínio sensível barra |
| `browser.gesto` (clicar, arrastar, digitar, rolar pelo CDP) | moderado | never | fora do objetivo ou sensível pede o sim; o risco dinâmico do clique segue no corpo |
| `script.rodar` | moderado | never | sem rede e sem categoria: passa; com rede: pede o sim; categoria de risco: barra |
| `mcp.<servidor>.<ferramenta>` | o que o dono escrever (`livre`/`moderado`/`perigoso`; padrão `moderado`) | do tier | `leitura`: passa; `perigoso`: pede o sim; o resto pelas regras e pelo Jev |

## Alternativas descartadas

- **O Jev em toda ação** (o desenho do portão): ~0,6 s em cada passo de uma depuração que tem dezenas, e nada quando o classificador está desligado — o caso do dono.
- **Só regras**: rápidas, mas não sabem que "abrir o painel de admin" foge de "ver por que o botão não responde"; a zona cinza existe.
- **O próprio motor (`claude -p`) como juiz**: 1,2–2,5 s até a primeira proposta (ADR-0029) e o mesmo modelo que propôs a ação julgando a si mesmo.
- **O guarda na extensão**: a extensão não conhece o objetivo, e script e MCP não passam por ela.
- **Confiar no guarda e dispensar a cerca**: classificador erra (ADR-0004; o próprio modo automático diz que reduz o risco, não o elimina). A cerca de cada camada vale mesmo com "permitir".

## Consequências

- Uma depuração típica faz a maior parte das ações sem rede de classificador (leituras e repetições); o Jev só entra na forma nova e ambígua.
- Sem o classificador ligado, a zona cinza pergunta ao dono: mais "sim" do que com o Jev, nunca menos segurança.
- O modelo ouve por que foi barrado e o que fazer no lugar, em vez de um "negado" seco que o faz tentar a mesma coisa de outro jeito.

## Riscos

- **Análise estática engana-se**: script ofuscado de um jeito que as regras não pegam cai na zona cinza (Jev) ou passa como leitura se não tiver nenhum token de escrita. Mitigação: a lista de "permite por regra" exige **ausência** de todo token de escrita, rede, navegação e armazenamento, e o mundo isolado + o bloqueio de domínio sensível valem mesmo assim.
- **Cache envenenado**: o veredito é do objetivo de agora; muda o objetivo, o cache esvazia.
- **Instrução que vira laço**: limitada pela segunda barrada da mesma forma.

## Como invalidar esta decisão

- A medição mostra o Jev em mais de um terço das ações de uma sessão típica (as regras não estão pegando o óbvio), ou o p95 do guarda acima do p95 do Jev sozinho.
- Um cenário fora do eixo (ler cookie, navegar para outro site, baixar e executar, mandar mensagem) passa sem barrar nem pedir o sim nos testes de `tests/unit/politica/test_guarda.py`.

## Fontes (acesso em 2026-10-29)

- Anthropic, "Claude Code auto mode: a safer way to skip permissions" — https://www.anthropic.com/engineering/claude-code-auto-mode
- Claude Code docs, "Auto mode config" — https://code.claude.com/docs/en/auto-mode-config
- Anthropic, "Auto mode for Claude Code" — https://claude.com/blog/auto-mode
