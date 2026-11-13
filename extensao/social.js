/*
 * O monitor das redes sociais (ADR-0060), SOMENTE LEITURA: só roda nos hosts das cinco redes
 * (manifest.json) e só lê o título, o contador de não lidas e quem mandou. Não clica, não digita,
 * não rola e não lê o texto das mensagens (mapear o formato delas é para depois).
 *
 * O estado vai ao fundo da extensão (`{tipo: "social"}`), que o repassa ao Jarvis como evento —
 * só quando muda, e uma vez por minuto para o Jarvis saber que a aba continua viva. Os seletores
 * de cada rede ficam todos aqui, num bloco por rede: quando a página mudar, é só aqui que mexe, e
 * o que não se reconhece vira "formato desconhecido" em vez de um número errado.
 *
 * O contador é lido de forma tolerante e conservadora (dono, 2026-11-13): «3», «1.234», «99+»,
 * «+999», espaço fino ou NBSP no milhar, dígitos de outros alfabetos, o número no aria-label
 * («3 mensagens não lidas», «2 unread messages», «2 mensajes no leídos») e a bolinha sem número
 * (conversa marcada como não lida = pelo menos 1). O que não se reconhece conta 1 por conversa e
 * vai como `pista: "contador_ilegivel"` com uma `amostra` sanitizada (palavras fora do
 * vocabulário do contador viram «x», telefone vira «###»), nunca como erro. A página que ainda
 * carrega (`pista: "carregando"`) não se confunde com a página que mudou (`"sem_lista"`).
 */

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const INTERVALO_MS = 15_000; // releitura de reserva: o título é observado
  const VIVO_MS = 60_000;
  const MAX_CONVERSAS = 20;
  const MAX_NOME = 80;
  const MAX_CONTAGEM = 9_999;
  const MAX_AMOSTRA = 60;
  const CARREGANDO_MS = 45_000;
  // Até aqui, sem login nem lista, é a página carregando (o WhatsApp Web leva segundos na tela de
  // «carregando suas conversas», mais ainda numa aba de fundo); depois, é a página que mudou.

  // Os seletores são dados, noutro arquivo (social-seletores.js, carregado antes deste): papel,
  // aria-label e atributo estável, em ordem de preferência (docs/redes-sociais-riscos.md §3).
  const SELETORES = globalThis.__jarvisSeletoresSociais ?? { versao: 0, redes: {} };
  const REDES = SELETORES.redes;

  function redeDoHost(host) {
    for (const [id, rede] of Object.entries(REDES)) {
      if (rede.hosts.includes(host)) {
        return id;
      }
    }
    return undefined;
  }

  function primeiro(raiz, seletores) {
    // O primeiro seletor da lista que acha algo: a ordem é a preferência, o resto é recuo.
    for (const seletor of seletores ?? []) {
      try {
        const achado = raiz.querySelector(seletor);
        if (achado) {
          return achado;
        }
      } catch {
        // seletor que este navegador não entende conta como ausente
      }
    }
    return null;
  }

  function todos(raiz, seletores) {
    for (const seletor of seletores ?? []) {
      try {
        const achados = [...raiz.querySelectorAll(seletor)];
        if (achados.length) {
          return achados;
        }
      } catch {
        // idem
      }
    }
    return [];
  }

  function existe(raiz, seletores) {
    return primeiro(raiz, seletores) !== null;
  }

  function limpo(texto, maximo) {
    // Texto da página é de terceiros: sem controle, sem quebra, cortado.
    return String(texto ?? "")
      .replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]/gu, " ")
      .replace(/\s+/gu, " ")
      .trim()
      .slice(0, maximo);
  }

  function emAscii(texto) {
    // NFKC leva o dígito de largura cheia e o matemático ao ASCII; os outros alfabetos (árabe,
    // persa, devanágari, bengali, tailandês…) têm os dez dígitos em sequência a partir do zero:
    // o valor é quantos dígitos há antes dele no mesmo bloco.
    return String(texto ?? "")
      .normalize("NFKC")
      .replace(/[\u00a0\u2007\u2009\u202f]/gu, " ")
      .replace(/\p{Nd}/gu, (digito) => {
        if (digito >= "0" && digito <= "9") {
          return digito;
        }
        let valor = 0;
        let ponto = digito.codePointAt(0) - 1;
        while (valor < 9 && /\p{Nd}/u.test(String.fromCodePoint(ponto))) {
          valor += 1;
          ponto -= 1;
        }
        return String(valor);
      });
  }

  function lerContador(texto) {
    // {n, tipo}: "numero" (3, 1.234), "minimo" (99+, +999: pelo menos n), "vazio" (nada escrito)
    // ou "ilegivel" (escrito, mas sem um número que se reconheça — 1,5 mil, 12:30, 99999).
    const normal = emAscii(limpo(texto, 200)).trim();
    if (!/[\p{L}\d]/u.test(normal)) {
      return { n: 0, tipo: "vazio" }; // nada, ou só um sinal («•»): a bolinha sem número
    }
    const achado = /(\+)?[ ]?(\d{1,3}(?:[., ]\d{3})+|\d+)[ ]?(\+)?/u.exec(normal);
    if (!achado) {
      return { n: 0, tipo: "ilegivel" };
    }
    const resto = normal.slice(achado.index + achado[0].length);
    if (/^[.,:]\d|^\s*(?:k|mil|mi|m)\b/iu.test(resto)) {
      return { n: 0, tipo: "ilegivel" }; // decimal, hora ou «mil»: não é contagem exata
    }
    const n = Number.parseInt(achado[2].replace(/\D/gu, ""), 10);
    if (!Number.isFinite(n) || n > MAX_CONTAGEM) {
      return { n: 0, tipo: "ilegivel" };
    }
    return { n, tipo: achado[1] || achado[3] ? "minimo" : "numero" };
  }

  function contadorDoTitulo(titulo) {
    // "(3) WhatsApp", "(1.234) WhatsApp", "(99+) …", "(12) Discord | #geral": só o grupo entre
    // parênteses no COMEÇO — «Grupo (3) amigos» é nome de conversa, não contador.
    const achado = /^\s*\(([^()]{1,12})\)/u.exec(emAscii(titulo));
    if (!achado) {
      return { n: 0, tipo: "vazio" };
    }
    return lerContador(achado[1]);
  }

  function contagemDoTitulo(titulo) {
    const lido = contadorDoTitulo(titulo);
    return lido.tipo === "numero" || lido.tipo === "minimo" ? lido.n : 0;
  }

  const VOCABULARIO = new Set(SELETORES.vocabularioDaAmostra ?? []);

  function semAcento(texto) {
    return texto.normalize("NFKD").replace(/[\u0300-\u036f]/gu, "").toLowerCase();
  }

  function amostraSegura(texto) {
    // O texto bruto do contador que não se reconheceu, para o dono mandar no diagnóstico — sem
    // dado de ninguém: palavra fora do vocabulário do contador vira «x», telefone vira «###», e
    // sobra só dígito, «x», vocabulário e pontuação de número.
    return emAscii(limpo(texto, 200))
      .replace(/\+?\d[\d ().-]{6,}\d/gu, "###")
      .replace(/[\p{L}\p{M}]+/gu, (palavra) => {
        const chave = semAcento(palavra);
        return VOCABULARIO.has(chave) ? chave : "x";
      })
      .replace(/[^a-z0-9#()+.,:|/ x-]/gu, " ")
      .replace(/\s+/gu, " ")
      .trim()
      .slice(0, MAX_AMOSTRA);
  }

  function contagemDoSelo(selo) {
    // O texto do selo primeiro, depois o aria-label. Selo sem número nenhum (a bolinha da
    // conversa marcada como não lida) conta 1; número que não se reconhece conta 1 e vira pista.
    const texto = selo.textContent;
    const rotulo = selo.getAttribute?.("aria-label") ?? "";
    const doTexto = lerContador(texto);
    if (doTexto.tipo === "numero" || doTexto.tipo === "minimo") {
      return { naoLidas: Math.max(1, doTexto.n), ilegivel: "" };
    }
    const doRotulo = lerContador(rotulo);
    if (doRotulo.tipo === "numero" || doRotulo.tipo === "minimo") {
      return { naoLidas: Math.max(1, doRotulo.n), ilegivel: "" };
    }
    if (doTexto.tipo === "vazio" && doRotulo.tipo !== "ilegivel") {
      return { naoLidas: 1, ilegivel: "" };
    }
    if (doTexto.tipo === "vazio" && !/\d/u.test(emAscii(rotulo))) {
      return { naoLidas: 1, ilegivel: "" }; // «Marcada como não lida»: a bolinha
    }
    return { naoLidas: 1, ilegivel: [texto, rotulo].filter((t) => limpo(t, 80)).join(" | ") };
  }

  function conversasNaoLidas(raiz, rede) {
    const saida = [];
    let ilegivel = "";
    for (const linha of todos(raiz, rede.conversa)) {
      const selo = primeiro(linha, rede.selo);
      if (!selo) {
        continue;
      }
      const lido = contagemDoSelo(selo);
      const elementoDoNome = primeiro(linha, rede.nome);
      const nome = limpo(
        elementoDoNome?.getAttribute?.("title") || elementoDoNome?.textContent,
        MAX_NOME,
      );
      if (lido.naoLidas > 0 && nome) {
        saida.push({ nome, naoLidas: Math.min(MAX_CONTAGEM, lido.naoLidas) });
        ilegivel ||= lido.ilegivel;
      }
      if (saida.length >= MAX_CONVERSAS) {
        break;
      }
    }
    return { conversas: saida, ilegivel };
  }

  // Sinais de alerta (docs/redes-sociais-riscos.md §6): captcha, verificação, conta limitada,
  // atividade incomum. Só o que está num diálogo ou aviso da própria página — nada de varrer o
  // corpo inteiro. O Jarvis para todo envio da rede por 24 h e avisa o dono; nunca contorna.
  const ALERTAS = SELETORES.alertas ?? { captcha: [], onde: [], textos: {} };

  function alertaDaPagina(documento) {
    if (existe(documento, ALERTAS.captcha)) {
      return "captcha";
    }
    const textos = [];
    for (const seletor of ALERTAS.onde ?? []) {
      try {
        for (const elemento of documento.querySelectorAll(seletor)) {
          textos.push(String(elemento.textContent ?? "").slice(0, 2_000));
        }
      } catch {
        // seletor que este navegador não entende
      }
    }
    const juntos = textos.join(" \n ").toLowerCase();
    if (!juntos) {
      return "";
    }
    for (const [alerta, padrao] of Object.entries(ALERTAS.textos ?? {})) {
      try {
        if (new RegExp(padrao, "iu").test(juntos)) {
          return alerta;
        }
      } catch {
        // padrão inválido nos dados: ignorado (o teste dos dados pega antes)
      }
    }
    return "";
  }

  // --- só para o envio (fatia D): ler o cabeçalho, achar a conversa e a caixa de texto. Continua
  // SÓ leitura: quem clica e digita é o fundo, pelo CDP. Devolve o centro do elemento na tela.
  const TELEFONE = /^\+?[\d\s().-]{8,24}$/u;

  function normal(texto) {
    return limpo(texto, MAX_NOME)
      .normalize("NFKD")
      .replace(/[̀-ͯ]/gu, "")
      .toLowerCase();
  }

  function centroDe(elemento) {
    const caixa = elemento?.getBoundingClientRect?.();
    if (!caixa || caixa.width <= 0 || caixa.height <= 0) {
      return {};
    }
    return { x: Math.round(caixa.left + caixa.width / 2), y: Math.round(caixa.top + caixa.height / 2) };
  }

  function cabecalhoDoChat(rede, documento) {
    const topo = primeiro(documento, rede.cabecalho);
    if (!topo) {
      return { nome: "", telefone: "", grupo: false, ambiguo: true };
    }
    const elemento = primeiro(topo, rede.nomeDoCabecalho);
    const nome = limpo(elemento?.getAttribute?.("title") || elemento?.textContent, MAX_NOME);
    return {
      nome,
      telefone: TELEFONE.test(nome) ? nome : "",
      grupo: existe(topo, rede.grupo),
      ambiguo: !nome,
    };
  }

  function conversaPeloNome(rede, documento, nome) {
    const alvo = normal(nome);
    const achadas = todos(documento, rede.conversa).filter((linha) => {
      const elemento = primeiro(linha, rede.nome);
      return normal(elemento?.getAttribute?.("title") || elemento?.textContent) === alvo;
    });
    return { quantas: achadas.length, ...(achadas.length === 1 ? centroDe(achadas[0]) : {}) };
  }

  function caixaDeTexto(rede, documento) {
    return centroDe(primeiro(documento, rede.caixa));
  }

  // Exportada para o teste (tests/unit/social/social.test.mjs), que a roda contra as páginas
  // falsas de tests/unit/social/paginas/ — nunca contra a rede de verdade. `idadeMs`: há quanto
  // tempo este script roda na página (o teste passa; sem ela, a página já teve tempo de carregar).
  function lerEstado(id, documento, opcoes = {}) {
    const rede = REDES[id];
    if (!rede) {
      return {
        rede: id,
        logado: false,
        naoLidas: 0,
        conversas: [],
        formato: "desconhecido",
        alerta: "",
        pista: "sem_lista",
        amostra: "",
      };
    }
    const alerta = alertaDaPagina(documento);
    const titulo = contadorDoTitulo(documento.title);
    const naoLidasDoTitulo = titulo.tipo === "numero" || titulo.tipo === "minimo" ? titulo.n : 0;
    if (existe(documento, rede.login)) {
      return {
        rede: id,
        logado: false,
        naoLidas: 0,
        conversas: [],
        formato: "conhecido",
        alerta,
        pista: "",
        amostra: "",
      };
    }
    // O canário: logado, pelo menos um elemento essencial tem de existir. Sem ele, ou a página
    // ainda carrega (o indicador de carga dela, ou o script nasceu há pouco), ou a página mudou e
    // a rede degrada para só notificar — nunca se chuta um elemento parecido.
    if (!existe(documento, rede.essenciais)) {
      const idadeMs = Number.isFinite(opcoes.idadeMs) ? opcoes.idadeMs : Number.POSITIVE_INFINITY;
      const carregando =
        existe(documento, rede.carregando) ||
        documento.readyState === "loading" ||
        idadeMs < CARREGANDO_MS;
      return {
        rede: id,
        logado: false,
        naoLidas: naoLidasDoTitulo,
        conversas: [],
        formato: "desconhecido",
        alerta,
        pista: carregando ? "carregando" : "sem_lista",
        amostra: carregando ? "" : amostraSegura(documento.title),
      };
    }
    const { conversas, ilegivel } = conversasNaoLidas(documento, rede);
    const somadas = conversas.reduce((total, conversa) => total + conversa.naoLidas, 0);
    const brutoIlegivel = ilegivel || (titulo.tipo === "ilegivel" ? documento.title : "");
    return {
      rede: id,
      logado: true,
      naoLidas: Math.min(MAX_CONTAGEM, Math.max(naoLidasDoTitulo, somadas)),
      conversas,
      formato: "conhecido",
      alerta,
      pista: brutoIlegivel ? "contador_ilegivel" : "",
      amostra: brutoIlegivel ? amostraSegura(brutoIlegivel) : "",
    };
  }

  globalThis.__jarvisSocial = {
    lerEstado,
    redeDoHost,
    contagemDoTitulo,
    lerContador,
    amostraSegura,
    alertaDaPagina,
    cabecalhoDoChat,
    conversaPeloNome,
    caixaDeTexto,
    versao: SELETORES.versao,
  };

  const id = redeDoHost(globalThis.location?.hostname ?? "");
  if (!id || !api?.runtime?.sendMessage) {
    return; // fora das redes (ou no teste): só as funções acima
  }

  let ultimo = "";
  let enviadoEm = 0;
  const nasceuEm = Date.now();

  function informar(forcar) {
    let estado;
    try {
      estado = lerEstado(id, document, { idadeMs: Date.now() - nasceuEm });
    } catch {
      estado = {
        rede: id,
        logado: false,
        naoLidas: 0,
        conversas: [],
        formato: "desconhecido",
        alerta: "",
        pista: "sem_lista",
        amostra: "",
      };
    }
    const assinatura = JSON.stringify(estado);
    const agora = Date.now();
    if (!forcar && assinatura === ultimo && agora - enviadoEm < VIVO_MS) {
      return estado;
    }
    ultimo = assinatura;
    enviadoEm = agora;
    Promise.resolve()
      .then(() => api.runtime.sendMessage({ tipo: "social", estado }))
      .catch(() => {
        // fundo da extensão reiniciando: o próximo tique manda de novo
      });
    return estado;
  }

  // O fundo pergunta o estado de agora (`social.estado`). `comando` fica de fora de propósito:
  // é o que o content.js atende, e as duas respostas disputariam a mesma mensagem.
  api.runtime.onMessage.addListener((mensagem, remetente, responder) => {
    if (remetente?.id !== api.runtime.id) {
      return false;
    }
    const rede = REDES[id];
    if (mensagem?.social === "estado") {
      responder(informar(true));
    } else if (mensagem?.social === "cabecalho" && rede?.cabecalho) {
      responder(cabecalhoDoChat(rede, document));
    } else if (mensagem?.social === "conversa" && rede?.cabecalho) {
      responder(conversaPeloNome(rede, document, String(mensagem.nome ?? "")));
    } else if (mensagem?.social === "caixa" && rede?.caixa) {
      responder(caixaDeTexto(rede, document));
    }
    return false;
  });

  const titulo = document.querySelector("title");
  if (titulo && typeof MutationObserver === "function") {
    new MutationObserver(() => informar(false)).observe(titulo, {
      childList: true,
      characterData: true,
      subtree: true,
    });
  }
  setInterval(() => informar(false), INTERVALO_MS);
  informar(true);
})();
