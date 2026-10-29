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
// A janela própria do Jarvis (ADR-0036) ficou só para a automação de redes sociais, e-mail e agenda,
// que ainda não existe (dono, 2026-10-21: ela parecia outra instância do Brave, e o vídeo abriu nela).
// Sem este modo no pedido a extensão nunca cria janela: o trabalho que o dono não pediu para ver é
// uma aba em segundo plano NA JANELA DELE, sem `active` e sem mexer no foco.
const MODO_AUTOMACAO_SOCIAL = "automacao_social";
// O controle (ADR-0027, regra 4): enquanto o Jarvis age numa aba, ela mostra a faixa "no controle"
// e o botão da extensão fica com o selo. Cada pedido traz a concessão do objetivo que o fez.
const COM_CONTROLE = new Set([
  "tabs.navigate",
  "tabs.open",
  "tabs.show",
  "page.read",
  "page.map",
  "page.capture",
  "page.inspect",
  "page.click",
  "page.type",
  "page.act",
  "page.scroll",
  "page.console",
  "page.network",
  "page.eval",
  "page.gesture",
]);
const OCIOSO_DO_CONTROLE_MS = 30_000;
const MAX_REVOGADAS = 32;
const SELO = "IA";
const COR_DO_SELO = "#b45309";

let nativePort;
let reconnectTimer;
let reconnectAttempt = 0;
let janelaDoJarvisId;
let janelaDoDonoId;
const controladas = new Map(); // tabId → concessão
const usoDaConcessao = new Map(); // concessão → último pedido (ms)
const revogadas = [];
let timerDoControle;

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
    ultimoAcesso: typeof tab.lastAccessed === "number" ? Math.round(tab.lastAccessed) : 0,
  };
}

// --- o controle: faixa, selo e PARAR -------------------------------------------------------------
function concessaoDe(params) {
  const valor = params.controle;
  return typeof valor === "string" && /^[a-z0-9]{8,32}$/u.test(valor) ? valor : undefined;
}

function conferirConcessao(params) {
  // Depois do PARAR, nada do que vier daquela concessão age — nem um pedido que já estava no ar.
  const concessao = concessaoDe(params);
  if (concessao && revogadas.includes(concessao)) {
    throw erro(
      "parado_pelo_dono",
      "o dono apertou parar no navegador: o Jarvis soltou as abas e não age mais neste pedido",
    );
  }
  return concessao;
}

function avisarAba(tabId, ligado) {
  // A faixa da página. Página sem o conteúdo (interna, de erro): a faixa vem quando ela carregar,
  // porque o conteúdo pergunta ao nascer.
  Promise.resolve()
    .then(() => api.tabs.sendMessage(tabId, { indicador: { ligado } }))
    .catch(() => undefined);
}

async function atualizarSelo() {
  const acao = api.action ?? api.browserAction;
  if (!acao) {
    return;
  }
  const quantas = controladas.size;
  try {
    await acao.setBadgeText({ text: quantas ? SELO : "" });
    if (quantas) {
      await acao.setBadgeBackgroundColor({ color: COR_DO_SELO });
    }
    await acao.setTitle({
      title: quantas
        ? `Jarvis no controle de ${quantas === 1 ? "uma aba" : `${quantas} abas`} — clique para parar`
        : "Jarvis — ponte local, sem controlar nenhuma aba",
    });
  } catch {
    // o selo é aviso a mais: a faixa da página é o principal
  }
}

function agendarOcioso() {
  // O Jarvis renova a concessão enquanto o objetivo dura; se ele sumir (caiu, fechou), a faixa
  // não fica para sempre.
  clearTimeout(timerDoControle);
  if (!usoDaConcessao.size) {
    return;
  }
  timerDoControle = setTimeout(() => {
    const agora = Date.now();
    for (const [concessao, uso] of [...usoDaConcessao]) {
      if (agora - uso >= OCIOSO_DO_CONTROLE_MS) {
        soltarConcessao(concessao);
      }
    }
    agendarOcioso();
  }, OCIOSO_DO_CONTROLE_MS);
}

function assumir(tabId, concessao) {
  if (!concessao || typeof tabId !== "number") {
    return;
  }
  usoDaConcessao.set(concessao, Date.now());
  const nova = controladas.get(tabId) !== concessao;
  controladas.set(tabId, concessao);
  agendarOcioso();
  if (nova) {
    avisarAba(tabId, true);
    void atualizarSelo();
  }
}

function soltarConcessao(concessao) {
  let soltas = 0;
  for (const [tabId, dela] of [...controladas]) {
    if (dela === concessao) {
      controladas.delete(tabId);
      avisarAba(tabId, false);
      void desanexarCdp(tabId); // soltar o controle da aba desanexa o depurador (ADR-0051)
      soltas += 1;
    }
  }
  usoDaConcessao.delete(concessao);
  agendarOcioso();
  void atualizarSelo();
  return soltas;
}

function revogarTudo() {
  const concessoes = [...new Set([...controladas.values(), ...usoDaConcessao.keys()])];
  for (const concessao of concessoes) {
    soltarConcessao(concessao);
    if (!revogadas.includes(concessao)) {
      revogadas.push(concessao);
    }
  }
  revogadas.splice(0, Math.max(0, revogadas.length - MAX_REVOGADAS));
  return concessoes;
}

function pararPeloDono(origem) {
  // O dono apertou PARAR (na faixa ou no botão da extensão): solta na hora, revoga, e avisa o
  // Jarvis pelo host — é por ali que o turno e a tarefa param.
  const concessoes = revogarTudo();
  if (nativePort) {
    try {
      nativePort.postMessage({ evento: "parar", concessoes, origem });
    } catch (causa) {
      console.warn("Jarvis: não deu para avisar o PARAR ao host", detalheDaFalha(causa));
    }
  }
  return concessoes;
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

function automacaoSocial(params) {
  return params.modo === MODO_AUTOMACAO_SOCIAL;
}

async function abaDoPedido(params) {
  if (typeof params.tabId === "number" && Number.isInteger(params.tabId) && params.tabId >= 0) {
    try {
      return await api.tabs.get(params.tabId);
    } catch {
      // O "No tab with id" do navegador virava "falha" crua, e o modelo largava a extensão para
      // abrir o navegador pela linha de comando (o caso do dono, 2026-10-21).
      throw erro(
        "sem_aba",
        "essa aba não existe mais (foi fechada ou o id é de outra sessão): veja as abas abertas",
      );
    }
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
  // A janela própria do Jarvis, atrás das do dono — só no modo `automacao_social` (quem chama aqui
  // é só o caminho desse modo): lembrada (ou achada) e refeita se o dono a fechou. A página dela
  // (`janela.html`) a segura aberta entre um trabalho e outro, diz ao dono o que ela é e é por onde
  // o fundo a reconhece depois de reiniciar.
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

async function criarEConferir(opcoes, concessao) {
  const vigia = vigiarNavegacao(undefined);
  let criada;
  try {
    criada = await api.tabs.create(opcoes);
  } catch (causa) {
    vigia.cancelar();
    throw causa;
  }
  vigia.definir(criada.id);
  assumir(criada.id, concessao); // a faixa já na página que nasce
  return conferido(criada.id, vigia);
}

async function abrirNaJanelaDoJarvis(url, concessao) {
  const doDono = await janelaEmFoco();
  const janelaId = await janelaDoJarvis();
  const resultado = await criarEConferir({ windowId: janelaId, url, active: true }, concessao);
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
  // Para provar que o trabalho do Jarvis não mexeu no foco do dono nem abriu janela (e para o
  // diagnóstico): `janelas` conta as janelas normais e popups que o navegador tem agora.
  await idDaJanelaDoJarvis();
  const janelaId = await janelaEmFoco();
  const ativas =
    typeof janelaId === "number" ? await api.tabs.query({ active: true, windowId: janelaId }) : [];
  return {
    janelaId: janelaId ?? null,
    abaAtivaId: typeof ativas[0]?.id === "number" ? ativas[0].id : null,
    janelaDoJarvisId: typeof janelaDoJarvisId === "number" ? janelaDoJarvisId : null,
    janelaDoDonoId: typeof janelaDoDonoId === "number" ? janelaDoDonoId : null,
    janelas: (await api.windows.getAll({})).length,
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
  // A busca na web pelo navegador do dono (ADR-0033): uma aba em segundo plano NA JANELA DELE — sem
  // `active`, então ela não ganha o foco nem troca a aba que ele está vendo —, lida e fechada no
  // fim, inclusive quando algo falha. Antes ela nascia na janela do Jarvis, que aparecia para o
  // dono como outra instância do navegador (ADR-0036, emenda de 2026-10-21); a janela própria fica
  // só para a automação social.
  const url = urlHttp(params.url);
  let aba;
  if (automacaoSocial(params)) {
    const doDono = await janelaEmFoco();
    const janelaId = await janelaDoJarvis();
    aba = await api.tabs.create({ windowId: janelaId, url, active: true });
    await devolverOFoco(doDono);
  } else {
    const dono = await janelaDoDono();
    aba = await api.tabs.create({
      url,
      active: false,
      ...(typeof dono === "number" ? { windowId: dono } : {}),
    });
  }
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

async function abrirAba(params, concessao) {
  const url = urlHttp(params.url);
  if (automacaoSocial(params)) {
    return abrirNaJanelaDoJarvis(url, concessao);
  }
  // Na janela do dono, dita pelo id: sem ele a aba nova nascia na "janela atual" do navegador,
  // que pode ser outra. Com `fundo` (o trabalho que o dono não pediu para ver), a aba nasce em
  // segundo plano: sem `active`, a aba que ele está vendo continua a mesma e o foco não muda.
  const dono = await janelaDoDono();
  const resultado = await criarEConferir(
    {
      url,
      active: params.fundo !== true,
      ...(typeof dono === "number" ? { windowId: dono } : {}),
    },
    concessao,
  );
  return { reutilizada: false, ...resultado };
}

function estadoDoControle() {
  return {
    abas: [...controladas].map(([tabId, concessao]) => ({ tabId, concessao })),
    concessoes: [...usoDaConcessao.keys()],
    revogadas: revogadas.length,
  };
}

// --- navegador por CDP (ADR-0051): console, rede, avaliar JS no mundo isolado e gestos físicos ---
const CDP_VERSAO = "1.3";
const MAX_LOGS = 200;
const MAX_REDE = 200;
const PRAZO_DO_EVAL_MS = 5_000;
// tabId → {logs, rede}. Só existe enquanto o Jarvis está anexado; soltar/parar desanexa.
const cdpPorAba = new Map();
let cdpOuvindo = false;

function temCdp() {
  // O Firefox não dá o CDP pela WebExtensions API (ADR-0051): lá `api.debugger` não existe, e
  // avaliar cai no `chrome.scripting`; console, rede e gesto por CDP não existem.
  return Boolean(api.debugger && typeof api.debugger.attach === "function");
}

function textoDosArgs(args) {
  return (args ?? [])
    .map((a) => (a && a.value !== undefined ? String(a.value) : String(a?.description ?? "")))
    .join(" ")
    .slice(0, 2_000);
}

function ouvirCdp() {
  if (cdpOuvindo || !temCdp()) {
    return;
  }
  cdpOuvindo = true;
  api.debugger.onEvent.addListener((origem, metodo, params) => {
    const estado = cdpPorAba.get(origem.tabId);
    if (!estado || !params) {
      return;
    }
    if (metodo === "Runtime.consoleAPICalled") {
      estado.logs.push({
        nivel: String(params.type ?? "log"),
        texto: textoDosArgs(params.args),
        origem: "console",
        hora: Math.round(params.timestamp ?? Date.now()),
      });
    } else if (metodo === "Log.entryAdded" && params.entry) {
      estado.logs.push({
        nivel: String(params.entry.level ?? "info"),
        texto: String(params.entry.text ?? "").slice(0, 2_000),
        origem: String(params.entry.source ?? "log"),
        hora: Math.round(params.entry.timestamp ?? Date.now()),
      });
    } else if (metodo === "Runtime.exceptionThrown" && params.exceptionDetails) {
      const d = params.exceptionDetails;
      estado.logs.push({
        nivel: "error",
        texto: `${d.text ?? ""} ${d.exception?.description ?? ""}`.trim().slice(0, 2_000),
        origem: "exception",
        hora: Math.round(params.timestamp ?? Date.now()),
      });
    } else if (metodo === "Network.requestWillBeSent" && params.request) {
      estado.rede.push({
        requestId: params.requestId,
        metodo: String(params.request.method ?? ""),
        url: String(params.request.url ?? "").slice(0, MAX_URL),
        status: null,
        tipo: String(params.type ?? ""),
      });
    } else if (metodo === "Network.responseReceived" && params.response) {
      const pedido = estado.rede.find((r) => r.requestId === params.requestId);
      if (pedido) {
        pedido.status = params.response.status ?? null;
        pedido.tipo = String(params.type ?? pedido.tipo);
      }
    }
    if (estado.logs.length > MAX_LOGS) {
      estado.logs.splice(0, estado.logs.length - MAX_LOGS);
    }
    if (estado.rede.length > MAX_REDE) {
      estado.rede.splice(0, estado.rede.length - MAX_REDE);
    }
  });
  api.debugger.onDetach?.addListener((origem) => cdpPorAba.delete(origem.tabId));
}

function enviarCdp(tabId, metodo, params = {}) {
  return api.debugger.sendCommand({ tabId }, metodo, params);
}

async function anexarCdp(tabId) {
  if (!temCdp()) {
    throw erro("sem_cdp", "este navegador não dá o protocolo de depuração (CDP)");
  }
  ouvirCdp();
  if (cdpPorAba.has(tabId)) {
    return cdpPorAba.get(tabId);
  }
  await api.debugger.attach({ tabId }, CDP_VERSAO);
  const estado = { logs: [], rede: [] };
  cdpPorAba.set(tabId, estado);
  for (const dominio of ["Runtime.enable", "Log.enable", "Network.enable", "Page.enable"]) {
    await enviarCdp(tabId, dominio);
  }
  return estado;
}

async function desanexarCdp(tabId) {
  if (!cdpPorAba.has(tabId)) {
    return;
  }
  cdpPorAba.delete(tabId);
  try {
    await api.debugger.detach({ tabId });
  } catch (causa) {
    // A aba fechou ou já se desanexou: nada a fazer.
    void causa;
  }
}

async function consoleDaAba(params) {
  const tabId = (await abaDoPedido(params)).id;
  if (!temCdp()) {
    return { mensagens: [], anexado: false, motivo: "sem_cdp_no_firefox" };
  }
  const estado = await anexarCdp(tabId);
  return { mensagens: estado.logs.slice(-MAX_LOGS), anexado: true };
}

async function redeDaAba(params) {
  const tabId = (await abaDoPedido(params)).id;
  if (!temCdp()) {
    return { pedidos: [], anexado: false, motivo: "sem_cdp_no_firefox" };
  }
  const estado = await anexarCdp(tabId);
  const pedidos = estado.rede.slice(-MAX_REDE).map(({ requestId: _id, ...resto }) => resto);
  return { pedidos, anexado: true };
}

function serializarValor(valor) {
  if (valor === undefined) {
    return null;
  }
  if (typeof valor === "string") {
    return valor.slice(0, 10_000);
  }
  try {
    return JSON.stringify(valor).slice(0, 10_000);
  } catch (causa) {
    void causa;
    return String(valor).slice(0, 10_000);
  }
}

async function avaliarPorScripting(tabId, codigo, mundo) {
  if (!api.scripting || typeof api.scripting.executeScript !== "function") {
    return { valor: null, mundo, cdp: false, recuo: "sem_cdp", erro: "sem CDP e sem chrome.scripting" };
  }
  const world = mundo === "principal" ? "MAIN" : "ISOLATED";
  try {
    const saida = await api.scripting.executeScript({
      target: { tabId },
      world,
      args: [String(codigo)],
      func: (src) => {
        try {
          // eslint-disable-next-line no-eval
          return { ok: true, v: (0, eval)(src) };
        } catch (e) {
          return { ok: false, e: String(e) };
        }
      },
    });
    const r = (saida && saida[0] && saida[0].result) || {};
    if (r.ok) {
      return { valor: serializarValor(r.v), mundo, cdp: false, recuo: "chrome.scripting" };
    }
    return { valor: null, mundo, cdp: false, recuo: "chrome.scripting", erro: String(r.e ?? "erro") };
  } catch (causa) {
    return { valor: null, mundo, cdp: false, recuo: "chrome.scripting", erro: detalheDaFalha(causa) };
  }
}

async function avaliarNaAba(params) {
  const tabId = (await abaDoPedido(params)).id;
  if (typeof tabId !== "number") {
    throw erro("sem_aba", "a aba escolhida não tem identificador");
  }
  const mundo = params.mundo === "principal" ? "principal" : "isolado";
  if (!temCdp()) {
    return avaliarPorScripting(tabId, params.codigo, mundo);
  }
  try {
    await anexarCdp(tabId);
    let contextId;
    if (mundo === "isolado") {
      const arvore = await enviarCdp(tabId, "Page.getFrameTree");
      const frameId = arvore?.frameTree?.frame?.id;
      const criado = await enviarCdp(tabId, "Page.createIsolatedWorld", {
        frameId,
        worldName: "jarvis",
        grantUniveralAccess: false,
      });
      contextId = criado?.executionContextId;
    }
    const r = await enviarCdp(tabId, "Runtime.evaluate", {
      expression: String(params.codigo),
      ...(contextId != null ? { contextId } : {}),
      returnByValue: true,
      awaitPromise: true,
      timeout: PRAZO_DO_EVAL_MS,
      userGesture: false,
    });
    if (r && r.exceptionDetails) {
      return { valor: null, mundo, cdp: true, erro: String(r.exceptionDetails.text ?? "erro no script") };
    }
    return { valor: serializarValor(r?.result?.value), mundo, cdp: true, recuo: null };
  } catch (causa) {
    // Não deu para anexar (política, já há um depurador, versão): recuo honesto.
    return avaliarPorScripting(tabId, params.codigo, mundo);
  }
}

async function centroDoAlvo(tabId, params) {
  const dados = comoObjeto(
    await mensagemDaPagina({ tabId, alvo: params.alvo, ref: params.ref }, "inspecionar"),
  );
  const centro = dados.centro;
  if (!Array.isArray(centro) || centro.length !== 2) {
    throw erro("alvo_ausente", "não achei o elemento para o gesto, ou ele não está à vista");
  }
  return { x: centro[0], y: centro[1] };
}

async function gestoNaAba(params) {
  const tabId = (await abaDoPedido(params)).id;
  if (typeof tabId !== "number") {
    throw erro("sem_aba", "a aba escolhida não tem identificador");
  }
  const gesto = params.gesto;
  if (!temCdp()) {
    throw erro("sem_cdp_no_firefox", "o gesto físico por CDP não existe neste navegador");
  }
  await anexarCdp(tabId);
  if (gesto === "rolar") {
    await enviarCdp(tabId, "Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x: 10,
      y: 10,
      deltaX: 0,
      deltaY: typeof params.pixels === "number" ? params.pixels : 600,
    });
    return { feito: true, gesto };
  }
  const { x, y } = await centroDoAlvo(tabId, params);
  // O ponteiro precisa passar pelo alvo (hover) antes do clique, e cada evento leva o `buttons`
  // (bitmask): sem o `mouseMoved` e o `buttons`, o Chromium não dispara o `onclick` (harness
  // 2026-10-29, Chromium 155).
  const mover = (px, botoes) =>
    enviarCdp(tabId, "Input.dispatchMouseEvent", {
      type: "mouseMoved",
      x: px,
      y,
      button: botoes ? "left" : "none",
      buttons: botoes,
    });
  const apertar = (px, type, buttons) =>
    enviarCdp(tabId, "Input.dispatchMouseEvent", {
      type,
      x: px,
      y,
      button: "left",
      buttons,
      clickCount: 1,
    });
  if (gesto === "arrastar") {
    await mover(x, 0);
    await apertar(x, "mousePressed", 1);
    await mover(x + 60, 1);
    await apertar(x + 60, "mouseReleased", 0);
    return { feito: true, gesto };
  }
  await mover(x, 0);
  await apertar(x, "mousePressed", 1);
  await apertar(x, "mouseReleased", 0);
  if (gesto === "digitar") {
    await enviarCdp(tabId, "Input.insertText", { text: String(params.texto ?? "") });
  }
  return { feito: true, gesto };
}

async function executar(method, params) {
  if (!COM_CONTROLE.has(method)) {
    return executarSemControle(method, params);
  }
  // A aba pedida mostra a faixa ANTES da ação (o dono vê enquanto acontece); a aba nova, ao
  // nascer; e a que voltar no resultado (movida, reaproveitada) também.
  const concessao = conferirConcessao(params);
  if (typeof params.tabId === "number") {
    assumir(params.tabId, concessao);
  }
  const resultado = await executarSemControle(method, params, concessao);
  const aba = comoObjeto(comoObjeto(resultado).aba);
  if (typeof aba.id === "number") {
    assumir(aba.id, concessao);
  }
  return resultado;
}

async function executarSemControle(method, params, concessao) {
  switch (method) {
    case "controle.soltar": {
      const solta = concessaoDe(params);
      return { soltas: solta ? soltarConcessao(solta) : 0 };
    }
    case "controle.manter": {
      const mantida = conferirConcessao(params);
      if (mantida && usoDaConcessao.has(mantida)) {
        usoDaConcessao.set(mantida, Date.now());
      }
      return { mantida: Boolean(mantida && usoDaConcessao.has(mantida)) };
    }
    case "controle.parar":
      // O PARAR da janela do Jarvis: quem pediu já sabe, não há evento a mandar.
      return { paradas: revogarTudo() };
    case "controle.estado":
      return estadoDoControle();
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
      return abrirAba(params, concessao);
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
    case "page.console":
      return consoleDaAba(params);
    case "page.network":
      return redeDaAba(params);
    case "page.eval":
      return avaliarNaAba(params);
    case "page.gesture":
      return gestoNaAba(params);
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

// O conteúdo de cada página pergunta ao nascer se a aba está no controle (a faixa já na página
// nova, sem esperar a página terminar) e manda o PARAR da faixa. Só o nosso conteúdo fala aqui.
api.runtime.onMessage?.addListener((mensagem, remetente, responderAoConteudo) => {
  if (remetente?.id !== api.runtime.id || typeof remetente?.tab?.id !== "number") {
    return false;
  }
  const corpo = comoObjeto(mensagem);
  if (corpo.tipo === "controle?") {
    responderAoConteudo({ ligado: controladas.has(remetente.tab.id) });
  } else if (corpo.tipo === "parar") {
    responderAoConteudo({ paradas: pararPeloDono("faixa").length });
  }
  return false;
});
(api.action ?? api.browserAction)?.onClicked?.addListener(() => {
  if (controladas.size) {
    pararPeloDono("barra");
  }
});
api.tabs.onRemoved?.addListener((tabId) => {
  if (controladas.delete(tabId)) {
    void atualizarSelo();
  }
});

api.runtime.onStartup.addListener(ligarAoHost);
api.runtime.onInstalled.addListener(ligarAoHost);
ligarAoHost();
