/*
 * A única ponte da extensão é Native Messaging. Não há WebSocket, HTTP, porta TCP nem
 * mensagens externas: o navegador só aceita pedidos do host local cujo manifesto o fixou.
 */

const api = globalThis.browser ?? globalThis.chrome;
const NATIVE_HOST = "br.com.granafacil.jarvis";
const MAX_ID = 80;
const MAX_URL = 2_048;
const RECONNECT_BASE_MS = 250;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_JITTER = 0.15;
const RECONNECT_STABLE_MS = 60_000;

let nativePort;
let reconnectTimer;
let reconnectAttempt = 0;

function erro(codigo, mensagem) {
  return { codigo, mensagem };
}

function comoObjeto(valor) {
  return valor !== null && typeof valor === "object" && !Array.isArray(valor) ? valor : {};
}

function identificar(valor) {
  if (typeof valor !== "string" || !/^[A-Za-z0-9_.:-]{1,80}$/.test(valor)) {
    throw erro("pedido_invalido", "id de pedido ausente ou inválido");
  }
  return valor;
}

function urlHttp(bruta) {
  if (typeof bruta !== "string" || bruta.length > MAX_URL) {
    throw erro("url_invalida", "URL ausente ou longa demais");
  }
  let url;
  try {
    url = new URL(bruta);
  } catch {
    throw erro("url_invalida", "URL inválida");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw erro("url_invalida", "a extensão só navega para http ou https");
  }
  if (url.username || url.password) {
    throw erro("url_invalida", "URL com credencial embutida é recusada");
  }
  return url.href;
}

function resumoDaAba(tab) {
  return {
    id: tab.id,
    janelaId: tab.windowId,
    ativa: Boolean(tab.active),
    url: tab.url ?? "",
    titulo: tab.title ?? "",
  };
}

async function abaAtiva() {
  const tabs = await api.tabs.query({ active: true, currentWindow: true });
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number") {
    throw erro("sem_aba", "não há aba ativa na janela atual");
  }
  return tab;
}

async function abaDoPedido(params) {
  if (typeof params.tabId === "number" && Number.isInteger(params.tabId) && params.tabId >= 0) {
    return api.tabs.get(params.tabId);
  }
  return abaAtiva();
}

async function mensagemDaPagina(params, comando) {
  const tab = await abaDoPedido(params);
  if (typeof tab.id !== "number") {
    throw erro("sem_aba", "a aba escolhida não tem identificador");
  }
  let resposta;
  try {
    resposta = await api.tabs.sendMessage(tab.id, { comando, params });
  } catch {
    throw erro(
      "pagina_indisponivel",
      "a página não está pronta ou não aceita a extensão nesta URL; se a aba já estava aberta " +
        "quando a extensão foi carregada, recarregue a aba",
    );
  }
  // O conteúdo responde `{ ok, result }` ou `{ ok: false, error }`. Ao host vai só o `result` (ou
  // o erro dele): repassar o envelope inteiro o aninhava dentro de outro `result`, e o Jarvis lia
  // página vazia e um alvo sem campo nem formulário — o risco do clique ficava cego.
  const corpo = comoObjeto(resposta);
  if (corpo.ok === true) {
    return comoObjeto(corpo.result);
  }
  const falha = comoObjeto(corpo.error);
  throw erro(
    typeof falha.codigo === "string" ? falha.codigo : "pagina_indisponivel",
    typeof falha.mensagem === "string" ? falha.mensagem : "a página não respondeu à extensão",
  );
}

async function abrirOuReutilizar(params) {
  const url = urlHttp(params.url);
  if (params.reutilizar === true) {
    const existente = (await api.tabs.query({})).find((tab) => tab.url === url);
    if (existente && typeof existente.id === "number") {
      await api.windows.update(existente.windowId, { focused: true });
      const ativada = await api.tabs.update(existente.id, { active: true });
      return { reutilizada: true, aba: resumoDaAba(ativada) };
    }
  }
  const criada = await api.tabs.create({ url, active: true });
  return { reutilizada: false, aba: resumoDaAba(criada) };
}

async function executar(method, params) {
  switch (method) {
    case "tabs.list": {
      const tabs = await api.tabs.query({});
      return { abas: tabs.map(resumoDaAba) };
    }
    case "tabs.current":
      return { aba: resumoDaAba(await abaDoPedido(params)) };
    case "tabs.active": {
      const tab = await abaAtiva();
      return { aba: resumoDaAba(tab), pagina: await mensagemDaPagina({ tabId: tab.id }, "ler") };
    }
    case "tabs.open":
      return abrirOuReutilizar(params);
    case "tabs.navigate": {
      const tab = await abaDoPedido(params);
      if (typeof tab.id !== "number") {
        throw erro("sem_aba", "a aba escolhida não tem identificador");
      }
      const atualizada = await api.tabs.update(tab.id, { url: urlHttp(params.url), active: true });
      return { aba: resumoDaAba(atualizada) };
    }
    case "page.read":
      return mensagemDaPagina(params, "ler");
    case "page.inspect":
      return mensagemDaPagina(params, "inspecionar");
    case "page.click":
      return mensagemDaPagina(params, "clicar");
    case "page.type":
      return mensagemDaPagina(params, "digitar");
    case "page.scroll":
      return mensagemDaPagina(params, "rolar");
    default:
      throw erro("metodo_invalido", "método não autorizado para a extensão");
  }
}

async function receberDoHost(bruto) {
  const pedido = comoObjeto(bruto);
  const id = identificar(pedido.id);
  if (typeof pedido.method !== "string" || pedido.method.length > MAX_ID) {
    throw erro("pedido_invalido", "método ausente ou inválido");
  }
  return { id, ok: true, result: await executar(pedido.method, comoObjeto(pedido.params)) };
}

function detalheDaFalha(causa) {
  if (causa && typeof causa.message === "string" && causa.message) {
    return causa.message;
  }
  return String(causa);
}

function atrasoDaReconexao(tentativa) {
  const expoente = Math.min(tentativa, 30);
  const atrasoBase = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** expoente);
  const fator = 1 - RECONNECT_JITTER + Math.random() * RECONNECT_JITTER * 2;
  return Math.round(Math.min(RECONNECT_MAX_MS, atrasoBase * fator));
}

function agendarReconexao(motivo) {
  if (nativePort || reconnectTimer !== undefined) {
    return;
  }
  const tentativa = reconnectAttempt;
  const atrasoMs = atrasoDaReconexao(tentativa);
  reconnectAttempt = Math.min(reconnectAttempt + 1, 30);
  console.warn("Jarvis: host nativo desconectou; reconexão agendada", {
    motivo,
    tentativa: tentativa + 1,
    atrasoMs,
  });
  // Um único timer one-shot: sem heartbeat, alarm ou polling para manter o worker acordado.
  reconnectTimer = setTimeout(() => {
    reconnectTimer = undefined;
    ligarAoHost();
  }, atrasoMs);
}

function responder(porta, mensagem) {
  if (porta !== nativePort) {
    return;
  }
  try {
    porta.postMessage(mensagem);
  } catch (causa) {
    console.warn("Jarvis: não foi possível responder ao host nativo", detalheDaFalha(causa));
  }
}

function ligarAoHost() {
  if (nativePort || reconnectTimer !== undefined) {
    return;
  }
  let porta;
  try {
    porta = api.runtime.connectNative(NATIVE_HOST);
  } catch (causa) {
    agendarReconexao(detalheDaFalha(causa));
    return;
  }
  nativePort = porta;
  const conectadaEm = Date.now();
  porta.onMessage.addListener((pedido) => {
    if (porta !== nativePort) {
      return;
    }
    reconnectAttempt = 0;
    receberDoHost(pedido)
      .then((mensagem) => responder(porta, mensagem))
      .catch((causa) => {
        const id = typeof pedido?.id === "string" ? pedido.id : null;
        const detalhe = comoObjeto(causa);
        responder(porta, {
          id,
          ok: false,
          error: {
            codigo: typeof detalhe.codigo === "string" ? detalhe.codigo : "falha",
            mensagem:
              typeof detalhe.mensagem === "string" ? detalhe.mensagem : "falha na extensão",
          },
        });
      });
  });
  porta.onDisconnect.addListener(() => {
    // O Chromium põe o motivo em `runtime.lastError`; o Firefox, em `porta.error`.
    const motivo =
      api.runtime.lastError?.message ?? porta.error?.message ?? "runtime.lastError sem detalhe";
    if (porta !== nativePort) {
      return;
    }
    nativePort = undefined;
    if (Date.now() - conectadaEm >= RECONNECT_STABLE_MS) {
      reconnectAttempt = 0;
    }
    agendarReconexao(motivo);
  });
}

api.runtime.onStartup.addListener(ligarAoHost);
api.runtime.onInstalled.addListener(ligarAoHost);
ligarAoHost();
