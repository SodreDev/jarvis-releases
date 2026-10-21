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
const QUALIDADE_DA_CAPTURA = 60;
const ESPERA_DA_PAGINA_MS = 15_000;
const TENTATIVAS_DO_CONTEUDO = 10;
const INTERVALO_DO_CONTEUDO_MS = 300;
const MAX_CAPTURA = 6 * 1024 * 1024;
// Navegar só "deu certo" quando a aba saiu do lugar, carregou e o conteúdo da extensão respondeu
// na página nova (auditoria de 2026-10-21: o `tabs.update` responde na hora, com a URL de ANTES).
const COMECO_DA_NAVEGACAO_MS = 4_000;
const ESPERA_DA_NAVEGACAO_MS = 12_000;
const TENTATIVAS_DO_ESTADO = 8;
const INTERVALO_DO_ESTADO_MS = 250;
const PAGINA_DA_JANELA = "janela.html";
const NORMAIS = { windowTypes: ["normal"] };

let nativePort;
let reconnectTimer;
let reconnectAttempt = 0;
let janelaDoJarvisId;
let janelaDoDonoId;

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
    janelaDoJarvis: typeof tab.windowId === "number" && tab.windowId === janelaDoJarvisId,
  };
}

function pausa(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function idDaJanelaDoJarvis() {
  // Lembrada enquanto o fundo vive. O service worker dorme e reinicia sem a memória: aí a janela
  // é achada pela página que a segura aberta — antes, o Jarvis esquecia a dele, a tratava como a
  // do dono (a "aba atual" caía nela) e criava outra (auditoria de 2026-10-21).
  if (typeof janelaDoJarvisId === "number") {
    try {
      await api.windows.get(janelaDoJarvisId);
      return janelaDoJarvisId;
    } catch {
      janelaDoJarvisId = undefined;
    }
  }
  const pagina = api.runtime.getURL(PAGINA_DA_JANELA);
  const segura = (await api.tabs.query({})).find((tab) => tab.url === pagina);
  janelaDoJarvisId = typeof segura?.windowId === "number" ? segura.windowId : undefined;
  return janelaDoJarvisId;
}

async function janelaDoDono() {
  // A janela normal em que o dono esteve por último — nunca a do Jarvis, um popup, um app ou o
  // DevTools (a "aba atual" do `currentWindow` podia cair num deles).
  const jarvis = await idDaJanelaDoJarvis();
  try {
    const janela = await api.windows.getLastFocused(NORMAIS);
    if (typeof janela?.id === "number" && janela.id !== jarvis) {
      janelaDoDonoId = janela.id;
      return janela.id;
    }
  } catch {
    // sem janela normal em foco: vale a última que se viu do dono
  }
  if (typeof janelaDoDonoId === "number" && janelaDoDonoId !== jarvis) {
    try {
      await api.windows.get(janelaDoDonoId);
      return janelaDoDonoId;
    } catch {
      janelaDoDonoId = undefined;
    }
  }
  const outra = (await api.windows.getAll(NORMAIS)).find((janela) => janela.id !== jarvis);
  return typeof outra?.id === "number" ? outra.id : undefined;
}

async function abaAtiva() {
  // A janela do Jarvis nunca é "a aba atual" do dono (ADR-0036).
  const janelaId = await janelaDoDono();
  const tabs =
    typeof janelaId === "number" ? await api.tabs.query({ active: true, windowId: janelaId }) : [];
  const tab = tabs[0];
  if (!tab || typeof tab.id !== "number") {
    throw erro("sem_aba", "não há aba ativa numa janela do dono");
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

async function janelaEmFoco() {
  try {
    const janela = await api.windows.getLastFocused(NORMAIS);
    const id = typeof janela?.id === "number" ? janela.id : undefined;
    if (typeof id === "number" && id !== janelaDoJarvisId) {
      janelaDoDonoId = id;
    }
    return id;
  } catch {
    return undefined;
  }
}

async function devolverOFoco(doDono) {
  // O foco só muda se o objetivo exigir — e criar a janela do Jarvis não exige (ADR-0036). O
  // Firefox pode ignorar `focused: false`: aí o foco volta para onde o dono estava.
  if (typeof doDono !== "number") {
    return;
  }
  const agora = await janelaEmFoco();
  if (agora !== doDono) {
    await api.windows.update(doDono, { focused: true }).catch(() => undefined);
  }
}

async function janelaDoJarvis() {
  // A janela própria do Jarvis, atrás das do dono: lembrada (ou achada) e refeita se o dono a
  // fechou. A página dela (`janela.html`) a segura aberta entre um trabalho e outro, diz ao dono o
  // que ela é e é por onde o fundo a reconhece depois de reiniciar.
  const existente = await idDaJanelaDoJarvis();
  if (typeof existente === "number") {
    return existente;
  }
  const doDono = await janelaEmFoco();
  const criada = await api.windows.create({
    url: api.runtime.getURL(PAGINA_DA_JANELA),
    focused: false,
    type: "normal",
  });
  janelaDoJarvisId = criada.id;
  await devolverOFoco(doDono);
  return janelaDoJarvisId;
}

function vigiarNavegacao(tabId) {
  // Registrado ANTES de mandar navegar (o "loading" pode chegar antes de o pedido voltar). A aba
  // tem de SAIR do lugar (loading, ou URL nova) e depois terminar; se ela nem começa a sair, algo a
  // segurou (a página pediu para confirmar a saída, o endereço foi recusado).
  const vistos = new Map();
  let alvo = tabId;
  let feito = false;
  let resolver;
  const promessa = new Promise((resolve) => {
    resolver = resolve;
  });
  const estadoDe = (id) => vistos.get(id) ?? { comecou: false, terminou: false };
  const terminar = () => {
    if (feito) {
      return;
    }
    feito = true;
    clearTimeout(limite);
    clearTimeout(inicio);
    api.tabs.onUpdated.removeListener(ouvir);
    api.tabs.onRemoved?.removeListener(sumiu);
    resolver(estadoDe(alvo));
  };
  function ouvir(id, mudanca, tab) {
    const estado = { ...estadoDe(id) };
    const urlNova = typeof mudanca?.url === "string" && /^https?:/u.test(mudanca.url);
    if (mudanca?.status === "loading" || urlNova) {
      estado.comecou = true;
    }
    // Navegação dentro do mesmo documento (só o #) muda a URL sem passar por "loading".
    if (estado.comecou && (mudanca?.status === "complete" || (urlNova && tab?.status === "complete"))) {
      estado.terminou = true;
    }
    vistos.set(id, estado);
    if (id === alvo && estado.terminou) {
      terminar();
    }
  }
  function sumiu(id) {
    if (id === alvo) {
      terminar();
    }
  }
  api.tabs.onUpdated.addListener(ouvir);
  api.tabs.onRemoved?.addListener(sumiu);
  const limite = setTimeout(terminar, ESPERA_DA_NAVEGACAO_MS);
  const inicio = setTimeout(() => {
    if (!estadoDe(alvo).comecou) {
      terminar();
    }
  }, COMECO_DA_NAVEGACAO_MS);
  return {
    promessa,
    definir(id) {
      // `tabs.create`: o id só existe depois que a aba nasce.
      alvo = id;
      if (estadoDe(id).terminou) {
        terminar();
      }
    },
    cancelar: terminar,
  };
}

async function estadoDaPagina(tabId) {
  // O conteúdo da extensão responde na página NOVA: ela abriu e é página de verdade. Página de
  // erro do navegador (sem internet, endereço que não existe) não tem o conteúdo e não responde.
  for (let tentativa = 0; tentativa < TENTATIVAS_DO_ESTADO; tentativa += 1) {
    try {
      return await mensagemDaPagina({ tabId }, "estado");
    } catch {
      await pausa(INTERVALO_DO_ESTADO_MS);
    }
  }
  return null;
}

async function visibilidade(tab) {
  // À vista = a aba ativa da janela que está na frente, e a janela não é a do Jarvis.
  let naFrente;
  try {
    naFrente = await api.windows.getLastFocused(NORMAIS);
  } catch {
    naFrente = undefined;
  }
  const doJarvis = typeof tab.windowId === "number" && tab.windowId === janelaDoJarvisId;
  const janelaNaFrente = naFrente?.id === tab.windowId && naFrente?.focused !== false;
  return {
    janela: doJarvis ? "jarvis" : "dono",
    visivel: Boolean(tab.active) && janelaNaFrente && !doJarvis,
  };
}

async function conferido(tabId, vigia) {
  const { comecou, terminou } = await vigia.promessa;
  let final;
  try {
    final = await api.tabs.get(tabId);
  } catch {
    throw erro("sem_aba", "a aba fechou antes de a página abrir");
  }
  const pagina = terminou ? await estadoDaPagina(tabId) : null;
  return {
    aba: resumoDaAba(final),
    comecou,
    carregou: terminou,
    pagina,
    ...(await visibilidade(final)),
  };
}

async function navegarEConferir(tabId, url) {
  const vigia = vigiarNavegacao(tabId);
  try {
    // Sem `active: true`: navegar a aba não a traz para a frente (ADR-0036).
    await api.tabs.update(tabId, { url });
  } catch (causa) {
    vigia.cancelar();
    throw causa;
  }
  return conferido(tabId, vigia);
}

async function criarEConferir(opcoes) {
  const vigia = vigiarNavegacao(undefined);
  let criada;
  try {
    criada = await api.tabs.create(opcoes);
  } catch (causa) {
    vigia.cancelar();
    throw causa;
  }
  vigia.definir(criada.id);
  return conferido(criada.id, vigia);
}

async function abrirNaJanelaDoJarvis(url) {
  const doDono = await janelaEmFoco();
  const janelaId = await janelaDoJarvis();
  const resultado = await criarEConferir({ windowId: janelaId, url, active: true });
  await devolverOFoco(doDono);
  return { reutilizada: false, ...resultado, janela: "jarvis", visivel: false };
}

async function mostrarAba(params) {
  // Pedido de "abre/mostra para mim" (o Jarvis decide pela fala do dono): a aba termina à vista.
  // Se ela está na janela do Jarvis, vai para a janela do dono — é lá que ele olha.
  let tab = await abaDoPedido(params);
  const jarvis = await idDaJanelaDoJarvis();
  if (typeof jarvis === "number" && tab.windowId === jarvis) {
    const dono = await janelaDoDono();
    if (typeof dono === "number") {
      const movida = await api.tabs.move(tab.id, { windowId: dono, index: -1 });
      tab = (Array.isArray(movida) ? movida[0] : movida) ?? tab;
    }
  }
  await api.tabs.update(tab.id, { active: true });
  const atual = await api.tabs.get(tab.id);
  await api.windows.update(atual.windowId, { focused: true }).catch(() => undefined);
  const final = await api.tabs.get(tab.id);
  return { aba: resumoDaAba(final), ...(await visibilidade(final)) };
}

async function focoAtual() {
  // Para provar que o trabalho do Jarvis não mexeu no foco do dono (e para o diagnóstico).
  await idDaJanelaDoJarvis();
  const janelaId = await janelaEmFoco();
  const ativas =
    typeof janelaId === "number" ? await api.tabs.query({ active: true, windowId: janelaId }) : [];
  return {
    janelaId: janelaId ?? null,
    abaAtivaId: typeof ativas[0]?.id === "number" ? ativas[0].id : null,
    janelaDoJarvisId: typeof janelaDoJarvisId === "number" ? janelaDoJarvisId : null,
    janelaDoDonoId: typeof janelaDoDonoId === "number" ? janelaDoDonoId : null,
  };
}

async function capturar(params) {
  // A tela da aba e o mapa do mesmo instante (ADR-0032): as caixas dos elementos são desta imagem.
  const tab = await abaDoPedido(params);
  if (typeof tab.id !== "number") {
    throw erro("sem_aba", "a aba escolhida não tem identificador");
  }
  // A permissão `<all_urls>` existe só para a captura (o Chromium e o Firefox a exigem); a tela
  // que sai daqui é sempre de página http ou https, como o resto da extensão.
  let endereco = null;
  try {
    endereco = new URL(tab.url ?? "");
  } catch {
    endereco = null;
  }
  if (!endereco || (endereco.protocol !== "http:" && endereco.protocol !== "https:")) {
    throw erro("aba_nao_http", "a tela só é capturada em página http ou https");
  }
  const opcoes = { format: "jpeg", quality: QUALIDADE_DA_CAPTURA };
  let imagem;
  try {
    if (typeof api.tabs.captureTab === "function") {
      // Firefox: captura a aba pedida mesmo que ela não esteja à vista, sem mexer no foco do dono.
      imagem = await api.tabs.captureTab(tab.id, opcoes);
    } else {
      if (!tab.active) {
        throw erro(
          "aba_escondida",
          "no Chromium a captura é da aba à vista na janela dela; esta aba está atrás de outra",
        );
      }
      imagem = await api.tabs.captureVisibleTab(tab.windowId, opcoes);
    }
  } catch (causa) {
    if (causa && typeof causa.codigo === "string") {
      throw causa;
    }
    throw erro("captura_negada", `o navegador não deixou capturar a aba: ${detalheDaFalha(causa)}`);
  }
  if (typeof imagem !== "string" || imagem.length > MAX_CAPTURA) {
    throw erro("captura_invalida", "a captura não veio ou passou do tamanho");
  }
  const mapa = await mensagemDaPagina({ tabId: tab.id }, "mapear");
  return { imagem, mapa };
}

function esperarCarregar(tabId) {
  // A aba terminou de carregar (`status: complete`), ou o prazo acabou.
  return new Promise((resolve, reject) => {
    let feito = false;
    const terminar = (falha) => {
      if (feito) {
        return;
      }
      feito = true;
      clearTimeout(limite);
      api.tabs.onUpdated.removeListener(ouvir);
      if (falha) {
        reject(falha);
      } else {
        resolve();
      }
    };
    const limite = setTimeout(
      () => terminar(erro("pagina_lenta", "a página não terminou de carregar a tempo")),
      ESPERA_DA_PAGINA_MS,
    );
    function ouvir(id, mudanca) {
      if (id === tabId && mudanca.status === "complete") {
        terminar();
      }
    }
    api.tabs.onUpdated.addListener(ouvir);
    api.tabs.get(tabId).then(
      (tab) => tab.status === "complete" && terminar(),
      () => terminar(erro("sem_aba", "a aba de fundo sumiu antes de carregar")),
    );
  });
}

async function lerEmSegundoPlano(params) {
  // A busca na web pelo navegador do dono (ADR-0033): uma aba de fundo, que não ganha o foco nem
  // troca a aba que ele está vendo, lida e fechada no fim — inclusive quando algo falha.
  const url = urlHttp(params.url);
  // Na janela do Jarvis (ADR-0036), não na do dono: nem a aba de fundo aparece para ele.
  const doDono = await janelaEmFoco();
  const janelaId = await janelaDoJarvis();
  const aba = await api.tabs.create({ windowId: janelaId, url, active: true });
  await devolverOFoco(doDono);
  try {
    await esperarCarregar(aba.id);
    let ultima;
    for (let tentativa = 0; tentativa < TENTATIVAS_DO_CONTEUDO; tentativa += 1) {
      try {
        const pagina = await mensagemDaPagina({ tabId: aba.id }, "ler");
        return { pagina };
      } catch (causa) {
        // O conteúdo da extensão pode registrar-se um pouco depois do `complete`.
        ultima = causa;
        await new Promise((resolve) => setTimeout(resolve, INTERVALO_DO_CONTEUDO_MS));
      }
    }
    throw ultima;
  } finally {
    await api.tabs.remove(aba.id).catch(() => undefined);
  }
}

async function abrirAba(params) {
  const url = urlHttp(params.url);
  if (params.janela === "jarvis") {
    return abrirNaJanelaDoJarvis(url);
  }
  // Na janela do dono, dita pelo id: sem ele a aba nova nascia na "janela atual" do navegador,
  // que pode ser a do Jarvis.
  const dono = await janelaDoDono();
  const resultado = await criarEConferir({
    url,
    active: true,
    ...(typeof dono === "number" ? { windowId: dono } : {}),
  });
  return { reutilizada: false, ...resultado };
}

async function executar(method, params) {
  switch (method) {
    case "windows.focused":
      return focoAtual();
    case "tabs.list": {
      await idDaJanelaDoJarvis(); // para cada aba dizer se é da janela do Jarvis
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
      return abrirAba(params);
    case "tabs.show":
      return mostrarAba(params);
    case "tabs.navigate": {
      const tab = await abaDoPedido(params);
      if (typeof tab.id !== "number") {
        throw erro("sem_aba", "a aba escolhida não tem identificador");
      }
      await idDaJanelaDoJarvis();
      return navegarEConferir(tab.id, urlHttp(params.url));
    }
    case "page.read":
      return mensagemDaPagina(params, "ler");
    case "page.inspect":
      return mensagemDaPagina(params, "inspecionar");
    case "page.map":
      return mensagemDaPagina(params, "mapear");
    case "page.act":
      return mensagemDaPagina(params, "acionar");
    case "page.capture":
      return capturar(params);
    case "page.readUrl":
      return lerEmSegundoPlano(params);
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
        // Erro do próprio navegador (sem o nosso código) chega com a mensagem dele: "falha na
        // extensão" sozinha escondia, por exemplo, a permissão que faltava.
        const nativa = causa instanceof Error && causa.message ? causa.message : "";
        responder(porta, {
          id,
          ok: false,
          error: {
            codigo: typeof detalhe.codigo === "string" ? detalhe.codigo : "falha",
            mensagem:
              typeof detalhe.mensagem === "string"
                ? detalhe.mensagem
                : nativa || "falha na extensão",
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
