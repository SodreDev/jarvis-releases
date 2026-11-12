/*
 * O monitor das redes sociais (ADR-0060), SOMENTE LEITURA: só roda nos hosts das cinco redes
 * (manifest.json) e só lê o título, o contador de não lidas e quem mandou. Não clica, não digita,
 * não rola e não lê o texto das mensagens (mapear o formato delas é para depois).
 *
 * O estado vai ao fundo da extensão (`{tipo: "social"}`), que o repassa ao Jarvis como evento —
 * só quando muda, e uma vez por minuto para o Jarvis saber que a aba continua viva. Os seletores
 * de cada rede ficam todos aqui, num bloco por rede: quando a página mudar, é só aqui que mexe, e
 * o que não se reconhece vira "formato desconhecido" em vez de um número errado.
 */

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const INTERVALO_MS = 15_000; // releitura de reserva: o título é observado
  const VIVO_MS = 60_000;
  const MAX_CONVERSAS = 20;
  const MAX_NOME = 80;
  const MAX_CONTAGEM = 9_999;

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

  function contagem(texto) {
    const achado = /\d+/u.exec(String(texto ?? ""));
    if (!achado) {
      return 0;
    }
    return Math.min(MAX_CONTAGEM, Number.parseInt(achado[0], 10));
  }

  function contagemDoTitulo(titulo) {
    // "(3) WhatsApp", "(12) Discord | #geral": o número entre parênteses no começo.
    const achado = /^\s*\((\d{1,4})\+?\)/u.exec(String(titulo ?? ""));
    return achado ? Math.min(MAX_CONTAGEM, Number.parseInt(achado[1], 10)) : 0;
  }

  function conversasNaoLidas(raiz, rede) {
    const saida = [];
    for (const linha of todos(raiz, rede.conversa)) {
      const selo = primeiro(linha, rede.selo);
      if (!selo) {
        continue;
      }
      const naoLidas = contagem(selo.textContent || selo.getAttribute?.("aria-label"));
      const elementoDoNome = primeiro(linha, rede.nome);
      const nome = limpo(
        elementoDoNome?.getAttribute?.("title") || elementoDoNome?.textContent,
        MAX_NOME,
      );
      if (naoLidas > 0 && nome) {
        saida.push({ nome, naoLidas });
      }
      if (saida.length >= MAX_CONVERSAS) {
        break;
      }
    }
    return saida;
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

  // Exportada para o teste (tests/unit/social/social.test.mjs), que a roda contra as páginas
  // falsas de tests/unit/social/paginas/ — nunca contra a rede de verdade.
  function lerEstado(id, documento) {
    const rede = REDES[id];
    if (!rede) {
      return {
        rede: id,
        logado: false,
        naoLidas: 0,
        conversas: [],
        formato: "desconhecido",
        alerta: "",
      };
    }
    const alerta = alertaDaPagina(documento);
    const naoLidasDoTitulo = contagemDoTitulo(documento.title);
    if (existe(documento, rede.login)) {
      return { rede: id, logado: false, naoLidas: 0, conversas: [], formato: "conhecido", alerta };
    }
    // O canário: logado, pelo menos um elemento essencial tem de existir. Sem ele, a página mudou
    // e a rede degrada para só notificar — nunca se chuta um elemento parecido.
    if (!existe(documento, rede.essenciais)) {
      return {
        rede: id,
        logado: false,
        naoLidas: naoLidasDoTitulo,
        conversas: [],
        formato: "desconhecido",
        alerta,
      };
    }
    const conversas = conversasNaoLidas(documento, rede);
    const somadas = conversas.reduce((total, conversa) => total + conversa.naoLidas, 0);
    return {
      rede: id,
      logado: true,
      naoLidas: Math.min(MAX_CONTAGEM, Math.max(naoLidasDoTitulo, somadas)),
      conversas,
      formato: "conhecido",
      alerta,
    };
  }

  globalThis.__jarvisSocial = {
    lerEstado,
    redeDoHost,
    contagemDoTitulo,
    alertaDaPagina,
    versao: SELETORES.versao,
  };

  const id = redeDoHost(globalThis.location?.hostname ?? "");
  if (!id || !api?.runtime?.sendMessage) {
    return; // fora das redes (ou no teste): só as funções acima
  }

  let ultimo = "";
  let enviadoEm = 0;

  function informar(forcar) {
    let estado;
    try {
      estado = lerEstado(id, document);
    } catch {
      estado = {
        rede: id,
        logado: false,
        naoLidas: 0,
        conversas: [],
        formato: "desconhecido",
        alerta: "",
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
    if (mensagem?.social !== "estado" || remetente?.id !== api.runtime.id) {
      return false;
    }
    responder(informar(true));
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
