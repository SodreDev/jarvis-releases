import assert from "node:assert/strict";
import test from "node:test";

import { NavegadorFalso, pedir } from "./navegador_falso.mjs";

// Navegador por CDP (ADR-0051): console, rede, avaliar JS no mundo isolado e gestos físicos pelo
// `chrome.debugger`, com recuo para `chrome.scripting` e a limitação do Firefox (sem CDP).

const DONO = { id: 1, abas: [{ id: 7, url: "https://loja.exemplo/p", title: "Loja" }] };
const CONCESSAO = "a1b2c3d4e5f60708";

function params(extra = {}) {
  return { tabId: 7, controle: CONCESSAO, ...extra };
}

test("avaliar anexa o depurador, cria o mundo isolado e roda Runtime.evaluate", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  nav.valorEval = "42 itens";

  const r = await pedir(porta, {
    id: "e1",
    method: "page.eval",
    params: params({ codigo: "document.title", mundo: "isolado" }),
  });

  assert.equal(r.ok, true);
  assert.deepEqual(r.result, { valor: "42 itens", mundo: "isolado", cdp: true, recuo: null });
  assert.ok(nav.anexadas.has(7), "anexou o chrome.debugger à aba");
  const metodos = nav.comandosCdp.map((c) => c.metodo);
  assert.ok(metodos.includes("Runtime.enable"), "ligou os domínios");
  assert.ok(metodos.includes("Page.createIsolatedWorld"), "criou o mundo isolado");
  const evalParams = nav.comandosCdp.find((c) => c.metodo === "Runtime.evaluate").params;
  assert.equal(evalParams.contextId, 99, "rodou no contexto do mundo isolado");
  assert.equal(evalParams.returnByValue, true);
});

test("avaliar no mundo principal não cria mundo isolado", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const r = await pedir(porta, {
    id: "e2",
    method: "page.eval",
    params: params({ codigo: "1+1", mundo: "principal" }),
  });

  assert.equal(r.result.mundo, "principal");
  const metodos = nav.comandosCdp.map((c) => c.metodo);
  assert.ok(!metodos.includes("Page.createIsolatedWorld"));
  const evalParams = nav.comandosCdp.find((c) => c.metodo === "Runtime.evaluate").params;
  assert.equal(evalParams.contextId, undefined, "sem contexto: o mundo da própria página");
});

test("o console e a rede vêm dos eventos do CDP, com anexado=true", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  // Anexa primeiro (qualquer tool de CDP anexa), depois o navegador emite os eventos.
  await pedir(porta, { id: "a0", method: "page.console", params: params() });
  nav.eventoCdp(7, "Runtime.consoleAPICalled", {
    type: "error",
    args: [{ value: "Uncaught TypeError" }],
    timestamp: 1,
  });
  nav.eventoCdp(7, "Network.requestWillBeSent", {
    requestId: "r1",
    request: { method: "GET", url: "https://loja.exemplo/api" },
    type: "XHR",
  });
  nav.eventoCdp(7, "Network.responseReceived", { requestId: "r1", response: { status: 500 }, type: "XHR" });

  const console = await pedir(porta, { id: "c1", method: "page.console", params: params() });
  const rede = await pedir(porta, { id: "n1", method: "page.network", params: params() });

  assert.equal(console.result.anexado, true);
  assert.deepEqual(console.result.mensagens.at(-1), {
    nivel: "error",
    texto: "Uncaught TypeError",
    origem: "console",
    hora: 1,
  });
  assert.equal(rede.result.pedidos.at(-1).status, 500);
  assert.equal(rede.result.pedidos.at(-1).metodo, "GET");
  assert.ok(!("requestId" in rede.result.pedidos.at(-1)), "o requestId interno não vaza");
});

test("gesto rolar manda mouseWheel; clicar manda mousePressed/Released no centro do elemento", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  // O conteúdo responde o inspecionar com o centro do elemento (ADR-0051).
  nav.responderDoConteudo = (_aba, msg) =>
    msg.comando === "inspecionar"
      ? { ok: true, result: { tag: "button", centro: [120, 40], rotulo: "Pagar" } }
      : { ok: true, result: {} };

  const rolar = await pedir(porta, {
    id: "g1",
    method: "page.gesture",
    params: params({ gesto: "rolar", pixels: 300 }),
  });
  assert.equal(rolar.result.feito, true);
  const wheel = nav.comandosCdp.find((c) => c.metodo === "Input.dispatchMouseEvent");
  assert.equal(wheel.params.type, "mouseWheel");
  assert.equal(wheel.params.deltaY, 300);

  nav.comandosCdp.length = 0;
  const clicar = await pedir(porta, {
    id: "g2",
    method: "page.gesture",
    params: params({ gesto: "clicar", ref: "ab12.1" }),
  });
  assert.equal(clicar.result.feito, true);
  const cliques = nav.comandosCdp.filter((c) => c.metodo === "Input.dispatchMouseEvent");
  assert.deepEqual(
    cliques.map((c) => c.params.type),
    ["mouseMoved", "mousePressed", "mouseReleased"],
    "o ponteiro passa pelo alvo (hover) antes de apertar e soltar",
  );
  assert.equal(cliques[1].params.x, 120);
  assert.equal(cliques[1].params.y, 40);
  assert.equal(cliques[1].params.buttons, 1, "o mousePressed leva o botão esquerdo no bitmask");
});

test("soltar o controle desanexa o depurador da aba", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "e3", method: "page.eval", params: params({ codigo: "1" }) });
  assert.ok(nav.anexadas.has(7));

  await pedir(porta, { id: "s1", method: "controle.soltar", params: { controle: CONCESSAO } });

  assert.ok(!nav.anexadas.has(7), "o depurador foi desanexado ao soltar o controle");
});

test("no Firefox (sem chrome.debugger) avaliar recua para chrome.scripting", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  nav.semCdp = true;
  nav.resultadoScripting = { ok: true, v: "pelo scripting" };
  const porta = nav.carregarFundo();

  const r = await pedir(porta, {
    id: "f1",
    method: "page.eval",
    params: params({ codigo: "document.title", mundo: "isolado" }),
  });

  assert.equal(r.result.valor, "pelo scripting");
  assert.equal(r.result.cdp, false);
  assert.equal(r.result.recuo, "chrome.scripting");
  assert.deepEqual(nav.scriptingMundos, ["ISOLATED"]);
});

test("no Firefox o console diz que não há CDP, sem inventar dado", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  nav.semCdp = true;
  const porta = nav.carregarFundo();

  const r = await pedir(porta, { id: "f2", method: "page.console", params: params() });

  assert.equal(r.result.anexado, false);
  assert.deepEqual(r.result.mensagens, []);
  assert.equal(r.result.motivo, "sem_cdp_no_firefox");
});
