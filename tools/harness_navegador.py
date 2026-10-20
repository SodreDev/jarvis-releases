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

O que se confere, por navegador (16 pontos): o host nasce; o modelo enxerga as `browser.*`;
`browser.tabs` acha a página e `browser.navigate` a recarrega; `browser.read` lê o texto; um botão
comum é clicado sem pergunta; um botão de **envio de formulário** com rótulo neutro
pede o "sim" (e o "não" impede o clique); `browser.type` digita na busca e recusa a senha;
`browser.estado` diz conectado; `sites.open` troca a URL da aba atual e `browser.navigate`
com `nova_aba` abre uma só; o host derrubado (PID conferido em `/proc`) volta pela reconexão
da extensão; e, 40 s sem pedido, o mesmo host continua respondendo.

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
import contextlib
import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

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
SEGUNDOS_POR_NAVEGADOR: Final = 300
OCIOSO_S: Final = 40.0
"""Mais que os 30 s em que o Chromium encerra service worker ocioso (e o Firefox, event page)."""
MARCA: Final = "RELATORIO "
CASA: Final = Path("/tmp/casa")  # noqa: S108 — dentro do contêiner descartável
RUN: Final = Path("/tmp/run")  # noqa: S108
PORTA_DO_MARIONETTE: Final = 2828
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


# --- dentro do contêiner ------------------------------------------------------------------------
@dataclass
class Relatorio:
    navegador: str
    versao: str = ""
    conferencias: list[dict[str, Any]] = field(default_factory=list)

    def conferir(self, nome: str, ok: object, detalhe: object = "") -> bool:
        passou = bool(ok)
        self.conferencias.append({"nome": nome, "ok": passou, "detalhe": str(detalhe)[:400]})
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


@contextlib.contextmanager
def _site() -> Iterator[str]:
    pasta = Path(tempfile.mkdtemp(prefix="site-"))
    (pasta / "pagina.html").write_text(PAGINA, encoding="utf-8")
    (pasta / "pagina2.html").write_text(SEGUNDA, encoding="utf-8")
    (pasta / "busca.html").write_text(BUSCA, encoding="utf-8")

    class Quieto(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

    def criar(*args: Any) -> Quieto:
        return Quieto(*args, directory=str(pasta))

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), criar)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}/pagina.html"
    finally:
        servidor.shutdown()


@contextlib.contextmanager
def _navegador(nome: str, extensao: Path, url: str, log: Path) -> Iterator[str]:
    """Abre o navegador headless com a extensão e devolve a versão dele."""
    saida = log.open("wb")
    extras: list[subprocess.Popen[bytes]] = []
    if nome == "chromium":
        versao = subprocess.run(
            [CHROMIUM, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        com_janela = Path(XVFB).exists() and Path(OPENBOX).exists()
        if com_janela:
            # Janela de verdade num X virtual, com gerenciador de janelas: o foco é observável.
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
        processo = subprocess.Popen(
            [
                CHROMIUM,
                *([] if com_janela else ["--headless=new"]),
                "--no-sandbox",  # o contêiner não tem o namespace que a caixa de areia pede
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=DisableLoadExtensionCommandLineSwitch",
                f"--user-data-dir={CASA / '.config' / 'chromium'}",
                f"--load-extension={extensao}",
                url,
            ],
            stdout=saida,
            stderr=subprocess.STDOUT,
        )
    else:
        versao = subprocess.run(
            [FIREFOX, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        perfil = CASA / "perfil-firefox"
        perfil.mkdir(parents=True, exist_ok=True)
        (perfil / "user.js").write_text(
            f'user_pref("marionette.port", {PORTA_DO_MARIONETTE});\n'
            'user_pref("browser.shell.checkDefaultBrowser", false);\n'
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n',
            encoding="utf-8",
        )
        processo = subprocess.Popen(
            [FIREFOX, "-headless", "-no-remote", "-profile", str(perfil), "-marionette"],
            stdout=saida,
            stderr=subprocess.STDOUT,
        )
        marionette = Marionette()
        marionette.comando("WebDriver:NewSession", {})
        marionette.comando("Addon:Install", {"path": str(extensao), "temporary": True})
        marionette.comando("WebDriver:Navigate", {"url": url})
    try:
        yield versao
    finally:
        for filho in (processo, *reversed(extras)):
            filho.terminate()  # o PID é o deste Popen: nada de matar por nome
            try:
                filho.wait(15)
            except subprocess.TimeoutExpired:
                filho.kill()
        saida.close()


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
    from jarvis.executor.web import BuscaIndisponivel
    from jarvis.navegador import instalar
    from jarvis.navegador.busca import Buscador, BuscaNoNavegador
    from jarvis.navegador.cliente import NavegadorFalhou, NavegadorIndisponivel
    from jarvis.s2.motor_claude_cli import sistema_com_ferramentas
    from jarvis.voz.app import Aplicativo
    from jarvis.voz.config import Configuracao

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

    with _site() as url, _navegador(nome, extensao, url, log) as versao:
        relatorio.versao = versao
        vivos = _esperar(lambda: _sockets(familia), 40)
        if not relatorio.conferir("o navegador lançou o host pelo manifesto", vivos, list(vivos)):
            relatorio.conferir("log do navegador", False, _log_util(log))
            return
        pid = next(iter(vivos))
        relatorio.conferir("o processo do socket é o host deste código", _e_o_host(pid), pid)

        raiz = CASA / "sessao"
        raiz.mkdir(exist_ok=True)
        app = Aplicativo(
            configuracao=Configuracao(
                asr="asr-whisper-local",
                tts="tts-parametrico",
                s2="eco",
                acesso="jarvis",
                navegador_controlado=True,
                navegadores=(f"{nome}={CHROMIUM if nome == 'chromium' else FIREFOX}",),
                navegador_principal=nome,
            ),
            raiz=raiz,
            ambiente={**os.environ, "JARVIS_AUDIO_BACKEND": "arquivo"},
            lar=CASA,
        )
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
        # A busca sem chave (ADR-0033): numa aba de fundo, lida e fechada; a do dono não muda.
        buscador = Buscador(
            "Página de busca de teste",
            url.replace("pagina.html", "busca.html") + "?q={consulta}",
            frozenset({""}),  # os links do próprio servidor (IP) são do buscador
        )
        ativa_antes = corpos.cliente.aba()
        try:
            achado = BuscaNoNavegador(corpos.cliente, (buscador,))("o primo rico")
        except BuscaIndisponivel as erro:
            achado = {"erro": str(erro)}
        fechou = _esperar(
            lambda: not any("Resultados de teste" in a.get("titulo", "") for a in abas_agora()), 10
        )
        ativa_depois = corpos.cliente.aba()
        relatorio.conferir(
            "a busca pela extensão lê numa aba de fundo, fecha a aba e não troca a aba do dono",
            [r.get("url") for r in achado.get("resultados", [])]
            == ["https://www.youtube.com/@primorico", "https://pt.wikipedia.org/wiki/Thiago_Nigro"]
            and bool(fechou)
            and ativa_depois.get("id") == ativa_antes.get("id"),
            {"achado": achado, "ativa": [ativa_antes.get("id"), ativa_depois.get("id")]},
        )

        # C3 (ADR-0036): o Jarvis trabalha na janela própria, sem tirar o foco do dono.
        x_antes = _janela_ativa_do_x()
        foco_antes = corpos.cliente.janela_em_foco()
        fundo = rodar("browser.navigate", {"url": url, "segundo_plano": True})
        tab_jarvis = fundo.dados.get("tab_id")

        def jarvis_pronta() -> bool:
            lida = rodar("browser.read", {"tab_id": tab_jarvis})
            return lida.status == "ok" and "Olá" in str(lida.dados.get("texto"))

        pronta = _esperar(jarvis_pronta, 15)
        clique_no_fundo = rodar("browser.click", {"tab_id": tab_jarvis, "alvo": "Mostrar detalhe"})
        lida_no_fundo = rodar("browser.read", {"tab_id": tab_jarvis})
        tela_no_fundo = rodar("browser.tela", {"tab_id": tab_jarvis})
        foco_depois = corpos.cliente.janela_em_foco()
        x_depois = _janela_ativa_do_x()
        relatorio.conferir(
            "o Jarvis lê, clica e vê a tela na janela própria, e o foco do dono não muda",
            fundo.status == "ok"
            and fundo.dados.get("janela") == "jarvis"
            and bool(pronta)
            and clique_no_fundo.status == "ok"
            and "detalhe aberto" in str(lida_no_fundo.dados.get("texto"))
            and tela_no_fundo.status == "ok"
            and foco_antes.get("janelaId") == foco_depois.get("janelaId")
            and foco_antes.get("abaAtivaId") == foco_depois.get("abaAtivaId")
            and foco_depois.get("janelaDoJarvisId") not in (None, foco_antes.get("janelaId"))
            and x_antes == x_depois,
            {
                "foco": [foco_antes, foco_depois],
                "x11": [x_antes, x_depois],
                "fundo": fundo.dados or fundo.motivo,
                "tela": tela_no_fundo.status + " " + tela_no_fundo.motivo,
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
