# ADR-0051 — Navegador por CDP: console, rede, avaliar JavaScript e gestos pelo `chrome.debugger`, com recuo para `chrome.scripting`

**Data:** 2026-10-29 · **Estado:** proposta · **Decide:** dono (as capacidades, mundo isolado, domínios sensíveis bloqueados), arquiteto (CDP × scripting, o recuo, o contrato das tools, o Firefox)
**Pedido:** dono, 2026-10-29 — "NAVEGADOR (Brave/Chromium via a extensão atual): console (logs, erros), rede, DOM, executar JavaScript (Runtime.evaluate / chrome.scripting), clicar, arrastar, digitar, rolar, screenshot, via chrome.debugger (CDP) com fallback para chrome.scripting; Firefox cai para scripts injetados (diga a limitação). Tools novas no catálogo (ex.: browser.console, browser.avaliar, browser.acionar_cdp…) respeitando a regra 4, a faixa 'Jarvis no controle', o botão PARAR, reuso de abas, instância única. JS roda por padrão em mundo isolado; nada de ler cookies/senhas/storage sensível; domínios sensíveis (banco, e-mail, gerenciadores de senha) bloqueados para executar script." Camada A da ADR-0049; o guarda de contexto (ADR-0049) decide cada ação antes do PDP.

## Contexto

A extensão de hoje (ADR-0027/0032) age por `chrome.scripting` e mensagem ao content script: ela mapeia a página, clica por rótulo/`ref`, digita, rola, lê o texto e captura a tela — tudo por uma **lista fechada** de ações, sem CDP e sem JavaScript livre. Isso resolve a automação, mas não a **depuração**: não vê o console, não vê a rede, e não roda um trecho de JavaScript para entender por que a página não responde. O dono quer esses três, pelo `chrome.debugger` (o Chrome DevTools Protocol), que a extensão pode abrir numa aba.

Fatos do CDP (fontes no fim): o `chrome.debugger` é o transporte do protocolo de depuração; a extensão **anexa** a uma aba (com a versão do protocolo), e aí alcança os domínios `Runtime` (`Runtime.evaluate` roda JavaScript num contexto), `Input` (`Input.dispatchMouseEvent`/`dispatchKeyEvent` — gestos de verdade, como a entrada virtual da ADR-0027 fatia 4), `Log`/`Console` e `Network` (os eventos de log e de rede), `Page` (`Page.createIsolatedWorld` dá o contexto do **mundo isolado**) e `Page.captureScreenshot`. **Só um** cliente de depuração por aba: enquanto o Jarvis está anexado, o DevTools do dono naquela aba não abre (e o Chrome mostra a faixa "um software de depuração está controlando o navegador") — some quando o Jarvis solta. Em política gerenciada, anexar pode ser barrado. O **Firefox** não expõe CDP pela WebExtensions API: lá só há o `chrome.scripting` (script injetado), sem console/rede/gesto de CDP — a limitação é dita ao dono e ao modelo.

## Decisão

### 1. As capacidades novas (catálogo)

| tool | o que faz | tier | guarda (ADR-0049) |
|---|---|---|---|
| `browser.console` | os logs e erros do console da aba (texto, nível, origem, hora), desde que o Jarvis anexou | livre (leitura) | leitura pura: passa |
| `browser.rede` | os pedidos de rede da aba (método, URL sem corpo, status, tipo, tempo) desde que anexou | livre (leitura) | leitura pura: passa |
| `browser.avaliar` | roda um JavaScript que **você** escreve no **mundo isolado** da aba (`Runtime.evaluate` num contexto de `Page.createIsolatedWorld`) e devolve o valor serializado | moderado | regras → cache → Jev; mundo principal, aba fora do objetivo ou sensível pedem o sim; cookie/storage/rede/navegação barram |
| `browser.gesto` | clicar, arrastar, digitar e rolar por `Input.*` do CDP (o gesto físico, quando o clique por `ref` não faz efeito) | moderado | fora do objetivo ou sensível pede o sim; o risco dinâmico do clique (`jarvis.navegador.risco`) segue no corpo |

O `browser.tela` de hoje passa a poder usar `Page.captureScreenshot` (a aba não precisa estar à frente, ao contrário do `captureVisibleTab`); o contrato não muda. As tools de mapa/ação de antes (`browser.inspecionar`, `browser.click`, `browser.type`, `browser.acionar`, `browser.scroll`) continuam — o CDP é um caminho novo, não a troca do que já funciona. O teto do namespace `browser` sobe de 12 para 16 no esquema, com a justificativa (o dono pediu console, rede, avaliar e gesto pelo nome); o núcleo visível ao modelo continua pequeno, porque o roteador de método (ADR-0035) só mostra as de depuração quando o pedido é de depurar.

### 2. Mundo isolado por padrão, e o que não se lê

`browser.avaliar` roda no **mundo isolado** (`Page.createIsolatedWorld`): o script vê o DOM, não as variáveis da página. O **mundo principal** (as variáveis e funções do site) só com o sim do dono (o guarda pede). Em qualquer mundo, **nunca**: `document.cookie`, `localStorage`/`sessionStorage`/`indexedDB`/`caches`, `navigator.credentials`, o valor de campo de senha — o guarda barra pela análise estática (ADR-0049), antes de o script chegar ao navegador. **Domínio sensível** (banco, corretora, e-mail, gerenciador de senhas, pagamento — `jarvis.navegador.risco.categoria`): `browser.avaliar` é **bloqueado**, decisão do dono; `browser.console`/`browser.rede` seguem (são leitura e ajudam a depurar), mas o texto deles é dado de terceiros e passa pelo `redigir`.

### 3. CDP com recuo para `chrome.scripting`

A extensão tenta anexar o `chrome.debugger`. Deu certo: `browser.avaliar` vai por `Runtime.evaluate` no mundo isolado, `browser.gesto` por `Input.*`, `browser.console`/`browser.rede` pelos eventos de `Log`/`Network`. Não deu (política gerenciada, já há um depurador, versão incompatível): **recuo para `chrome.scripting`** — `browser.avaliar` roda via `chrome.scripting.executeScript` com `world: "ISOLATED"` (sem console/rede/gesto de CDP, que o scripting não dá); `browser.gesto` cai no clique por `ref` de antes; `browser.console`/`browser.rede` voltam "não anexado" com o porquê. O modelo ouve a limitação, não um erro cru.

### 4. Firefox: a limitação dita

No Firefox não há CDP pela WebExtensions. `browser.avaliar` roda por script injetado no mundo isolado; `browser.console`/`browser.rede`/`browser.gesto` de CDP **não existem** e a tool devolve `sem_cdp_no_firefox` com a explicação. O `browser.estado` (ADR-0027) passa a dizer se o CDP está disponível, para o modelo não prometer o que o navegador do dono não dá.

### 5. O controle, a faixa e o PARAR

Tudo pela mesma concessão por objetivo da regra 4 (ADR-0027): anexar o depurador leva a concessão; a faixa "Jarvis no controle" (indicador.js) cobre a aba; o PARAR (faixa, barra do navegador, "parar o navegador") **desanexa** o `chrome.debugger`, revoga a concessão e vira o evento `parar` que para o turno e a tarefa. Soltar a concessão, ficar ocioso ou o Jarvis sumir também desanexa — a faixa do Chrome de "depuração" nunca fica órfã. Reuso de abas e instância única (ADR-0036 emendada) valem igual: o CDP age na aba que já existe, sem nova janela.

### 6. O guarda e a privacidade (D20)

`browser.avaliar` e `browser.gesto` são **guardadas** (ADR-0049): o guarda compara a ação com o objetivo antes do PDP. Ao Jev (nuvem) vai só o host da aba, o mundo, o esqueleto do script redigido e o objetivo — nunca o conteúdo da página, o resultado do script, cookie ou valor de campo. O resultado de `Runtime.evaluate`, os logs e os pedidos de rede são `trust_input: untrusted`: dado, nunca ordem.

## O que falta provar (não feito nesta ADR)

A implementação na extensão (`chrome.debugger.attach`, os domínios, o recuo) e a prova em navegador real **não estão feitas**: esta ADR é o desenho. O guarda (ADR-0049) **já** classifica `SCRIPT_NA_PAGINA` e `GESTO` e tem teste (`tests/unit/politica/test_guarda.py`); falta o corpo das tools na extensão e no cliente, os manifestos no catálogo e o harness em contêiner (Chromium e Firefox) provando: anexar e desanexar, o mundo isolado, o bloqueio de domínio sensível, o recuo quando não dá para anexar, e a faixa/PARAR desanexando. Enquanto não houver isso, as tools não aparecem (como as `browser.*` sem a extensão, ADR-0027).

## Alternativas descartadas

- **Só `chrome.scripting`, sem CDP**: não dá console, rede nem gesto físico — justamente o que o dono pediu para depurar.
- **Mundo principal por padrão**: veria as variáveis do site, inclusive segredos, e seria vetor de injeção; fica atrás do sim.
- **JavaScript livre sem o guarda**: é o canivete suíço que a §4 recusa; o guarda e o mundo isolado são a cerca.

## Como invalidar esta decisão

- O harness em contêiner mostra que anexar o `chrome.debugger` quebra a automação de hoje (o content script deixa de responder), ou que o recuo para `chrome.scripting` não cobre o caso comum.
- O custo de anexar/desanexar a cada objetivo pesa no uso real (medir no harness, como o da ADR-0027).

## Fontes (acesso em 2026-10-29)

- `chrome.debugger` — developer.chrome.com/docs/extensions/reference/api/debugger (transporte do CDP, `attach` com versão, domínios `Runtime`/`Input`, sessões planas desde o Chrome 125, política gerenciada pode barrar).
- Chrome DevTools Protocol — `Page.createIsolatedWorld`, `Runtime.evaluate`, `Input.dispatchMouseEvent`, `Page.captureScreenshot` (referência do protocolo).
- `chrome.scripting` — `world: "ISOLATED"` / `"MAIN"` (o recuo sem CDP).
