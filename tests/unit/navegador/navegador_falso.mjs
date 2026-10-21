import { readFile } from "node:fs/promises";
import vm from "node:vm";

// Um navegador de mentira, com janelas, abas e os eventos delas, para rodar o `background.js` de
// verdade numa VM. O que ele imita foi visto no Chromium 155 e no Firefox 158 reais (contêiner,
// 2026-10-21): o `tabs.update` responde na hora com a URL de ANTES; a aba passa por "loading" e
// "complete"; página sem rede vira página de erro do navegador, sem o conteúdo da extensão.

export const FONTE_DO_FUNDO = await readFile(
  new URL("../../../extensao/background.js", import.meta.url),
  "utf8",
);
export const ORIGEM = "chrome-extension://teste/";

export class EventoFalso {
  listeners = [];

  addListener(listener) {
    this.listeners.push(listener);
  }

  removeListener(listener) {
    this.listeners = this.listeners.filter((outro) => outro !== listener);
  }

  hasListener(listener) {
    return this.listeners.includes(listener);
  }

  emitir(...args) {
    for (const listener of [...this.listeners]) {
      listener(...args);
    }
  }
}

class PortaFalsa {
  onMessage = new EventoFalso();
  onDisconnect = new EventoFalso();
  respostas = [];
  enviadas = [];

  postMessage(mensagem) {
    this.enviadas.push(JSON.parse(JSON.stringify(mensagem)));
    this.respostas.push(mensagem);
  }
}

const proximo = () => new Promise((resolve) => setImmediate(resolve));

export class NavegadorFalso {
  /**
   * @param {object} opcoes
   * @param {Array} opcoes.janelas `[{ id, tipo, abas: [{ id, url, title, active }] }]`
   * @param {number} opcoes.foco a janela em foco (-1 = o navegador está atrás de outro programa)
   * @param {boolean} opcoes.roubaFoco janela criada "sem foco" fica em foco (o Firefox pode fazer)
   * @param {Set<string>} opcoes.semRede hosts que viram página de erro do navegador
   * @param {Set<string>} opcoes.seguraSaida hosts cuja página segura a saída (nem começa a navegar)
   */
  constructor({
    janelas = [{ id: 1, abas: [{ id: 7, url: "https://exemplo.org/", title: "Exemplo" }] }],
    foco = 1,
    roubaFoco = false,
    semRede = new Set(),
    seguraSaida = new Set(),
    focoNegado = false,
  } = {}) {
    this.janelas = new Map();
    this.abas = new Map();
    this.foco = foco;
    this.roubaFoco = roubaFoco;
    this.semRede = semRede;
    this.seguraSaida = seguraSaida;
    this.focoNegado = focoNegado;
    this.proximaAba = 100;
    this.proximaJanela = 50;
    this.criadas = [];
    this.focadas = [];
    this.atualizadas = [];
    this.movidas = [];
    this.mensagens = [];
    this.portas = [];
    this.onUpdated = new EventoFalso();
    this.onRemoved = new EventoFalso();
    this.onMessage = new EventoFalso();
    this.onClicked = new EventoFalso();
    this.selo = { texto: "", cor: "", titulo: "" };
    for (const janela of janelas) {
      this.janelas.set(janela.id, { id: janela.id, tipo: janela.tipo ?? "normal" });
      for (const [indice, aba] of (janela.abas ?? []).entries()) {
        this.abas.set(aba.id, {
          id: aba.id,
          windowId: janela.id,
          index: indice,
          active: aba.active ?? indice === 0,
          url: aba.url,
          title: aba.title ?? "",
          status: "complete",
          erro: false,
        });
      }
    }
  }

  aba(id) {
    const aba = this.abas.get(id);
    if (!aba) {
      throw new Error(`No tab with id: ${id}.`);
    }
    return { ...aba };
  }

  abasDa(janelaId) {
    return [...this.abas.values()].filter((aba) => aba.windowId === janelaId);
  }

  janela(id) {
    const janela = this.janelas.get(id);
    if (!janela) {
      throw new Error(`No window with id: ${id}.`);
    }
    return { id, type: janela.tipo, focused: this.foco === id };
  }

  ativar(id) {
    const aba = this.abas.get(id);
    for (const outra of this.abasDa(aba.windowId)) {
      outra.active = outra.id === id;
    }
  }

  async navegar(id, url) {
    // Como o navegador: começa a carregar no tique seguinte e termina depois.
    const aba = this.abas.get(id);
    if (this.seguraSaida.has(new URL(aba.url).host)) {
      return; // beforeunload: a aba fica onde está
    }
    await proximo();
    aba.status = "loading";
    this.onUpdated.emitir(id, { status: "loading", url }, { ...aba, url });
    await proximo();
    const host = new URL(url).host;
    aba.url = url;
    aba.erro = this.semRede.has(host);
    aba.title = aba.erro ? host : `Página de ${host}`;
    if (!aba.erro) {
      // O indicador.js da página nova pergunta ao nascer se a aba está no controle.
      const resposta = await this.conteudoDiz(id, { tipo: "controle?" });
      aba.faixa = resposta?.ligado === true;
    }
    aba.status = "complete";
    this.onUpdated.emitir(id, { status: "complete" }, { ...aba });
  }

  responderDoConteudo(aba, mensagem) {
    if (aba.erro || !/^https?:/u.test(aba.url)) {
      throw new Error("Could not establish connection. Receiving end does not exist.");
    }
    if (mensagem.indicador) {
      aba.faixa = mensagem.indicador.ligado === true; // o indicador.js da página
      return { ligado: aba.faixa };
    }
    if (mensagem.comando === "estado") {
      return { ok: true, result: { url: aba.url, titulo: aba.title } };
    }
    return { ok: true, result: {} };
  }

  api() {
    const nav = this;
    return {
      action: {
        async setBadgeText({ text }) {
          nav.selo.texto = text;
        },
        async setBadgeBackgroundColor({ color }) {
          nav.selo.cor = color;
        },
        async setTitle({ title }) {
          nav.selo.titulo = title;
        },
        onClicked: nav.onClicked,
      },
      runtime: {
        id: "teste",
        lastError: undefined,
        onStartup: new EventoFalso(),
        onInstalled: new EventoFalso(),
        onMessage: nav.onMessage,
        getURL: (caminho) => `${ORIGEM}${caminho}`,
        connectNative() {
          const porta = new PortaFalsa();
          nav.portas.push(porta);
          return porta;
        },
      },
      windows: {
        async getLastFocused(filtro = {}) {
          const tipos = filtro.windowTypes;
          const candidata = nav.janelas.get(nav.foco) ?? nav.janelas.get(nav.ultimaFocada);
          if (candidata && (!tipos || tipos.includes(candidata.tipo))) {
            return nav.janela(candidata.id);
          }
          const normal = [...nav.janelas.values()].find((j) => !tipos || tipos.includes(j.tipo));
          if (!normal) {
            throw new Error("No last-focused window");
          }
          return nav.janela(normal.id);
        },
        async get(id) {
          return nav.janela(id);
        },
        async getAll(filtro = {}) {
          const tipos = filtro.windowTypes;
          return [...nav.janelas.values()]
            .filter((j) => !tipos || tipos.includes(j.tipo))
            .map((j) => nav.janela(j.id));
        },
        async create(opcoes) {
          nav.criadas.push(JSON.parse(JSON.stringify(opcoes)));
          const id = nav.proximaJanela;
          nav.proximaJanela += 1;
          nav.janelas.set(id, { id, tipo: opcoes.type ?? "normal" });
          const abaId = nav.proximaAba;
          nav.proximaAba += 1;
          nav.abas.set(abaId, {
            id: abaId,
            windowId: id,
            index: 0,
            active: true,
            url: opcoes.url ?? "about:blank",
            title: "Janela de trabalho do Jarvis",
            status: "complete",
            erro: false,
          });
          if (opcoes.focused !== false || nav.roubaFoco) {
            nav.foco = id;
          }
          return nav.janela(id);
        },
        async update(id, opcoes) {
          nav.focadas.push({ id, ...opcoes });
          if (opcoes.focused && !nav.focoNegado) {
            nav.foco = id;
          }
          return nav.janela(id);
        },
      },
      tabs: {
        onUpdated: nav.onUpdated,
        onRemoved: nav.onRemoved,
        async query(filtro = {}) {
          let abas = [...nav.abas.values()];
          if (filtro.active !== undefined) {
            abas = abas.filter((aba) => aba.active === filtro.active);
          }
          if (filtro.windowId !== undefined) {
            abas = abas.filter((aba) => aba.windowId === filtro.windowId);
          }
          if (filtro.currentWindow || filtro.lastFocusedWindow) {
            // No service worker a "janela atual" é a última em foco, de qualquer tipo.
            abas = abas.filter((aba) => aba.windowId === nav.foco);
          }
          if (filtro.windowType !== undefined) {
            abas = abas.filter((aba) => nav.janelas.get(aba.windowId)?.tipo === filtro.windowType);
          }
          return abas.map((aba) => ({ ...aba }));
        },
        async get(id) {
          return nav.aba(id);
        },
        async create(opcoes) {
          const id = nav.proximaAba;
          nav.proximaAba += 1;
          const janelaId = opcoes.windowId ?? nav.foco;
          nav.abas.set(id, {
            id,
            windowId: janelaId,
            index: nav.abasDa(janelaId).length,
            active: false,
            url: "about:blank",
            title: "",
            status: "loading",
            erro: false,
          });
          if (opcoes.active) {
            nav.ativar(id);
          }
          nav.criadas.push({ aba: id, ...JSON.parse(JSON.stringify(opcoes)) });
          void nav.navegar(id, opcoes.url);
          return nav.aba(id);
        },
        async update(id, opcoes) {
          nav.atualizadas.push({ id, ...opcoes });
          if (opcoes.active) {
            nav.ativar(id);
          }
          const antes = nav.aba(id);
          if (opcoes.url) {
            void nav.navegar(id, opcoes.url);
          }
          return antes; // a URL de ANTES, como o navegador de verdade
        },
        async move(id, opcoes) {
          nav.movidas.push({ id, ...opcoes });
          const aba = nav.abas.get(id);
          aba.windowId = opcoes.windowId;
          aba.index = nav.abasDa(opcoes.windowId).length;
          aba.active = false;
          return nav.aba(id);
        },
        async remove(id) {
          nav.abas.delete(id);
          nav.onRemoved.emitir(id, {});
        },
        async sendMessage(id, mensagem) {
          nav.mensagens.push({ tabId: id, mensagem: JSON.parse(JSON.stringify(mensagem)) });
          nav.aba(id); // aba que não existe: o erro do navegador
          return nav.responderDoConteudo(nav.abas.get(id), mensagem);
        },
      },
    };
  }

  /** O conteúdo de uma aba (o indicador.js) manda uma mensagem ao fundo e espera a resposta. */
  conteudoDiz(tabId, mensagem, remetente = { id: "teste", tab: { id: tabId } }) {
    return new Promise((resolve) => {
      let respondida = false;
      for (const listener of [...this.onMessage.listeners]) {
        listener(mensagem, remetente, (resposta) => {
          respondida = true;
          resolve(JSON.parse(JSON.stringify(resposta ?? null)));
        });
      }
      if (!respondida) {
        setTimeout(() => resolve(undefined), 5);
      }
    });
  }

  /** As mensagens da faixa que o fundo mandou a uma aba, em ordem. */
  faixas(tabId) {
    return this.mensagens
      .filter((m) => m.tabId === tabId && m.mensagem.indicador)
      .map((m) => m.mensagem.indicador.ligado);
  }

  /** Carrega o `background.js` numa VM nova sobre este navegador (de novo = o worker reiniciou). */
  carregarFundo({ escala = 50 } = {}) {
    // O relógio do fundo anda na mesma escala dos prazos encolhidos.
    const zero = Date.now();
    const relogio = { now: () => zero + (Date.now() - zero) * escala };
    const contexto = vm.createContext({
      URL,
      Date: relogio,
      Math,
      chrome: this.api(),
      console: { warn() {}, log() {} },
      // Os prazos do fundo encolhidos (4 s viram 80 ms): o teste anda sem esperar de verdade.
      setTimeout: (funcao, ms = 0) => setTimeout(funcao, ms / escala),
      clearTimeout: (id) => clearTimeout(id),
    });
    vm.runInContext(FONTE_DO_FUNDO, contexto, { filename: "extensao/background.js" });
    return this.portas.at(-1);
  }
}

/** Manda um pedido do host e espera a resposta (como JSON, que é o que o host lê). */
export async function pedir(porta, pedido, voltas = 400) {
  const antes = porta.respostas.length;
  porta.onMessage.emitir(pedido);
  for (let volta = 0; volta < voltas && porta.respostas.length === antes; volta += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  if (porta.respostas.length === antes) {
    throw new Error(`a extensão não respondeu a ${pedido.method}`);
  }
  return JSON.parse(JSON.stringify(porta.respostas.at(-1)));
}
