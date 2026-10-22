# ADR-0033 — Busca na web de verdade: a API com chave, senão o navegador do dono

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono) · **Decide:** dono (a ordem das fontes), arquiteto (o caminho e o risco)
**Pedido:** dono, 2026-10-20 — "BUSCA NA WEB de verdade: hoje só Wikipédia. Implemente busca geral sem chave obrigatória usando a EXTENSÃO como motor (abrir uma aba de busca no navegador do dono, ler os resultados, fechar/reutilizar a aba) e, se existir chave configurada no ambiente/chaveiro (nunca ler nem imprimir), usar a API (ex.: Brave Search API) como preferência; web.ler em vários sites seguidos; corrigir o 404 do YouTube (descubra a causa; pode ser a URL de busca/feed)". Emenda a ADR-0027 (a extensão ganha `page.readUrl`) e a ADR-0030 (a regra do dado do dono na URL passa a valer também para `web.ler`).

## Contexto

O `web.buscar` usava a Wikipédia e só ia ao Brave Search com `BRAVE_SEARCH_API_KEY` no ambiente — lido cru, sem o chaveiro, que é onde a janela guarda as chaves. O DuckDuckGo em HTML, pedido pelo cliente HTTP do Jarvis, devolve 202 de anti-robô. No teste do dono ("abra o canal do Thiago Nigro") a busca não achou nada útil e o `web.canal_videos` deu 404.

**A causa do 404** (medida em 2026-10-20 com requisições públicas): o modelo chutou o handle do canal — `https://www.youtube.com/@thiagonigro` e `@oprimorico` respondem 404; o de verdade é `@primorico` — e o `web.canal_videos` não tinha plano B para isso. O feed `feeds/videos.xml?channel_id=` respondia 200 nesse dia, mas teve 404 intermitente desde dez/2025 (relatos de leitores de RSS), e a busca do YouTube pelo nome ("o primo rico") acha o canal certo no primeiro resultado.

## Decisão

1. **A ordem das fontes** (`jarvis.executor.web.buscar`): a **API do Brave Search** quando há `BRAVE_SEARCH_API_KEY` no ambiente **ou no chaveiro** (`jarvis.voz.chaves.Chave`: a chave nunca é mostrada, e `usar()` só aparece no cabeçalho da requisição; a variável entra em `VARIAVEIS`, então a janela a guarda como as outras); sem chave, o **navegador do dono**; sem navegador (controle desligado, nenhum aberto, nenhum resultado), a **Wikipédia** — e o resultado diz por que não houve busca geral (`sem_busca_geral`).
2. **A busca pelo navegador** (`jarvis.navegador.busca.BuscaNoNavegador`). A extensão ganha `page.readUrl`: abre o endereço numa aba **de fundo** (`active: false` — não ganha o foco nem troca a aba que o dono está vendo), espera carregar (até 15 s), lê como lê qualquer página e **fecha a aba no fim, inclusive quando algo falha**. A página de resultados é do Brave Search (`search.brave.com`, que entrega a página pronta e cujos links vão direto ao site); o DuckDuckGo em HTML fica de reserva, com o redirecionamento `/l/?uddg=` desfeito. Resultado é o link que sai do buscador, com o texto dele, sem repetir endereço, até 8. A consulta é a mesma da API: redigida, curta e sem dado pessoal. Os resultados contaminam o turno e entram no objetivo como alcançados (ADR-0030), como os da API.
3. **Vários sites seguidos.** `web.ler` aceita `url` ou `urls` (até 5, um dos dois): cada site pelo mesmo caminho seguro (só IP público, redirecionamento conferido), o texto repartido para caber no resultado, e um site que falha volta com o motivo sem derrubar os outros.
4. **Dado do dono na URL do `web.ler`.** Ler é livre, mas a requisição leva a URL ao site: endereço com dado do dono ou segredo (ADR-0030, `leva_dado_do_dono`) para um site que ele não citou pede o sim — em `url` e em cada um de `urls`. Sem dado do dono, ler não pergunta, nem com o turno contaminado (o pedido de "ler vários sites seguidos").
5. **O 404 do YouTube.** Handle ou endereço de canal que responde 404 cai na **busca do YouTube pelo nome** que estava nele (`@thiagonigro` → "thiagonigro"); depois, a página canônica confere o id, como antes. Sem o feed do canal, vale o da playlist de envios (`playlist_id=UU…`) e, sem os dois, a aba "Vídeos" da página do canal (os vídeos lidos do JSON da página, sem data). O resultado diz a fonte (`feed` ou `página do canal`). A persona (v9) manda pesquisar o nome em vez de chutar o `@`.

## Alternativas descartadas

- **DuckDuckGo pelo cliente HTTP do Jarvis:** 202 de anti-robô (medido em 2026-10-19).
- **Buscar na aba que o dono está vendo:** troca a página dele; a aba de fundo não troca, e fecha sozinha.
- **Uma API de busca paga obrigatória:** o dono pediu busca sem chave obrigatória; a API fica como preferência quando há chave.

## Consequências

- **Risco aceito:** a busca pelo navegador vai com a sessão do dono no buscador (é o navegador dele). A consulta já não leva dado pessoal (recusada antes de sair), e a aba é fechada.
- **Risco aceito:** a extração por links depende da página de resultados; se o Brave Search mudar e não trouxer links para fora, o DuckDuckGo é tentado, e sem nenhum o resultado é a Wikipédia com o motivo. Sem trechos pelo navegador — o modelo lê o site com `web.ler`.
- A aba de fundo aparece por um instante na janela do dono; a janela própria do Jarvis em segundo plano é o Lote C (C3).
- **Não provado:** a API do Brave com chave de verdade (sem chave aqui) e o `search.brave.com` real no navegador do dono (o contêiner não tem rede: a página de resultados é local).
- Testes: `tests/unit/executor/test_web.py` (a ordem das fontes, a Wikipédia dizendo o porquê, vários sites, o 404 do handle, o feed e a página de vídeos), `tests/unit/navegador/test_busca.py` (links para fora, o `uddg`, a reserva, sem navegador), `tests/unit/navegador/test_ferramentas_browser.py` (o caminho pelo executor e o objetivo), `tests/unit/politica/test_objetivo.py` (o dado do dono no `web.ler`), `tests/unit/navegador/background_respostas.test.mjs` (aba de fundo sem foco, fechada mesmo na falha) e o roteiro em contêiner `tools/harness_navegador.py` (Chromium e Firefox: resultados lidos numa aba de fundo, aba fechada, aba ativa do dono igual).

## Emenda de 2026-10-21 — a aba de fundo volta para a janela do dono (ADR-0036, emenda (2))

A busca sem chave tinha ido para a janela própria do Jarvis (Lote C); foi ela que criou a «outra
instância do Brave» que o dono viu. O `page.readUrl` volta a abrir a aba de fundo **na janela do
dono**, pelo id, sem `active` — ela aparece por um instante na barra de abas dele e fecha no fim,
mesmo na falha; a aba que ele está vendo e o foco não mudam. A janela própria só no modo
`automacao_social` (desligado). Testes: `tests/unit/navegador/background_navegacao.test.mjs` (a
aba de fundo na janela do dono, nenhuma janela criada) e o roteiro em contêiner.

## Emenda de 2026-10-21 (2) — a busca genérica vai direto, sem navegador (ADR-0045)

**Relato do dono:** "ao iniciar, o Jarvis abre uma aba (link inicial), ela fecha sozinha, e o passo
a passo só começa depois". Era esta busca: sem chave, o primeiro passo de toda tarefa de site era o
`web.buscar`, lido numa aba de fundo do navegador dele e fechado no fim (trilha de 21/10: 5 buscas
assim, 0,3–1,4 s cada, antes de qualquer página à vista). O dono decidiu: busca **genérica** (sem
site) vai direto, sem abrir navegador; pedido de **site** usa o navegador dele desde o primeiro
passo, com a busca do próprio site (emenda da ADR-0035).

- **A ordem das fontes** passa a ser: a API do Brave Search com chave; sem chave, o **DuckDuckGo em
  HTML pedido pelo cliente do Jarvis** (`web._duckduckgo`: o agente honesto, sem cookie; os links
  com o redirecionamento `uddg` desfeito, sem anúncio nem repetido, até 8, com o trecho); no 202 do
  anti-robô, noutra resposta ou sem resultado, a Wikipédia com `sem_busca_geral` dizendo por quê.
  A alternativa descartada lá em cima ("202 de anti-robô, medido em 2026-10-19") é intermitente: em
  2026-10-21 o GET e o POST do `html.duckduckgo.com` responderam 200 com 10 resultados desta rede.
- **Sai o `jarvis.navegador.busca`** (a busca pela aba de fundo) e a ligação dele no executor. O
  `page.readUrl` fica na extensão para a automação social (ADR-0036, emenda (2)); o roteiro em
  contêiner prova que ele ainda lê numa aba de fundo e fecha, e que a busca genérica não abre nem
  fecha aba nenhuma e não mexe no foco (Chromium 155 e Firefox 158).
- Testes: `tests/unit/executor/test_web.py` (a busca direta, o 202, a resposta de erro, a página
  sem resultado, a API preferida), `tests/unit/navegador/test_ferramentas_browser.py` (a busca não
  chama a extensão e ainda alimenta o objetivo).
