# ADR-0036 — A extensão trabalha numa janela própria do Jarvis, sem tirar o foco do dono

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono, Lote C) · **Decide:** dono (quando o foco pode mudar), arquiteto (a janela e a prova)
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
