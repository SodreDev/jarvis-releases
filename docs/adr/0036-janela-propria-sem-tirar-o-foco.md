# ADR-0036 — A extensão trabalha numa janela própria do Jarvis, sem tirar o foco do dono

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono, Lote C); emendada em 2026-10-21 — a janela própria ficou só para a automação social, e o trabalho de fundo é aba da janela do dono · **Decide:** dono (quando o foco pode mudar; uma instância só), arquiteto (a aba de fundo e a prova)
**Pedido:** dono, 2026-10-20 — "EXTENSÃO EM JANELA ESPECÍFICA SEM TIRAR O FOCO: a extensão passa a atuar numa janela/aba escolhida (por windowId/tabId) sem trazê-la ao primeiro plano nem mudar a janela ativa do dono (ex.: o dono está no Google, o Jarvis trabalha no Twitter em outra janela). O foco só muda quando o objetivo realmente exigir (ex.: ação que o navegador só aceita com a janela focada), e então volta para onde o dono estava. Prefira criar/usar uma janela própria do Jarvis em segundo plano. Prove no contêiner (Chromium e Firefox) que a janela ativa do dono não muda." Emenda a ADR-0027 (a extensão) e a ADR-0033 (a aba de fundo da busca vai para esta janela).

## Contexto

Toda ação da extensão já mira uma aba pelo id (`tab_id`, resolvido pelo código antes de agir), e ler, clicar, digitar, acionar e mapear funcionam em aba que não está à vista. O que mexia no que o dono vê era: `tabs.navigate` com `active: true` (trazia a aba para a frente na janela dela), `tabs.open` criando a aba ativa na janela do dono, e a aba de fundo da busca (ADR-0033), que aparecia na barra de abas dele.

## Decisão

1. **A janela do Jarvis** (`janelaDoJarvis` no fundo da extensão): criada com `focused: false` e uma aba `about:blank` que a segura aberta; lembrada pelo id enquanto o fundo vive e refeita se o dono a fechar. Antes e depois de criar a janela e as abas dela, o fundo lê a janela em foco (`windows.getLastFocused`) e, se o navegador tiver tomado o foco — o Firefox pode ignorar `focused: false` —, **devolve o foco para a janela onde o dono estava**.
2. **Trabalho em segundo plano.** `browser.navigate` com `segundo_plano: true` abre a URL numa aba nova da janela do Jarvis (`tabs.open` com `janela: "jarvis"`) e devolve o `tab_id`; as outras `browser.*` agem nela por esse id. A busca sem chave (`page.readUrl`, ADR-0033) usa a mesma janela: nem a aba de fundo aparece para o dono. Com `tab_id`, o `segundo_plano` navega aquela aba, onde ela estiver.
3. **Navegar não traz para a frente:** `tabs.navigate` atualiza a URL sem `active: true`.
4. **Quando o foco muda:** nenhuma ação da extensão precisa da janela focada hoje — no Chromium a captura da tela (ADR-0032) pega a aba à vista na janela dela, e a aba ativa da janela do Jarvis está à vista nela. O que precisa de foco é o teclado e o mouse virtuais, que já conferem o foco antes e o devolvem depois do "sim" (ADR-0027, emenda de 2026-10-18).
5. **A janela do Jarvis nunca é "a aba atual" do dono:** se o navegador a tratar como a janela em foco, `tabs.current` (sem id) responde com a aba ativa da última janela do dono (`janelaDoDonoId`) — o que valia para "navegar na aba atual" não pode cair na janela do Jarvis.
6. **Para provar e diagnosticar:** `windows.focused` diz a janela em foco, a aba ativa dela, a janela do Jarvis e a última do dono.

## Alternativas descartadas

- **Janela minimizada:** página minimizada é estrangulada pelo navegador e a captura sai preta ou falha.
- **Aba de fundo na janela do dono:** não troca a aba dele, mas aparece na barra de abas; a janela própria não aparece.

## Consequências

- O caso do dono: ele no Google, o Jarvis lendo e clicando no Twitter em outra janela, e a janela e a aba ativa dele iguais antes e depois.
- **Risco aceito:** a janela do Jarvis aparece na lista de janelas do sistema (é uma janela de verdade); o dono pode fechá-la, e ela é refeita na próxima vez.
- **Achado da prova:** o Chromium **headless** trata a janela mais nova como a em foco e ignora a devolução do foco — por isso a prova do Chromium roda com janela de verdade, num X virtual (Xvfb) com gerenciador de janelas (openbox), na imagem `localhost/jarvis-nav-teste:x11`, e confere o foco também pelo X (`xprop -root _NET_ACTIVE_WINDOW`). O Firefox continua headless, onde o foco já se observa.
- **Não provado:** o KDE de verdade (o KWin pode tratar `focused: false` de outro jeito que o openbox); o código devolve o foco quando o navegador sabe que o perdeu.
- Testes: `tests/unit/navegador/background_respostas.test.mjs` (a janela sem foco, reaproveitada, o foco devolvido quando o navegador o toma, `tabs.navigate` sem trazer para a frente, a busca na janela do Jarvis, `windows.focused`), `tests/unit/navegador/test_ferramentas_browser.py`, `tests/unit/navegador/test_quadro_e_protocolo.py` e o roteiro em contêiner `tools/harness_navegador.py` (Chromium com janela e Firefox: ler, clicar e ver a tela na janela do Jarvis com a janela em foco, a aba ativa do dono e a janela ativa do X iguais antes e depois; a busca numa aba da janela do Jarvis, fechada no fim).

## Emenda de 2026-10-21 — ver ou não ver (auditoria da integração)

O dono pediu «abra um vídeo no YouTube» e o navegador dele «continuou igual»: a aba mudou atrás do
app do Jarvis e nada a trouxe para a frente — esta ADR tinha tirado o `active: true` e nada mais
punha o resultado à vista. Agora o código decide pela fala do dono (`quer_ver`, ADR-0035):

- **Pedido de ver** (abrir, mostrar, pôr, tocar, assistir): navega a aba atual do dono (ou a que o
  modelo escolheu) e, no fim, a traz para a frente (`tabs.show`: ativa e com a janela em foco; a aba
  da janela do Jarvis vai para a janela do dono). O resultado diz `visivel` — o sistema pode negar o
  foco ao navegador, e aí a ferramenta diz que não ficou à vista.
- **Trabalho que o dono não pediu para ver** (pesquisar, ler, conferir): vai para esta janela mesmo
  sem `segundo_plano`, e a aba de trabalho do pedido é o alvo das `browser.*` sem `tab_id`.
- **A janela do Jarvis** agora se segura com uma página própria (`extensao/janela.html`, que diz ao
  dono o que ela é) e é reconhecida por ela depois que o service worker reinicia; a "aba atual" do
  dono é a da última janela **normal** dele (nunca popup, app, DevTools ou esta janela).

Testes: `tests/unit/navegador/background_navegacao.test.mjs` (navegador falso com janelas, abas e
eventos), `tests/unit/navegador/test_ferramentas_browser.py` (o caso do dono) e o roteiro em
contêiner.

## Emenda de 2026-10-21 (2) — uma instância só: o fundo é aba da janela do dono, e a janela própria fica para a automação social

**Pedido do dono (2026-10-21, depois de testar o `8cc7bf6`):** o Jarvis começou no navegador que
ele já usava, depois **abriu outra instância do Brave** — a janela própria do Jarvis, desta ADR, que
ele não precisa acompanhar — e abriu a aba do vídeo **nela**, não no navegador em uso. As regras
novas dele:

1. O Jarvis só abre um navegador se **não houver um ativo** (extensão conectada ou processo dele).
   Havendo: se a aba atual não é o site do pedido, **guia nova** no navegador atual (a janela dele,
   aba nova, sem nova instância); se já existe aba com o site, reaproveitar conforme o estado (a
   regra 4 da ADR-0027, mantida). Nunca nova instância nem perfil para pedido comum. Pedido de
   «abra/mostre para eu ver» continua terminando à vista dele.
2. Trabalho em abas **sem mostrar** ao dono (ler, pesquisar, automação comum) usa o navegador
   **dele**, controlando as abas sem trazê-las ao foco, como o Claude in Chrome: aba nova em
   segundo plano, sem `active`, sem mudar a janela focada.
3. A janela/instância própria do Jarvis fica **reservada ao futuro** — depuração e automação de
   redes sociais, e-mails e agendas (Instagram, WhatsApp, Discord, Facebook, Twitter…) com
   digitação humanizada tecla por tecla —, por um modo `automacao_social` (padrão desligado), que é
   o **único** caminho para ela. Sem esse modo, nunca janela nem instância própria.

**A causa, na trilha do dono** (`~/.local/state/jarvis/voz/diagnostico/turnos.jsonl`, 21/10 das
15:30 às 15:32, só metadados). Duas, uma em cada metade do sintoma:

- **A "outra instância":** o `web.buscar` sem chave (ADR-0033) leu numa aba da janela do Jarvis, e
  a janela nasceu ali — outra janela do Brave na tela dele, com a página `janela.html`. A decisão 1
  desta ADR contava devolver o foco à janela do dono se o navegador o tomasse; no Wayland do KDE o
  navegador não consegue pegar o foco de volta sozinho, e a janela do Jarvis ficou a ativa dele.
- **O vídeo nela:** o modelo mandou um `tab_id` velho, ouviu a falha crua do navegador («No tab with
  id») e caiu num `sites.open` com `nova_aba` (2,4 ms na trilha). Com `nova_aba` o `sites.open`
  **pulava a extensão** e executava o binário do principal do dono (`brave-browser.desktop` →
  `/usr/bin/brave-browser-stable <url>`); o Brave já aberto entregou a URL à **última janela ativa**
  dele — a do Jarvis.

**O que vale agora** (substitui as decisões 1 e 2 desta ADR e a emenda «ver ou não ver» onde ela
manda o fundo para a janela do Jarvis):

1. **Sem janela própria fora da automação social.** A extensão só cria janela com
   `modo: "automacao_social"` no pedido (`tabs.open`, `page.readUrl`), e o Jarvis só o manda com
   `ClienteDoNavegador.automacao_social` ligado — o gancho, desligado e **sem chave na
   configuração** até a automação social existir. É o único caminho para `janelaDoJarvis()`
   (`tests/unit/navegador/test_extensao.py` conta as chamadas; o navegador falso prova que, sem o
   modo, nenhum pedido cria janela).
2. **O trabalho de fundo é uma aba em segundo plano na janela do dono:** `tabs.open` com `fundo` e
   a busca do `page.readUrl` criam a aba na janela dele, pelo id, **sem `active`** — a aba que ele
   está vendo continua a mesma e a janela em foco não muda; nada pede foco. As `browser.*` agem
   nela pelo id; o trabalho reaproveita a aba de fundo que ele mesmo abriu enquanto ela continua em
   segundo plano — a que o dono trouxe para a frente passa a ser dele e não é mais navegada.
3. **Guia nova em vez de trocar a página do dono.** Pedido de ver sem aba do site: a guia que o
   próprio pedido já abriu, ou a «nova aba» vazia do dono (não há página dele nela), ou uma **guia
   nova** na janela dele. A aba que já está na página (só ativa) e a do mesmo site (navegada)
   continuam como na regra 4 da ADR-0027.
4. **Abrir navegador só sem um ativo** (`executor/navegadores.py`, `AbridorDeNavegador.ja_aberto`):
   com a extensão conectada, o `sites.open` vai por ela — também com `nova_aba` —; o «abre o
   navegador» (`browser.launch`, e o `apps.launch` de um app que é navegador, configurado ou só
   liberado) traz a janela do dono para a frente (`tabs.show` da aba atual, sem concessão nem
   faixa) e diz `ja_aberto`. Sem extensão, um processo do navegador rodando também conta como
   aberto: lido em `/proc/<pid>/exe` — só o executável, nunca o ambiente nem a linha de comando. Só
   sem nenhum dos dois (ou com ele aberto sem janela nenhuma) o navegador é lançado — o
   `apps.launch`, então, abre como qualquer app, com o foco acompanhado (ADR-0037).
5. **Ditos:** aba pedida que não existe mais é `sem_aba` («essa aba não existe mais…: veja as abas
   abertas»), e não a falha crua; `windows.focused` conta as janelas (`janelas`), para a prova.

**Alternativas descartadas:** manter a janela própria e só devolver o foco melhor — no Wayland do
KDE o navegador não pega o foco de volta sem um token de ativação, e a janela continua parecendo
outra instância; um grupo de abas «Jarvis» como o do Claude in Chrome — dar nome e cor ao grupo
pede a permissão `tabGroups` no Chromium, uma permissão nova, e não era o pedido; fechar sozinho a
janela do Jarvis que ficou da versão anterior — ela pode ter uma aba que o dono está usando (o
vídeo).

**O que se perde (aceito):** a aba de fundo aparece na barra de abas do dono enquanto o Jarvis
trabalha — a da busca fecha no fim, a do trabalho fica, como as do Claude in Chrome —; e a **tela**
de uma aba de fundo só sai no Firefox (`captureTab`): no Chromium e no Brave a captura é da aba à
vista na janela dela, e o Jarvis não a traz para a frente só para isso — a `browser.tela` diz
`aba_escondida` e a leitura e o mapa da página continuam valendo.

**Reservado ao futuro (não feito):** a automação social com digitação humanizada, que vai usar a
janela própria (hoje só o gancho existe, desligado); a limpeza automática da janela do Jarvis que
ficou aberta da versão anterior — a página dela (`janela.html`) agora diz que ela pode ser fechada.

**Provas.** Testes que falham no código de antes: o fundo da extensão num navegador falso
(`tests/unit/navegador/background_navegacao.test.mjs`: a busca e a aba de fundo na janela do dono
sem `active`, nenhum pedido sem o modo cria janela, `sem_aba` dito — 11 falham no `background.js`
do `6ed4134`), `test_extensao.py` (um `windows.create` só, alcançável só pelo modo),
`test_ferramentas_browser.py`, `test_quadro_e_protocolo.py`, `test_ligacao_ao_app.py` (o app
inteiro com o host de verdade: a guia nova pela extensão e o `browser.launch` sem lançar),
`tests/unit/executor/test_navegadores.py` e `test_ferramentas.py` (o `nova_aba`, o processo em
`/proc`, «sem navegador ativo abre um», o `apps.launch`) e `tests/unit/politica/test_metodo.py`. E o
roteiro em contêiner (`tools/harness_navegador.py`, Chromium 155 e Firefox 158 de verdade): 41/41
nos dois — sem navegador ativo o Jarvis abre um pelo `sites.open` (o único caso) e, com ele aberto,
o `browser.launch` e a aba nova não lançam nada; depois da busca, do trabalho de fundo, da guia nova
e do reuso, uma janela, nenhuma janela do Jarvis nem `janela.html` e um processo principal; a aba
de fundo na janela do dono sem `active`, com a janela em foco, a aba à vista e a janela ativa do X
iguais. O **mesmo roteiro no código de antes** (o `src/`, a `extensao/` e o `catalogo/` do
`6ed4134` montados por cima, só leitura) reproduz o bug nos dois navegadores: depois da busca sem
chave, **2 janelas**, com a do Jarvis e a `janela.html`; o `sites.open` com `nova_aba` **executou**
`/usr/bin/chromium-browser <url>` e `/usr/bin/firefox <url>`; e o «abre o navegador» com ele aberto
o lançou de novo (no Chromium, um desses lançamentos ficou como um segundo processo principal).

**Não provado:** o Brave e o KWin/Wayland de verdade (o roteiro usa o Chromium do Fedora e o
openbox; no KDE a guia nova e a aba de fundo não dependem do foco, o que mudava era a janela
própria); o YouTube de verdade (o contêiner não tem rede); a janela do Jarvis que ficou aberta no
Brave do dono, que o Jarvis não fecha sozinho.

## Emenda de 2026-10-21 (3) — o Brave aberto vem para a frente pelo KWin, e o app lançado sabe que está no Plasma 6

**Relato do dono:** "não consegue abrir o Brave". Três causas: (a) com um site junto, o roteador
tirava o `browser.launch` do turno (emenda (2) da ADR-0035); (b) com o Brave aberto, a extensão
pede a frente (`windows.update` com `focused`), e no Wayland do KDE o navegador não consegue pegar
o foco sozinho — a resposta era «já estava aberto, mas não veio para a frente», e para o dono nada
acontecia; (c) o app lançado pelo Jarvis recebia um ambiente sem as variáveis do desktop: sem
`KDE_SESSION_VERSION` o Chromium/Brave lê o KDE como "KDE4" (`base/nix/xdg_util.cc`) e escolhe
outro chaveiro para as senhas e os cookies do perfil.

- **O gerenciador de janelas traz o navegador** quando a extensão não trouxe ou não está conectada
  (`AbridorDeNavegador.focar_janela`, `CorposDoNavegador.trazer_a_frente`,
  `janelas.focar_o_navegador`): a janela da família (a classe `brave-browser`), a que mostra a aba
  pedida pelo título, senão a ativa ou a da frente. O KWin ativa a janela mesmo com outra ativa
  noutro monitor — provado no KWin 6.7.5 virtual (`tools/harness_foco.py`). O pedido de ver uma
  página que o sistema segurou atrás termina à vista do mesmo jeito.
- **O ambiente do app lançado** leva as variáveis de identidade do desktop, como o lançador do KDE
  passa (`KDE_SESSION_VERSION`, `KDE_FULL_SESSION`, `XDG_SESSION_DESKTOP`, `DESKTOP_SESSION`, as da
  sessão e das pastas, locale, cursor, tema, `SSH_AUTH_SOCK`) — e só a lista fechada: nenhuma chave.
- **Não provado:** o Brave de verdade vindo para a frente no KWin do dono (o roteiro usa janelas
  Qt com a classe dele); o efeito do chaveiro sobre o perfil dele — a variável agora vai, e o
  `tools/diagnostico_foco.py` mostra a sessão e as janelas.
- Testes: `tests/unit/executor/test_navegadores.py`, `tests/unit/executor/test_janelas.py`,
  `tests/unit/navegador/test_ferramentas_browser.py`, `tests/unit/executor/test_lancador.py`.
