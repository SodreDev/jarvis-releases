"""A ponte do navegador de ponta a ponta, num navegador DE VERDADE, em contêiner (ADR-0027).

    uv run --frozen python -m tools.harness_navegador                        # chromium e firefox
    uv run --frozen python -m tools.harness_navegador --navegador firefox

Por que contêiner: teste não toca o navegador do dono, a sessão dele nem o microfone. O navegador
roda headless numa rede própria (`--network none`), com HOME e `XDG_RUNTIME_DIR` descartáveis; o
repositório e o Python do `uv` entram **só leitura** no mesmo caminho, então o `.venv` funciona lá
dentro sem instalar nada. Cada contêiner tem `--name` e `--timeout` (nunca `kill` solto).

O caminho provado é o do dono, sem atalho: `jarvis-native-host --instalar` (modo repositório) → o
navegador carrega a cópia da extensão que ele gravou → `connectNative` → o navegador lança o stub →
host deste código → socket Unix → `Aplicativo._montar_ferramentas` (catálogo C0, PDP e risco
reais) → as `browser.*`, numa página servida no 127.0.0.1 do contêiner.

O que se confere, por navegador (41 pontos): instalar no modo repositório; **sem navegador ativo**
(nem extensão nem processo dele) o Jarvis abre um pelo `sites.open` — o único caso —, e com ele
aberto nem o `browser.launch` nem a aba nova lançam outro, e o roteiro o fecha pelo PID conferido
(dono, 2026-10-21); o host nasce pelo manifesto e é o deste código; o modelo enxerga as `browser.*`;
`browser.tabs` acha a página e `browser.navigate` a recarrega; `browser.read` lê o texto; um botão
comum é clicado sem pergunta; um botão de **envio de formulário** com rótulo neutro pede o "sim" (e
o "não" impede o clique); `browser.type` digita na busca e recusa a senha; a busca sem rótulo, que
não se acha pelo texto, se acha pelo mapa (`browser.inspecionar`: ref, caixa, painel ligado ao
script), digitar pela ref e Enter buscam por GET sem pedir o sim, e `browser.acionar` passa o mouse,
clica no link que chama a função e pede o "sim" no «enviar» (ADR-0032); `browser.tela` captura a aba
com o mapa do mesmo instante; `browser.estado` diz conectado; `sites.open` troca a URL da aba do
mesmo site; a busca pela extensão lê numa aba de fundo e a fecha sem trocar a aba do dono
(ADR-0033) e **sem abrir janela nem instância** (era a «outra instância do Brave» do dono); o Jarvis
lê e clica numa aba de fundo da janela do dono, sem `active` e com o foco dele igual (a tela dela,
só no Firefox); `browser.navigate` com `nova_aba` abre uma só; sem rede, «abra um vídeo no YouTube»
volta erro dito e não `ok`; pedido de ver traz para a frente a aba que estava atrás; pesquisa sem
pedido de ver vai numa aba de fundo da janela do dono e a leitura sem `tab_id` lê a aba de
trabalho; `tabs.show` a traz para a frente; o `sites.open` com `nova_aba` abre a guia pela extensão,
sem executar o navegador (a outra metade do caso do dono); a faixa «no controle» em toda página da
aba controlada, medida pela própria página, e fora dela ao soltar; o PARAR da faixa com clique de
verdade (`Input` do CDP no Chromium, ações do Marionette no Firefox) cancela o turno e recusa o
pedido parado; os 3 casos de reuso de aba (ADR-0027 regra 4: a mesma página só ativa, o mesmo site
navega, e site novo com a aba atual de outro abre **guia nova** na janela do dono); nada executou
o navegador com ele aberto; só o modo `automacao_social` (o gancho) abre a janela própria do
Jarvis; o host derrubado (PID conferido em `/proc`) volta pela reconexão da extensão; e, 40 s sem
pedido, o mesmo host continua respondendo. "Uma instância só" é medido pelo navegador (`janelas`
de `windows.focused`, a janela do Jarvis, a página dela) e pelos processos principais em `/proc`.

Fatos que este roteiro descobriu (2026-10-19, Chromium 155 e Firefox 158 do Fedora 44):
- o Chromium ≥ 137 ignora `--load-extension` sem
  `--disable-features=DisableLoadExtensionCommandLineSwitch`;
- o manifesto do usuário mora em `<user-data-dir>/NativeMessagingHosts`: o headless usa uma pasta
  temporária, então o `--user-data-dir` vai explícito;
- o Firefox instala extensão temporária pelo Marionette (`Addon:Install` com `temporary`);
- a URL da linha de comando do Chromium corre com o registro do conteúdo da extensão: às vezes a
  página carrega antes e fica sem ele — por isso o roteiro navega de novo antes de ler.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import http.server
import json
import os
import shlex
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from jarvis.voz.app import Aplicativo

RAIZ: Final = Path(__file__).resolve().parent.parent
IMAGEM: Final = "localhost/jarvis-nav-teste:x11"
CONTAINERFILE: Final = (
    "FROM registry.fedoraproject.org/fedora:44\n"
    "RUN dnf -y install --setopt=install_weak_deps=False chromium firefox procps-ng findutils "
    "xorg-x11-server-Xvfb openbox xprop && dnf clean all\n"
)
"""Xvfb e openbox (2026-10-20, ADR-0036): o Chromium headless trata a janela mais nova como a em
foco e não devolve o foco, então a prova de "a janela do dono não muda" roda o Chromium com janela,
num X virtual com gerenciador de janelas, e confere o foco também pelo X (`xprop`)."""
TELA_VIRTUAL: Final = ":99"
XVFB: Final = "/usr/bin/Xvfb"  # os da imagem (fedora:44)
OPENBOX: Final = "/usr/bin/openbox"
XPROP: Final = "/usr/bin/xprop"
NAVEGADORES: Final = ("chromium", "firefox")
SEGUNDOS_POR_NAVEGADOR: Final = 600
OCIOSO_S: Final = 40.0
"""Mais que os 30 s em que o Chromium encerra service worker ocioso (e o Firefox, event page)."""
MARCA: Final = "RELATORIO "
CASA: Final = Path("/tmp/casa")  # noqa: S108 — dentro do contêiner descartável
RUN: Final = Path("/tmp/run")  # noqa: S108
PORTA_DO_MARIONETTE: Final = 2828
PORTA_DO_CDP: Final = 9229
"""Só para o clique de verdade do dono no PARAR da faixa (Input do CDP): o Jarvis não usa CDP."""
CHROMIUM: Final = "/usr/bin/chromium-browser"  # o da imagem (fedora:44)
FIREFOX: Final = "/usr/bin/firefox"

PAGINA: Final = """<!doctype html><meta charset=utf-8><title>Página de teste do Jarvis</title>
<h1>Olá, Jarvis</h1>
<p id=estado>estado inicial</p>
<button type=button onclick="document.getElementById('estado').textContent='detalhe aberto'">
Mostrar detalhe</button>
<form action="/enviado" method=post><label>Comentário <input name=c></label>
<button>Pronto</button></form>
<form role=search action="/busca"><label>Busca <input type=search name=q></label></form>
<label>Senha <input type=password name=s></label>
<form id=topo action="/resultados">
<input name=search_query placeholder="Pesquisar" autocomplete=off></form>
<div id=menu tabindex=0 onmouseover="document.getElementById('estado').textContent='menu aberto'">
Menu</div>
<script>
function abrirPainel(){document.getElementById('estado').textContent='painel aberto'}</script>
<a href="#painel" onclick="abrirPainel();return false">Painel</a>
"""
"""«Pronto» é um envio de formulário com rótulo neutro: só a inspeção do alvo o pega. A busca do
topo imita a do YouTube (2026-10-20): sem rótulo que diga "busca", só o mapa a acha (ADR-0032)."""
SEGUNDA: Final = "<!doctype html><meta charset=utf-8><title>Segunda página do Jarvis</title><p>dois"
BUSCA: Final = """<!doctype html><meta charset=utf-8><title>Resultados de teste</title>
<a href="/configuracoes">Configurações da busca</a>
<a href="https://www.youtube.com/@primorico">O Primo Rico - YouTube</a>
<a href="https://pt.wikipedia.org/wiki/Thiago_Nigro">Thiago Nigro – Wikipédia</a>
"""
"""Uma página de resultados sem rede (ADR-0033): o link para o próprio buscador não é resultado."""
VIGIA: Final = """<!doctype html><meta charset=utf-8><title>{titulo}</title><p id=e>vigia</p>
<script>
const doc = Math.random().toString(36).slice(2, 8);
function avisa(ev) {{
  const t = (performance.timeOrigin + performance.now()).toFixed(1);
  fetch(`/registro?doc=${{doc}}&ev=${{ev}}&t=${{t}}&p=${{location.pathname}}`,
        {{method: "POST", keepalive: true}}).catch(() => {{}});
}}
avisa("inicio");
let tinha = false;
function olhar() {{
  const tem = Boolean(document.querySelector("jarvis-no-controle"));
  if (tem !== tinha) {{ tinha = tem; avisa(tem ? "faixa" : "sem_faixa"); }}
}}
olhar();
new MutationObserver(olhar).observe(document.documentElement, {{childList: true}});
</script>"""
"""A própria página vê a faixa do Jarvis entrar e sair (o elemento dela, não o que tem dentro, que é
de sombra fechada) e conta ao servidor de teste, com o relógio dela: é a medida do "100% do tempo"
(ADR-0027 regra 4)."""
REGISTRO: Final[list[dict[str, Any]]] = []
"""O que as páginas-vigia contaram: `{doc, ev, t, p}`."""
DRIVER: Final[dict[str, Any]] = {}
"""Quem faz o clique de verdade do dono: o Marionette (Firefox) ou a porta do CDP (Chromium)."""


# --- dentro do contêiner ------------------------------------------------------------------------
@dataclass
class Relatorio:
    navegador: str
    versao: str = ""
    conferencias: list[dict[str, Any]] = field(default_factory=list)

    def conferir(self, nome: str, ok: object, detalhe: object = "") -> bool:
        passou = bool(ok)
        self.conferencias.append({"nome": nome, "ok": passou, "detalhe": str(detalhe)[:1500]})
        print(f"{'ok ' if passou else 'FALHOU'} {nome}  {str(detalhe)[:160]}", flush=True)
        return passou

    @property
    def ok(self) -> bool:
        return bool(self.conferencias) and all(c["ok"] for c in self.conferencias)


class Marionette:
    """O mínimo do protocolo do Firefox: mensagem `<tamanho>:<json>`, comando
    `[0, id, nome, parâmetros]`, resposta `[1, id, erro, valor]`."""

    def __init__(self, prazo_s: float = 60) -> None:
        fim = time.monotonic() + prazo_s
        while True:
            try:
                self._s = socket.create_connection(("127.0.0.1", PORTA_DO_MARIONETTE), timeout=30)
                break
            except OSError:
                if time.monotonic() > fim:
                    raise
                time.sleep(0.5)
        self._id = 0
        self._buffer = b""
        self._ler()  # saudação

    def _ler(self) -> Any:
        while b":" not in self._buffer:
            self._buffer += self._receber()
        tamanho, _, resto = self._buffer.partition(b":")
        while len(resto) < int(tamanho):
            resto += self._receber()
        self._buffer = resto[int(tamanho) :]
        return json.loads(resto[: int(tamanho)])

    def _receber(self) -> bytes:
        pedaco = self._s.recv(65536)
        if not pedaco:
            raise ConnectionError("o Marionette fechou")
        return pedaco

    def comando(self, nome: str, parametros: dict[str, Any]) -> Any:
        self._id += 1
        corpo = json.dumps([0, self._id, nome, parametros]).encode()
        self._s.sendall(str(len(corpo)).encode() + b":" + corpo)
        while True:
            resposta = self._ler()
            if isinstance(resposta, list) and resposta[:2] == [1, self._id]:
                if resposta[2]:
                    raise RuntimeError(f"{nome}: {resposta[2]}")
                return resposta[3]

    def fechar(self) -> None:
        self._s.close()


class Cdp:
    """O mínimo do CDP por WebSocket, sem biblioteca — só para o **clique de verdade do dono** no
    PARAR da faixa (`Input.dispatchMouseEvent` é entrada do navegador: `isTrusted`). O Jarvis não
    usa CDP; a extensão também não."""

    def __init__(self, porta: int, trecho_da_url: str, prazo_s: float = 10.0) -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{porta}/json/list", timeout=prazo_s) as r:
            alvos = json.loads(r.read())
        alvo = next(
            a for a in alvos if a.get("type") == "page" and trecho_da_url in a.get("url", "")
        )
        caminho = urllib.parse.urlsplit(alvo["webSocketDebuggerUrl"]).path
        self._s = socket.create_connection(("127.0.0.1", porta), timeout=prazo_s)
        chave = base64.b64encode(os.urandom(16)).decode()
        self._s.sendall(
            (
                f"GET {caminho} HTTP/1.1\r\nHost: 127.0.0.1:{porta}\r\nUpgrade: websocket\r\n"
                f"Connection: Upgrade\r\nSec-WebSocket-Key: {chave}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        cabecalho = b""
        while b"\r\n\r\n" not in cabecalho:
            cabecalho += self._s.recv(1)  # byte a byte: nada do quadro seguinte se perde
        if b" 101 " not in cabecalho.split(b"\r\n", 1)[0]:
            raise ConnectionError(f"o CDP recusou o WebSocket: {cabecalho[:80]!r}")
        self._id = 0

    def _exato(self, quantos: int) -> bytes:
        dados = b""
        while len(dados) < quantos:
            pedaco = self._s.recv(quantos - len(dados))
            if not pedaco:
                raise ConnectionError("o CDP fechou")
            dados += pedaco
        return dados

    def _enviar(self, objeto: dict[str, Any]) -> None:
        dados = json.dumps(objeto).encode()
        cabecalho = bytearray([0x81])
        if len(dados) < 126:
            cabecalho.append(0x80 | len(dados))
        elif len(dados) < 65536:
            cabecalho += bytes([0x80 | 126]) + struct.pack(">H", len(dados))
        else:
            cabecalho += bytes([0x80 | 127]) + struct.pack(">Q", len(dados))
        mascara = os.urandom(4)
        corpo = bytes(b ^ mascara[i % 4] for i, b in enumerate(dados))
        self._s.sendall(bytes(cabecalho) + mascara + corpo)

    def _receber(self) -> dict[str, Any]:
        partes = b""
        while True:
            primeiro, segundo = self._exato(2)
            tamanho = segundo & 0x7F
            if tamanho == 126:
                (tamanho,) = struct.unpack(">H", self._exato(2))
            elif tamanho == 127:
                (tamanho,) = struct.unpack(">Q", self._exato(8))
            partes += self._exato(tamanho)
            if primeiro & 0x80:
                objeto: dict[str, Any] = json.loads(partes)
                return objeto

    def comando(self, metodo: str, parametros: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        self._enviar({"id": self._id, "method": metodo, "params": parametros or {}})
        while True:
            mensagem = self._receber()
            if mensagem.get("id") == self._id:
                if "error" in mensagem:
                    raise RuntimeError(f"{metodo}: {mensagem['error']}")
                resultado: dict[str, Any] = mensagem.get("result", {})
                return resultado

    def fechar(self) -> None:
        self._s.close()


def _clicar_no_parar(nome: str, trecho_da_url: str) -> str:
    """O clique de verdade do dono no PARAR da faixa: o botão fica na ponta direita da faixa de
    26 px do topo (o roteiro não enxerga dentro da sombra fechada; mira pelo desenho)."""
    if nome == "chromium":
        cdp = Cdp(PORTA_DO_CDP, trecho_da_url)
        try:
            avaliado = cdp.comando(
                "Runtime.evaluate", {"expression": "innerWidth", "returnByValue": True}
            )
            x, y = int(avaliado["result"]["value"]) - 40, 13
            cdp.comando("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
            for tipo in ("mousePressed", "mouseReleased"):
                cdp.comando(
                    "Input.dispatchMouseEvent",
                    {"type": tipo, "x": x, "y": y, "button": "left", "clickCount": 1},
                )
        finally:
            cdp.fechar()
        return f"CDP Input em {x},{y}"
    marionette = DRIVER["marionette"]
    largura = marionette.comando(
        "WebDriver:ExecuteScript", {"script": "return innerWidth;", "args": []}
    )["value"]
    x, y = int(largura) - 40, 13
    passos = [
        {"type": "pointerMove", "x": x, "y": y, "origin": "viewport"},
        {"type": "pointerDown", "button": 0},
        {"type": "pointerUp", "button": 0},
    ]
    marionette.comando(
        "WebDriver:PerformActions",
        {
            "actions": [
                {
                    "type": "pointer",
                    "id": "dono",
                    "parameters": {"pointerType": "mouse"},
                    "actions": passos,
                }
            ]
        },
    )
    marionette.comando("WebDriver:ReleaseActions", {})
    return f"Marionette em {x},{y}"


def _cobertura(
    registro: list[dict[str, Any]], comeco_ms: float, soltou_ms: float
) -> dict[str, Any]:
    """A faixa em cada documento da aba controlada, pelo relógio da própria página: quanto tempo
    depois de o documento nascer ela apareceu, se sumiu antes de soltar, e quanto levou para sumir
    depois de soltar."""
    documentos: dict[str, list[dict[str, Any]]] = {}
    for evento in sorted(registro, key=lambda e: e["t"]):
        documentos.setdefault(evento["doc"], []).append(evento)
    controlados = [
        eventos
        for eventos in documentos.values()
        if eventos[0]["ev"] == "inicio" and comeco_ms <= eventos[0]["t"] <= soltou_ms
    ]
    atrasos, buracos, sumiu_ms = [], 0, None
    for indice, eventos in enumerate(controlados):
        inicio = eventos[0]["t"]
        faixa = next((e["t"] for e in eventos if e["ev"] == "faixa"), None)
        atrasos.append(round(faixa - inicio, 1) if faixa is not None else None)
        ultimo = indice == len(controlados) - 1
        for evento in eventos:
            if evento["ev"] == "sem_faixa":
                if evento["t"] < soltou_ms:
                    buracos += 1
                elif ultimo:
                    sumiu_ms = round(evento["t"] - soltou_ms, 1)
    ok = (
        len(controlados) >= 2
        and all(a is not None and a <= 500 for a in atrasos)
        and buracos == 0
        and sumiu_ms is not None
        and sumiu_ms <= 1500
    )
    return {
        "ok": ok,
        "documentos": len(controlados),
        "faixa_depois_de_nascer_ms": atrasos,
        "buracos": buracos,
        "sumiu_depois_de_soltar_ms": sumiu_ms,
    }


@contextlib.contextmanager
def _site() -> Iterator[str]:
    pasta = Path(tempfile.mkdtemp(prefix="site-"))
    (pasta / "pagina.html").write_text(PAGINA, encoding="utf-8")
    (pasta / "pagina2.html").write_text(SEGUNDA, encoding="utf-8")
    (pasta / "busca.html").write_text(BUSCA, encoding="utf-8")
    (pasta / "vigia.html").write_text(VIGIA.format(titulo="Vigia do Jarvis"), encoding="utf-8")
    (pasta / "vigia2.html").write_text(VIGIA.format(titulo="Vigia dois"), encoding="utf-8")

    class Quieto(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            consulta = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            REGISTRO.append(
                {
                    "doc": consulta.get("doc", [""])[0],
                    "ev": consulta.get("ev", [""])[0],
                    "t": float(consulta.get("t", ["0"])[0]),
                    "p": consulta.get("p", [""])[0],
                }
            )
            self.send_response(204)
            self.end_headers()

    def criar(*args: Any) -> Quieto:
        return Quieto(*args, directory=str(pasta))

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), criar)
    outro = http.server.ThreadingHTTPServer(("127.0.0.1", 0), criar)
    """Outro "site" (outra porta) para o caso do reuso em que nenhuma aba tem o site."""
    for qual in (servidor, outro):
        threading.Thread(target=qual.serve_forever, daemon=True).start()
    DRIVER["outra_porta"] = outro.server_address[1]
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}/pagina.html"
    finally:
        servidor.shutdown()
        outro.shutdown()


def _argv(nome: str, extensao: Path) -> list[str]:
    """O navegador como este roteiro o abre, sem a URL: é o mesmo quando quem o abre é o Jarvis
    (o caso «sem navegador ativo», em que o `sites.open` lança o binário da configuração)."""
    if nome == "chromium":
        return [
            CHROMIUM,
            *([] if os.environ.get("DISPLAY") else ["--headless=new"]),
            "--no-sandbox",  # o contêiner não tem o namespace que a caixa de areia pede
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=DisableLoadExtensionCommandLineSwitch",
            f"--user-data-dir={CASA / '.config' / 'chromium'}",
            f"--remote-debugging-port={PORTA_DO_CDP}",  # o clique do dono no PARAR, só isso
            f"--load-extension={extensao}",
        ]
    perfil = CASA / "perfil-firefox"
    perfil.mkdir(parents=True, exist_ok=True)
    (perfil / "user.js").write_text(
        f'user_pref("marionette.port", {PORTA_DO_MARIONETTE});\n'
        'user_pref("browser.shell.checkDefaultBrowser", false);\n'
        'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n',
        encoding="utf-8",
    )
    return [FIREFOX, "-headless", "-no-remote", "-profile", str(perfil), "-marionette"]


def _instalar_no_firefox(extensao: Path) -> Marionette:
    """O Firefox instala extensão temporária pelo Marionette (`Addon:Install`)."""
    marionette = Marionette()
    marionette.comando("WebDriver:NewSession", {})
    marionette.comando("Addon:Install", {"path": str(extensao), "temporary": True})
    return marionette


@contextlib.contextmanager
def _tela(nome: str, log: Path) -> Iterator[None]:
    """Janela de verdade num X virtual, com gerenciador de janelas, para o Chromium: o foco é
    observável (ADR-0036). O Firefox continua headless."""
    extras: list[subprocess.Popen[bytes]] = []
    saida = log.open("ab")
    if nome == "chromium" and Path(XVFB).exists() and Path(OPENBOX).exists():
        extras.append(
            subprocess.Popen(
                [XVFB, TELA_VIRTUAL, "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
                stdout=saida,
                stderr=subprocess.STDOUT,
            )
        )
        _esperar(lambda: Path(f"/tmp/.X11-unix/X{TELA_VIRTUAL[1:]}").exists(), 10)  # noqa: S108
        os.environ["DISPLAY"] = TELA_VIRTUAL
        extras.append(subprocess.Popen([OPENBOX], stdout=saida, stderr=subprocess.STDOUT))
    try:
        yield
    finally:
        for filho in reversed(extras):
            filho.terminate()  # o PID é o deste Popen: nada de matar por nome
            try:
                filho.wait(15)
            except subprocess.TimeoutExpired:
                filho.kill()
        saida.close()


@contextlib.contextmanager
def _navegador(nome: str, extensao: Path, url: str, log: Path) -> Iterator[str]:
    """Abre o navegador com a extensão e devolve a versão dele."""
    saida = log.open("ab")
    binario = CHROMIUM if nome == "chromium" else FIREFOX
    versao = subprocess.run(
        [binario, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if nome == "chromium":
        processo = subprocess.Popen(
            [*_argv(nome, extensao), url], stdout=saida, stderr=subprocess.STDOUT
        )
    else:
        processo = subprocess.Popen(_argv(nome, extensao), stdout=saida, stderr=subprocess.STDOUT)
        marionette = _instalar_no_firefox(extensao)
        marionette.comando("WebDriver:Navigate", {"url": url})
        DRIVER["marionette"] = marionette
    try:
        yield versao
    finally:
        processo.terminate()  # o PID é o deste Popen: nada de matar por nome
        try:
            processo.wait(15)
        except subprocess.TimeoutExpired:
            processo.kill()
        saida.close()


def _principais(nome: str) -> list[int]:
    """Os processos PRINCIPAIS do navegador no contêiner — uma instância é um: o processo do
    navegador cujo pai não é do navegador (renderizador, GPU, conteúdo… são filhos dele). Lido em
    `/proc` (o executável e o pai), só dentro do contêiner descartável. A linha de comando não
    serve: o Chromium e o Firefox reescrevem a dos filhos, sem os separadores (medido aqui)."""
    nomes = (
        {"chromium-browser", "chromium", "chrome"}
        if nome == "chromium"
        else {"firefox", "firefox-bin"}
    )

    def executavel(pid: str) -> str:
        try:
            return (Path("/proc") / pid / "exe").readlink().name
        except OSError:
            return ""

    def pai(pid: str) -> str:
        try:
            for linha in (Path("/proc") / pid / "status").read_text("utf-8").splitlines():
                if linha.startswith("PPid:"):
                    return linha.split()[1]
        except (OSError, IndexError):
            return ""
        return ""

    pids = [e.name for e in Path("/proc").iterdir() if e.name.isdigit()]
    return sorted(
        int(p) for p in pids if executavel(p) in nomes and executavel(pai(p)) not in nomes
    )


def _janelas(abas: list[dict[str, Any]]) -> int:
    """Quantas janelas o navegador tem, pelas abas (toda janela tem aba): conta igual no código de
    antes, que não tinha o `janelas` do `windows.focused`."""
    return len({a.get("janelaId") for a in abas})


def _janela_ativa_do_x() -> str:
    """A janela ativa pelo X (`_NET_ACTIVE_WINDOW`), quando há X; vazio no headless."""
    if not os.environ.get("DISPLAY") or not Path(XPROP).exists():
        return ""
    saida = subprocess.run(
        [XPROP, "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, check=False
    )
    return saida.stdout.strip()


def _sockets(familia: str) -> dict[int, Path]:
    pasta = RUN / "jarvis" / "navegador"
    achados: dict[int, Path] = {}
    for caminho in pasta.glob(f"{familia}-*.sock") if pasta.is_dir() else ():
        with contextlib.suppress(ValueError):
            achados[int(caminho.stem.split("-", 1)[1])] = caminho
    return achados


def _esperar(condicao: Callable[[], Any], prazo_s: float) -> Any:
    fim = time.monotonic() + prazo_s
    while time.monotonic() < fim:
        valor = condicao()
        if valor:
            return valor
        time.sleep(0.2)
    return condicao()


def _e_o_host(pid: int) -> bool:
    try:
        linha = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except OSError:
        return False
    return b"jarvis.navegador.host" in linha


def _log_util(log: Path) -> str:
    linhas = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return " | ".join(linha[:200] for linha in linhas if "dbus" not in linha.lower())[-1500:]


def _aplicativo(nome: str, binario: str, raiz: Path) -> Aplicativo:
    """O app de verdade (catálogo C0, PDP e risco reais) com este navegador como o principal do
    dono: `binario` é o que o `sites.open` executa quando não há navegador ativo."""
    from jarvis.voz.app import Aplicativo
    from jarvis.voz.config import Configuracao

    raiz.mkdir(parents=True, exist_ok=True)
    return Aplicativo(
        configuracao=Configuracao(
            asr="asr-whisper-local",
            tts="tts-parametrico",
            s2="eco",
            acesso="jarvis",
            navegador_controlado=True,
            navegadores=(f"{nome}={binario}",),
            navegador_principal=nome,
        ),
        raiz=raiz,
        ambiente={**os.environ, "JARVIS_AUDIO_BACKEND": "arquivo"},
        lar=CASA,
    )


def _o_unico_caso_de_abrir(nome: str, extensao: Path, url: str, relatorio: Relatorio) -> None:
    """Sem navegador ativo — nem extensão conectada nem processo dele —, o Jarvis abre um, e é o
    único caso em que ele abre navegador (dono, 2026-10-21). O de verdade: o `sites.open` executa o
    binário da configuração do dono, que aqui é um roteirinho com as opções deste contêiner. Com ele
    aberto, nem o `browser.launch` nem a aba nova lançam outro. No fim o roteiro o fecha pelo PID
    que o lançamento devolveu, conferido em `/proc` como o principal dele."""
    from jarvis.executor.ferramentas import ResultadoDeFerramenta
    from jarvis.executor.lancador import lancar_argv

    familia = "chromium" if nome == "chromium" else "firefox"
    abrir = CASA / "bin" / f"abrir-{nome}"
    abrir.parent.mkdir(parents=True, exist_ok=True)
    abrir.write_text(f'#!/bin/sh\nexec {shlex.join(_argv(nome, extensao))} "$@"\n', "utf-8")
    abrir.chmod(0o755)
    app = _aplicativo(nome, str(abrir), CASA / "sessao-previa")
    ferramentas = app._montar_ferramentas()
    assert ferramentas.navegadores is not None
    lancados: list[int] = []

    def lancar(argv: Any, **opcoes: Any) -> int:
        pid = lancar_argv(argv, **opcoes)
        lancados.append(pid)
        return pid

    ferramentas.navegadores.lancar = lancar

    def pedir(fala: str, tool: str, args: dict[str, Any]) -> ResultadoDeFerramenta:
        ferramentas.novo_turno(fala)
        return ferramentas.executar(tool, args, cancelado=lambda: False, confirmar=lambda _: True)

    antes = (_principais(nome), sorted(_sockets(familia)))
    aberto = pedir("abre a página de teste pra eu ver", "sites.open", {"url": url})
    rodando = _esperar(lambda: _principais(nome), 20)
    marionette = _instalar_no_firefox(extensao) if nome == "firefox" and rodando else None
    vivos = _esperar(lambda: _sockets(familia), 40)
    relatorio.conferir(
        "sem navegador ativo (nem extensão nem processo dele), o Jarvis abre um — o único caso: o "
        "sites.open lança o navegador da configuração",
        antes == ([], [])
        and aberto.status == "ok"
        and len(lancados) == 1
        and bool(rodando)
        and bool(vivos),
        {
            "antes": antes,
            "sites.open": aberto.dados or aberto.motivo,
            "lancados": lancados,
            "rodando": rodando,
            "sockets": sorted(vivos or {}),
        },
    )
    principais = _principais(nome)
    trazido = pedir("abre o navegador", "browser.launch", {})
    segunda = url.replace("pagina.html", "pagina2.html")
    nova = pedir(
        "abre a segunda página numa aba nova pra eu ver",
        "sites.open",
        {"url": segunda, "nova_aba": True},
    )
    relatorio.conferir(
        "com ele aberto, abrir de novo não lança nada: o browser.launch traz a janela do dono e a "
        "aba nova vai pela extensão — uma instância só",
        trazido.status == "ok"
        and trazido.dados.get("ja_aberto") is True
        and nova.status == "ok"
        and len(lancados) == 1
        and len(principais) == 1
        and _principais(nome) == principais,
        {
            "browser.launch": trazido.dados or trazido.motivo,
            "sites.open": nova.dados or nova.motivo,
            "lancados": lancados,
            "principais": [principais, _principais(nome)],
        },
    )
    for corpos in (ferramentas.navegador, *app._navegadores_de_outra_familia.values()):
        if corpos is not None:
            corpos.controle.fechar()
    if marionette is not None:
        marionette.fechar()
    for pid in lancados:
        if pid in _principais(nome):  # o PID do lançamento, conferido: nada de matar por nome
            os.kill(pid, signal.SIGTERM)
    fechou = _esperar(lambda: not _principais(nome) and not _sockets(familia), 30)
    relatorio.conferir(
        "o navegador que o Jarvis abriu fecha pelo PID conferido, e o host vai junto",
        bool(fechou),
        {"principais": _principais(nome), "sockets": sorted(_sockets(familia))},
    )


def dentro(nome: str) -> int:
    """Roda o roteiro e imprime o relatório — também quando ele quebra no meio."""
    relatorio = Relatorio(nome)
    try:
        _roteiro(nome, relatorio)
    except Exception as erro:  # quebrar no meio é resultado do teste: vai para o relatório
        relatorio.conferir("o roteiro chegou ao fim", False, f"{type(erro).__name__}: {erro}")
    print(MARCA + json.dumps(relatorio.__dict__, ensure_ascii=False), flush=True)
    return 0 if relatorio.ok else 1


def _roteiro(nome: str, relatorio: Relatorio) -> None:
    """O roteiro, de cima a baixo: um roteiro linear lê melhor que dez funções."""
    from jarvis.executor.ferramentas import Confirmacao, ResultadoDeFerramenta
    from jarvis.executor.nativas import Nativas
    from jarvis.executor.web import Resposta
    from jarvis.navegador import instalar
    from jarvis.navegador.cliente import NavegadorFalhou, NavegadorIndisponivel
    from jarvis.politica.objetivo import EstadoDoObjetivo
    from jarvis.s2.motor_claude_cli import sistema_com_ferramentas
    from jarvis.voz.estado import Estado

    os.environ.update(HOME=str(CASA), XDG_RUNTIME_DIR=str(RUN))
    os.environ.pop("XDG_CONFIG_HOME", None)
    CASA.mkdir(parents=True, exist_ok=True)
    RUN.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUN.chmod(0o700)
    familia = "chromium" if nome == "chromium" else "firefox"

    falas: list[str] = []
    codigo = instalar.principal(
        ["--instalar"],
        os.environ,
        CASA,
        saida=falas.append,
        repositorio=RAIZ,
        python=sys.executable,
    )
    relatorio.conferir("instalar no modo repositório", codigo == 0, falas[0] if falas else "")
    extensao = CASA / instalar.EXTENSAO_NO_USUARIO
    log = CASA / "navegador.log"

    with contextlib.ExitStack() as pilha:
        url = pilha.enter_context(_site())
        pilha.enter_context(_tela(nome, log))
        # Uma instância só (dono, 2026-10-21): sem navegador ativo, o Jarvis abre um; com ele
        # aberto, não abre outro. O roteiro de antes começa depois, com um navegador aberto por ele.
        _o_unico_caso_de_abrir(nome, extensao, url, relatorio)
        relatorio.versao = pilha.enter_context(_navegador(nome, extensao, url, log))
        vivos = _esperar(lambda: _sockets(familia), 40)
        if not relatorio.conferir("o navegador lançou o host pelo manifesto", vivos, list(vivos)):
            relatorio.conferir("log do navegador", False, _log_util(log))
            return
        pid = next(iter(vivos))
        relatorio.conferir("o processo do socket é o host deste código", _e_o_host(pid), pid)

        app = _aplicativo(nome, CHROMIUM if nome == "chromium" else FIREFOX, CASA / "sessao")
        ferramentas = app._montar_ferramentas()
        # O roteiro prova a extensão; o motor que enxerga a imagem tem prova à parte
        # (`tools/harness_tela_no_motor.py`), então aqui a tela fica ligada.
        ferramentas.motor_ve_imagem = lambda: True
        perguntas: list[Confirmacao] = []

        def rodar(tool: str, args: dict[str, Any], sim: bool = False) -> ResultadoDeFerramenta:
            ferramentas.novo_turno()  # um turno por conferência: leitura não contamina a outra

            def confirmar(pergunta: Confirmacao) -> bool:
                perguntas.append(pergunta)
                return sim

            return ferramentas.executar(tool, args, cancelado=lambda: False, confirmar=confirmar)

        catalogo = ferramentas.catalogo_para_o_modelo()
        ids = {t["id"] for t in catalogo}
        esperadas = {
            "browser.tabs",
            "browser.read",
            "browser.click",
            "browser.type",
            "browser.scroll",
            "browser.navigate",
            "browser.estado",
            "browser.inspecionar",
            "browser.acionar",
            "browser.tela",
        }
        prompt = sistema_com_ferramentas("Você é o Jarvis.", catalogo)
        relatorio.conferir(
            "o modelo enxerga as browser.* no prompt",
            esperadas <= ids and "- browser.read:" in prompt and "browser.acao_sensivel" not in ids,
            sorted(i for i in ids if i.startswith("browser.")),
        )

        abas = rodar("browser.tabs", {})
        aba = next(
            (a for a in abas.dados.get("abas", []) if "teste do Jarvis" in a["titulo"]), None
        )
        relatorio.conferir("browser.tabs acha a página", aba is not None, abas.dados or abas.motivo)
        alvo = {"tab_id": aba["tab_id"]} if aba else {}

        # O Chromium abre a URL da linha de comando correndo com o registro do conteúdo da
        # extensão: às vezes a página carrega antes, e fica sem ele (o produto diz «recarregue a
        # aba»). Navegar de novo, já com a extensão de pé, tira a sorte do roteiro — e prova a
        # browser.navigate.
        ida = rodar("browser.navigate", {**alvo, "url": url})
        relatorio.conferir(
            "browser.navigate leva a aba de novo à página",
            ida.status == "ok",
            ida.dados or ida.motivo,
        )

        def pagina_pronta() -> ResultadoDeFerramenta | None:
            lida = rodar("browser.read", alvo)
            return lida if lida.status == "ok" and "Olá" in str(lida.dados.get("texto")) else None

        lido = _esperar(pagina_pronta, 15) or rodar("browser.read", alvo)
        relatorio.conferir(
            "browser.read devolve o texto da página (não o envelope aninhado)",
            lido.status == "ok" and "estado inicial" in str(lido.dados.get("texto")),
            lido.dados or lido.motivo,
        )

        antes = len(perguntas)
        clique = rodar("browser.click", {**alvo, "alvo": "Mostrar detalhe"})
        depois = rodar("browser.read", alvo)
        relatorio.conferir(
            "browser.click num botão comum clica sem pedir o sim",
            clique.status == "ok"
            and len(perguntas) == antes
            and "detalhe aberto" in str(depois.dados.get("texto")),
            clique.dados or clique.motivo,
        )

        antes = len(perguntas)
        envio = rodar("browser.click", {**alvo, "alvo": "Pronto"}, sim=False)
        ainda = rodar("browser.read", alvo)
        pediu = perguntas[antes:]
        relatorio.conferir(
            "envio de formulário com rótulo neutro pede o sim, e o não impede o clique",
            envio.status == "negado"
            and pediu
            and "formulário" in pediu[0].motivo
            and "Olá" in str(ainda.dados.get("texto")),
            f"{envio.status}: {pediu[0].motivo if pediu else 'NÃO PERGUNTOU'}",
        )

        digitou = rodar("browser.type", {**alvo, "alvo": "Busca", "texto": "jarvis"})
        corpos = ferramentas.navegador
        assert corpos is not None
        try:
            campo = corpos.cliente.inspecionar(aba["tab_id"], "Busca") if aba else {}
        except (NavegadorFalhou, NavegadorIndisponivel) as erro:
            campo = {"erro": str(erro)}
        relatorio.conferir(
            "browser.type digita no campo de busca",
            digitou.status == "ok" and campo.get("texto") == "jarvis",
            digitou.dados or digitou.motivo,
        )

        senha = rodar("browser.type", {**alvo, "alvo": "Senha", "texto": "123456"})
        relatorio.conferir(
            "browser.type recusa o campo de senha",
            senha.status != "ok" and "senha" in senha.motivo.lower(),
            f"{senha.status}: {senha.motivo}",
        )

        # O caso do dono (2026-10-20): o campo de busca não se acha pelo texto; pelo mapa, sim.
        nao_achou = rodar("browser.type", {**alvo, "alvo": "campo de busca", "texto": "o primo"})
        relatorio.conferir(
            "a busca sem rótulo não se acha pelo texto (o caso do dono)",
            nao_achou.status == "erro" and "alvo_ausente" in nao_achou.motivo,
            f"{nao_achou.status}: {nao_achou.motivo}",
        )
        mapa = rodar("browser.inspecionar", {**alvo, "scripts": True})
        elementos = list(mapa.dados.get("elementos", []))
        busca = next((e for e in elementos if e.get("rotulo") == "Pesquisar"), None)
        painel = next((e for e in elementos if e.get("rotulo") == "Painel"), None)
        do_painel = [
            s.get("id")
            for s in mapa.dados.get("scripts", [])
            if "abrirPainel" in s.get("define", [])
        ]
        caixa = list(busca.get("caixa", [])) if busca else []
        relatorio.conferir(
            "browser.inspecionar acha a busca (ref, caixa em pixels) e liga o painel ao script",
            mapa.status == "ok"
            and busca is not None
            and busca.get("busca") is True
            and len(caixa) == 4
            and caixa[2] > 0
            and painel is not None
            and bool(do_painel)
            and painel.get("scripts") == do_painel,
            {"busca": busca, "painel": painel, "scripts": do_painel}
            if mapa.status == "ok"
            else mapa.motivo,
        )
        if busca is not None and aba is not None:
            antes = len(perguntas)
            pela_ref = rodar("browser.type", {**alvo, "ref": busca["ref"], "texto": "o primo rico"})
            enter = rodar(
                "browser.acionar", {**alvo, "ref": busca["ref"], "acao": "tecla", "tecla": "Enter"}
            )
            buscou = _esperar(
                lambda: (
                    "search_query=o+primo+rico" in str(corpos.cliente.aba(aba["tab_id"]).get("url"))
                ),
                10,
            )
            relatorio.conferir(
                "digitar pela ref e Enter buscam por GET, sem pedir o sim",
                pela_ref.status == "ok"
                and enter.status == "ok"
                and bool(buscou)
                and len(perguntas) == antes,
                f"{pela_ref.status}/{enter.status} {enter.dados or enter.motivo}",
            )
            rodar("browser.navigate", {**alvo, "url": url})
            _esperar(pagina_pronta, 15)
        de_novo = rodar("browser.inspecionar", alvo)
        refs = {e.get("rotulo"): e.get("ref") for e in de_novo.dados.get("elementos", [])}
        passou = rodar(
            "browser.acionar", {**alvo, "ref": str(refs.get("Menu")), "acao": "passar_o_mouse"}
        )
        menu = rodar("browser.read", alvo)
        relatorio.conferir(
            "browser.acionar passa o mouse no menu (mouseover da página roda)",
            passou.status == "ok" and "menu aberto" in str(menu.dados.get("texto")),
            passou.dados or passou.motivo,
        )
        clicou = rodar(
            "browser.acionar", {**alvo, "ref": str(refs.get("Painel")), "acao": "clicar"}
        )
        aberto = rodar("browser.read", alvo)
        relatorio.conferir(
            "browser.acionar clica no link que chama a função do script da página",
            clicou.status == "ok" and "painel aberto" in str(aberto.dados.get("texto")),
            clicou.dados or clicou.motivo,
        )
        antes = len(perguntas)
        envio = rodar(
            "browser.acionar", {**alvo, "ref": str(refs.get("Pronto")), "acao": "enviar"}, sim=False
        )
        ficou = rodar("browser.read", alvo)
        pediu = perguntas[antes:]
        relatorio.conferir(
            "browser.acionar «enviar» num formulário que envia pede o sim, e o não impede",
            envio.status == "negado"
            and bool(pediu)
            and "formulário" in pediu[0].motivo
            and "Olá" in str(ficou.dados.get("texto")),
            f"{envio.status}: {pediu[0].motivo if pediu else 'NÃO PERGUNTOU'}",
        )

        tela = rodar("browser.tela", alvo)
        imagem = tela.anexos[0] if tela.anexos else None
        caixas = [e.get("caixa", []) for e in tela.dados.get("inspecao", {}).get("elementos", [])]
        dentro_da_imagem = imagem is not None and all(
            len(c) == 4 and -2 <= c[0] < imagem.largura and -2 <= c[1] < imagem.altura
            for c in caixas
        )
        relatorio.conferir(
            "browser.tela captura a aba e traz o mapa do mesmo instante, com as caixas na imagem",
            tela.status == "ok"
            and imagem is not None
            and imagem.largura > 0
            and imagem.altura > 0
            and bool(caixas)
            and dentro_da_imagem
            and tela.dados.get("tela", {}).get("id") == imagem.id
            and str(tela.dados.get("inspecao", {}).get("id", "")).endswith(
                str(tela.dados.get("instantaneo"))
            ),
            {
                "imagem": [imagem.tipo, imagem.largura, imagem.altura, len(imagem.dados)]
                if imagem
                else None,
                "tela": tela.dados.get("tela"),
                "caixas": caixas[:4],
                "motivo": tela.motivo,
            },
        )

        estado = rodar("browser.estado", {})
        relatorio.conferir(
            "browser.estado diz conectado",
            estado.status == "ok" and estado.dados.get("situacao") == "conectado",
            estado.dados or estado.motivo,
        )

        def abas_agora() -> list[dict[str, Any]]:
            return list(rodar("browser.tabs", {}).dados.get("abas", []))

        abas_antes = abas_agora()
        segunda = url.replace("pagina.html", "pagina2.html")
        aberto = rodar("sites.open", {"url": segunda})
        abas_depois = (
            _esperar(
                lambda: (
                    (lista := abas_agora())
                    and any("Segunda página" in a["titulo"] for a in lista)
                    and lista
                ),
                10,
            )
            or abas_agora()
        )
        relatorio.conferir(
            "sites.open troca a URL da aba atual, sem aba nova nem lançar o navegador",
            aberto.status == "ok"
            and aberto.dados.get("reutilizou_aba") is True
            and len(abas_depois) == len(abas_antes)
            and any("Segunda página" in a["titulo"] for a in abas_depois),
            f"{aberto.status} {aberto.dados or aberto.motivo}; "
            f"abas {len(abas_antes)} → {len(abas_depois)}",
        )

        # Uma instância só (dono, 2026-10-21): o trabalho de fundo abria a janela própria do
        # Jarvis — a busca sem chave a criava —, o dono a viu como outra instância do Brave, e o
        # vídeo foi parar nela. Agora o fundo é uma aba em segundo plano NA JANELA DO DONO.
        def instancia() -> dict[str, Any]:
            """O que contaria como outra janela ou instância: as janelas do navegador, a janela do
            Jarvis, a página que a segura e os processos principais do navegador."""
            foco = corpos.cliente.janela_em_foco()
            return {
                "janelas": _janelas(corpos.cliente.abas()),
                "janela_do_jarvis": foco.get("janelaDoJarvisId"),
                "janela_html": sum(
                    str(a.get("url", "")).endswith("/janela.html") for a in corpos.cliente.abas()
                ),
                "principais": len(_principais(nome)),
            }

        uma_so = {"janelas": 1, "janela_do_jarvis": None, "janela_html": 0, "principais": 1}

        # A busca genérica (ADR-0033, emenda de 2026-10-21) não toca o navegador do dono: sem
        # chave, ela abria uma aba de fundo e a fechava — a «aba que abre e fecha sozinha» no
        # começo da tarefa. Agora vai direto (o buscador aqui é falso: o contêiner não tem rede).
        resultado_falso = (
            '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.youtube.com'
            '%2F%40primorico">O Primo Rico - YouTube</a>'
        )
        ferramentas.nativas = Nativas(
            lar=ferramentas.lar,
            ambiente={},
            obter=lambda u, _h: Resposta(200, u, "text/html", resultado_falso.encode()),
            resolver=lambda _host: ["93.184.216.34"],
        )
        ids_antes = sorted(str(a.get("id")) for a in abas_agora())
        x_antes = _janela_ativa_do_x()
        foco_antes = corpos.cliente.janela_em_foco()
        busca = rodar("web.buscar", {"consulta": "o primo rico"})
        time.sleep(1.0)  # uma aba que nascesse e fechasse teria aparecido nos eventos até aqui
        relatorio.conferir(
            "a busca genérica vai direto: nenhuma aba abre nem fecha no navegador do dono e o foco "
            "não muda",
            busca.status == "ok"
            and busca.dados.get("fonte") == "DuckDuckGo (direto, sem navegador)"
            and sorted(str(a.get("id")) for a in abas_agora()) == ids_antes
            and corpos.cliente.janela_em_foco().get("janelaId") == foco_antes.get("janelaId")
            and _janela_ativa_do_x() == x_antes,
            {"busca": busca.status, "fonte": busca.dados.get("fonte"), "abas": ids_antes},
        )

        # A leitura numa aba de fundo (`page.readUrl`) ficou só para a automação social: a
        # extensão continua lendo na janela do dono, sem foco, e fechando a aba no fim.
        ativa_antes = corpos.cliente.aba()
        foco_antes = corpos.cliente.janela_em_foco()
        try:
            lida = corpos.cliente.ler_em_segundo_plano(
                url.replace("pagina.html", "busca.html") + "?q=o+primo+rico"
            )
        except (NavegadorFalhou, NavegadorIndisponivel) as erro:
            lida = {"erro": str(erro)}
        fechou = _esperar(
            lambda: not any("Resultados de teste" in a.get("titulo", "") for a in abas_agora()), 10
        )
        links = [str(link.get("href")) for link in (lida.get("pagina") or {}).get("links", [])]
        ativa_depois = corpos.cliente.aba()
        foco_depois = corpos.cliente.janela_em_foco()
        relatorio.conferir(
            "page.readUrl lê numa aba de fundo, fecha a aba e não troca a aba do dono",
            "https://www.youtube.com/@primorico" in links
            and bool(fechou)
            and ativa_depois.get("id") == ativa_antes.get("id")
            and foco_depois.get("janelaId") == foco_antes.get("janelaId")
            and _janela_ativa_do_x() == x_antes,
            {
                "links": links[:4],
                "ativa": [ativa_antes.get("id"), ativa_depois.get("id")],
                "foco": [foco_antes, foco_depois],
            },
        )
        depois_da_busca = instancia()
        relatorio.conferir(
            "uma instância só: a busca sem chave não abre janela nem instância (era a «outra "
            "instância do Brave» do dono)",
            depois_da_busca == uma_so,
            depois_da_busca,
        )

        # C3 (ADR-0036, emendada): o Jarvis lê e clica numa aba de fundo da janela do dono, sem
        # tirar o foco dele. A tela da aba de fundo só sai no Firefox (`captureTab`); o Chromium só
        # captura a aba à vista, e o Jarvis não a traz para a frente para isso.
        x_antes = _janela_ativa_do_x()
        foco_antes = corpos.cliente.janela_em_foco()
        fundo = rodar("browser.navigate", {"url": url, "segundo_plano": True})
        tab_fundo = fundo.dados.get("tab_id")

        def fundo_pronta() -> bool:
            lida = rodar("browser.read", {"tab_id": tab_fundo})
            return lida.status == "ok" and "Olá" in str(lida.dados.get("texto"))

        pronta = _esperar(fundo_pronta, 15)
        clique_no_fundo = rodar("browser.click", {"tab_id": tab_fundo, "alvo": "Mostrar detalhe"})
        lida_no_fundo = rodar("browser.read", {"tab_id": tab_fundo})
        tela_no_fundo = rodar("browser.tela", {"tab_id": tab_fundo})
        foco_depois = corpos.cliente.janela_em_foco()
        x_depois = _janela_ativa_do_x()
        aba_de_fundo = corpos.cliente.aba(tab_fundo) if isinstance(tab_fundo, int) else {}
        tela_certa = (
            tela_no_fundo.status == "ok"
            if nome == "firefox"
            else tela_no_fundo.status == "erro" and "aba_escondida" in tela_no_fundo.motivo
        )
        no_fundo = instancia()
        relatorio.conferir(
            "o Jarvis lê e clica numa aba de fundo da janela do dono (sem active), sem janela "
            "nova, e o foco do dono não muda; a tela dela só no Firefox",
            fundo.status == "ok"
            and fundo.dados.get("janela") == "dono"
            and fundo.dados.get("segundo_plano") is True
            and aba_de_fundo.get("janelaId") == foco_antes.get("janelaId")
            and aba_de_fundo.get("ativa") is False
            and bool(pronta)
            and clique_no_fundo.status == "ok"
            and "detalhe aberto" in str(lida_no_fundo.dados.get("texto"))
            and tela_certa
            and foco_antes.get("janelaId") == foco_depois.get("janelaId")
            and foco_antes.get("abaAtivaId") == foco_depois.get("abaAtivaId")
            and no_fundo == uma_so
            and x_antes == x_depois,
            {
                "foco": [foco_antes, foco_depois],
                "x11": [x_antes, x_depois],
                "fundo": fundo.dados or fundo.motivo,
                "aba": aba_de_fundo,
                "tela": tela_no_fundo.status + " " + tela_no_fundo.motivo,
                "instancia": no_fundo,
            },
        )

        abas_antes_da_nova = len(abas_agora())
        nova = rodar("browser.navigate", {"url": url, "nova_aba": True})
        com_nova = _esperar(lambda: len(abas_agora()) == abas_antes_da_nova + 1, 10)
        relatorio.conferir(
            "browser.navigate com nova_aba abre uma aba e só uma",
            nova.status == "ok" and nova.dados.get("nova_aba") is True and com_nova,
            nova.dados or nova.motivo,
        )

        # Auditoria da integração (2026-10-21): o dono pediu "abra um vídeo no YouTube", a extensão
        # disse ok em 25 ms com a URL de antes, e o navegador dele "continuou igual".
        def turno(fala: str) -> Callable[..., ResultadoDeFerramenta]:
            """Um turno com a fala do dono (o objetivo e o método nascem dela), vários passos. O
            turno anterior respondeu: o objetivo dele acaba, como o cérebro faz."""
            if ferramentas.objetivo is not None:
                ferramentas.objetivo.concluir(EstadoDoObjetivo.CONCLUIDO)
            ferramentas.novo_turno(fala)

            def passo(tool: str, args: dict[str, Any], sim: bool = False) -> ResultadoDeFerramenta:
                def confirmar(pergunta: Confirmacao) -> bool:
                    perguntas.append(pergunta)
                    return sim

                return ferramentas.executar(
                    tool, args, cancelado=lambda: False, confirmar=confirmar
                )

            return passo

        video = turno("abra um vídeo no YouTube")(
            "browser.navigate",
            {**alvo, "url": "https://www.youtube.com/results?search_query=gatos"},
        )
        relatorio.conferir(
            "sem rede, «abra um vídeo no YouTube» volta erro dito (a página não abriu), não ok",
            video.status == "erro" and "(pagina_nao_abriu)" in video.motivo,
            f"{video.status}: {video.motivo or video.dados}",
        )
        rodar("browser.navigate", {**alvo, "url": url})

        # A aba do dono que estava ATRÁS de outra: pedido de ver traz a aba para a frente.
        frente = nova.dados.get("tab_id")
        foco_antes = corpos.cliente.janela_em_foco()
        visto = turno("abre a página de teste pra eu ver")("browser.navigate", {**alvo, "url": url})
        foco_depois = corpos.cliente.janela_em_foco()
        relatorio.conferir(
            "pedido de ver: a aba que estava atrás vem para a frente, e o resultado diz «visível»",
            visto.status == "ok"
            and visto.dados.get("visivel") is True
            and foco_antes.get("abaAtivaId") == frente
            and foco_depois.get("abaAtivaId") == (aba or {}).get("tab_id")
            and foco_depois.get("janelaId") == foco_antes.get("janelaId"),
            {"foco": [foco_antes, foco_depois], "navegou": visto.dados or visto.motivo},
        )

        # Trabalho que o dono não pediu para ver: numa aba de fundo da janela dele, e o foco fica.
        x_antes = _janela_ativa_do_x()
        foco_antes = corpos.cliente.janela_em_foco()
        pesquisa = turno("pesquisa o que diz a página de teste")
        ida = pesquisa("browser.navigate", {"url": url})
        lida_de_fundo = pesquisa("browser.read", {})
        foco_depois = corpos.cliente.janela_em_foco()
        x_depois = _janela_ativa_do_x()
        tab_da_pesquisa = ida.dados.get("tab_id")
        da_pesquisa = (
            corpos.cliente.aba(tab_da_pesquisa) if isinstance(tab_da_pesquisa, int) else {}
        )
        na_pesquisa = instancia()
        relatorio.conferir(
            "pesquisa sem pedido de ver vai numa aba de fundo da janela do dono, a leitura sem "
            "tab_id lê ela, e o foco do dono não muda",
            ida.status == "ok"
            and ida.dados.get("janela") == "dono"
            and ida.dados.get("segundo_plano") is True
            and ida.dados.get("visivel") is False
            and da_pesquisa.get("janelaId") == foco_antes.get("janelaId")
            and da_pesquisa.get("ativa") is False
            and lida_de_fundo.status == "ok"
            and lida_de_fundo.dados.get("tab_id") == tab_da_pesquisa
            and "Olá" in str(lida_de_fundo.dados.get("texto"))
            and foco_antes.get("janelaId") == foco_depois.get("janelaId")
            and foco_antes.get("abaAtivaId") == foco_depois.get("abaAtivaId")
            and na_pesquisa == uma_so
            and x_antes == x_depois,
            {
                "foco": [foco_antes, foco_depois],
                "x11": [x_antes, x_depois],
                "ida": ida.dados or ida.motivo,
                "aba": da_pesquisa,
                "lida": lida_de_fundo.status + " " + lida_de_fundo.motivo,
                "instancia": na_pesquisa,
            },
        )
        try:
            mostrada = corpos.cliente.mostrar(int(ida.dados["tab_id"]))
        except (NavegadorFalhou, NavegadorIndisponivel, KeyError, TypeError, ValueError) as erro:
            mostrada = {"erro": str(erro)}
        foco_mostrado = corpos.cliente.janela_em_foco()
        relatorio.conferir(
            "tabs.show traz a aba de fundo para a frente, na janela do dono",
            mostrada.get("janela") == "dono"
            and mostrada.get("visivel") is True
            and foco_mostrado.get("abaAtivaId") == tab_da_pesquisa
            and foco_mostrado.get("janelaId") == foco_antes.get("janelaId"),
            {"mostrada": mostrada, "foco": foco_mostrado},
        )

        # A outra metade do caso do dono: o sites.open com nova_aba executava o binário do
        # navegador com a URL, e o Brave já aberto a punha na última janela ativa dele.
        executados: list[tuple[str, ...]] = []

        def nao_lancar(argv: Any, **_: Any) -> int:
            executados.append(tuple(argv))
            return 0

        assert ferramentas.navegadores is not None
        ferramentas.navegadores.lancar = nao_lancar  # se algo tentar abrir o navegador, fica aqui
        antes_da_guia = len(abas_agora())
        foco_antes = corpos.cliente.janela_em_foco()
        guia = turno("abre a segunda página numa aba nova pra eu ver")(
            "sites.open", {"url": segunda, "nova_aba": True}
        )
        com_a_guia = _esperar(lambda: len(abas_agora()) == antes_da_guia + 1, 10)
        foco_depois = corpos.cliente.janela_em_foco()
        com_guia = instancia()
        relatorio.conferir(
            "sites.open com nova_aba e o navegador aberto: guia nova na janela do dono, pela "
            "extensão, sem executar o navegador nem abrir janela",
            guia.status == "ok"
            and executados == []
            and bool(com_a_guia)
            and foco_depois.get("janelaId") == foco_antes.get("janelaId")
            and foco_depois.get("abaAtivaId") not in (None, foco_antes.get("abaAtivaId"))
            and com_guia == uma_so,
            {
                "sites.open": guia.dados or guia.motivo,
                "executados": executados,
                "foco": [foco_antes, foco_depois],
                "instancia": com_guia,
            },
        )

        # O indicador e o PARAR (ADR-0027 regra 4) -------------------------------------------------
        app.ferramentas = ferramentas  # o PARAR cancela o turno do app (epoch) e as tarefas dele
        vigia = url.replace("pagina.html", "vigia.html")
        vigia2 = url.replace("pagina.html", "vigia2.html")
        REGISTRO.clear()
        pedido = turno("abre a página de vigia pra eu ver")
        comeco_ms = time.time() * 1000
        passos = [
            pedido("browser.navigate", {**alvo, "url": vigia}),
            pedido("browser.read", {}),
            # Depois de ler, o turno está contaminado, e um IP (o site de teste) não tem domínio
            # registrável para entrar no objetivo: a política pergunta (ADR-0030) e o dono diz sim.
            pedido("browser.navigate", {"url": vigia2}, sim=True),
            pedido("browser.read", {}),
        ]
        time.sleep(1.5)  # o Jarvis pensando: a aba continua no controle
        durante = corpos.cliente.chamar("controle.estado")
        soltou_ms = time.time() * 1000
        assert ferramentas.objetivo is not None
        ferramentas.objetivo.concluir(EstadoDoObjetivo.CONCLUIDO)  # o turno respondeu
        _esperar(lambda: any(e["ev"] == "sem_faixa" and e["t"] >= soltou_ms for e in REGISTRO), 5)
        solto = corpos.cliente.chamar("controle.estado")
        cobertura = _cobertura(REGISTRO, comeco_ms, soltou_ms)
        na_aba = [a["tabId"] for a in durante.get("abas", []) if a["tabId"] == alvo.get("tab_id")]
        relatorio.conferir(
            "a faixa «no controle» está em toda página da aba enquanto o Jarvis controla, e some "
            "sozinha quando ele solta",
            all(p.status == "ok" for p in passos)
            and cobertura["ok"]
            and bool(na_aba)
            and not any(a["tabId"] == alvo.get("tab_id") for a in solto.get("abas", [])),
            {
                **cobertura,
                "passos": [f"{p.status} {p.dados.get('tab_id', '')} {p.motivo}" for p in passos],
                "eventos": [
                    (e["doc"], e["ev"], e["p"], round(e["t"] - comeco_ms)) for e in REGISTRO
                ],
                "solto": solto,
            },
        )

        REGISTRO.clear()
        parado = turno("abre a página de vigia pra eu ver")
        ida = parado("browser.navigate", {**alvo, "url": vigia})
        _esperar(lambda: any(e["ev"] == "faixa" for e in REGISTRO), 5)
        epoca = app.epoch
        app.estado = Estado.PENSANDO  # o turno ainda no ar
        try:
            clique_do_dono = _clicar_no_parar(nome, "vigia.html")
        except Exception as erro:  # o clique faz parte da prova: vai para o relatório
            clique_do_dono = f"{type(erro).__name__}: {erro}"
        saiu = _esperar(lambda: any(e["ev"] == "sem_faixa" for e in REGISTRO), 5)
        cancelou = _esperar(lambda: app.epoch > epoca, 5)
        recusado = parado("browser.read", {})
        app.estado = Estado.PARADO
        de_novo = turno("lê a página de vigia")("browser.read", alvo)
        relatorio.conferir(
            "PARAR na faixa (clique de verdade do dono): a faixa some, o turno é cancelado "
            "(epoch) e o pedido parado não age mais; o pedido seguinte volta a agir",
            ida.status == "ok"
            and bool(saiu)
            and bool(cancelou)
            and recusado.status == "negado"
            and de_novo.status == "ok",
            {
                "clique_do_dono": clique_do_dono,
                "epoch": [epoca, app.epoch],
                "recusado": f"{recusado.status}: {recusado.motivo}",
                "de_novo": de_novo.status,
            },
        )

        # Reaproveitar a aba (pedido do dono, 2026-10-21): 3 casos --------------------------------
        local = url.replace("127.0.0.1", "localhost")  # outro "site" no mesmo servidor
        segunda_local = local.replace("pagina.html", "pagina2.html")
        rodar("browser.navigate", {**alvo, "url": url})
        criada = rodar("browser.navigate", {"url": segunda_local, "nova_aba": True})
        atras = criada.dados.get("tab_id")
        corpos.cliente.mostrar(alvo["tab_id"])  # a aba de teste do dono à frente; a nova, atrás
        total = len(abas_agora())

        mesma = turno("abre a segunda página pra eu ver")("sites.open", {"url": segunda_local})
        foco = corpos.cliente.janela_em_foco()
        url_do_dono = corpos.cliente.aba(alvo["tab_id"]).get("url")
        relatorio.conferir(
            "reuso 1/3 — a página já aberta numa aba de trás: só ativa, sem recarregar nem abrir",
            mesma.status == "ok"
            and foco.get("abaAtivaId") == atras
            and len(abas_agora()) == total
            and url_do_dono == url,
            {"sites.open": mesma.dados or mesma.motivo, "foco": foco, "aba_do_dono": url_do_dono},
        )

        corpos.cliente.mostrar(alvo["tab_id"])
        mesmo_site = turno("abre a página de teste do localhost pra eu ver")(
            "browser.navigate", {"url": local}
        )
        url_do_dono = corpos.cliente.aba(alvo["tab_id"]).get("url")
        relatorio.conferir(
            "reuso 2/3 — mesmo site noutra página: navega a aba que já tem o site, não a atual",
            mesmo_site.status == "ok"
            and mesmo_site.dados.get("reutilizou") == "mesmo_site"
            and mesmo_site.dados.get("tab_id") == atras
            and len(abas_agora()) == total
            and url_do_dono == url,
            {"navegou": mesmo_site.dados or mesmo_site.motivo, "aba_do_dono": url_do_dono},
        )

        corpos.cliente.mostrar(alvo["tab_id"])
        terceiro = f"http://127.0.0.1:{DRIVER['outra_porta']}/pagina2.html"
        nenhuma = turno("abre a outra página pra eu ver")("browser.navigate", {"url": terceiro})
        url_do_dono = corpos.cliente.aba(alvo["tab_id"]).get("url")
        foco = corpos.cliente.janela_em_foco()
        com_terceiro = instancia()
        relatorio.conferir(
            "reuso 3/3 — nenhuma aba tem o site e a atual é de outro: guia nova na janela do dono, "
            "à vista, e a página da aba dele fica (dono, 2026-10-21)",
            nenhuma.status == "ok"
            and nenhuma.dados.get("tab_id") != alvo["tab_id"]
            and nenhuma.dados.get("nova_aba") is True
            and nenhuma.dados.get("visivel") is True
            and "reutilizou" not in nenhuma.dados
            and len(abas_agora()) == total + 1
            and url_do_dono == url
            and foco.get("abaAtivaId") == nenhuma.dados.get("tab_id")
            and com_terceiro == uma_so,
            {
                "navegou": nenhuma.dados or nenhuma.motivo,
                "aba_do_dono": url_do_dono,
                "foco": foco,
                "instancia": com_terceiro,
            },
        )
        relatorio.conferir(
            "nada executou o navegador com ele aberto (o lançador ficou vazio no roteiro inteiro)",
            executados == [],
            executados,
        )

        # O gancho da automação social (desligado no Jarvis): o ÚNICO caminho para a janela
        # própria. Ligado só aqui, para provar que ele ainda funciona no navegador de verdade.
        foco_antes = corpos.cliente.janela_em_foco()
        x_antes = _janela_ativa_do_x()
        janelas_antes_social = _janelas(corpos.cliente.abas())
        corpos.cliente.automacao_social = True
        try:
            social = turno("pesquisa o que diz a segunda página")(
                "browser.navigate", {"url": segunda}
            )
        finally:
            corpos.cliente.automacao_social = False
        foco_social = corpos.cliente.janela_em_foco()
        janelas_com_social = _janelas(corpos.cliente.abas())
        relatorio.conferir(
            "só o modo automacao_social (o gancho) abre a janela própria do Jarvis, sem tirar o "
            "foco do dono",
            social.status == "ok"
            and social.dados.get("janela") == "jarvis"
            and janelas_com_social == janelas_antes_social + 1
            and foco_social.get("janelaDoJarvisId") is not None
            and foco_social.get("janelaId") == foco_antes.get("janelaId")
            and _janela_ativa_do_x() == x_antes,
            {"social": social.dados or social.motivo, "foco": [foco_antes, foco_social]},
        )
        rodar("browser.navigate", {**alvo, "url": url})

        os.kill(pid, signal.SIGTERM)  # PID conferido acima em /proc: é o host, e só ele
        novo = _esperar(lambda: [p for p in _sockets(familia) if p != pid and _e_o_host(p)], 30)
        de_volta = rodar("browser.tabs", {})
        relatorio.conferir(
            "host derrubado volta sozinho pela reconexão da extensão",
            bool(novo) and de_volta.status == "ok",
            f"{pid} → {novo}: {de_volta.status} {de_volta.motivo}",
        )

        vivo = novo[0] if novo else pid
        time.sleep(OCIOSO_S)
        ocioso = rodar("browser.tabs", {})
        relatorio.conferir(
            f"depois de {OCIOSO_S:.0f} s sem pedido o mesmo host responde",
            _e_o_host(vivo) and ocioso.status == "ok",
            f"pid {vivo}: {ocioso.status} {ocioso.motivo}",
        )


# --- no host --------------------------------------------------------------------------------------
def _podman() -> str:
    achado = shutil.which("podman")
    if achado is None:
        raise SystemExit("o podman não está no PATH: este roteiro só roda em contêiner")
    return achado


def _garantir_imagem(podman: str) -> None:
    existe = subprocess.run([podman, "image", "exists", IMAGEM], check=False)
    if existe.returncode == 0:
        return
    print(f"construindo {IMAGEM} (fedora:44 + chromium + firefox)…", flush=True)
    with tempfile.TemporaryDirectory() as contexto:
        subprocess.run(
            [podman, "build", "-t", IMAGEM, "-f", "-", contexto],
            input=CONTAINERFILE,
            text=True,
            check=True,
        )


def rodar_no_conteiner(podman: str, nome: str) -> dict[str, Any]:
    python = RAIZ / ".venv" / "bin" / "python"
    pythons_do_uv = Path(sys.base_prefix).parent  # o `.venv` aponta para cá (cpython-3.12…)
    comando = [
        podman,
        "run",
        "--rm",
        "--name",
        f"jarvis-nav-{nome}-{int(time.time())}",
        "--timeout",
        str(SEGUNDOS_POR_NAVEGADOR),
        "--network",
        "none",
        "--userns=keep-id",
        "-v",
        f"{RAIZ}:{RAIZ}:ro",
        "-v",
        f"{pythons_do_uv}:{pythons_do_uv}:ro",
        IMAGEM,
        str(python),
        str(RAIZ / "tools" / "harness_navegador.py"),
        "--dentro",
        nome,
    ]
    feito = subprocess.run(
        comando, capture_output=True, text=True, check=False, timeout=SEGUNDOS_POR_NAVEGADOR + 60
    )
    for linha in feito.stdout.splitlines():
        if linha.startswith(MARCA):
            dados: dict[str, Any] = json.loads(linha[len(MARCA) :])
            return dados
    return {
        "navegador": nome,
        "versao": "",
        "conferencias": [
            {
                "nome": "o roteiro terminou",
                "ok": False,
                "detalhe": (feito.stdout + feito.stderr)[-1500:],
            }
        ],
    }


def main(argumentos: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("--navegador", choices=NAVEGADORES, action="append")
    analisador.add_argument("--dentro", choices=NAVEGADORES, help=argparse.SUPPRESS)
    analisador.add_argument(
        "--detalhes", action="store_true", help="mostra o detalhe também das que passaram"
    )
    args = analisador.parse_args(argumentos)
    if args.dentro:
        return dentro(args.dentro)
    podman = _podman()
    _garantir_imagem(podman)
    falhas = 0
    for nome in args.navegador or NAVEGADORES:
        print(f"\n== {nome} (contêiner sem rede, HOME descartável) ==", flush=True)
        relatorio = rodar_no_conteiner(podman, nome)
        print(f"   {relatorio.get('versao') or 'versão desconhecida'}")
        for conferencia in relatorio["conferencias"]:
            marca = "ok " if conferencia["ok"] else "FALHOU"
            print(f"   {marca} {conferencia['nome']}")
            if not conferencia["ok"] or args.detalhes:
                print(f"          {conferencia['detalhe']}")
        falhas += not all(c["ok"] for c in relatorio["conferencias"])
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
