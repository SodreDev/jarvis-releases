import assert from "node:assert/strict";
import test from "node:test";

import { NavegadorFalso, ORIGEM, pedir } from "./navegador_falso.mjs";

// Auditoria da integração (2026-10-21). O dono pediu "abra um vídeo no YouTube"; a extensão
// respondeu ok em 25 ms e o navegador dele "continuou igual". Navegar respondia na hora, com a URL
// de ANTES, sem conferir que a aba saiu do lugar, nem que a página abriu, nem se ficou à vista.

const DONO = { id: 1, abas: [{ id: 7, url: "https://exemplo.org/", title: "Exemplo" }] };

test("tabs.navigate espera a página nova e devolve a URL e o título dela, não os de antes", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "n1",
    method: "tabs.navigate",
    params: { tabId: 7, url: "https://www.youtube.com/results?search_query=gatos" },
  });

  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.aba.url, "https://www.youtube.com/results?search_query=gatos");
  assert.equal(resposta.result.comecou, true);
  assert.equal(resposta.result.carregou, true);
  assert.deepEqual(resposta.result.pagina, {
    url: "https://www.youtube.com/results?search_query=gatos",
    titulo: "Página de www.youtube.com",
  });
  assert.equal(resposta.result.janela, "dono");
  assert.equal(resposta.result.visivel, true, "a aba ativa da janela em foco");
  assert.deepEqual(nav.atualizadas, [
    { id: 7, url: "https://www.youtube.com/results?search_query=gatos" },
  ], "navegar não traz a aba para a frente (ADR-0036)");
});

test("sem rede a página de erro do navegador não responde: pagina vem nula, não sucesso", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], semRede: new Set(["www.youtube.com"]) });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "n2",
    method: "tabs.navigate",
    params: { tabId: 7, url: "https://www.youtube.com/" },
  });

  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.carregou, true);
  assert.equal(resposta.result.pagina, null, "o conteúdo da extensão não existe na página de erro");
});

test("página que segura a saída: a aba nem começa a navegar, e isso volta dito", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], seguraSaida: new Set(["exemplo.org"]) });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "n3",
    method: "tabs.navigate",
    params: { tabId: 7, url: "https://www.youtube.com/" },
  });

  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.comecou, false);
  assert.equal(resposta.result.carregou, false);
  assert.equal(resposta.result.aba.url, "https://exemplo.org/", "a aba ficou onde estava");
});

test("com o dono em outro programa a aba muda mas não está à vista: visivel é falso", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], foco: -1 });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "n4",
    method: "tabs.navigate",
    params: { url: "https://www.youtube.com/" },
  });

  assert.equal(resposta.result.aba.id, 7, "a aba atual é a da última janela do dono");
  assert.equal(resposta.result.visivel, false);
});

test("tabs.show traz a aba e a janela dela para a frente, e diz que ficou à vista", async () => {
  const nav = new NavegadorFalso({
    janelas: [
      {
        id: 1,
        abas: [
          { id: 7, url: "https://exemplo.org/", title: "Exemplo" },
          { id: 8, url: "https://www.youtube.com/", title: "YouTube", active: false },
        ],
      },
    ],
    foco: -1,
  });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, { id: "n5", method: "tabs.show", params: { tabId: 8 } });

  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.visivel, true);
  assert.equal(nav.aba(8).active, true);
  assert.equal(nav.foco, 1);
});

test("tabs.show com o foco negado pelo sistema diz que a aba não ficou à vista", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], foco: -1, focoNegado: true });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, { id: "n6", method: "tabs.show", params: { tabId: 7 } });

  assert.equal(resposta.result.visivel, false, "sem fingir: a janela não veio para a frente");
});

test("tabs.show leva a aba da janela do Jarvis para a janela do dono", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  const aberta = await pedir(porta, {
    id: "n7",
    method: "tabs.open",
    params: { url: "https://www.youtube.com/watch?v=1", janela: "jarvis" },
  });
  assert.equal(aberta.result.janela, "jarvis");
  assert.equal(aberta.result.visivel, false);

  const mostrada = await pedir(porta, {
    id: "n8",
    method: "tabs.show",
    params: { tabId: aberta.result.aba.id },
  });

  assert.equal(mostrada.result.aba.janelaId, 1, "foi para a janela do dono");
  assert.equal(mostrada.result.janela, "dono");
  assert.equal(mostrada.result.visivel, true);
  assert.deepEqual(nav.movidas, [{ id: aberta.result.aba.id, windowId: 1, index: -1 }]);
});

test("a janela do Jarvis segura-se com a página dela e é reconhecida depois que o fundo reinicia", async () => {
  // O Firefox pode dar o foco à janela criada "sem foco"; e o service worker dorme e reinicia sem
  // memória. Antes, a "aba atual" caía na janela do Jarvis e ele criava outra janela.
  const nav = new NavegadorFalso({ janelas: [DONO], roubaFoco: true });
  const primeira = nav.carregarFundo();
  await pedir(primeira, {
    id: "n9",
    method: "tabs.open",
    params: { url: "https://x.example/a", janela: "jarvis" },
  });
  assert.equal(nav.criadas[0].url, `${ORIGEM}janela.html`);
  nav.foco = 50; // o navegador deixou a janela do Jarvis em foco

  const depois = nav.carregarFundo(); // o worker reiniciou
  const atual = await pedir(depois, { id: "n10", method: "tabs.current", params: {} });
  await pedir(depois, {
    id: "n11",
    method: "tabs.open",
    params: { url: "https://x.example/b", janela: "jarvis" },
  });

  assert.equal(atual.result.aba.id, 7, "a aba do dono, não a da janela do Jarvis");
  assert.equal(
    nav.criadas.filter((c) => c.type === "normal").length,
    1,
    "a janela do Jarvis foi reconhecida, não refeita",
  );
});

test("a aba atual nunca é de um popup ou do DevTools", async () => {
  const nav = new NavegadorFalso({
    janelas: [
      DONO,
      { id: 3, tipo: "popup", abas: [{ id: 30, url: "https://login.example/", title: "Entrar" }] },
    ],
    foco: 3,
  });
  const porta = nav.carregarFundo();

  const atual = await pedir(porta, { id: "n12", method: "tabs.current", params: {} });

  assert.equal(atual.result.aba.id, 7);
});

test("tabs.open do dono nasce na janela dele, mesmo com a do Jarvis em foco", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], roubaFoco: true });
  const porta = nav.carregarFundo();
  await pedir(porta, {
    id: "n13",
    method: "tabs.open",
    params: { url: "https://x.example/a", janela: "jarvis" },
  });
  nav.foco = 50;

  const aberta = await pedir(porta, {
    id: "n14",
    method: "tabs.open",
    params: { url: "https://www.youtube.com/" },
  });

  assert.equal(aberta.result.aba.janelaId, 1);
  assert.equal(aberta.result.janela, "dono");
  assert.equal(aberta.result.carregou, true);
});

test("tabs.list marca as abas da janela do Jarvis", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, {
    id: "n15",
    method: "tabs.open",
    params: { url: "https://x.example/a", janela: "jarvis" },
  });

  const lista = await pedir(porta, { id: "n16", method: "tabs.list", params: {} });

  const doJarvis = lista.result.abas.filter((aba) => aba.janelaDoJarvis).map((aba) => aba.janelaId);
  assert.ok(doJarvis.length >= 1 && doJarvis.every((id) => id === 50));
  assert.equal(lista.result.abas.find((aba) => aba.id === 7).janelaDoJarvis, false);
});

// --- a janela do Jarvis (ADR-0036), no navegador falso com eventos ---------------------------------
test("page.readUrl lê numa aba da janela do Jarvis, sem foco, e a fecha no fim", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "j1",
    method: "page.readUrl",
    params: { url: "https://search.brave.com/search?q=x" },
  });

  assert.equal(resposta.ok, true);
  const daBusca = nav.criadas.find((c) => c.url === "https://search.brave.com/search?q=x");
  assert.equal(daBusca.windowId, 50, "na janela do Jarvis");
  assert.equal(nav.abas.has(daBusca.aba), false, "a aba de fundo foi fechada");
  assert.equal(nav.criadas[0].focused, false);
  assert.deepEqual(nav.focadas, [], "o foco do dono não foi tocado");
  assert.ok(nav.mensagens.every((m) => m.tabId === daBusca.aba), "leu a aba de fundo, não a do dono");
});

test("page.readUrl fecha a aba de fundo mesmo quando a página não responde", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], semRede: new Set(["search.brave.com"]) });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, {
    id: "j2",
    method: "page.readUrl",
    params: { url: "https://search.brave.com/search?q=x" },
  });

  assert.equal(resposta.ok, false);
  assert.equal(resposta.error.codigo, "pagina_indisponivel");
  const daBusca = nav.criadas.find((c) => c.url === "https://search.brave.com/search?q=x");
  assert.equal(nav.abas.has(daBusca.aba), false);
});

test("tabs.open na janela do Jarvis cria a janela sem foco uma vez e a reaproveita depois", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const primeira = await pedir(porta, {
    id: "j3",
    method: "tabs.open",
    params: { url: "https://x.example/a", janela: "jarvis" },
  });
  await pedir(porta, {
    id: "j4",
    method: "tabs.open",
    params: { url: "https://x.example/b", janela: "jarvis" },
  });

  assert.equal(primeira.ok, true);
  assert.equal(primeira.result.janela, "jarvis");
  const janelas = nav.criadas.filter((c) => c.type === "normal");
  assert.equal(janelas.length, 1, "uma janela só, reaproveitada");
  assert.equal(janelas[0].focused, false);
  assert.deepEqual(
    nav.criadas.filter((c) => c.aba !== undefined).map((c) => c.windowId),
    [50, 50],
    "as abas vão para a janela do Jarvis",
  );
  assert.deepEqual(nav.focadas, [], "o foco do dono não foi tocado");
});

test("se o navegador tomar o foco ao criar a janela, ele volta para a janela do dono", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO], roubaFoco: true });
  const porta = nav.carregarFundo();

  await pedir(porta, {
    id: "j5",
    method: "tabs.open",
    params: { url: "https://x.example/a", janela: "jarvis" },
  });

  assert.deepEqual(nav.focadas, [{ id: 1, focused: true }]);
  assert.equal(nav.foco, 1);
});

test("windows.focused diz a janela e a aba ativa do dono", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, { id: "j6", method: "windows.focused", params: {} });

  assert.deepEqual(resposta.result, {
    janelaId: 1,
    abaAtivaId: 7,
    janelaDoJarvisId: null,
    janelaDoDonoId: 1,
  });
});

test("tabs.list continua respondendo com as abas resumidas, sem falar com a página", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const resposta = await pedir(porta, { id: "j7", method: "tabs.list", params: {} });

  assert.deepEqual(resposta, {
    id: "j7",
    ok: true,
    result: {
      abas: [
        {
          id: 7,
          janelaId: 1,
          ativa: true,
          url: "https://exemplo.org/",
          titulo: "Exemplo",
          janelaDoJarvis: false,
          ultimoAcesso: 0,
        },
      ],
    },
  });
  assert.deepEqual(nav.mensagens, []);
});
