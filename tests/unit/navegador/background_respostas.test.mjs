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

function carregar(responderPagina) {
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
        query: async () => [ABA],
        get: async () => ABA,
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
