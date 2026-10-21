# ADR-0027 — Navegador controlável: extensão própria, entrada virtual e PDP por ação

**Data:** 2026-10-17 · **Estado:** aceita em 2026-10-18 · **Decide:** dono (navegadores;
loja ou sideload; quando "responder pelo dono" entra), planejador (o desenho e a prova)
**Pedido:** dono, 2026-10-17 (ajuste da fatia 6 do roteiro da F2): para a fase seguinte, o
Jarvis controla o navegador como o "Claude in Chrome" — uma **extensão própria** distribuída
junto dos releases do repositório, navegador aberto para depuração, a extensão lê a tela e o DOM,
depura e interage; **mouse e teclado virtuais** (evento de entrada sintetizado, nunca automação
por script de página); **PDP por ação**; **indicador visível** de quando a IA está controlando;
**botão de parar imediato**; páginas sensíveis (banco, senhas, mensageiros) **só com
confirmação explícita**; e "responder mensagens pelo dono" como **fase posterior**, com opt-in
por conversa. **Sem implementar nesta fatia.**

## Histórico de decisão

- **2026-10-18 — aceita pelo dono.** O produto terá uma extensão WebExtension própria, entregue
  com os releases e controlada pelo Jarvis, além de mouse e teclado virtuais. Acionar uma função
  ou ação do DOM é equivalente a clicar o elemento; em sites que proíbem automação (inclusive
  Instagram e WhatsApp Web), a interação usa mouse e teclado virtuais. A ponte continua sendo
  native messaging por `stdio`, sem porta de rede aberta. Esta decisão substitui as perguntas
  abertas sobre aceitar a ADR e inclui Firefox e Chromium no v1.

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

## Emenda de 2026-10-18 — entrada virtual (fatia 4)

Mouse e teclado virtuais servem onde o DOM não serve (sites que proíbem automação, como Instagram e
WhatsApp Web) e fora do navegador. Escolhas, com a fonte de cada uma (acesso em 2026-10-18):

| Peça | Escolha | Por quê |
|---|---|---|
| Wayland (padrão) | portal `org.freedesktop.portal.RemoteDesktop` por `jeepney` | `Start` mostra o diálogo de consentimento e a sessão é revogável; o `xdg-desktop-portal-kde` implementa `NotifyPointerMotion`, `NotifyPointerButton` e `NotifyKeyboardKeysym` (e `ConnectToEIS` via KWin). Não mistura `Notify*` com EIS. Fontes: <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html>, `src/remotedesktop.cpp` do xdg-desktop-portal-kde |
| X11 / sem portal | `uinput` do kernel, **reserva**, só se o dono ligar (`entrada_uinput`) | o backend KDE do portal só existe em Wayland (`CreateSession` recusa em X11). `uinput` não pede consentimento a ninguém: por isso é desligado por padrão e exige acesso a `/dev/uinput` dado pelo dono. Fonte: <https://docs.kernel.org/input/uinput.html> |
| `uinput` sem biblioteca | `fcntl.ioctl` + `struct` da biblioteca padrão | zero dependência e zero licença nova; `UI_DEV_SETUP` (o que o kernel recomenda) com os números vindos da fórmula `_IOC` e conferidos em `linux/uinput.h` |
| Foco da janela | `kdotool` (Apache-2.0, programa separado e opcional) no Wayland/KDE; `xprop` no X11 | evento de entrada cai na janela em foco, e o aplicativo precisa saber qual é. <https://github.com/jinliu/kdotool> |
| **Recusados** | `ydotool` (AGPL-3.0), `xdotool`, `pynput` | `ydotool` é AGPL (Debian `copyright`: AGPL-3+; EL10: AGPL-3.0-only): não entra no caminho do produto. `python-evdev` (BSD-3-Clause) serviria, mas a biblioteca padrão basta |

**Regras (tudo decidido pelo código, nada pela página nem pelo modelo):**
1. Ordem: parada → argumentos → foco → risco → foco de novo → taxa → evento.
2. **Foco desconhecido é recusa** e **o próprio Jarvis em foco é recusa**. Motivo: o "sim" do dono é
   clicado na janela do Jarvis, que ganha o foco; um clique virtual com foco desconhecido poderia
   cair no botão «confirmar» dele. Depois do "sim" o código devolve o foco à janela de origem
   (`kdotool windowactivate`) e recusa se ele não voltar.
3. **Perigoso (o "sim" do dono, por ação):** janela em foco de terminal, gerenciador de senhas,
   autenticação (polkit, pinentry, título com «entrar»/«senha»), banco/pagamento ou mensageiro/e-mail
   (por título); **Enter** ou quebra de linha (Enter envia); turno que leu conteúdo de terceiros.
4. **Recusa sem pergunta:** digitar em gerenciador de senhas ou janela de autenticação; digitar
   número de cartão (Luhn).
5. Vocabulário fechado: mover (relativo, até 2000 px), clicar (3 botões, até 3x), digitar (até 500
   caracteres) e apertar teclas de uma lista (letras, dígitos, enter, tab, esc, setas…) com
   `ctrl`/`shift`/`alt`. Não existem `super`, `ctrl+alt`, F-teclas nem posição absoluta.
6. **Limite de taxa** (40 ações por minuto) e **interruptor de parada** que o dono aciona (botão,
   ou o arquivo `PARADA` em `<sessão>/entrada/`) e só ele solta; parar fecha a sessão do portal.

**Não verificado ao vivo** (só fakes: portal num `dbus-daemon` privado, `uinput` com dispositivo
falso, `kdotool`/`xprop` com lançador falso): o diálogo do KDE de verdade, o `restore`/revogação, o
keysym de maiúscula/acentuada no KWin, o `kdotool windowactivate` devolvendo o foco, e o `uinput`
num X11 real. **Limites conhecidos:** o ponteiro só move relativo (posição absoluta pede captura de
tela/ScreenCast, fora desta fatia); o `uinput` só digita o que tem a mesma tecla em US e ABNT2.

## Emenda de 2026-10-20 — o mapa da página e acionar (ADR-0032)

A regra 1 passa a valer como escrita: o alvo pode ser a **referência** (`ref`) do mapa que a página
devolveu (`browser.inspecionar`), além do texto visível; seletor CSS e coordenada continuam sem vir
do Jarvis (o seletor estável é gerado e usado só dentro da página, para reencontrar o elemento). E
"acionar uma função ou ação do DOM é equivalente a clicar" virou `browser.acionar`: clicar com a
sequência inteira de ponteiro, focar, passar o mouse, Enter/Escape/Tab/setas, enviar o formulário e
escolher opção — vocabulário fechado, sem `eval` nem função da página chamada pelo nome, com o risco
do clique (o envio e o Enter num campo contam como envio do formulário).

## Emenda de 2026-10-20 — ler numa aba de fundo (ADR-0033)

`page.readUrl` abre um endereço numa aba de fundo (`active: false`), lê e fecha a aba no fim, mesmo
na falha: é como o `web.buscar` sem chave usa o navegador do dono como motor de busca, sem trocar a
aba que ele está vendo. Não há tool `browser.*` para isso; o modelo chama `web.buscar`.

## Emenda de 2026-10-20 — a janela do Jarvis (ADR-0036)

O trabalho que o dono não precisa ver vai numa janela própria do Jarvis, criada sem foco; se o
navegador tomar o foco, o fundo o devolve à janela do dono. `tabs.navigate` não traz mais a aba
para a frente.

## Emenda de 2026-10-20 — o que o código tem hoje (conferência do Lote C)

A aceitação de 2026-10-18 (Histórico de decisão) trocou o caminho da proposta, e três itens da
"Decisão proposta" ficaram assim no código — esta emenda é a que vale onde eles divergem:

- **Os nomes (item 1).** `browser.read_page` é `browser.read`; `browser.screenshot` é
  `browser.tela` (ADR-0032); vieram também `browser.tabs`, `browser.estado`, `browser.launch`,
  `browser.inspecionar` e `browser.acionar` (ADR-0032), e a interna `browser.acao_sensivel` (o
  "sim" por ação sensível, que o modelo não vê). O `alvo` é o texto visível do elemento ou o `ref`
  do mapa da página (ADR-0032), nunca seletor CSS nem coordenada inventada.
- **Sem CDP (item 3).** A extensão não pede a permissão `debugger` (o manifesto tem `activeTab`,
  `tabs`, `nativeMessaging` e `<all_urls>`, este só pela captura da ADR-0032): ler, clicar e digitar
  são ações no DOM pelo script de conteúdo, que a aceitação equiparou ao clique. Onde o site proíbe
  automação, o mouse e o teclado são os virtuais do sistema (emenda de 2026-10-18).
- **O indicador e o parar (item 4)** foram feitos em 2026-10-21 — ver a emenda daquela data,
  «o indicador e o PARAR». Sem `chrome.debugger`, "anexada" virou "no controle": do primeiro pedido
  de um objetivo numa aba até o objetivo acabar.

## Emenda de 2026-10-21 — auditoria da integração: o caso «abra um vídeo no YouTube»

**Sintoma do dono:** pediu «abra um vídeo no YouTube»; o Jarvis usou a extensão, o navegador dele
«continuou igual» e a resposta parou depois do primeiro comando. A trilha de diagnóstico dele (só
metadados) mostra o turno: método `navegador`/`cita_site`, **uma** `browser.navigate` com só `url`,
`ok` em 25,7 ms, e o turno fechado (`concluido`) com a fala interrompida. Reproduzido em contêiner
(Chromium 155 e Firefox 158): o `tabs.update` responde na hora com a URL e o título **de antes**;
sem rede a aba vira a página de erro do navegador e a ferramenta dizia `ok` do mesmo jeito.

O que a ponte passa a garantir (código da extensão e das `browser.*`; o laço do cérebro é de outra
frente, em andamento):

1. **Navegar é conferido.** `tabs.navigate` e `tabs.open` só voltam depois de ver a aba **sair do
   lugar** (loading ou URL nova), **terminar** e o conteúdo da extensão **responder na página nova**
   (`estado`). A aba que não sai do lugar (a página segura a saída) é erro `aba_nao_mudou`; a página
   que não abre (sem internet, erro do site, página onde a extensão não entra) é erro
   `pagina_nao_abriu` — dito ao dono como é, nunca `ok`. A URL do resultado é a da página nova.
2. **Pedido de ver termina à vista.** O código lê a fala do dono (`quer_ver`, junto do roteador da
   ADR-0035): abrir, mostrar, pôr, tocar, assistir → a aba vem para a frente no fim (`tabs.show`:
   ativa, janela em foco; a aba da janela do Jarvis vai para a janela do dono). O resultado diz
   `visivel` — e, se o sistema negar o foco ao navegador, diz que não ficou, sem fingir.
3. **Trabalho que o dono não pediu para ver** (pesquisar, ler, conferir) vai para a janela do Jarvis
   (ADR-0036) mesmo sem `segundo_plano` — antes trocava a página da aba que o dono usava. E a
   **aba de trabalho** do pedido (a última em que o Jarvis abriu, navegou ou agiu) é o alvo das
   `browser.*` sem `tab_id`: antes, ler depois de abrir algo em segundo plano lia a aba do dono.
4. **A aba atual do dono** é a ativa da última janela **normal** em que ele esteve: nunca um popup,
   um app, o DevTools nem a janela do Jarvis — que agora se segura com uma página dela
   (`janela.html`) e é **reconhecida depois que o service worker reinicia** (antes, a memória dela
   se perdia: a "aba atual" podia cair lá e uma segunda janela era criada). Aba nova do dono nasce
   na janela dele, pelo id.

**Não consertado aqui:** o laço que encerra o turno depois de uma ferramenta só (o «conferir antes
de dizer que abriu» do cérebro é de outra frente, em andamento); dois perfis/navegadores com a
extensão ao mesmo tempo (o cliente usa o host mais recente, já dito no handoff); o KWin de verdade
negando o foco (o resultado diz `visivel: false`, provado só com fakes e com openbox).

## Emenda de 2026-10-21 — o indicador e o PARAR (item 4 feito) e o reuso de abas

**Pedido do dono (2026-10-21):** o item 4 desta ADR — indicador visível e botão de parar — e o
Jarvis poder listar as abas e reaproveitar a que já tem o site. Como foi feito:

1. **Concessão por objetivo.** Cada objetivo que age no navegador (o pedido do turno, ou o de uma
   tarefa — ADR-0030 C2, ADR-0038) recebe uma concessão aleatória (`jarvis.navegador.controle`) que
   vai em todo pedido que lê ou mexe numa aba (`controle`). É o que a extensão usa para saber quais
   abas estão **no controle** e o que recusar depois de um PARAR.
2. **O indicador.** Na aba no controle, uma **faixa no topo da página** desenhada pela extensão
   (`extensao/indicador.js`): shadow DOM **fechado** (os scripts da página não leem nem mexem no que
   tem dentro), por cima do conteúdo sem empurrá-lo, só o botão recebe clique, nada pede o foco
   (o botão nem entra na ordem do Tab, e apertá-lo não tira o foco do campo do dono). O script nasce
   com o documento (`document_start`) e pergunta ao fundo se a aba está no controle: numa aba que o
   Jarvis navega, a faixa já está na página nova. No botão da extensão, o **selo** «IA» e o título
   «Jarvis no controle de N abas — clique para parar». Vale para **qualquer** aba controlada,
   inclusive a que o dono já tinha aberta.
3. **Soltar.** A faixa e o selo somem quando o Jarvis solta: o objetivo acabou (a vigia vê a fase de
   concluir e pede `controle.soltar`), ficou 45 s sem agir no navegador, ou o Jarvis sumiu (sem
   `controle.manter`, a extensão solta sozinha em 30 s). E a faixa confere com o fundo a cada 4 s:
   se ele não a tem mais no controle (o aviso de soltar se perdeu) ou a extensão foi recarregada ou
   removida, ela some sozinha — nunca fica presa na página.
4. **PARAR**, em três lugares: o botão da faixa, o botão da extensão na barra e o botão «parar o
   navegador» da janela do Jarvis (só aparece depois que a extensão aceitou um pedido: pedido que
   nem chegou ao navegador não põe nada no controle). O da faixa e o da barra soltam
   na hora, **revogam** a concessão (a extensão recusa o que vier dela depois, mesmo um pedido que
   já estava no ar: `parado_pelo_dono`) e mandam o evento `parar` ao host, que o entrega a quem
   assinou (`eventos.assinar`, a conexão que a vigia mantém aberta). No Jarvis, o evento — ou a
   recusa, se o evento se perdeu — vira o mecanismo de parar de sempre: as tarefas daquele objetivo
   são canceladas e o turno, se ainda está no ar, interrompido (epoch). Clique sintético da página
   (`isTrusted` falso) não para nada.
5. **Abas do dono e reuso.** `browser.tabs` diz a janela e o estado de cada aba (à vista, ativa
   noutra janela, segundo plano, janela do Jarvis), e qualquer uma se controla pelo `tab_id`, com o
   PDP e o risco de sempre. Pedido de **ver** (`quer_ver`) sem `tab_id`: a aba que **já está** na
   URL só é ativada (sem recarregar); a do **mesmo site** noutra página é navegada; sem nenhuma, a
   aba atual. Banco, senha, pagamento, mensageiro e e-mail são protegidos: a aba do dono num deles
   não tem a página trocada (do mesmo site, vem como está — uma segunda aba do WhatsApp Web derruba
   a primeira; de outro site, o pedido abre numa aba nova). `sites.open` passa pelo mesmo caminho.

A extensão **não ganhou permissão**: o manifesto só passou a declarar o botão (`action`, sem
popup — o clique é o PARAR) e o segundo script de conteúdo.

**Não feito:** o atalho global de parar. Na janela do Jarvis o PARAR do navegador é o botão
«parar o navegador» (o Esc interrompe a fala, não a tarefa — ADR-0038). **Não provado:** o KDE de
verdade (a faixa e o foco foram provados com openbox e com o Firefox headless); o Brave do dono (o
roteiro usa o Chromium do Fedora); sites que montam o `<html>` de novo a cada navegação interna (a
faixa volta até 20 vezes por documento e desiste).

## Emenda de 2026-10-21 — uma instância só (ADR-0036, emenda (2))

**Relato do dono depois do `8cc7bf6`:** o Jarvis começou no navegador dele e depois abriu «outra
instância do Brave» — a janela própria do Jarvis — e o vídeo foi parar nela. O que muda aqui (o
desenho todo, a causa e a prova estão na emenda (2) da ADR-0036):

- **A regra 4 (reuso) continua** e ganha o fim que faltava: sem aba do site, o pedido de ver usa a
  guia que ele mesmo abriu ou uma «nova aba» vazia, e senão abre uma **guia nova na janela do
  dono** — a aba dele com outro site não tem a página trocada. A aba de banco, senha, pagamento,
  mensageiro e e-mail continua protegida como antes.
- **O trabalho de fundo é aba da janela do dono**, em segundo plano (sem `active`, sem mexer no
  foco); a janela própria do Jarvis (emenda de 2026-10-20) só no modo `automacao_social`, o gancho
  da automação de redes sociais, e-mail e agenda que vem depois — desligado e sem chave na
  configuração.
- **Abrir navegador só sem um ativo:** com a extensão conectada, `sites.open` (também com
  `nova_aba`) vai por ela, e «abre o navegador» traz a janela do dono para a frente; sem extensão,
  o processo do navegador rodando também conta como aberto. O binário só é executado sem nenhum dos
  dois — antes, o `sites.open` com `nova_aba` o executava com a URL mesmo com o navegador aberto.
