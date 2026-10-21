import assert from "node:assert/strict";
import test from "node:test";

import { NavegadorFalso, pedir } from "./navegador_falso.mjs";

// O indicador e o PARAR (ADR-0027, regra 4): enquanto o Jarvis age numa aba, ela mostra a faixa
// "no controle" e o botão da extensão o selo; o Jarvis solta no fim do pedido; o PARAR do dono
// solta na hora, revoga a concessão e avisa o Jarvis pelo host.

const DONO = { id: 1, abas: [{ id: 7, url: "https://exemplo.org/", title: "Exemplo" }] };
const CONCESSAO = "a1b2c3d4e5f60708";

test("pedido com concessão liga a faixa da aba antes de agir, e o selo do botão", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const lido = await pedir(porta, {
    id: "c1",
    method: "page.read",
    params: { tabId: 7, controle: CONCESSAO },
  });

  assert.equal(lido.ok, true);
  const ordem = nav.mensagens.map((m) => (m.mensagem.indicador ? "faixa" : m.mensagem.comando));
  assert.deepEqual(ordem, ["faixa", "ler"], "a faixa vai antes da leitura");
  assert.equal(nav.aba(7).faixa, true);
  assert.equal(nav.selo.texto, "IA");
  assert.match(nav.selo.titulo, /no controle de uma aba/u);
});

test("pedido sem concessão (o modo de antes) não liga faixa nenhuma", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  await pedir(porta, { id: "c2", method: "page.read", params: { tabId: 7 } });

  assert.deepEqual(nav.faixas(7), []);
  assert.equal(nav.selo.texto, "");
});

test("controle.soltar tira a faixa das abas daquela concessão e apaga o selo", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c3", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  const solta = await pedir(porta, {
    id: "c4",
    method: "controle.soltar",
    params: { controle: CONCESSAO },
  });

  assert.deepEqual(solta.result, { soltas: 1 });
  assert.deepEqual(nav.faixas(7), [true, false]);
  assert.equal(nav.aba(7).faixa, false);
  assert.equal(nav.selo.texto, "");
});

test("a página que nasce pergunta e só a aba no controle recebe a faixa", async () => {
  const nav = new NavegadorFalso({
    janelas: [
      {
        id: 1,
        abas: [
          { id: 7, url: "https://exemplo.org/", title: "Exemplo" },
          { id: 8, url: "https://outro.example/", title: "Outro", active: false },
        ],
      },
    ],
  });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c5", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  assert.deepEqual(await nav.conteudoDiz(7, { tipo: "controle?" }), { ligado: true });
  assert.deepEqual(await nav.conteudoDiz(8, { tipo: "controle?" }), { ligado: false });
  const deFora = await nav.conteudoDiz(7, { tipo: "controle?" }, { id: "outra", tab: { id: 7 } });
  assert.equal(deFora, undefined, "mensagem de outra extensão não é respondida");
});

test("PARAR na faixa: solta, revoga, avisa o host, e o pedido seguinte daquela concessão é recusado", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c6", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  await nav.conteudoDiz(7, { tipo: "parar" });
  const depois = await pedir(porta, {
    id: "c7",
    method: "page.click",
    params: { tabId: 7, alvo: "Enviar", controle: CONCESSAO },
  });
  const outra = await pedir(porta, {
    id: "c8",
    method: "page.read",
    params: { tabId: 7, controle: "ffffeeeeddddcccc" },
  });

  assert.deepEqual(
    porta.enviadas.find((m) => m.evento),
    { evento: "parar", concessoes: [CONCESSAO], origem: "faixa" },
    "o host recebe o evento, e por ele o Jarvis para o turno e a tarefa",
  );
  assert.equal(depois.ok, false);
  assert.equal(depois.error.codigo, "parado_pelo_dono");
  assert.ok(!nav.mensagens.some((m) => m.mensagem.comando === "clicar"), "nada clicou");
  assert.equal(outra.ok, true, "um pedido novo do dono volta a agir");
  assert.equal(nav.faixas(7).at(-1), true);
});

test("PARAR no botão da extensão na barra faz o mesmo", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c9", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  nav.onClicked.emitir({ id: 7 });
  await new Promise((resolve) => setTimeout(resolve, 5)); // a faixa e o selo saem em seguida

  assert.deepEqual(porta.enviadas.find((m) => m.evento), {
    evento: "parar",
    concessoes: [CONCESSAO],
    origem: "barra",
  });
  assert.equal(nav.aba(7).faixa, false);
  assert.equal(nav.selo.texto, "");
});

test("botão da barra sem nada no controle não manda evento", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  nav.onClicked.emitir({ id: 7 });

  assert.equal(porta.enviadas.length, 0);
});

test("controle.parar (a janela do Jarvis) solta e revoga sem mandar evento", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c10", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  const parada = await pedir(porta, { id: "c11", method: "controle.parar", params: {} });
  const depois = await pedir(porta, {
    id: "c12",
    method: "controle.manter",
    params: { controle: CONCESSAO },
  });

  assert.deepEqual(parada.result, { paradas: [CONCESSAO] });
  assert.equal(nav.aba(7).faixa, false);
  assert.ok(!porta.enviadas.some((m) => m.evento));
  assert.equal(depois.error.codigo, "parado_pelo_dono");
});

test("sem controle.manter a faixa some sozinha (o Jarvis caiu); com ele, fica", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo(); // prazos ÷ 50: os 30 s viram 600 ms
  await pedir(porta, { id: "c13", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });
  const outra = "0011223344556677";
  await pedir(porta, {
    id: "c14",
    method: "page.read",
    params: { tabId: 7, controle: outra },
  });
  for (let volta = 0; volta < 4; volta += 1) {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await pedir(porta, { id: `m${volta}`, method: "controle.manter", params: { controle: outra } });
  }

  const estado = await pedir(porta, { id: "c15", method: "controle.estado", params: {} });

  assert.deepEqual(estado.result.concessoes, [outra], "a mantida fica; a outra soltou sozinha");
});

test("aba nova (tabs.open) nasce no controle: a faixa vai antes de a página responder", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();

  const aberta = await pedir(porta, {
    id: "c16",
    method: "tabs.open",
    params: { url: "https://www.youtube.com/", controle: CONCESSAO },
  });

  const nova = aberta.result.aba.id;
  const daNova = nav.mensagens.filter((m) => m.tabId === nova);
  assert.equal(daNova[0].mensagem.indicador?.ligado, true, "a faixa primeiro");
  assert.equal(nav.aba(nova).faixa, true);
});

test("aba fechada sai do controle e o selo acompanha", async () => {
  const nav = new NavegadorFalso({ janelas: [DONO] });
  const porta = nav.carregarFundo();
  await pedir(porta, { id: "c17", method: "page.read", params: { tabId: 7, controle: CONCESSAO } });

  await nav.api().tabs.remove(7);
  await new Promise((resolve) => setTimeout(resolve, 5));

  assert.equal(nav.selo.texto, "");
});
