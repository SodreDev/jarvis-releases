import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const background = await readFile(
  new URL("../../../extensao/background.js", import.meta.url),
  "utf8",
);

class EventoFalso {
  listeners = [];

  addListener(listener) {
    this.listeners.push(listener);
  }

  emitir(...args) {
    for (const listener of this.listeners) {
      listener(...args);
    }
  }
}

class PortaFalsa {
  onMessage = new EventoFalso();
  onDisconnect = new EventoFalso();
  respostas = [];

  postMessage(mensagem) {
    this.respostas.push(mensagem);
  }
}

function carregar({ falhasAoConectar = [], aleatorio = 0.5, consultarAbas = async () => [] } = {}) {
  let agora = 0;
  let proximoTimer = 1;
  const timers = new Map();
  const portas = [];
  const avisos = [];
  const onStartup = new EventoFalso();
  const onInstalled = new EventoFalso();
  const runtime = {
    lastError: undefined,
    onStartup,
    onInstalled,
    connectNative(nome) {
      assert.equal(nome, "br.com.granafacil.jarvis");
      const falha = falhasAoConectar.shift();
      if (falha) {
        throw falha;
      }
      const porta = new PortaFalsa();
      portas.push(porta);
      return porta;
    },
  };
  const matematica = Object.create(Math);
  matematica.random = () => aleatorio;
  const contexto = vm.createContext({
    URL,
    Date: { now: () => agora },
    Math: matematica,
    chrome: {
      runtime,
      tabs: {
        query: consultarAbas,
      },
    },
    console: {
      warn: (...args) => avisos.push(args),
    },
    setTimeout(funcao, atraso) {
      const id = proximoTimer++;
      timers.set(id, { funcao, atraso });
      return id;
    },
  });

  vm.runInContext(background, contexto, { filename: "extensao/background.js" });

  return {
    avisos,
    onStartup,
    portas,
    timers,
    avancar(ms) {
      agora += ms;
    },
    desconectar(porta, motivo) {
      runtime.lastError = { message: motivo };
      porta.onDisconnect.emitir();
      runtime.lastError = undefined;
    },
    rodarProximoTimer() {
      const entrada = timers.entries().next().value;
      assert.ok(entrada, "era esperado um timer pendente");
      const [id, timer] = entrada;
      timers.delete(id);
      agora += timer.atraso;
      timer.funcao();
      return timer.atraso;
    },
  };
}

test("mantém somente uma porta e um timer de reconexão", () => {
  const cenario = carregar();
  assert.equal(cenario.portas.length, 1);
  assert.equal(cenario.timers.size, 0);

  const primeira = cenario.portas[0];
  cenario.desconectar(primeira, "Native host has exited.");
  cenario.desconectar(primeira, "evento repetido");
  cenario.onStartup.emitir();

  assert.equal(cenario.timers.size, 1);
  assert.equal(cenario.portas.length, 1);
  assert.equal(cenario.avisos[0][1].motivo, "Native host has exited.");
  assert.equal(cenario.avisos[0][1].tentativa, 1);
  assert.equal(cenario.avisos[0][1].atrasoMs, 250);

  assert.equal(cenario.rodarProximoTimer(), 250);
  assert.equal(cenario.portas.length, 2);
  assert.equal(cenario.timers.size, 0);
});

test("aplica backoff exponencial com teto e reinicia após tráfego válido", () => {
  const cenario = carregar();
  const atrasos = [];

  for (let indice = 0; indice < 10; indice += 1) {
    const porta = cenario.portas.at(-1);
    cenario.desconectar(porta, `queda ${indice + 1}`);
    atrasos.push(cenario.rodarProximoTimer());
  }

  assert.deepEqual(atrasos, [
    250,
    500,
    1_000,
    2_000,
    4_000,
    8_000,
    16_000,
    30_000,
    30_000,
    30_000,
  ]);

  const recuperada = cenario.portas.at(-1);
  recuperada.onMessage.emitir({ id: "pedido-1", method: "tabs.list", params: {} });
  cenario.desconectar(recuperada, "queda depois de mensagem");
  assert.equal(cenario.rodarProximoTimer(), 250);
});

test("falha síncrona ao conectar também agenda uma única tentativa", () => {
  const cenario = carregar({ falhasAoConectar: [new Error("manifesto ausente")] });

  assert.equal(cenario.portas.length, 0);
  assert.equal(cenario.timers.size, 1);
  assert.equal(cenario.avisos[0][1].motivo, "manifesto ausente");
  cenario.onStartup.emitir();
  assert.equal(cenario.timers.size, 1);

  assert.equal(cenario.rodarProximoTimer(), 250);
  assert.equal(cenario.portas.length, 1);
  assert.equal(cenario.timers.size, 0);
});

test("jitter é pequeno, respeita o teto e conexão estável reinicia o atraso", () => {
  const cedo = carregar({ aleatorio: 0 });
  cedo.desconectar(cedo.portas[0], "queda cedo");
  assert.equal(cedo.rodarProximoTimer(), 213);

  const tarde = carregar({ aleatorio: 1 });
  tarde.avancar(60_000);
  tarde.desconectar(tarde.portas[0], "queda depois de estável");
  assert.equal(tarde.rodarProximoTimer(), 288);

  for (let indice = 0; indice < 10; indice += 1) {
    tarde.desconectar(tarde.portas.at(-1), `queda ${indice}`);
    assert.ok(tarde.rodarProximoTimer() <= 30_000);
  }
});

test("resposta pendente de uma porta antiga não atravessa a reconexão", async () => {
  let concluirConsulta;
  const consulta = new Promise((resolve) => {
    concluirConsulta = resolve;
  });
  const cenario = carregar({ consultarAbas: () => consulta });
  const antiga = cenario.portas[0];

  antiga.onMessage.emitir({ id: "pedido-antigo", method: "tabs.list", params: {} });
  cenario.desconectar(antiga, "queda durante o pedido");
  cenario.rodarProximoTimer();
  const nova = cenario.portas[1];

  concluirConsulta([{ id: 1, windowId: 1, active: true }]);
  await consulta;
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(antiga.respostas, []);
  assert.deepEqual(nova.respostas, []);
});
