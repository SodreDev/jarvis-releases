# ADR-0027 — Navegador controlável: extensão própria, entrada virtual e PDP por ação

**Data:** 2026-10-17 · **Estado:** proposta · **Decide:** dono (aceitar; quais navegadores;
loja ou sideload; quando "responder pelo dono" entra), planejador (o desenho e a prova)
**Pedido:** dono, 2026-10-17 (ajuste da fatia 6 do roteiro da F2): para a fase seguinte, o
Jarvis controla o navegador como o "Claude in Chrome" — uma **extensão própria** distribuída
junto dos releases do repositório, navegador aberto para depuração, a extensão lê a tela e o DOM,
depura e interage; **mouse e teclado virtuais** (evento de entrada sintetizado, nunca automação
por script de página); **PDP por ação**; **indicador visível** de quando a IA está controlando;
**botão de parar imediato**; páginas sensíveis (banco, senhas, mensageiros) **só com
confirmação explícita**; e "responder mensagens pelo dono" como **fase posterior**, com opt-in
por conversa. **Sem implementar nesta fatia.**

## Contexto

O que existe hoje (ADR-0028, fatia 6): `sites.open` abre uma URL `http(s)` no navegador padrão
pelo portal `OpenURI` e **não** lê nem mexe na página. Esta ADR é o próximo degrau, e é o mais
perigoso do catálogo: a página é conteúdo de terceiro (P6) com acesso à conta do dono.

Fatos verificados na origem (acesso em 2026-10-17):

- **Depuração remota mudou no Chrome 136**: `--remote-debugging-port` e `--remote-debugging-pipe`
  "will no longer be respected if attempting to debug the default Chrome data directory"; é
  preciso `--user-data-dir` não padrão, e o motivo declarado foi o roubo de cookies por depuração
  remota depois da App-Bound Encryption. Para automação, o Google recomenda o *Chrome for
  Testing* (blog do Chrome, 2025-03-17). **Consequência:** "abrir o navegador do dono com a flag
  de depuração" não alcança o perfil do dono — ou é um perfil separado, ou é extensão.
- **`chrome.debugger`** (MV3) é "an alternate transport for Chrome's remote debugging protocol":
  com a permissão `debugger` declarada, a extensão se anexa a uma aba e manda comandos do CDP,
  e o domínio `Input` está entre os disponíveis — é por ele que sai a entrada **virtual**
  (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`), que o navegador trata como entrada,
  e não como script da página. A página da API diz ainda que a sessão termina quando o DevTools
  é aberto naquela aba e que política corporativa pode bloquear o anexo.
- **Discord** proíbe automatizar conta de usuário ("self-bots"), com risco de encerramento da
  conta; automação é só por conta de bot via OAuth2/API (artigo de suporte do Discord).

Não verificado na origem, e por isso **[SUPOSIÇÃO]**: a faixa "<extensão> está depurando este
navegador" aparece enquanto a `chrome.debugger` está anexada e o usuário não a esconde
(observado em uso, não achado na documentação); os termos do WhatsApp sobre automação de conta
pessoal; e o caminho de instalação de extensão fora da loja em cada distro. **[SUPOSIÇÃO:
confirma ou derruba a fatia mínima abaixo, que instala por sideload no Chrome desta máquina e
registra o que aparece na tela.]**

## Três desenhos comparados

**A — extensão própria + `chrome.debugger` no perfil do dono.** A extensão (MV3) fala com o
`agentd` por *native messaging* (um programa nosso registrado no navegador, `stdio`, sem porta
aberta); lê DOM e árvore de acessibilidade, tira captura da aba e manda entrada pelo CDP.

**B — navegador separado (Chrome for Testing) com `--remote-debugging-pipe` e perfil próprio
do Jarvis.** O `agentd` dirige por CDP direto, sem extensão.

**C — automação de página (injetar script, Playwright/Selenium no perfil do dono).**

| Critério | A | B | C |
|---|---|---|---|
| Sessões e contas do dono | as dele, no navegador dele | nenhuma (perfil vazio) | as dele |
| Entrada virtual (não é script da página) | sim, `Input` do CDP | sim | **não**: dispara evento pela página |
| Indicador e parar sob controle nosso | ícone e faixa da extensão + botão no Jarvis | janela separada, fácil de ver | difícil |
| Superfície nova no navegador do dono | a extensão (permissões altas) | nenhuma | o script |
| Esbarra na mudança do Chrome 136 | não (não usa a flag no perfil padrão) | não (perfil próprio) | — |
| Distribuição | loja ou sideload | binário do Chrome for Testing | — |

## Decisão proposta

**Desenho A para o perfil do dono, com B como modo "navegador do Jarvis" para tarefas que não
precisam de conta; C fica fora.** Regras:

1. **Tool tipada por ação, nunca script.** O catálogo ganha `browser.read_page` (texto e árvore
   de acessibilidade, `third_party`), `browser.screenshot`, `browser.click(alvo)`,
   `browser.type(alvo, texto)`, `browser.navigate(url)`, `browser.scroll`. `alvo` é referência
   à árvore que a leitura devolveu (id estável), nunca seletor CSS nem coordenada inventada. Não
   existe `browser.eval`, nem `Runtime.evaluate` exposto: o lint de canivete-suíço da §4 cobre.
2. **PDP por ação**, com o domínio da aba como destino: ler é `leitura` com contaminação de
   sessão (§5.3); clicar e digitar são `transitorio_reversivel` em domínio comum e `egress` em
   formulário que envia; **domínios sensíveis** (banco, gerenciador de senha, mensageiros, e-mail,
   loja com pagamento — lista versionada mais a do dono) são **confirmação por ação na UI**, uma
   por vez, como `alto_impacto`. Campo de senha e cartão: o Jarvis não digita, entrega ao dono
   (`credencial_barreira`).
3. **Entrada só virtual** pelo domínio `Input` do CDP, com o foco conferido na aba anexada. Nada
   de `xdotool`/`ydotool`/portal de entrada para o navegador.
4. **Indicador e parar.** Enquanto a extensão está anexada: ícone da extensão em estado "no
   controle", uma faixa no topo da página (desenhada pela extensão, fora do DOM da página), e o
   **botão parar** na janela do Jarvis e na extensão. Parar = desanexar a `chrome.debugger` na
   hora e cancelar o turno (epoch). Atalho global também para.
5. **O que vem da página é dado** (P6): texto, título, `alt`, até o que imita instrução, entra
   como `third_party`, não amplia ferramenta, não cria grant, não muda domínio sensível para
   comum. Página que contém "ignore as instruções" vira **sinal de contaminação** e sobe o rigor.
6. **Native messaging com origem pinada**: o manifesto do host aceita só o id da nossa extensão;
   a extensão aceita só o nosso host. Nada de porta TCP.
7. **"Responder mensagens pelo dono" é outra fase**: `egress_representacao`, opt-in **por
   conversa** na UI, rascunho mostrado e confirmado no envio (§5.3), e só onde os termos do
   serviço permitem — o Discord não permite em conta de usuário; WhatsApp a verificar (D11 do
   roteiro já diz "só a plataforma oficial").

## Riscos

| Risco | Controle |
|---|---|
| A extensão vira superfície de ataque (permissões `debugger`, `tabs`, todas as URLs) | código mínimo, sem dependência de terceiros, revisão e build reprodutível; native messaging pinado; extensão inerte sem o host |
| Injeção de prompt vinda da página | regra 5; leitura e ação em turnos separados com o PDP no meio; contaminação sobe o rigor |
| Termos de serviço de plataformas (Discord proíbe self-bot; outras a verificar) | regra 7; lista de domínios onde ação fica desligada por padrão |
| Manifest V3: service worker que dorme, limites de tempo | estado mora no `agentd`, não na extensão; reconexão por native messaging |
| Loja × sideload: loja pede revisão e pode recusar a permissão `debugger`; sideload no Chrome exige modo de desenvolvedor ou política | decisão do dono (pergunta 2); a prova mede o sideload |
| Licença: a extensão sai do repositório | mesma licença do repositório; ícone e nome próprios (não usar marca de terceiro) |
| O dono não percebe que a IA está no controle | regra 4, e teste na prova: indicador visível em 100% do tempo anexado |
| Política corporativa bloqueia `debugger` | a extensão diz isso e cai para `sites.open` |

## Fatia mínima de prova (antes de qualquer tool no catálogo)

1. Extensão MV3 com `debugger` e native messaging, instalada por sideload no Chrome desta
   máquina; host nativo em Python que só ecoa.
2. Três comandos de prova numa página **local** de teste (servida do disco): ler a árvore de
   acessibilidade, clicar num botão por id da árvore, digitar num campo — tudo pelo `Input`.
3. Medir e registrar: o que aparece na tela enquanto anexado (faixa do Chrome, ícone, nossa
   faixa); tempo de parar (do clique ao desanexo); comportamento com o DevTools aberto.
4. Suíte de injeção: a página de teste com texto que imita instrução e com `<<ferramenta>>` no
   DOM: 0 ações disparadas pelo conteúdo.

## Perguntas ao dono

1. Navegadores no v1: só Chrome/Chromium (tem `chrome.debugger`), ou também Firefox (não tem o
   mesmo transporte; o desenho mudaria)?
2. Loja do Chrome ou sideload pelo release do repositório?
3. Lista inicial de domínios sensíveis além de bancos, gerenciadores de senha e mensageiros.
4. "Responder pelo dono" entra quando, e em quais serviços (dado o que os termos permitem)?

## Como invalidar esta proposta

- A prova mostrar que a `chrome.debugger` não dá entrada confiável sem script de página: o
  desenho volta para B (navegador do Jarvis) e o perfil do dono fica fora.
- A loja recusar a extensão e o dono não quiser sideload: fica só B.
- O dono preferir não ter extensão no navegador dele: fica `sites.open` e B.

## Fontes (acesso em 2026-10-17)

- Chrome, "Changes to remote debugging switches to improve security" (2025-03-17):
  <https://developer.chrome.com/blog/remote-debugging-port>
- Chrome Extensions, `chrome.debugger`: <https://developer.chrome.com/docs/extensions/reference/api/debugger>
- Discord, posição sobre self-bots: <https://support.discord.com/hc/articles/115002192352>
