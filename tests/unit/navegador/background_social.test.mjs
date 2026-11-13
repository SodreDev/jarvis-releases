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

function carregar({ abas = [], responderPagina = () => ({}), comCdp = false } = {}) {
  const estado = {
    abas: [...abas],
    criadas: [],
    atualizadas: [],
    janelasCriadas: 0,
    enviadas: [],
    cdp: [],
  };
  const debugger_ = comCdp
    ? {
        attach: async (alvo) => estado.cdp.push(["attach", alvo.tabId]),
        detach: async (alvo) => estado.cdp.push(["detach", alvo.tabId]),
        sendCommand: async (alvo, metodo, params) => estado.cdp.push([metodo, params]),
        onEvent: new EventoFalso(),
        onDetach: new EventoFalso(),
      }
    : undefined;
  const portas = [];
  const onMessage = new EventoFalso();
  const contexto = vm.createContext({
    URL,
    Date,
    Math,
    chrome: {
      ...(debugger_ ? { debugger: debugger_ } : {}),
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
    // As esperas curtas da digitação correm na hora; as longas (reconexão, o prazo de 120 s do
    // envio) nunca disparam no teste.
    setTimeout(funcao, ms) {
      if (ms <= 2_000) {
        queueMicrotask(funcao);
      }
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
  for (let volta = 0; volta < 300 && cenario.porta.respostas.length === 0; volta += 1) {
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
      pista: "contador_ilegivel",
      amostra: "1,5 mil\u0000 | x" + "9".repeat(80),
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
    pista: "contador_ilegivel",
    amostra: ("1,5 mil | x" + "9".repeat(80)).slice(0, 60),
  });
  // pista fora da lista não passa
  const outra = carregar({
    abas: [DO_DONO],
    responderPagina: () => ({ rede: "whatsapp", logado: true, naoLidas: 0, pista: "rm -rf" }),
  });
  const recusada = await pedir(outra, { id: "s7", method: "social.estado", params: { rede: "whatsapp" } });
  assert.equal(recusada.result.pista, "");
  assert.deepEqual(JSON.parse(JSON.stringify(cenario.estado.enviadas)), [
    { tabId: 3, mensagem: { social: "estado" } },
  ]);
});

test("só o social.js da própria rede repassa estado ao Jarvis", async () => {
  const cenario = carregar();
  const estado = {
    rede: "whatsapp",
    logado: true,
    naoLidas: 1,
    conversas: [],
    formato: "conhecido",
    alerta: "",
    pista: "",
    amostra: "",
  };
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

function paginaDoChat(mensagem) {
  if (mensagem.social === "conversa") {
    return mensagem.nome === "Carlos" ? { quantas: 2 } : { quantas: 1, x: 60, y: 35 };
  }
  if (mensagem.social === "caixa") {
    return { x: 300, y: 700 };
  }
  if (mensagem.social === "cabecalho") {
    return { nome: "Ana Souza", telefone: "", grupo: false, ambiguo: false, extra: "não vai" };
  }
  return {};
}

test("envio: anexa SÓ a entrada, clique e teclas confiáveis, Enter no fim e solta", async () => {
  const cenario = carregar({ abas: [DO_DONO], responderPagina: paginaDoChat, comCdp: true });
  const abrir = await pedir(cenario, {
    id: "d1",
    method: "social.abrirConversa",
    params: { rede: "whatsapp", nome: "Ana Souza" },
  });
  assert.deepEqual(abrir.result, { ambiguo: false });
  const cabecalho = await pedir(cenario, { id: "d2", method: "social.cabecalho", params: { rede: "whatsapp" } });
  assert.deepEqual(cabecalho.result, { nome: "Ana Souza", telefone: "", grupo: false, ambiguo: false });
  const digitar = await pedir(cenario, {
    id: "d3",
    method: "social.digitar",
    params: { rede: "whatsapp", texto: "oi!", atrasos: [120, 90, 300] },
  });
  assert.deepEqual(digitar.result, { digitadas: 3 });
  const enviar = await pedir(cenario, { id: "d4", method: "social.enviar", params: { rede: "whatsapp" } });
  assert.deepEqual(enviar.result, { enviado: true });

  const cdp = JSON.parse(JSON.stringify(cenario.estado.cdp));
  const metodos = cdp.map(([m]) => m);
  assert.deepEqual(cdp[0], ["attach", 3]);
  assert.equal(metodos.filter((m) => m === "attach").length, 1, "um anexo por envio");
  assert.equal(metodos.some((m) => /\.enable$/u.test(m)), false, "nenhum domínio ligado");
  assert.equal(metodos.at(-1), "detach", "solta no fim do envio");
  const teclas = cdp.filter(([m, p]) => m === "Input.dispatchKeyEvent" && p.type === "keyDown");
  assert.deepEqual(
    teclas.map(([, p]) => p.key),
    ["o", "i", "!", "Enter"],
    "uma tecla por caractere e o Enter só no fim",
  );
  const cliques = cdp.filter(([m, p]) => m === "Input.dispatchMouseEvent" && p.type === "mousePressed");
  assert.deepEqual(
    cliques.map(([, p]) => [p.x, p.y]),
    [
      [60, 35],
      [300, 700],
    ],
    "a conversa e depois a caixa de texto",
  );
});

test("envio: homônimo não abre, rede só leitura recusa, digitar sem conversa recusa", async () => {
  const cenario = carregar({ abas: [DO_DONO], responderPagina: paginaDoChat, comCdp: true });
  const homonimo = await pedir(cenario, {
    id: "d5",
    method: "social.abrirConversa",
    params: { rede: "whatsapp", nome: "Carlos" },
  });
  assert.deepEqual(homonimo.result, { ambiguo: true });
  assert.equal(cenario.estado.cdp.length, 0, "nem anexou");
  const insta = await pedir(cenario, { id: "d6", method: "social.enviar", params: { rede: "instagram" } });
  assert.equal(insta.error.codigo, "rede_sem_envio");
  const solto = await pedir(cenario, {
    id: "d7",
    method: "social.digitar",
    params: { rede: "whatsapp", texto: "oi", atrasos: [1, 1] },
  });
  assert.equal(solto.error.codigo, "sem_envio");
});

test("envio: no Firefox (sem CDP) não existe", async () => {
  const cenario = carregar({ abas: [DO_DONO], responderPagina: paginaDoChat, comCdp: false });
  const resposta = await pedir(cenario, {
    id: "d8",
    method: "social.abrirConversa",
    params: { rede: "whatsapp", nome: "Ana Souza" },
  });
  assert.equal(resposta.error.codigo, "sem_cdp_no_firefox");
});

test("social.soltar desanexa o que estiver anexado", async () => {
  const cenario = carregar({ abas: [DO_DONO], responderPagina: paginaDoChat, comCdp: true });
  await pedir(cenario, {
    id: "d9",
    method: "social.abrirConversa",
    params: { rede: "whatsapp", nome: "Ana Souza" },
  });
  const soltar = await pedir(cenario, { id: "d10", method: "social.soltar", params: { rede: "whatsapp" } });
  assert.deepEqual(soltar.result, { soltas: 1 });
  assert.deepEqual(JSON.parse(JSON.stringify(cenario.estado.cdp.at(-1))), ["detach", 3]);
});
