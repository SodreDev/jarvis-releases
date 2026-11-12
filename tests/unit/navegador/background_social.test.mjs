import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

// O fundo da extensão no monitor das redes (ADR-0060; docs/redes-sociais-riscos.md §1–§2), com
// abas e porta FALSAS: a aba da rede que já existe é reusada (nunca duas da mesma conta), a nova
// nasce em segundo plano na janela do dono (nunca janela nova), e só o social.js da própria rede
// repassa estado ao Jarvis. Nenhum navegador, nenhuma conta.

const background = await readFile(
  new URL("../../../extensao/background.js", import.meta.url),
  "utf8",
);

class EventoFalso {
  listeners = [];

  addListener(listener) {
    this.listeners.push(listener);
  }

  removeListener(listener) {
    this.listeners = this.listeners.filter((outro) => outro !== listener);
  }

  emitir(...args) {
    return this.listeners.map((listener) => listener(...args));
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

function carregar({ abas = [], responderPagina = () => ({}) } = {}) {
  const estado = { abas: [...abas], criadas: [], atualizadas: [], janelasCriadas: 0, enviadas: [] };
  const portas = [];
  const onMessage = new EventoFalso();
  const contexto = vm.createContext({
    URL,
    Date,
    Math,
    chrome: {
      windows: {
        getLastFocused: async () => ({ id: 1 }),
        get: async (id) => ({ id }),
        getAll: async () => [{ id: 1 }],
        create: async () => {
          estado.janelasCriadas += 1;
          return { id: 50 };
        },
        update: async (id) => ({ id }),
      },
      runtime: {
        id: "jarvis",
        getURL: (caminho) => `chrome-extension://jarvis/${caminho}`,
        lastError: undefined,
        onStartup: new EventoFalso(),
        onInstalled: new EventoFalso(),
        onMessage,
        connectNative() {
          const porta = new PortaFalsa();
          portas.push(porta);
          return porta;
        },
      },
      tabs: {
        query: async () => estado.abas,
        get: async (id) => estado.abas.find((a) => a.id === id),
        create: async (opcoes) => {
          estado.criadas.push(opcoes);
          const aba = { id: 90 + estado.criadas.length, windowId: opcoes.windowId, ...opcoes };
          estado.abas.push(aba);
          return aba;
        },
        update: async (id, opcoes) => {
          estado.atualizadas.push({ id, ...opcoes });
          return { id };
        },
        sendMessage: async (tabId, mensagem) => {
          estado.enviadas.push({ tabId, mensagem });
          return responderPagina(mensagem);
        },
      },
    },
    console: { warn() {} },
    setTimeout() {
      return 1;
    },
    clearTimeout() {},
  });
  vm.runInContext(background, contexto, { filename: "extensao/background.js" });
  return { porta: portas[0], estado, onMessage };
}

async function pedir(cenario, pedido) {
  cenario.porta.respostas.length = 0;
  cenario.porta.onMessage.emitir(pedido);
  for (let volta = 0; volta < 30 && cenario.porta.respostas.length === 0; volta += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.equal(cenario.porta.respostas.length, 1, "a extensão tinha de responder uma vez");
  return JSON.parse(JSON.stringify(cenario.porta.respostas[0]));
}

const DO_DONO = { id: 3, windowId: 1, active: false, url: "https://web.whatsapp.com/", lastAccessed: 5 };

test("social.abrir reusa a aba da rede que o dono já tem: nada novo é criado", async () => {
  const cenario = carregar({ abas: [{ id: 1, windowId: 1, active: true, url: "https://exemplo.org/" }, DO_DONO] });
  const resposta = await pedir(cenario, { id: "s1", method: "social.abrir", params: { rede: "whatsapp" } });
  assert.deepEqual(resposta, { id: "s1", ok: true, result: { tabId: 3, reutilizada: true } });
  assert.equal(cenario.estado.criadas.length, 0);
  assert.equal(cenario.estado.janelasCriadas, 0);
});

test("sem aba da rede: uma aba de fundo na janela do dono, no endereço fixo, sem janela nova", async () => {
  const cenario = carregar({ abas: [{ id: 1, windowId: 1, active: true, url: "https://exemplo.org/" }] });
  const resposta = await pedir(cenario, { id: "s2", method: "social.abrir", params: { rede: "discord" } });
  assert.equal(resposta.ok, true);
  assert.equal(resposta.result.reutilizada, false);
  assert.deepEqual(JSON.parse(JSON.stringify(cenario.estado.criadas)), [
    { url: "https://discord.com/channels/@me", active: false, windowId: 1 },
  ]);
  assert.equal(cenario.estado.janelasCriadas, 0, "nunca janela nova");
  assert.equal(cenario.estado.atualizadas[0].autoDiscardable, false);
  // pedir de novo reusa a que acabou de nascer
  const outra = await pedir(cenario, { id: "s3", method: "social.abrir", params: { rede: "discord" } });
  assert.equal(outra.result.reutilizada, true);
  assert.equal(cenario.estado.criadas.length, 1);
});

test("rede fora da lista é recusada, e endereço quem escolhe é a extensão", async () => {
  const cenario = carregar();
  const resposta = await pedir(cenario, { id: "s4", method: "social.abrir", params: { rede: "orkut" } });
  assert.equal(resposta.ok, false);
  assert.equal(resposta.error.codigo, "rede_invalida");
  const comUrl = await pedir(cenario, {
    id: "s5",
    method: "social.abrir",
    params: { rede: "whatsapp", url: "https://golpe.example/" },
  });
  assert.equal(comUrl.ok, true);
  assert.equal(cenario.estado.criadas[0].url, "https://web.whatsapp.com/");
});

test("social.estado pergunta à aba da rede e devolve só o contrato, limpo", async () => {
  const cenario = carregar({
    abas: [DO_DONO],
    responderPagina: () => ({
      rede: "whatsapp",
      logado: true,
      naoLidas: 2,
      conversas: [{ nome: "Ana‮\nX", naoLidas: 2, texto: "não pode ir" }],
      formato: "conhecido",
      alerta: "",
      cookie: "nunca",
    }),
  });
  const resposta = await pedir(cenario, { id: "s6", method: "social.estado", params: { rede: "whatsapp" } });
  assert.deepEqual(resposta.result, {
    logado: true,
    naoLidas: 2,
    conversas: [{ nome: "Ana X", naoLidas: 2 }],
    formato: "conhecido",
    alerta: "",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(cenario.estado.enviadas)), [
    { tabId: 3, mensagem: { social: "estado" } },
  ]);
});

test("só o social.js da própria rede repassa estado ao Jarvis", async () => {
  const cenario = carregar();
  const estado = { rede: "whatsapp", logado: true, naoLidas: 1, conversas: [], formato: "conhecido", alerta: "" };
  const remetente = (url) => ({ id: "jarvis", tab: { id: 3, url } });
  cenario.onMessage.emitir({ tipo: "social", estado }, remetente("https://web.whatsapp.com/"), () => {});
  cenario.onMessage.emitir({ tipo: "social", estado }, remetente("https://golpe.example/"), () => {});
  cenario.onMessage.emitir(
    { tipo: "social", estado: { ...estado, rede: "discord" } },
    remetente("https://web.whatsapp.com/"),
    () => {},
  );
  cenario.onMessage.emitir({ tipo: "social", estado }, { id: "outra", tab: { id: 3, url: "https://web.whatsapp.com/" } }, () => {});
  const eventos = JSON.parse(JSON.stringify(cenario.porta.respostas));
  assert.deepEqual(eventos, [{ evento: "social", ...estado }]);
});
