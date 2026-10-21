/*
 * A faixa "Jarvis no controle" (ADR-0027, regra 4). Desenhada pela extensão num shadow DOM
 * fechado, por cima da página: os scripts dela não leem nem mexem no que tem dentro, o conteúdo
 * não é empurrado (a faixa só deixa clicar no botão), nada pede o foco, e ela some sozinha quando
 * o Jarvis solta a aba. O botão PARAR solta o navegador na hora e para o turno e a tarefa do Jarvis.
 *
 * Roda ao nascer o documento (`document_start`) e pergunta ao fundo se a aba está no controle:
 * numa aba que o Jarvis está navegando, a faixa já está na página nova.
 */

(() => {
  const api = globalThis.browser ?? globalThis.chrome;
  const NOME = "jarvis-no-controle";
  const MAX_REANEXOS = 20;
  const CONFERIR_MS = 4_000;
  let hospedeiro = null;
  let observador = null;
  let conferencia;
  let ligado = false;
  let reanexos = 0;

  function estilo(elemento, regras) {
    for (const [propriedade, valor] of Object.entries(regras)) {
      elemento.style.setProperty(propriedade, valor, "important");
    }
  }

  function criar() {
    const caixa = document.createElement(NOME);
    estilo(caixa, {
      all: "initial",
      position: "fixed",
      top: "0",
      left: "0",
      width: "0",
      height: "0",
      "z-index": "2147483647",
      display: "block",
      "pointer-events": "none",
    });
    const raiz = caixa.attachShadow({ mode: "closed" });
    const faixa = document.createElement("div");
    faixa.setAttribute("role", "status");
    estilo(faixa, {
      position: "fixed",
      top: "0",
      left: "0",
      right: "0",
      height: "26px",
      display: "flex",
      "align-items": "center",
      "justify-content": "space-between",
      gap: "12px",
      padding: "0 10px 0 14px",
      "box-sizing": "border-box",
      background: "rgba(120, 53, 15, 0.92)",
      "border-bottom": "2px solid #f59e0b",
      color: "#ffffff",
      font: "600 12px/1 system-ui, sans-serif",
      "letter-spacing": "0.2px",
      "pointer-events": "none",
    });
    const texto = document.createElement("span");
    texto.textContent = "● Jarvis no controle desta aba";
    const botao = document.createElement("button");
    botao.type = "button";
    botao.tabIndex = -1; // fora da ordem do Tab da página
    botao.textContent = "Parar";
    botao.title = "Parar o Jarvis agora e soltar o navegador";
    estilo(botao, {
      "pointer-events": "auto",
      cursor: "pointer",
      font: "700 12px/1 system-ui, sans-serif",
      color: "#ffffff",
      background: "#dc2626",
      border: "0",
      "border-radius": "999px",
      padding: "4px 12px",
      margin: "0",
    });
    // Apertar não tira o foco do campo em que o dono estava.
    botao.addEventListener("mousedown", (evento) => evento.preventDefault());
    botao.addEventListener("click", (evento) => {
      if (!evento.isTrusted) {
        return; // a página não aperta por ele
      }
      evento.preventDefault();
      evento.stopPropagation();
      esconder();
      Promise.resolve()
        .then(() => api.runtime.sendMessage({ tipo: "parar" }))
        .catch(() => undefined);
    });
    faixa.append(texto, botao);
    raiz.append(faixa);
    return caixa;
  }

  function anexar() {
    const documento = document.documentElement;
    if (!documento) {
      document.addEventListener("readystatechange", anexar, { once: true });
      return;
    }
    hospedeiro ??= criar();
    if (!hospedeiro.isConnected) {
      documento.append(hospedeiro);
    }
    if (!observador) {
      // Página que arranca a faixa: ela volta (até um limite, para não brigar sem fim).
      observador = new MutationObserver(() => {
        if (ligado && !hospedeiro.isConnected && reanexos < MAX_REANEXOS) {
          reanexos += 1;
          document.documentElement?.append(hospedeiro);
        }
      });
      observador.observe(documento, { childList: true });
    }
  }

  function conferirDepois() {
    // Enquanto a faixa está à vista, ela pergunta de novo de tempos em tempos: se o fundo não a
    // tem mais no controle (o aviso de soltar se perdeu) ou a extensão foi recarregada ou removida
    // (a página fica com um conteúdo órfão), a faixa some sozinha — nunca fica presa na página.
    clearTimeout(conferencia);
    conferencia = setTimeout(() => {
      if (!ligado) {
        return;
      }
      Promise.resolve()
        .then(() => api.runtime.sendMessage({ tipo: "controle?" }))
        .then((resposta) => (resposta?.ligado === true ? conferirDepois() : esconder()))
        .catch(() => esconder());
    }, CONFERIR_MS);
  }

  function mostrar() {
    ligado = true;
    anexar();
    conferirDepois();
  }

  function esconder() {
    ligado = false;
    clearTimeout(conferencia);
    observador?.disconnect();
    observador = null;
    hospedeiro?.remove();
  }

  api.runtime.onMessage.addListener((mensagem, remetente, responder) => {
    if (remetente?.id !== api.runtime.id || typeof mensagem?.indicador !== "object") {
      return false;
    }
    if (mensagem.indicador?.ligado === true) {
      mostrar();
    } else {
      esconder();
    }
    responder({ ligado });
    return false;
  });

  Promise.resolve()
    .then(() => api.runtime.sendMessage({ tipo: "controle?" }))
    .then((resposta) => {
      if (resposta?.ligado === true) {
        mostrar();
      }
    })
    .catch(() => undefined);
})();
