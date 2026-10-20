/* Código isolado da página. O DOM é dado de terceiro: ele só responde pedidos tipados da extensão. */

const api = globalThis.browser ?? globalThis.chrome;
const LIMITE_TEXTO = 12_000;
const LIMITE_LINKS = 300;
const LIMITE_ALVOS = 80;
const LIMITE_DIGITACAO = 10_000;
const LIMITE_DO_MAPA = 120;
const LIMITE_DE_SCRIPTS = 30;
const INSTANTANEOS_GUARDADOS = 3;
const ACOES = new Set(["clicar", "focar", "passar_o_mouse", "tecla", "enviar", "selecionar"]);
const TECLAS = new Set(["Enter", "Escape", "Tab", "ArrowDown", "ArrowUp"]);
const INTERATIVOS =
  "a[href], button, input:not([type=hidden]), textarea, select, summary, [contenteditable=true], " +
  "[role=button], [role=link], [role=menuitem], [role=tab], [role=checkbox], [role=radio], " +
  "[role=switch], [role=option], [role=combobox], [role=searchbox], [role=textbox], [onclick], " +
  "[tabindex]:not([tabindex='-1'])";
// O mapa é desta página: a referência leva a marca dela e não vale em outra (ADR-0032).
const MARCA_DA_PAGINA = Math.random().toString(36).slice(2, 6);
let ultimoInstantaneo = 0;
const instantaneos = new Map();

function falhar(codigo, mensagem) {
  throw { codigo, mensagem };
}

function normalizar(texto) {
  return String(texto ?? "").replace(/\s+/gu, " ").trim();
}

function visivel(elemento) {
  const estilo = getComputedStyle(elemento);
  return (
    estilo.visibility !== "hidden" &&
    estilo.display !== "none" &&
    elemento.getClientRects().length > 0
  );
}

function campoDeTexto(elemento) {
  if (elemento instanceof HTMLTextAreaElement) {
    return true;
  }
  if (elemento instanceof HTMLInputElement) {
    return !["button", "submit", "reset", "image", "checkbox", "radio", "file", "range", "color"].includes(
      elemento.type,
    );
  }
  return elemento instanceof HTMLElement && elemento.isContentEditable;
}

function textoDoElemento(elemento) {
  if (elemento instanceof HTMLInputElement) {
    return normalizar(elemento.value || elemento.getAttribute("value") || "");
  }
  return normalizar(elemento.innerText || elemento.textContent || "");
}

function formularioSensivel(formulario) {
  return Boolean(
    formulario?.querySelector(
      "input[type=password], input[autocomplete^=cc-], input[autocomplete=one-time-code]",
    ),
  );
}

const NOME_DE_BUSCA = /(?:^|[^a-z])(?:q|query|search|search_query|s|k|busca|pesquisa|termo|keywords?|field-keywords)(?:$|[^a-z])/iu;
const ROTULO_DE_BUSCA = /pesquis|busca|buscar|procurar|search/iu;
const ACAO_DE_BUSCA = /\/(?:search|results|resultados|busca|pesquisa)(?:[/?#]|$)/iu;

function campoDeBusca(elemento) {
  if (!campoDeTexto(elemento)) {
    return false;
  }
  const papel = elemento.getAttribute("role") ?? "";
  return (
    (elemento instanceof HTMLInputElement && elemento.type === "search") ||
    papel === "searchbox" ||
    NOME_DE_BUSCA.test(elemento.getAttribute("name") ?? "") ||
    ROTULO_DE_BUSCA.test(
      `${elemento.getAttribute("placeholder") ?? ""} ${elemento.getAttribute("aria-label") ?? ""}`,
    )
  );
}

function formularioDeBusca(formulario) {
  if (!formulario) {
    return false;
  }
  return Boolean(
    formulario.matches("[role=search]") ||
      formulario.closest("[role=search]") ||
      formulario.querySelector("input[type=search], [role=searchbox]") ||
      ACAO_DE_BUSCA.test(formulario.getAttribute("action") ?? "") ||
      Array.from(formulario.elements).some((campo) => campoDeBusca(campo)),
  );
}

function dadosDoElemento(elemento) {
  const formulario = elemento instanceof HTMLFormElement ? elemento : elemento.closest("form");
  const campo = elemento instanceof HTMLInputElement || elemento instanceof HTMLTextAreaElement;
  const autocomplete = elemento.getAttribute("autocomplete") ?? "";
  const sensivel =
    (elemento instanceof HTMLInputElement && elemento.type === "password") ||
    /(?:^|\s)(?:cc-|one-time-code|current-password|new-password)/iu.test(autocomplete);
  const ancora = elemento.closest("a[href]");
  return {
    tag: elemento.tagName.toLowerCase(),
    texto: textoDoElemento(elemento).slice(0, 500),
    campo,
    sensivel,
    enviaFormulario:
      elemento instanceof HTMLButtonElement || elemento instanceof HTMLInputElement
        ? elemento.type === "submit" || elemento.type === "image"
        : false,
    acaoDoFormulario: formulario?.action ?? "",
    metodoDoFormulario: formulario ? formulario.method.toLowerCase() : "",
    formularioDeBusca: formularioDeBusca(formulario),
    formularioSensivel: formularioSensivel(formulario),
    noFormulario: Boolean(formulario),
    editavel: campoDeTexto(elemento),
    campoDeBusca: campoDeBusca(elemento),
    papel: papelDe(elemento),
    rotulo: rotuloDe(elemento),
    destinoDoLink: ancora ? ancora.href.slice(0, 2_048) : "",
  };
}

function papelDe(elemento) {
  const explicito = (elemento.getAttribute("role") ?? "").trim().split(/\s+/u)[0];
  if (explicito) {
    return explicito;
  }
  const tag = elemento.tagName.toLowerCase();
  if (tag === "a") {
    return "link";
  }
  if (tag === "button" || tag === "summary") {
    return "button";
  }
  if (tag === "select") {
    return "combobox";
  }
  if (tag === "textarea") {
    return "textbox";
  }
  if (elemento instanceof HTMLInputElement) {
    const tipo = elemento.type;
    if (["button", "submit", "reset", "image"].includes(tipo)) {
      return "button";
    }
    if (tipo === "checkbox" || tipo === "radio") {
      return tipo;
    }
    return tipo === "search" ? "searchbox" : "textbox";
  }
  return elemento instanceof HTMLElement && elemento.isContentEditable ? "textbox" : "generic";
}

function rotuloDe(elemento) {
  // O valor de um campo nunca entra: pode ser o que o dono digitou (ADR-0032).
  const rotuladoPor = (elemento.getAttribute("aria-labelledby") ?? "")
    .split(/\s+/u)
    .filter(Boolean)
    .map((id) => document.getElementById(id)?.textContent ?? "")
    .join(" ");
  const botao =
    elemento instanceof HTMLInputElement && ["button", "submit", "reset"].includes(elemento.type)
      ? elemento.value
      : "";
  const visivel = campoDeTexto(elemento) || elemento instanceof HTMLSelectElement
    ? ""
    : normalizar(elemento.innerText || elemento.textContent || "");
  const imagem = elemento.querySelector?.("img[alt]")?.getAttribute("alt") ?? "";
  return normalizar(
    elemento.getAttribute("aria-label") ||
      rotuladoPor ||
      elemento.labels?.[0]?.textContent ||
      botao ||
      elemento.getAttribute("placeholder") ||
      visivel ||
      elemento.getAttribute("title") ||
      elemento.getAttribute("alt") ||
      imagem ||
      elemento.getAttribute("name") ||
      "",
  ).slice(0, 120);
}

function candidatosClicaveis() {
  return Array.from(
    document.querySelectorAll(
      "a[href], button, input[type=button], input[type=submit], input[type=image], [role=button], [role=link], [onclick]",
    ),
  ).filter(visivel);
}

function candidatosEditaveis() {
  return Array.from(document.querySelectorAll("input, textarea, [contenteditable=true]"))
    .filter(visivel)
    .filter((elemento) => !(elemento instanceof HTMLInputElement && elemento.disabled));
}

function porTexto(texto, candidatos) {
  const procurado = normalizar(texto).toLocaleLowerCase();
  if (!procurado || procurado.length > 500) {
    falhar("alvo_invalido", "texto do alvo ausente ou longo demais");
  }
  const exatos = candidatos.filter(
    (elemento) => textoDoElemento(elemento).toLocaleLowerCase() === procurado,
  );
  if (exatos.length === 1) {
    return exatos[0];
  }
  if (exatos.length > 1) {
    falhar("alvo_ambiguo", "há mais de um elemento com esse texto");
  }
  const porRotulo = candidatos.filter((elemento) => {
    const rotulo = normalizar(
      elemento.getAttribute("aria-label") ||
        elemento.getAttribute("placeholder") ||
        elemento.labels?.[0]?.textContent ||
        elemento.getAttribute("title") ||
        "",
    ).toLocaleLowerCase();
    return rotulo === procurado;
  });
  if (porRotulo.length === 1) {
    return porRotulo[0];
  }
  if (porRotulo.length > 1) {
    falhar("alvo_ambiguo", "há mais de um elemento com esse rótulo");
  }
  falhar("alvo_ausente", "não encontrei um único elemento visível com esse texto");
}

function porReferencia(ref) {
  // A referência é do mapa que esta página devolveu (ADR-0027, regra 1; ADR-0032): o Jarvis
  // nunca manda seletor CSS nem coordenada. Se a página redesenhou o elemento, o seletor estável
  // guardado no mapa o reencontra — e só se achar um, visível.
  const [instantaneo] = String(ref).split(".");
  const guardado = instantaneos.get(instantaneo)?.get(ref);
  if (!guardado) {
    falhar("ref_expirada", "essa referência não é do mapa atual desta página: inspecione de novo");
  }
  const vivo = guardado.elemento.deref();
  if (vivo?.isConnected && visivel(vivo)) {
    return vivo;
  }
  const achados = guardado.seletor
    ? Array.from(document.querySelectorAll(guardado.seletor)).filter(visivel)
    : [];
  if (achados.length === 1) {
    return achados[0];
  }
  falhar("ref_expirada", "o elemento dessa referência saiu da página: inspecione de novo");
}

function resolverAlvo(params, candidatos) {
  if (typeof params.ref === "string" && params.ref) {
    return porReferencia(params.ref);
  }
  return porTexto(params.alvo, candidatos);
}

function seletorEstavel(elemento) {
  const tag = elemento.tagName.toLowerCase();
  const unico = (seletor) => {
    try {
      return document.querySelectorAll(seletor).length === 1 ? seletor : "";
    } catch {
      return "";
    }
  };
  if (elemento.id && /^[A-Za-z][\w-]{0,60}$/u.test(elemento.id)) {
    const porId = unico(`#${CSS.escape(elemento.id)}`);
    if (porId) {
      return porId;
    }
  }
  for (const atributo of ["data-testid", "name", "aria-label", "placeholder"]) {
    const valor = elemento.getAttribute(atributo);
    if (valor && valor.length <= 80) {
      const porAtributo = unico(`${tag}[${atributo}="${valor.replace(/["\\]/gu, "\\$&")}"]`);
      if (porAtributo) {
        return porAtributo;
      }
    }
  }
  const partes = [];
  let atual = elemento;
  while (atual && atual !== document.body && partes.length < 6) {
    const pai = atual.parentElement;
    if (!pai) {
      break;
    }
    const irmaos = Array.from(pai.children).filter((filho) => filho.tagName === atual.tagName);
    const nome = atual.tagName.toLowerCase();
    partes.unshift(irmaos.length > 1 ? `${nome}:nth-of-type(${irmaos.indexOf(atual) + 1})` : nome);
    if (pai.id && /^[A-Za-z][\w-]{0,60}$/u.test(pai.id)) {
      partes.unshift(`#${CSS.escape(pai.id)}`);
      break;
    }
    atual = pai;
  }
  return unico(partes.join(" > "));
}

const CHAMADA = /([A-Za-z_$][\w$]*)\s*\(/gu;
const DEFINICAO =
  /(?:function\s+([A-Za-z_$][\w$]*)|([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>))/gu;
const PALAVRAS_DO_JS = new Set(["if", "for", "while", "switch", "return", "function", "catch"]);

function manipuladores(elemento) {
  // Só o que se vê do mundo isolado: atributo on*, jsaction, javascript: e formulário. Ouvinte
  // posto por addEventListener não aparece fora do DevTools.
  const achados = elemento.getAttributeNames().filter((nome) => /^on[a-z]+$/u.test(nome));
  if (elemento.hasAttribute("jsaction")) {
    achados.push("jsaction");
  }
  if (/^\s*javascript:/iu.test(elemento.getAttribute("href") ?? "")) {
    achados.push("javascript:");
  }
  if (elemento.closest("form")) {
    achados.push("form");
  }
  return achados.slice(0, 6);
}

function chamadas(elemento) {
  const codigo = [
    ...elemento.getAttributeNames().filter((nome) => /^on[a-z]+$/u.test(nome)),
    "href",
  ]
    .map((nome) => elemento.getAttribute(nome) ?? "")
    .join(" ");
  const nomes = new Set();
  for (const achado of codigo.matchAll(CHAMADA)) {
    if (!PALAVRAS_DO_JS.has(achado[1])) {
      nomes.add(achado[1]);
    }
  }
  return Array.from(nomes).slice(0, 5);
}

function scriptsDaPagina() {
  return Array.from(document.scripts)
    .slice(0, LIMITE_DE_SCRIPTS)
    .map((script, indice) => {
      const codigo = script.src ? "" : (script.textContent ?? "");
      const define = new Set();
      for (const achado of codigo.slice(0, 200_000).matchAll(DEFINICAO)) {
        define.add(achado[1] || achado[2]);
        if (define.size >= 12) {
          break;
        }
      }
      return {
        id: `s${indice + 1}`,
        src: script.src ? script.src.slice(0, 300) : "",
        tipo: script.type || "",
        tamanho: codigo.length,
        resumo: normalizar(codigo).slice(0, 160),
        define: Array.from(define),
      };
    });
}

function mapear() {
  ultimoInstantaneo += 1;
  const instantaneo = `${MARCA_DA_PAGINA}${ultimoInstantaneo}`;
  const dpr = window.devicePixelRatio || 1;
  const largura = window.innerWidth;
  const altura = window.innerHeight;
  const vistos = Array.from(document.querySelectorAll(INTERATIVOS)).filter(visivel);
  const naTela = (caixa) =>
    caixa.bottom > 0 && caixa.right > 0 && caixa.top < altura && caixa.left < largura;
  const caixas = new Map(vistos.map((elemento) => [elemento, elemento.getBoundingClientRect()]));
  // Os que estão na tela primeiro; depois, na ordem do documento.
  vistos.sort((a, b) => Number(naTela(caixas.get(b))) - Number(naTela(caixas.get(a))));
  const scripts = scriptsDaPagina();
  const definidoPor = new Map();
  for (const script of scripts) {
    for (const nome of script.define) {
      definidoPor.set(nome, script.id);
    }
  }
  const referencias = new Map();
  const elementos = vistos.slice(0, LIMITE_DO_MAPA).map((elemento, indice) => {
    const ref = `${instantaneo}.${indice + 1}`;
    const seletor = seletorEstavel(elemento);
    referencias.set(ref, { elemento: new WeakRef(elemento), seletor });
    const caixa = caixas.get(elemento);
    const tipo = elemento instanceof HTMLInputElement ? elemento.type : "";
    const href = elemento instanceof HTMLAnchorElement ? elemento.href.slice(0, 300) : "";
    const ligados = chamadas(elemento)
      .map((nome) => definidoPor.get(nome))
      .filter(Boolean);
    return {
      ref,
      papel: papelDe(elemento),
      rotulo: rotuloDe(elemento),
      tag: elemento.tagName.toLowerCase(),
      tipo,
      nome: elemento.getAttribute("name") ?? "",
      href,
      seletor,
      // Em pixels da captura da aba (CSS × devicePixelRatio), relativos ao canto da tela.
      caixa: [caixa.x, caixa.y, caixa.width, caixa.height].map((valor) => Math.round(valor * dpr)),
      naTela: naTela(caixa),
      desabilitado: elemento.disabled === true || elemento.getAttribute("aria-disabled") === "true",
      marcado: elemento.checked === true || elemento.getAttribute("aria-checked") === "true",
      expandido: elemento.getAttribute("aria-expanded") ?? "",
      campo: campoDeTexto(elemento),
      campoDeBusca: campoDeBusca(elemento),
      manipuladores: manipuladores(elemento),
      chama: chamadas(elemento),
      scripts: Array.from(new Set(ligados)),
    };
  });
  instantaneos.set(instantaneo, referencias);
  for (const antigo of Array.from(instantaneos.keys()).slice(0, -INSTANTANEOS_GUARDADOS)) {
    instantaneos.delete(antigo);
  }
  return {
    instantaneo,
    url: location.href,
    titulo: document.title,
    dpr,
    viewport: [largura, altura],
    rolagem: [Math.round(window.scrollX), Math.round(window.scrollY)],
    total: vistos.length,
    elementos,
    scripts,
  };
}

function leitura() {
  const corpo = document.body;
  const links = Array.from(document.querySelectorAll("a[href]"))
    .filter(visivel)
    .slice(0, LIMITE_LINKS)
    .map((link) => {
      const tempo = link.querySelector("time[datetime]");
      return {
        texto: textoDoElemento(link).slice(0, 500),
        href: link.href,
        data: tempo?.getAttribute("datetime") ?? "",
      };
    });
  const datas = Array.from(document.querySelectorAll("time[datetime]"))
    .filter(visivel)
    .slice(0, LIMITE_LINKS)
    .map((tempo) => ({ texto: textoDoElemento(tempo).slice(0, 300), data: tempo.dateTime }));
  return {
    url: location.href,
    titulo: document.title,
    textoVisivel: normalizar(corpo?.innerText ?? "").slice(0, LIMITE_TEXTO),
    links,
    datas,
  };
}

function inspecionar(params) {
  const alvo = resolverAlvo(params, [...candidatosClicaveis(), ...candidatosEditaveis()].slice(0, LIMITE_ALVOS));
  return dadosDoElemento(alvo);
}

function eventosDePonteiro(alvo, tipos) {
  const caixa = alvo.getBoundingClientRect();
  const base = {
    bubbles: true,
    cancelable: true,
    composed: true,
    clientX: caixa.left + caixa.width / 2,
    clientY: caixa.top + caixa.height / 2,
    button: 0,
  };
  for (const tipo of tipos) {
    const Tipo = tipo.startsWith("pointer") ? PointerEvent : MouseEvent;
    const apertado = tipo.endsWith("down") ? 1 : 0;
    alvo.dispatchEvent(new Tipo(tipo, { ...base, buttons: apertado, pointerType: "mouse" }));
  }
}

function apertarTecla(alvo, tecla) {
  if (!TECLAS.has(tecla)) {
    falhar("tecla_invalida", "tecla fora da lista (Enter, Escape, Tab, setas para cima e baixo)");
  }
  alvo.focus({ preventScroll: true });
  const opcoes = { key: tecla, code: tecla, bubbles: true, cancelable: true, composed: true };
  const seguiu = alvo.dispatchEvent(new KeyboardEvent("keydown", opcoes));
  if (tecla === "Enter") {
    alvo.dispatchEvent(new KeyboardEvent("keypress", opcoes));
  }
  alvo.dispatchEvent(new KeyboardEvent("keyup", opcoes));
  // Evento sintético não faz o que o navegador faria: o Enter num campo envia o formulário dele
  // (envio implícito), a não ser que a página tenha tratado a tecla (`preventDefault`).
  const formulario = alvo.form ?? alvo.closest?.("form");
  if (tecla === "Enter" && seguiu && formulario && campoDeTexto(alvo)) {
    formulario.requestSubmit();
    return true;
  }
  return false;
}

function acionar(params) {
  // Acionar a ação do DOM equivale a clicar o elemento (dono, 2026-10-18, ADR-0027): vocabulário
  // fechado, sem eval nem função da página chamada pelo nome (ADR-0032).
  if (!ACOES.has(params.acao)) {
    falhar("acao_invalida", "ação fora da lista");
  }
  const alvo = resolverAlvo(
    params,
    [...candidatosClicaveis(), ...candidatosEditaveis()].slice(0, LIMITE_ALVOS),
  );
  let enviado = false;
  switch (params.acao) {
    case "clicar":
      // A sequência inteira de ponteiro: há página que escuta pointerdown/mousedown e não click.
      // Sem rolar a página: a tela é do dono.
      eventosDePonteiro(alvo, ["pointerover", "mouseover", "pointerdown", "mousedown"]);
      alvo.focus({ preventScroll: true });
      eventosDePonteiro(alvo, ["pointerup", "mouseup"]);
      alvo.click();
      break;
    case "focar":
      alvo.focus({ preventScroll: true });
      break;
    case "passar_o_mouse":
      eventosDePonteiro(alvo, ["pointerover", "pointerenter", "mouseover", "mouseenter", "pointermove", "mousemove"]);
      break;
    case "tecla":
      enviado = apertarTecla(alvo, params.tecla);
      break;
    case "enviar": {
      const formulario = alvo instanceof HTMLFormElement ? alvo : (alvo.form ?? alvo.closest("form"));
      if (!formulario) {
        falhar("sem_formulario", "o elemento não está num formulário");
      }
      formulario.requestSubmit();
      enviado = true;
      break;
    }
    case "selecionar": {
      if (!(alvo instanceof HTMLSelectElement)) {
        falhar("alvo_incompativel", "selecionar é só para lista de opções");
      }
      const procurado = normalizar(params.valor).toLocaleLowerCase();
      const opcao = Array.from(alvo.options).find(
        (item) => normalizar(item.textContent).toLocaleLowerCase() === procurado || item.value === params.valor,
      );
      if (!opcao) {
        falhar("opcao_ausente", "não há essa opção na lista");
      }
      alvo.value = opcao.value;
      alvo.dispatchEvent(new Event("input", { bubbles: true }));
      alvo.dispatchEvent(new Event("change", { bubbles: true }));
      break;
    }
  }
  return { acionado: params.acao, enviado, ...dadosDoElemento(alvo) };
}

function clicar(params) {
  const alvo = resolverAlvo(params, candidatosClicaveis().slice(0, LIMITE_ALVOS));
  const dados = dadosDoElemento(alvo);
  alvo.focus({ preventScroll: true });
  alvo.click();
  return { clicado: true, ...dados };
}

function campoSensivel(alvo) {
  const dados = dadosDoElemento(alvo);
  return dados.sensivel || /(?:cart[aã]o|card|cvv|cvc|senha|password)/iu.test(dados.texto);
}

function digitar(params) {
  if (typeof params.texto !== "string" || params.texto.length > LIMITE_DIGITACAO) {
    falhar("texto_invalido", "texto ausente ou longo demais");
  }
  const alvo = resolverAlvo(params, candidatosEditaveis().slice(0, LIMITE_ALVOS));
  if (campoSensivel(alvo)) {
    falhar("campo_sensivel", "senha, OTP ou cartão é digitado somente pelo dono");
  }
  const limpar = params.limpar === true;
  alvo.focus({ preventScroll: true });
  if (alvo instanceof HTMLInputElement || alvo instanceof HTMLTextAreaElement) {
    const prototipo = alvo instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype;
    const definirValor = Object.getOwnPropertyDescriptor(prototipo, "value")?.set;
    if (!definirValor) {
      falhar("campo_incompativel", "o campo não aceita texto");
    }
    definirValor.call(alvo, limpar ? params.texto : alvo.value + params.texto);
  } else if (alvo instanceof HTMLElement && alvo.isContentEditable) {
    alvo.textContent = limpar ? params.texto : (alvo.textContent ?? "") + params.texto;
  } else {
    falhar("campo_incompativel", "o alvo não é um campo editável");
  }
  alvo.dispatchEvent(
    new InputEvent("input", { bubbles: true, inputType: "insertText", data: params.texto }),
  );
  alvo.dispatchEvent(new Event("change", { bubbles: true }));
  return { digitado: params.texto.length, ...dadosDoElemento(alvo) };
}

function rolar(params) {
  const pixels = Number.isFinite(params.pixels) ? Math.trunc(params.pixels) : 600;
  const limitado = Math.max(-2_000, Math.min(2_000, pixels));
  window.scrollBy({ top: limitado, left: 0, behavior: "instant" });
  return { deslocamento: limitado, y: Math.round(window.scrollY) };
}

async function responder(mensagem, remetente) {
  if (remetente.id !== api.runtime.id || !mensagem || typeof mensagem !== "object") {
    return undefined;
  }
  try {
    switch (mensagem.comando) {
      case "ler":
        return { ok: true, result: leitura() };
      case "inspecionar":
        return { ok: true, result: inspecionar(mensagem.params ?? {}) };
      case "mapear":
        return { ok: true, result: mapear() };
      case "acionar":
        return { ok: true, result: acionar(mensagem.params ?? {}) };
      case "clicar":
        return { ok: true, result: clicar(mensagem.params ?? {}) };
      case "digitar":
        return { ok: true, result: digitar(mensagem.params ?? {}) };
      case "rolar":
        return { ok: true, result: rolar(mensagem.params ?? {}) };
      default:
        return { ok: false, error: { codigo: "comando_invalido", mensagem: "comando não permitido" } };
    }
  } catch (causa) {
    const detalhe = causa && typeof causa === "object" ? causa : {};
    return {
      ok: false,
      error: {
        codigo: typeof detalhe.codigo === "string" ? detalhe.codigo : "falha",
        mensagem: typeof detalhe.mensagem === "string" ? detalhe.mensagem : "falha na página",
      },
    };
  }
}

api.runtime.onMessage.addListener((mensagem, remetente, enviarResposta) => {
  responder(mensagem, remetente).then(enviarResposta);
  return true;
});
