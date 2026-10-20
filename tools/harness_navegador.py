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

O que se confere, por navegador (14 pontos): o host nasce; o modelo enxerga as `browser.*`;
`browser.tabs` acha a página e `browser.navigate` a recarrega; `browser.read` lê o texto; um botão
comum é clicado sem pergunta; um botão de **envio de formulário** com rótulo neutro
pede o "sim" (e o "não" impede o clique); `browser.type` digita na busca e recusa a senha;
`browser.estado` diz conectado; o host derrubado (PID conferido em `/proc`) volta pela reconexão
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
IMAGEM: Final = "localhost/jarvis-nav-teste:latest"
CONTAINERFILE: Final = (
    "FROM registry.fedoraproject.org/fedora:44\n"
    "RUN dnf -y install --setopt=install_weak_deps=False chromium firefox procps-ng findutils "
    "&& dnf clean all\n"
)
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
"""
"""«Pronto» é um envio de formulário com rótulo neutro: só a inspeção do alvo o pega."""


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
    if nome == "chromium":
        versao = subprocess.run(
            [CHROMIUM, "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        processo = subprocess.Popen(
            [
                CHROMIUM,
                "--headless=new",
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
        processo.terminate()  # o PID é o deste Popen: nada de matar por nome
        try:
            processo.wait(15)
        except subprocess.TimeoutExpired:
            processo.kill()
        saida.close()


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
    from jarvis.navegador import instalar
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
            ),
            raiz=raiz,
            ambiente={**os.environ, "JARVIS_AUDIO_BACKEND": "arquivo"},
            lar=CASA,
        )
        ferramentas = app._montar_ferramentas()
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

        estado = rodar("browser.estado", {})
        relatorio.conferir(
            "browser.estado diz conectado",
            estado.status == "ok" and estado.dados.get("situacao") == "conectado",
            estado.dados or estado.motivo,
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
            if not conferencia["ok"]:
                print(f"          {conferencia['detalhe']}")
        falhas += not all(c["ok"] for c in relatorio["conferencias"])
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
