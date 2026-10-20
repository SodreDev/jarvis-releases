import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

// O que o host recebe da extensão: `{ id, ok, result }` com o resultado do conteúdo **plano**, ou
// `{ id, ok: false, error }` com o erro dele. Antes, o envelope do conteúdo chegava inteiro dentro
// de `result` e o Jarvis lia página vazia (reproduzido no Chromium 155, 2026-10-19).

const background = await readFile(
  new URL("../../../extensao/background.js", import.meta.url),
  "utf8",
);

class EventoFalso {
  listeners = [];

  addListener(listener) {
    this.listeners.push(listener);
  }

  emitir(...args) {
    for (const listener of this.listeners) {
      listener(...args);
    }
  }
}

class PortaFalsa {
  onMessage = new EventoFalso();
  onDisconnect = new EventoFalso();
  respostas = [];

  postMessage(mensagem) {
    this.respostas.push(mensagem);
  }
}

const ABA = { id: 7, windowId: 1, active: true, url: "https://exemplo.org/", title: "Exemplo" };

function carregar(responderPagina, extraDasAbas = {}, aba = ABA) {
  const portas = [];
  const enviadas = [];
  const contexto = vm.createContext({
    URL,
    Date,
    Math,
    chrome: {
      runtime: {
        lastError: undefined,
        onStartup: new EventoFalso(),
        onInstalled: new EventoFalso(),
        connectNative() {
          const porta = new PortaFalsa();
          portas.push(porta);
          return porta;
        },
      },
      tabs: {
        ...extraDasAbas,
        query: async () => [aba],
        get: async () => aba,
        sendMessage: async (tabId, mensagem) => {
          enviadas.push({ tabId, mensagem });
          return responderPagina(mensagem);
        },
      },
    },
    console: { warn() {} },
    setTimeout() {
      return 1;
    },
  });
  vm.runInContext(background, contexto, { filename: "extensao/background.js" });
  return { porta: portas[0], enviadas };
}

async function pedir(cenario, pedido) {
  cenario.porta.onMessage.emitir(pedido);
  for (let volta = 0; volta < 20 && cenario.porta.respostas.length === 0; volta += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(cenario.porta.respostas.length, 1, "a extensão tinha de responder uma vez");
  // Objetos do contexto `vm` têm outro `Object.prototype`: compara-se o JSON, que é o que o host lê.
  return JSON.parse(JSON.stringify(cenario.porta.respostas[0]));
}

test("page.read devolve ao host o resultado do conteúdo sem o envelope dele", async () => {
  const cenario = carregar(() => ({
    ok: true,
    result: { url: ABA.url, titulo: "Exemplo", textoVisivel: "Olá", links: [], datas: [] },
  }));

  const resposta = await pedir(cenario, { id: "j1-1", method: "page.read", params: { tabId: 7 } });

  assert.deepEqual(resposta, {
    id: "j1-1",
    ok: true,
    result: { url: ABA.url, titulo: "Exemplo", textoVisivel: "Olá", links: [], datas: [] },
  });
  assert.equal(cenario.enviadas[0].mensagem.comando, "ler");
});

test("page.inspect chega plano: o risco do clique enxerga o envio de formulário", async () => {
  const cenario = carregar(() => ({
    ok: true,
    result: { tag: "button", texto: "OK", campo: false, enviaFormulario: true },
  }));

  const resposta = await pedir(cenario, {
    id: "j1-2",
    method: "page.inspect",
    params: { tabId: 7, alvo: "OK" },
  });

  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.enviaFormulario, true);
  assert.equal(resposta.result.ok, undefined);
});

test("page.map e page.act chegam ao conteúdo como mapear e acionar, com a referência", async () => {
  const cenario = carregar((mensagem) => ({ ok: true, result: { comando: mensagem.comando } }));

  const mapa = await pedir(cenario, { id: "j1-5", method: "page.map", params: { tabId: 7 } });
  assert.deepEqual(mapa.result, { comando: "mapear" });

  cenario.porta.respostas.length = 0;
  const acao = await pedir(cenario, {
    id: "j1-6",
    method: "page.act",
    params: { tabId: 7, ref: "ab1.3", acao: "tecla", tecla: "Enter" },
  });
  assert.deepEqual(acao.result, { comando: "acionar" });
  assert.deepEqual(JSON.parse(JSON.stringify(cenario.enviadas[1].mensagem.params)), {
    tabId: 7,
    ref: "ab1.3",
    acao: "tecla",
    tecla: "Enter",
  });
});

test("page.capture: a captura da aba visível e o mapa do mesmo instante", async () => {
  const capturas = [];
  const cenario = carregar(
    (mensagem) => ({ ok: true, result: { comando: mensagem.comando, instantaneo: "ab1" } }),
    {
      captureVisibleTab: async (janela, opcoes) => {
        capturas.push({ janela, formato: opcoes.format });
        return "data:image/jpeg;base64,AAAA";
      },
    },
  );
  const resposta = await pedir(cenario, { id: "j1-7", method: "page.capture", params: { tabId: 7 } });
  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.imagem, "data:image/jpeg;base64,AAAA");
  assert.deepEqual(resposta.result.mapa, { comando: "mapear", instantaneo: "ab1" });
  assert.deepEqual(JSON.parse(JSON.stringify(capturas)), [{ janela: 1, formato: "jpeg" }]);
});

test("page.capture no Chromium recusa a aba escondida atrás de outra, sem trocar o foco", async () => {
  const escondida = { ...ABA, active: false };
  const cenario = carregar(() => ({ ok: true, result: {} }), {
    captureVisibleTab: async () => {
      throw new Error("não devia capturar outra aba");
    },
  }, escondida);
  const resposta = await pedir(cenario, { id: "j1-8", method: "page.capture", params: { tabId: 7 } });
  assert.equal(resposta.ok, false);
  assert.equal(resposta.error.codigo, "aba_escondida");
});

test("page.capture no Firefox usa captureTab, que pega a aba mesmo escondida", async () => {
  const escondida = { ...ABA, active: false };
  const pedidas = [];
  const cenario = carregar(() => ({ ok: true, result: { instantaneo: "ab1" } }), {
    captureTab: async (tabId) => {
      pedidas.push(tabId);
      return "data:image/jpeg;base64,BBBB";
    },
  }, escondida);
  const resposta = await pedir(cenario, { id: "j1-9", method: "page.capture", params: { tabId: 7 } });
  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.imagem, "data:image/jpeg;base64,BBBB");
  assert.deepEqual(pedidas, [7]);
});

test("page.capture só captura página http ou https", async () => {
  const interna = { ...ABA, url: "chrome://settings/" };
  const cenario = carregar(() => ({ ok: true, result: {} }), {
    captureVisibleTab: async () => "data:image/jpeg;base64,AAAA",
  }, interna);
  const resposta = await pedir(cenario, { id: "j1-10", method: "page.capture", params: { tabId: 7 } });
  assert.equal(resposta.ok, false);
  assert.equal(resposta.error.codigo, "aba_nao_http");
});

test("erro do próprio navegador na captura chega com a mensagem dele", async () => {
  const cenario = carregar(() => ({ ok: true, result: {} }), {
    captureVisibleTab: async () => {
      throw new Error("Either the '<all_urls>' or 'activeTab' permission is required.");
    },
  });
  const resposta = await pedir(cenario, { id: "j1-11", method: "page.capture", params: { tabId: 7 } });
  assert.equal(resposta.ok, false);
  assert.equal(resposta.error.codigo, "captura_negada");
  assert.match(resposta.error.mensagem, /all_urls/);
});

test("erro do conteúdo vira erro da ponte com o código dele", async () => {
  const cenario = carregar(() => ({
    ok: false,
    error: { codigo: "campo_sensivel", mensagem: "senha é digitada somente pelo dono" },
  }));

  const resposta = await pedir(cenario, {
    id: "j1-3",
    method: "page.type",
    params: { tabId: 7, alvo: "Senha", texto: "x" },
  });

  assert.deepEqual(resposta, {
    id: "j1-3",
    ok: false,
    error: { codigo: "campo_sensivel", mensagem: "senha é digitada somente pelo dono" },
  });
});

test("página sem o conteúdo da extensão ou sem resposta é indisponível, não sucesso", async () => {
  for (const responderPagina of [
    () => {
      throw new Error("Could not establish connection. Receiving end does not exist.");
    },
    () => undefined,
  ]) {
    const cenario = carregar(responderPagina);
    const resposta = await pedir(cenario, {
      id: "j1-4",
      method: "page.read",
      params: { tabId: 7 },
    });
    assert.equal(resposta.ok, false);
    assert.equal(resposta.error.codigo, "pagina_indisponivel");
  }
});

test("tabs.list continua respondendo com as abas resumidas", async () => {
  const cenario = carregar(() => assert.fail("tabs.list não fala com a página"));

  const resposta = await pedir(cenario, { id: "j1-5", method: "tabs.list", params: {} });

  assert.deepEqual(resposta, {
    id: "j1-5",
    ok: true,
    result: {
      abas: [{ id: 7, janelaId: 1, ativa: true, url: ABA.url, titulo: "Exemplo" }],
    },
  });
});
