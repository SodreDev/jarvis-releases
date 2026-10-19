/* Código isolado da página. O DOM é dado de terceiro: ele só responde pedidos tipados da extensão. */

const api = globalThis.browser ?? globalThis.chrome;
const LIMITE_TEXTO = 12_000;
const LIMITE_LINKS = 300;
const LIMITE_ALVOS = 80;
const LIMITE_DIGITACAO = 10_000;

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

function dadosDoElemento(elemento) {
  const formulario = elemento.closest("form");
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
    formularioDeBusca: Boolean(
      formulario?.matches("[role=search]") || formulario?.querySelector("input[type=search]"),
    ),
    formularioSensivel: formularioSensivel(formulario),
    destinoDoLink: ancora ? ancora.href.slice(0, 2_048) : "",
  };
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

function resolverAlvo(params, candidatos) {
  // O alvo é sempre o texto ou rótulo visível: seletor CSS vindo do Jarvis não existe (ADR-0027).
  return porTexto(params.alvo, candidatos);
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
