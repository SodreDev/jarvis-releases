/*
 * A única ponte da extensão é Native Messaging. Não há WebSocket, HTTP, porta TCP nem
 * mensagens externas: o navegador só aceita pedidos do host local cujo manifesto o fixou.
 */

const api = globalThis.browser ?? globalThis.chrome;
const NATIVE_HOST = "br.com.granafacil.jarvis";
const MAX_ID = 80;
const MAX_URL = 2_048;

let nativePort;

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
  try {
    return await api.tabs.sendMessage(tab.id, { comando, params });
  } catch {
    throw erro(
      "pagina_indisponivel",
      "a página ainda não está pronta ou não permite a extensão nesta URL",
    );
  }
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

function responder(mensagem) {
  if (nativePort) {
    nativePort.postMessage(mensagem);
  }
}

function ligarAoHost() {
  if (nativePort) {
    return;
  }
  try {
    nativePort = api.runtime.connectNative(NATIVE_HOST);
  } catch (causa) {
    console.warn("Jarvis: host nativo indisponível", causa);
    nativePort = undefined;
    return;
  }
  nativePort.onMessage.addListener((pedido) => {
    receberDoHost(pedido).then(responder).catch((causa) => {
      const id = typeof pedido?.id === "string" ? pedido.id : null;
      const detalhe = comoObjeto(causa);
      responder({
        id,
        ok: false,
        error: {
          codigo: typeof detalhe.codigo === "string" ? detalhe.codigo : "falha",
          mensagem: typeof detalhe.mensagem === "string" ? detalhe.mensagem : "falha na extensão",
        },
      });
    });
  });
  nativePort.onDisconnect.addListener(() => {
    const motivo = api.runtime.lastError?.message;
    if (motivo) {
      console.warn("Jarvis: host nativo desconectou", motivo);
    }
    nativePort = undefined;
  });
}

api.runtime.onStartup.addListener(ligarAoHost);
api.runtime.onInstalled.addListener(ligarAoHost);
ligarAoHost();
