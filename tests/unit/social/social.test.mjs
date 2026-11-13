import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

// O monitor das redes (extensao/social.js, ADR-0060) contra PÁGINAS FALSAS (./paginas/*.html),
// num DOM mínimo feito aqui: o suficiente para os seletores que o script usa (tag, #id, .classe,
// [atributo], [atributo='v'], [atributo*='v'], descendente e vírgula). Nenhuma rede de verdade,
// nenhum navegador, nenhuma conta.

const FONTE = await readFile(new URL("../../../extensao/social.js", import.meta.url), "utf8");
const DADOS = await readFile(
  new URL("../../../extensao/social-seletores.js", import.meta.url),
  "utf8",
);
const VAZIOS = new Set(["input", "img", "br", "meta", "link", "hr", "source"]);

function decodificar(texto) {
  return texto
    .replace(/&#x([0-9a-f]+);/giu, (_, h) => String.fromCodePoint(Number.parseInt(h, 16)))
    .replace(/&#(\d+);/gu, (_, d) => String.fromCodePoint(Number.parseInt(d, 10)))
    .replace(/&lt;/gu, "<")
    .replace(/&gt;/gu, ">")
    .replace(/&quot;/gu, '"')
    .replace(/&amp;/gu, "&");
}

class No {
  constructor(tag, atributos = {}) {
    this.tag = tag;
    this.atributos = atributos;
    this.filhos = [];
    this.pai = null;
  }

  get textContent() {
    return this.filhos.map((f) => (typeof f === "string" ? f : f.textContent)).join("");
  }

  getBoundingClientRect() {
    // Uma caixa fixa: o DOM de teste não tem layout; o script só precisa do centro.
    return { left: 10, top: 20, width: 100, height: 30 };
  }

  getAttribute(nome) {
    return Object.hasOwn(this.atributos, nome) ? this.atributos[nome] : null;
  }

  *descendentes() {
    for (const filho of this.filhos) {
      if (typeof filho !== "string") {
        yield filho;
        yield* filho.descendentes();
      }
    }
  }

  querySelectorAll(seletores) {
    const grupos = partir(seletores, ",").map((s) => partir(s.trim(), " ").map(compilar));
    const achados = [];
    for (const no of this.descendentes()) {
      if (grupos.some((partes) => casa(no, partes, this))) {
        achados.push(no);
      }
    }
    return achados;
  }

  querySelector(seletores) {
    return this.querySelectorAll(seletores)[0] ?? null;
  }
}

function partir(texto, separador) {
  // Separa por vírgula ou espaço, mas não dentro de [atributo='valor com espaço'].
  const partes = [];
  let atual = "";
  let dentro = 0;
  for (const c of texto) {
    if (c === "[") dentro += 1;
    if (c === "]") dentro -= 1;
    if (!dentro && (separador === " " ? /\s/u.test(c) : c === separador)) {
      if (atual.trim()) partes.push(atual.trim());
      atual = "";
    } else {
      atual += c;
    }
  }
  if (atual.trim()) partes.push(atual.trim());
  return partes;
}

function compilar(simples) {
  const resto = simples.replace(/\[[^\]]+\]/gu, "");
  if (/[>+~:]/u.test(resto)) {
    throw new SyntaxError(`seletor fora do DOM de teste: ${simples}`);
  }
  const tag = /^[a-z][a-z0-9-]*/iu.exec(resto)?.[0];
  const id = /#([\w-]+)/u.exec(resto)?.[1];
  const classes = [...resto.matchAll(/\.([\w-]+)/gu)].map((m) => m[1]);
  const atributos = [...simples.matchAll(/\[([\w-]+)(?:(\*?=)'([^']*)')?\]/gu)].map((m) => ({
    nome: m[1],
    op: m[2],
    valor: m[3],
  }));
  return (no) => {
    if (tag && no.tag !== tag.toLowerCase()) return false;
    if (id && no.getAttribute("id") !== id) return false;
    const deClasse = (no.getAttribute("class") ?? "").split(/\s+/u);
    if (!classes.every((c) => deClasse.includes(c))) return false;
    return atributos.every(({ nome, op, valor }) => {
      const atual = no.getAttribute(nome);
      if (atual === null) return false;
      if (op === "=") return atual === valor;
      if (op === "*=") return atual.includes(valor);
      return true;
    });
  };
}

function casa(no, partes, raiz) {
  // A última parte casa o próprio nó; as anteriores, ancestrais em ordem (descendente).
  if (!partes[partes.length - 1](no)) return false;
  let indice = partes.length - 2;
  let atual = no.pai;
  while (indice >= 0 && atual && atual !== raiz.pai) {
    if (partes[indice](atual)) indice -= 1;
    atual = atual.pai;
  }
  return indice < 0;
}

function analisar(html) {
  const raiz = new No("#documento");
  let atual = raiz;
  const marcas = /<!--[\s\S]*?-->|<!doctype[^>]*>|<\/([a-z0-9]+)\s*>|<([a-z0-9]+)([^>]*)>|([^<]+)/giu;
  for (const m of html.matchAll(marcas)) {
    if (m[1]) {
      while (atual !== raiz && atual.tag !== m[1].toLowerCase()) atual = atual.pai;
      if (atual !== raiz) atual = atual.pai;
    } else if (m[2]) {
      const atributos = {};
      for (const a of m[3].matchAll(/([\w-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/gu)) {
        atributos[a[1].toLowerCase()] = decodificar(a[2] ?? a[3] ?? a[4] ?? "");
      }
      const no = new No(m[2].toLowerCase(), atributos);
      no.pai = atual;
      atual.filhos.push(no);
      if (!VAZIOS.has(no.tag) && !m[3].trim().endsWith("/")) atual = no;
    } else if (m[4] && atual !== raiz) {
      atual.filhos.push(decodificar(m[4]));
    }
  }
  return {
    get title() {
      return raiz.querySelector("title")?.textContent ?? "";
    },
    querySelector: (s) => raiz.querySelector(s),
    querySelectorAll: (s) => raiz.querySelectorAll(s),
  };
}

async function pagina(nome) {
  return analisar(await readFile(new URL(`./paginas/${nome}.html`, import.meta.url), "utf8"));
}

function carregar(host = "", api = undefined) {
  const contexto = { location: { hostname: host }, chrome: api, setInterval: () => 0 };
  contexto.globalThis = contexto;
  vm.createContext(contexto);
  vm.runInContext(DADOS, contexto); // a ordem do manifest.json: os dados antes do script
  vm.runInContext(FONTE, contexto);
  return contexto.__jarvisSocial;
}

const social = carregar();

test("WhatsApp logado: contagem do título, quem mandou e nome limpo de controle", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-logado"));
  assert.equal(estado.logado, true);
  assert.equal(estado.formato, "conhecido");
  assert.equal(estado.naoLidas, 3);
  assert.deepEqual(JSON.parse(JSON.stringify(estado.conversas)), [
    { nome: "Ana Prestadora", naoLidas: 2 },
    { nome: "Bruno moc.elpmaxe", naoLidas: 1 },
  ]);
});

test("WhatsApp pedindo o QR: não logado, nada contado", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-login"));
  assert.equal(estado.logado, false);
  assert.equal(estado.formato, "conhecido");
  assert.equal(estado.naoLidas, 0);
});

test("DOM que mudou vira formato desconhecido, sem inventar conversa", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-mudou"));
  assert.equal(estado.formato, "desconhecido");
  assert.equal(estado.logado, false);
  assert.equal(estado.conversas.length, 0);
  // já teve tempo de carregar: a página mudou, com a amostra do título para o diagnóstico
  assert.equal(estado.pista, "sem_lista");
  assert.equal(estado.amostra, "(5) whatsapp");
  // o mesmo DOM logo depois de o script nascer ainda é a página carregando, não a que mudou
  const cedo = social.lerEstado("whatsapp", await pagina("whatsapp-mudou"), { idadeMs: 2_000 });
  assert.equal(cedo.pista, "carregando");
  assert.equal(cedo.amostra, "");
});

// --- o contador tolerante (bug do dono, 2026-11-13: «formato não reconhecido do contador») ------
test("a tela de carga do WhatsApp é «carregando», não «a página mudou»", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-carregando"));
  assert.equal(estado.formato, "desconhecido");
  assert.equal(estado.pista, "carregando");
  assert.equal(estado.logado, false);
  assert.equal(estado.conversas.length, 0);
});

test("todos os formatos de contador da página: milhar, 99+, bolinha, outros alfabetos, NBSP", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-contadores"));
  assert.equal(estado.formato, "conhecido");
  assert.equal(estado.pista, "", "tudo reconhecido: nenhuma pista");
  assert.deepEqual(JSON.parse(JSON.stringify(estado.conversas)), [
    { nome: "Ana", naoLidas: 1234 },
    { nome: "Bruno", naoLidas: 99 },
    { nome: "Carla", naoLidas: 1 },
    { nome: "Davi", naoLidas: 3 },
    { nome: "Eva", naoLidas: 5 },
    { nome: "Fábio", naoLidas: 7 },
    { nome: "Gil", naoLidas: 4 },
  ]);
  assert.equal(estado.naoLidas, 1234 + 99 + 1 + 3 + 5 + 7 + 4);
});

test("interface em inglês e em espanhol", async () => {
  const ingles = social.lerEstado("whatsapp", await pagina("whatsapp-ingles"));
  assert.equal(ingles.formato, "conhecido");
  assert.deepEqual(JSON.parse(JSON.stringify(ingles.conversas)), [{ nome: "Grace", naoLidas: 2 }]);
  const espanhol = social.lerEstado("whatsapp", await pagina("whatsapp-espanhol"));
  assert.equal(espanhol.formato, "conhecido");
  assert.equal(espanhol.logado, true);
  assert.deepEqual(JSON.parse(JSON.stringify(espanhol.conversas)), [{ nome: "Inés", naoLidas: 1 }]);
});

test("contador que não se reconhece conta 1, dá a pista e uma amostra sem o nome de ninguém", async () => {
  const estado = social.lerEstado("whatsapp", await pagina("whatsapp-contador-estranho"));
  assert.equal(estado.formato, "conhecido");
  assert.equal(estado.logado, true);
  assert.deepEqual(JSON.parse(JSON.stringify(estado.conversas)), [{ nome: "Zé Ninguém", naoLidas: 1 }]);
  assert.equal(estado.pista, "contador_ilegivel");
  assert.equal(estado.amostra, "1,5 mil | 1,5 mil mensagens nao lidas de x x");
  assert.ok(estado.amostra.length <= 60);
});

test("o leitor de número: cada formato e o que fica ilegível", () => {
  const casos = [
    ["3", 3, "numero"],
    ["1.234", 1234, "numero"],
    ["1,234", 1234, "numero"],
    ["1\u00a0234", 1234, "numero"],
    ["2\u202f345", 2345, "numero"],
    ["99+", 99, "minimo"],
    ["+999", 999, "minimo"],
    ["\u0663", 3, "numero"],
    ["\u06f5\u06f2", 52, "numero"],
    ["\u096a", 4, "numero"],
    ["\uff15", 5, "numero"],
    ["3 mensagens não lidas", 3, "numero"],
    ["1 mensagem não lida", 1, "numero"],
    ["2 unread messages", 2, "numero"],
    ["2 mensajes no leídos", 2, "numero"],
    ["", 0, "vazio"],
    ["•", 0, "vazio"],
    ["1,5 mil", 0, "ilegivel"],
    ["2K", 0, "ilegivel"],
    ["12:30", 0, "ilegivel"],
    ["99999", 0, "ilegivel"],
    ["Marcada como não lida", 0, "ilegivel"],
  ];
  for (const [texto, n, tipo] of casos) {
    assert.deepEqual({ ...social.lerContador(texto) }, { n, tipo }, JSON.stringify(texto));
  }
});

test("a amostra não leva nome, texto nem telefone", () => {
  assert.equal(social.amostraSegura("(1,5 mil) Ana Paula | WhatsApp"), "(1,5 mil) x x | whatsapp");
  assert.equal(social.amostraSegura("+55 11 98765-4321 mensagem"), "### mensagem");
  assert.equal(social.amostraSegura("Bom dia 😀 <b>Sr. José</b>"), "x x x x. x /x");
  assert.ok(social.amostraSegura("9".repeat(500)).length <= 60);
});

test("Discord, Instagram, Facebook e TikTok pelas páginas falsas", async () => {
  const discord = social.lerEstado("discord", await pagina("discord-logado"));
  assert.equal(discord.logado, true);
  assert.equal(discord.naoLidas, 4);
  assert.deepEqual(
    [...discord.conversas].map((c) => c.nome),
    ["carla_dev", "edu"],
  );
  const instagram = social.lerEstado("instagram", await pagina("instagram-login"));
  assert.equal(instagram.logado, false);
  assert.equal(instagram.formato, "conhecido");
  const facebook = social.lerEstado("facebook", await pagina("facebook-logado"));
  assert.equal(facebook.logado, true);
  assert.equal(facebook.naoLidas, 2);
  const tiktok = social.lerEstado("tiktok", await pagina("tiktok-logado"));
  assert.equal(tiktok.logado, true);
  assert.equal(tiktok.naoLidas, 2);
  assert.deepEqual(
    [...tiktok.conversas].map((c) => c.nome),
    ["fabio.tk"],
  );
});

test("o título só conta o número no começo", () => {
  assert.equal(social.contagemDoTitulo("(12) Discord | #geral"), 12);
  assert.equal(social.contagemDoTitulo("WhatsApp"), 0);
  assert.equal(social.contagemDoTitulo("Grupo (3) amigos"), 0);
  assert.equal(social.contagemDoTitulo("(99999) X"), 0);
  assert.equal(social.contagemDoTitulo("(1.234) WhatsApp"), 1234);
  assert.equal(social.contagemDoTitulo("(99+) WhatsApp"), 99);
  assert.equal(social.contagemDoTitulo("(\u00a03\u00a0) WhatsApp"), 3);
  assert.equal(social.contagemDoTitulo("(\u0663) WhatsApp"), 3);
});

test("a rede sai do host exato; fora das cinco o script não faz nada", () => {
  assert.equal(social.redeDoHost("web.whatsapp.com"), "whatsapp");
  assert.equal(social.redeDoHost("discord.com"), "discord");
  assert.equal(social.redeDoHost("web.whatsapp.com.golpe.example"), undefined);
  let mensagens = 0;
  const api = { runtime: { id: "x", sendMessage: () => mensagens++, onMessage: { addListener() {} } } };
  carregar("exemplo.com", api);
  assert.equal(mensagens, 0);
});

test("o script não tem caminho para agir na página", () => {
  for (const proibido of [".click(", "dispatchEvent", ".value =", "execCommand", ".focus(", "scroll"]) {
    assert.equal(FONTE.includes(proibido), false, `social.js não pode ter ${proibido}`);
  }
});

test("os seletores são só dados, versionados e sem classe CSS", () => {
  const corpo = DADOS.split("\n")
    .filter((linha) => !linha.startsWith("//"))
    .join("\n")
    .trim();
  const prefixo = "globalThis.__jarvisSeletoresSociais = ";
  assert.ok(corpo.startsWith(prefixo) && corpo.endsWith(";"), "um objeto literal atribuído, nada mais");
  const dados = JSON.parse(corpo.slice(prefixo.length, -1));
  assert.equal(typeof dados.versao, "number");
  assert.deepEqual(Object.keys(dados.redes), ["whatsapp", "instagram", "facebook", "tiktok", "discord"]);
  for (const [id, rede] of Object.entries(dados.redes)) {
    for (const chave of ["login", "essenciais", "conversa", "nome", "selo", "carregando"]) {
      if (chave === "carregando" && !(chave in rede)) {
        continue; // opcional
      }
      assert.ok(Array.isArray(rede[chave]) && rede[chave].length, `${id}.${chave}`);
      for (const seletor of rede[chave]) {
        assert.equal(/\[class|(^|\s)[a-z]*\.[\w-]/u.test(seletor), false, `${id}: ${seletor} usa classe`);
      }
    }
  }
  assert.equal(social.versao, dados.versao);
  for (const padrao of Object.values(dados.alertas.textos)) {
    assert.doesNotThrow(() => new RegExp(padrao, "iu"));
  }
});

test("sinais de alerta: conta bloqueada no diálogo e captcha", async () => {
  const bloqueada = social.lerEstado("whatsapp", await pagina("whatsapp-bloqueada"));
  assert.equal(bloqueada.alerta, "limitada");
  const captcha = social.lerEstado("instagram", await pagina("instagram-captcha"));
  assert.equal(captcha.alerta, "captcha");
  const normal = social.lerEstado("whatsapp", await pagina("whatsapp-logado"));
  assert.equal(normal.alerta, "");
});

test("envio: cabeçalho, conversa pelo nome exato (homônimo conta) e a caixa de texto", async () => {
  const chat = await pagina("whatsapp-chat");
  const rede = JSON.parse(
    DADOS.split("\n").filter((l) => !l.startsWith("//")).join("\n").trim()
      .slice("globalThis.__jarvisSeletoresSociais = ".length, -1),
  ).redes.whatsapp;
  const cabecalho = social.cabecalhoDoChat(rede, chat);
  assert.deepEqual(JSON.parse(JSON.stringify(cabecalho)), {
    nome: "Ana Souza",
    telefone: "",
    grupo: false,
    ambiguo: false,
  });
  assert.deepEqual(JSON.parse(JSON.stringify(social.conversaPeloNome(rede, chat, "ana  souza"))), {
    quantas: 1,
    x: 60,
    y: 35,
  });
  assert.equal(social.conversaPeloNome(rede, chat, "Carlos").quantas, 2);
  assert.equal(social.conversaPeloNome(rede, chat, "Ninguém").quantas, 0);
  assert.deepEqual(JSON.parse(JSON.stringify(social.caixaDeTexto(rede, chat))), { x: 60, y: 35 });
  const grupo = social.cabecalhoDoChat(rede, await pagina("whatsapp-grupo"));
  assert.equal(grupo.grupo, true);
  const sem = social.cabecalhoDoChat(rede, await pagina("whatsapp-logado"));
  assert.equal(sem.ambiguo, true, "sem chat aberto, nada a conferir: ambíguo");
});

test("fatia E: Instagram, Facebook, TikTok e Discord — logado, login e alerta", async () => {
  const instagram = social.lerEstado("instagram", await pagina("instagram-logado"));
  assert.equal(instagram.logado, true);
  assert.equal(instagram.naoLidas, 2);
  assert.deepEqual([...instagram.conversas].map((c) => c.nome), ["lia.foto", "nina"]);

  const messenger = social.lerEstado("facebook", await pagina("facebook-messenger"));
  assert.equal(messenger.logado, true);
  assert.deepEqual(
    JSON.parse(JSON.stringify(messenger.conversas)),
    [{ nome: "Otávio Lima", naoLidas: 1 }],
  );

  for (const [rede, nome] of [
    ["facebook", "facebook-login"],
    ["tiktok", "tiktok-login"],
    ["discord", "discord-login"],
  ]) {
    const estado = social.lerEstado(rede, await pagina(nome));
    assert.equal(estado.logado, false, nome);
    assert.equal(estado.formato, "conhecido", nome);
    assert.equal(estado.naoLidas, 0, nome);
  }

  const verificacao = social.lerEstado("discord", await pagina("discord-verificacao"));
  assert.equal(verificacao.alerta, "verificacao");
});

test("fatia E: página de uma rede lida com os seletores de outra não inventa contagem", async () => {
  const errada = social.lerEstado("tiktok", await pagina("instagram-logado"));
  assert.equal(errada.formato, "desconhecido");
  assert.equal(errada.conversas.length, 0);
});
