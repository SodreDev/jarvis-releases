import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

import { EventoFalso } from "./navegador_falso.mjs";

// A faixa "Jarvis no controle" (extensao/indicador.js, ADR-0027 regra 4) num DOM de mentira: o
// suficiente para ver onde ela entra, que a sombra é fechada, que o PARAR só vale com clique de
// verdade e que ela volta se a página a arrancar. A prova num navegador real é o roteiro em
// contêiner (tools/harness_navegador.py), que mede a faixa pela própria página.

const FONTE = await readFile(new URL("../../../extensao/indicador.js", import.meta.url), "utf8");

class Elemento {
  constructor(documento, tag) {
    this.documento = documento;
    this.tag = tag;
    this.filhos = [];
    this.pai = null;
    this.ouvintes = {};
    this.atributos = {};
    this.estilos = {};
    this.textContent = "";
    this.sombra = null;
    this.style = {
      setProperty: (propriedade, valor, prioridade) => {
        this.estilos[propriedade] = { valor, prioridade };
      },
    };
  }

  attachShadow({ mode }) {
    this.sombra = new Elemento(this.documento, "#sombra");
    this.sombra.modo = mode;
    this.sombra.pai = this;
    return this.sombra;
  }

  append(...filhos) {
    for (const filho of filhos) {
      filho.remove();
      filho.pai = this;
      this.filhos.push(filho);
    }
    this.documento.mudou(this);
  }

  remove() {
    if (!this.pai) {
      return;
    }
    const pai = this.pai;
    pai.filhos = pai.filhos.filter((filho) => filho !== this);
    this.pai = null;
    this.documento.mudou(pai);
  }

  get isConnected() {
    let no = this;
    while (no.pai) {
      no = no.pai;
    }
    return no === this.documento.documentElement;
  }

  addEventListener(tipo, funcao) {
    (this.ouvintes[tipo] ??= []).push(funcao);
  }

  setAttribute(nome, valor) {
    this.atributos[nome] = valor;
  }

  disparar(tipo, evento) {
    for (const funcao of this.ouvintes[tipo] ?? []) {
      funcao(evento);
    }
  }

  achar(tag) {
    for (const filho of [...this.filhos, ...(this.sombra ? [this.sombra] : [])]) {
      if (filho.tag === tag) {
        return filho;
      }
      const dentro = filho.achar(tag);
      if (dentro) {
        return dentro;
      }
    }
    return null;
  }
}

class Documento {
  constructor() {
    this.observadores = [];
    this.documentElement = new Elemento(this, "html");
  }

  createElement(tag) {
    return new Elemento(this, tag);
  }

  addEventListener() {}

  mudou(alvo) {
    for (const observador of this.observadores) {
      if (observador.alvo === alvo) {
        observador.funcao([]);
      }
    }
  }
}

function carregar({ noControle = false } = {}) {
  const documento = new Documento();
  const enviadas = [];
  const onMessage = new EventoFalso();
  const relogio = { pendentes: [] };
  const fundo = { ligado: noControle, recarregado: false };
  class Observador {
    constructor(funcao) {
      this.funcao = funcao;
    }

    observe(alvo) {
      this.alvo = alvo;
      documento.observadores.push(this);
    }

    disconnect() {
      documento.observadores = documento.observadores.filter((o) => o !== this);
    }
  }
  const contexto = vm.createContext({
    document: documento,
    MutationObserver: Observador,
    Promise,
    // O tempo da página é o do teste: a conferência periódica roda quando o teste manda.
    setTimeout(funcao) {
      relogio.pendentes.push(funcao);
      return relogio.pendentes.length;
    },
    clearTimeout() {},
    chrome: {
      runtime: {
        id: "jarvis",
        onMessage,
        async sendMessage(mensagem) {
          enviadas.push(mensagem);
          if (fundo.recarregado) {
            throw new Error("Extension context invalidated.");
          }
          return mensagem.tipo === "controle?" ? { ligado: fundo.ligado } : { paradas: 1 };
        },
      },
    },
  });
  vm.runInContext(FONTE, contexto, { filename: "extensao/indicador.js" });
  const faixa = () => documento.documentElement.filhos.find((f) => f.tag === "jarvis-no-controle");
  const fundoDiz = (ligado, id = "jarvis") => {
    let resposta;
    for (const listener of onMessage.listeners) {
      listener({ indicador: { ligado } }, { id }, (r) => {
        resposta = r;
      });
    }
    return resposta;
  };
  const passarOTempo = async () => {
    for (const funcao of relogio.pendentes.splice(0)) {
      funcao();
    }
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { documento, enviadas, faixa, fundoDiz, fundo, passarOTempo };
}

const umTique = () => new Promise((resolve) => setImmediate(resolve));

test("a página que nasce numa aba no controle já mostra a faixa, numa sombra fechada", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();

  const caixa = pagina.faixa();
  assert.ok(caixa, "a faixa entrou na página");
  assert.equal(caixa.sombra.modo, "closed", "os scripts da página não a leem nem mexem nela");
  assert.equal(caixa.estilos["z-index"].prioridade, "important");
  assert.equal(caixa.estilos["pointer-events"].valor, "none", "não bloqueia a página");
  const botao = caixa.achar("button");
  assert.equal(botao.textContent, "Parar");
  assert.equal(botao.tabIndex, -1, "fora da ordem do Tab");
  assert.equal(botao.estilos["pointer-events"].valor, "auto", "só o botão recebe o clique");
  assert.match(caixa.achar("span").textContent, /Jarvis no controle desta aba/u);
  assert.equal(JSON.stringify(pagina.enviadas), JSON.stringify([{ tipo: "controle?" }]));
});

test("aba fora do controle: nada na página", async () => {
  const pagina = carregar({ noControle: false });
  await umTique();

  assert.equal(pagina.faixa(), undefined);
});

test("o fundo liga e desliga a faixa; mensagem de outra extensão é ignorada", async () => {
  const pagina = carregar();
  await umTique();

  assert.equal(pagina.fundoDiz(true, "outra"), undefined);
  assert.equal(pagina.faixa(), undefined);
  assert.equal(JSON.stringify(pagina.fundoDiz(true)), '{"ligado":true}');
  assert.ok(pagina.faixa());
  assert.equal(JSON.stringify(pagina.fundoDiz(false)), '{"ligado":false}');
  assert.equal(pagina.faixa(), undefined, "some sozinha ao soltar");
});

test("PARAR: só o clique de verdade do dono manda parar, e a faixa some na hora", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();
  const botao = pagina.faixa().achar("button");
  const evento = (isTrusted) => ({ isTrusted, preventDefault() {}, stopPropagation() {} });

  botao.disparar("click", evento(false)); // a página tentando apertar por ele
  await umTique();
  assert.ok(pagina.faixa());
  assert.ok(!pagina.enviadas.some((m) => m.tipo === "parar"));

  botao.disparar("click", evento(true));
  await umTique();
  assert.equal(pagina.faixa(), undefined);
  assert.ok(pagina.enviadas.some((m) => m.tipo === "parar"));
});

test("apertar o PARAR não tira o foco do campo em que o dono estava", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();
  let impedido = false;

  pagina.faixa().achar("button").disparar("mousedown", {
    preventDefault() {
      impedido = true;
    },
  });

  assert.ok(impedido);
});

test("página que arranca a faixa: ela volta, até um limite (sem brigar sem fim)", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();

  pagina.faixa().remove();
  const voltou = Boolean(pagina.faixa());
  for (let vez = 0; vez < 30; vez += 1) {
    pagina.faixa()?.remove();
  }

  assert.ok(voltou, "voltou depois de arrancada");
  assert.equal(pagina.faixa(), undefined, "e desiste depois do limite");
});

test("a faixa confere de tempos em tempos: some se o fundo já soltou e o aviso se perdeu", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();

  await pagina.passarOTempo(); // ainda no controle: fica
  assert.ok(pagina.faixa());
  pagina.fundo.ligado = false; // o "soltar" não chegou a esta página
  await pagina.passarOTempo();

  assert.equal(pagina.faixa(), undefined);
});

test("extensão recarregada ou removida: a faixa da página órfã some sozinha", async () => {
  const pagina = carregar({ noControle: true });
  await umTique();

  pagina.fundo.recarregado = true;
  await pagina.passarOTempo();

  assert.equal(pagina.faixa(), undefined);
});
