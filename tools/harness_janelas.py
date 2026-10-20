"""O foco de um app aberto, de ponta a ponta, num X DE VERDADE, em contêiner (ADR-0037).

    uv run --frozen python -m tools.harness_janelas
    uv run --frozen python -m tools.harness_janelas --detalhes

Por que contêiner: teste não toca as janelas do dono. Um X virtual (Xvfb) com gerenciador de
janelas (openbox, configurado para **não** dar o foco a janela nova — o caso em que o Jarvis tem de
pô-la na frente), `wmctrl` e `xprop` de verdade, e "apps" que são `xterm` com a classe e o título
de cada caso, abertos por lançadores que demoram como o Steam. Sem rede (`--network none`), HOME
descartável; o repositório e o Python do `uv` entram só leitura. Cada contêiner tem `--name` e
`--timeout`; os processos de cada caso saem pelo grupo do PID que o lançamento devolveu.

O caminho provado é o do Jarvis: `Aplicativo.abrir` (a porta de janelas que o ambiente escolhe, o
gestor de tarefas e o prazo da configuração) → `apps.launch` no executor de verdade (PDP, catálogo,
auditoria) → o lançador abre o processo → a tarefa de foco lista as janelas (`wmctrl -lxp`,
`xprop`) e pede `window.focus_app` com o id → o PDP deixa → `wmctrl -i -a` → o
`_NET_ACTIVE_WINDOW` do X muda para a janela do app, e só para ela.

Os casos: o app que abre na hora (vai para a frente, sem aviso falado); o jogo pelo Steam (a conta
pedida ao dono, a janela do Steam, uma janela genérica com o nome do jogo e, nove segundos depois,
o jogo — só ele vai para a frente, ligado pelo `reaper` do Steam com `AppId=480`); duas janelas
empatadas (pergunta ao dono, ninguém vai para a frente); e o prazo (a falha diz que a janela não
apareceu e cita a genérica, sem ligação).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
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
IMAGEM: Final = "localhost/jarvis-janelas-teste:x11"
CONTAINERFILE: Final = (
    "FROM registry.fedoraproject.org/fedora:44\n"
    "RUN dnf -y install --setopt=install_weak_deps=False xorg-x11-server-Xvfb openbox xprop "
    "wmctrl xterm procps-ng && dnf clean all\n"
)
TELA_VIRTUAL: Final = ":99"
XVFB: Final = "/usr/bin/Xvfb"  # os da imagem (fedora:44)
OPENBOX: Final = "/usr/bin/openbox"
XTERM: Final = "/usr/bin/xterm"
SLEEP: Final = "/usr/bin/sleep"
WMCTRL: Final = "/usr/bin/wmctrl"
XPROP: Final = "/usr/bin/xprop"
SEGUNDOS: Final = 240
MARCA: Final = "RELATORIO "
CASA: Final = Path("/tmp/casa")  # noqa: S108 — dentro do contêiner descartável
LANCADORES: Final = Path("/tmp/lancadores")  # noqa: S108
SEM_FOCO_NOVO: Final = """<?xml version="1.0" encoding="UTF-8"?>
<openbox_config xmlns="http://openbox.org/3.4/rc">
  <focus><focusNew>no</focusNew><followMouse>no</followMouse></focus>
</openbox_config>
"""


@dataclass
class Relatorio:
    versao: str = ""
    conferencias: list[dict[str, Any]] = field(default_factory=list)

    def conferir(self, nome: str, ok: object, detalhe: object = "") -> bool:
        passou = bool(ok)
        self.conferencias.append({"nome": nome, "ok": passou, "detalhe": str(detalhe)[:400]})
        print(f"{'ok ' if passou else 'FALHOU'} {nome}  {str(detalhe)[:160]}", flush=True)
        return passou


# --- dentro do contêiner ------------------------------------------------------------------
def _ativa() -> int:
    saida = subprocess.run(
        [XPROP, "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, check=False
    ).stdout
    texto = saida.split("#", 1)[-1].split(",")[0].strip() if "#" in saida else ""
    return int(texto, 16) if texto.startswith("0x") else 0


def _janelas() -> list[tuple[int, str, str]]:
    """(id, classe, título) pelo `wmctrl -lxp`, como o Jarvis vê."""
    saida = subprocess.run([WMCTRL, "-lxp"], capture_output=True, text=True, check=False).stdout
    achadas = []
    for linha in saida.splitlines():
        partes = linha.split(None, 5)
        if len(partes) >= 5 and partes[0].startswith("0x"):
            titulo = partes[5] if len(partes) > 5 else ""
            achadas.append((int(partes[0], 16), partes[3].split(".")[-1], titulo))
    return achadas


def _id_de(classe: str, titulo: str = "") -> int:
    return next((i for i, c, t in _janelas() if c == classe and (not titulo or t == titulo)), 0)


def _esperar(condicao: Callable[[], Any], prazo_s: float) -> Any:
    fim = time.monotonic() + prazo_s
    while time.monotonic() < fim:
        valor = condicao()
        if valor:
            return valor
        time.sleep(0.1)
    return condicao()


def _xterm(classe: str, titulo: str) -> list[str]:
    return [XTERM, "-class", classe, "-T", titulo, "-e", SLEEP, "900"]


def _escrever_lancador(nome: str, corpo: str) -> Path:
    LANCADORES.mkdir(parents=True, exist_ok=True)
    caminho = LANCADORES / nome
    caminho.write_text(f"#!{sys.executable}\n{corpo}", "utf-8")
    caminho.chmod(0o755)
    return caminho


def _preparar_apps() -> dict[str, str]:
    """Os `.desktop` (na pasta do usuário, onde o Jarvis procura) e os lançadores de cada caso."""
    reaper = _escrever_lancador(
        "reaper",
        "import subprocess, sys\ni = sys.argv.index('--')\n"
        "sys.exit(subprocess.call(sys.argv[i + 1:]))\n",
    )
    steam = _escrever_lancador(
        "steam",
        "import subprocess, time\n"
        f"conta = subprocess.Popen({_xterm('steam', 'Steam - Entrar')!r})\n"
        "time.sleep(5)\n"
        "conta.terminate()\nconta.wait()\n"
        f"cliente = subprocess.Popen({_xterm('steam', 'Steam')!r})\n"
        "time.sleep(4)\n"
        f"jogo = [{str(reaper)!r}, 'SteamLaunch', 'AppId=480', '--', "
        f"*{_xterm('spacewar_linux', 'SW')!r}]\n"
        "subprocess.call(jogo)\n",
    )
    notas = _escrever_lancador(
        "notas",
        "import subprocess\n"
        f"a = subprocess.Popen({_xterm('notas', 'Notas')!r})\n"
        f"b = subprocess.Popen({_xterm('notas', 'Notas')!r})\n"
        "a.wait()\n",
    )
    planilha = _escrever_lancador("planilha", f"import os\nos.execv({SLEEP!r}, ['sleep', '900'])\n")
    pasta = CASA / ".local" / "share" / "applications"
    pasta.mkdir(parents=True, exist_ok=True)
    apps = {
        "calculadora": ("Calculadora", " ".join(_xterm("Calculadora", "Calculadora"))),
        "spacewar": ("Spacewar", f"{steam} steam://rungameid/480"),
        "notas": ("Notas", str(notas)),
        "planilha": ("Planilha", str(planilha)),
    }
    for identificador, (nome, exec_) in apps.items():
        (pasta / f"{identificador}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName={nome}\nExec={exec_}\n", "utf-8"
        )
    return {i: nome for i, (nome, _) in apps.items()}


@contextlib.contextmanager
def _tela() -> Iterator[None]:
    """Xvfb e openbox sem foco em janela nova; tudo sai pelo PID que este código abriu."""
    rc = CASA / "openbox-rc.xml"
    rc.write_text(SEM_FOCO_NOVO, "utf-8")
    xvfb = subprocess.Popen([XVFB, TELA_VIRTUAL, "-screen", "0", "1280x800x24", "-nolisten", "tcp"])
    os.environ["DISPLAY"] = TELA_VIRTUAL
    _esperar(lambda: Path(f"/tmp/.X11-unix/X{TELA_VIRTUAL[1:]}").exists(), 10)  # noqa: S108
    openbox = subprocess.Popen([OPENBOX, "--config-file", str(rc)])
    _esperar(
        lambda: (
            "_NET_SUPPORTING_WM_CHECK(WINDOW)"
            in subprocess.run(
                [XPROP, "-root", "_NET_SUPPORTING_WM_CHECK"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout
        ),
        10,
    )
    try:
        yield
    finally:
        for processo in (openbox, xvfb):
            processo.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                processo.wait(timeout=5)


class Registradas:
    """A porta de verdade, guardando quem o Jarvis pôs na frente."""

    def __init__(self, porta: Any) -> None:
        self.porta = porta
        self.ativadas: list[int] = []

    def listar(self) -> Any:
        return self.porta.listar()

    def ativar(self, janela_id: str) -> bool:
        self.ativadas.append(int(janela_id, 16))
        return bool(self.porta.ativar(janela_id))


class Amostras:
    """A janela ativa do X a cada 0,25 s, numa linha à parte."""

    def __init__(self) -> None:
        self.valores: list[tuple[float, int]] = []
        self._parar = threading.Event()
        self._linha = threading.Thread(target=self._rodar, daemon=True)
        self._comeco = time.monotonic()
        self._linha.start()

    def _rodar(self) -> None:
        while not self._parar.is_set():
            self.valores.append((time.monotonic() - self._comeco, _ativa()))
            self._parar.wait(0.25)

    def parar(self) -> list[tuple[float, int]]:
        self._parar.set()
        self._linha.join(timeout=2)
        return self.valores


def dentro() -> int:
    relatorio = Relatorio()
    try:
        _roteiro(relatorio)
    except Exception as erro:  # o relatório sai mesmo assim, com a falha
        relatorio.conferir("o roteiro terminou", False, f"{type(erro).__name__}: {erro}")
    print(MARCA + json.dumps({"versao": relatorio.versao, "conferencias": relatorio.conferencias}))
    return 0


def _roteiro(relatorio: Relatorio) -> None:
    """O roteiro, de cima a baixo: um roteiro linear lê melhor que dez funções."""
    from jarvis.executor.janelas import JanelasPorWmctrl
    from jarvis.tarefas.gestor import EstadoDaTarefa
    from jarvis.voz.app import Aplicativo
    from jarvis.voz.config import Configuracao

    # O xterm grava título com acento no WM_NAME em COMPOUND_TEXT, que o `wmctrl` não lê (sai
    # "N/A", e o Jarvis o trata como título desconhecido): os casos usam nomes sem acento.
    os.environ.update(
        HOME=str(CASA), XDG_RUNTIME_DIR=str(CASA / "run"), LANG="C.UTF-8", LC_ALL="C.UTF-8"
    )
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ.pop("XDG_CURRENT_DESKTOP", None)
    (CASA / "run").mkdir(mode=0o700, parents=True, exist_ok=True)
    nomes = _preparar_apps()
    versao = subprocess.run([OPENBOX, "--version"], capture_output=True, text=True, check=False)
    relatorio.versao = versao.stdout.splitlines()[0] if versao.stdout else "openbox"
    abertos: list[subprocess.Popen[bytes]] = []

    with _tela():
        dono = subprocess.Popen(_xterm("Editor", "Documento — Editor"))
        abertos.append(dono)
        id_do_dono = _esperar(lambda: _id_de("Editor"), 15)
        subprocess.run([WMCTRL, "-i", "-a", hex(id_do_dono)], check=False)
        relatorio.conferir(
            "a janela do dono está em foco no X",
            _esperar(lambda: _ativa() == id_do_dono, 5),
            hex(id_do_dono),
        )

        app = Aplicativo(
            configuracao=Configuracao(
                asr="asr-whisper-local",
                tts="tts-parametrico",
                s2="eco",
                acesso="jarvis",
                apps_autorizados=tuple(nomes),
            ),
            raiz=CASA / "sessao",
            ambiente={**os.environ, "JARVIS_AUDIO_BACKEND": "arquivo"},
            lar=CASA,
            escrever_na_tela=lambda _: None,
        )
        app.abrir(com_asr=False)
        ferramentas = app.ferramentas
        assert ferramentas is not None and ferramentas.tarefas is not None
        porta = ferramentas.portas().janelas
        relatorio.conferir(
            "no X11 o ambiente escolhe o wmctrl e o xprop (o critério da entrada virtual)",
            isinstance(porta, JanelasPorWmctrl),
            type(porta).__name__,
        )
        registradas = Registradas(porta)
        ferramentas.portas().janelas = registradas

        def abrir(nome: str) -> tuple[Any, float]:
            ferramentas.novo_turno(f"abre o {nome}")
            comeco = time.monotonic()
            resultado = ferramentas.executar("apps.launch", {"nome": nome}, cancelado=lambda: False)
            return resultado, time.monotonic() - comeco

        def esperar_a_tarefa(resultado: Any, prazo_s: float) -> Any:
            tarefa_id = str(resultado.dados.get("tarefa_do_foco", ""))
            assert ferramentas.tarefas is not None
            ferramentas.tarefas.esperar(tarefa_id, prazo_s)
            return ferramentas.tarefas.tarefas.get(tarefa_id)

        def avisos() -> list[str]:
            return [a["resumo"] for a in app.avisos.dados_do_card(time.monotonic())["avisos"]]

        def encerrar(resultado: Any) -> None:
            pid = resultado.dados.get("pid") if resultado.status == "ok" else None
            if isinstance(pid, int) and pid > 1:  # o grupo do processo que este código lançou
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGTERM)
            subprocess.run([WMCTRL, "-i", "-a", hex(id_do_dono)], check=False)
            _esperar(lambda: _ativa() == id_do_dono, 5)
            registradas.ativadas.clear()

        # 1. o app que abre na hora --------------------------------------------------------
        resultado, demora = abrir("Calculadora")
        relatorio.conferir(
            "rápido: apps.launch devolve na hora, com a tarefa do foco",
            resultado.status == "ok" and demora < 2.0 and "tarefa_do_foco" in resultado.dados,
            f"{demora:.2f} s, {dict(resultado.dados)}",
        )
        tarefa = esperar_a_tarefa(resultado, 30)
        id_do_app = _id_de("Calculadora")
        relatorio.conferir(
            "rápido: a janela do app vai para a frente no X (o openbox não a focou sozinho)",
            tarefa is not None
            and tarefa.estado is EstadoDaTarefa.CONCLUIDA
            and id_do_app
            and _ativa() == id_do_app
            and registradas.ativadas == [id_do_app],
            f"{tarefa.estado if tarefa else '?'} {tarefa.resumo if tarefa else ''}; ativa "
            f"{hex(_ativa())}, app {hex(id_do_app)}",
        )
        auditoria = [
            (r["tool_id"], r["veredito"], r["resultado"])
            for r in ferramentas.pdp.auditoria._con.execute(
                "SELECT d.tool_id, d.veredito, r.resultado FROM audit_log d"
                " LEFT JOIN audit_result r ON r.decision_id = d.decision_id ORDER BY d.rowid"
            )
        ]
        relatorio.conferir(
            "rápido: o foco passou pelo PDP como qualquer window.focus_app",
            ("window.focus_app", "allow", "ok") in auditoria,
            auditoria,
        )
        relatorio.conferir(
            "rápido: o fim não vira aviso falado (o dono acabou de ouvir que abriu)",
            tarefa is not None
            and tarefa.aviso == ""
            and not any("Calculadora" in a for a in avisos()),
            avisos(),
        )
        encerrar(resultado)

        # 2. o jogo pelo Steam -------------------------------------------------------------
        amostras = Amostras()
        resultado, _ = abrir("Spacewar")
        time.sleep(2)
        generica = subprocess.Popen(_xterm("qualquer", "Spacewar"))  # outro processo, mesmo nome
        abertos.append(generica)
        tarefa = esperar_a_tarefa(resultado, 90)
        valores = amostras.parar()
        id_do_jogo = _id_de("spacewar_linux")
        ids_do_steam = {i for i, c, _ in _janelas() if c in ("steam", "qualquer")}
        antes_do_jogo = [a for t, a in valores if t < 8.5]
        relatorio.conferir(
            "Steam: enquanto ele pede a conta, a janela ativa do X segue a do dono",
            antes_do_jogo and all(a == id_do_dono for a in antes_do_jogo),
            f"{len(antes_do_jogo)} amostras; {sorted({hex(a) for a in antes_do_jogo})}",
        )
        relatorio.conferir(
            "Steam: só o jogo foi para a frente (nem a conta, nem o Steam, nem a «Spacewar» à toa)",
            id_do_jogo
            and registradas.ativadas == [id_do_jogo]
            and not (set(registradas.ativadas) & ids_do_steam),
            f"ativadas {[hex(i) for i in registradas.ativadas]}, jogo {hex(id_do_jogo)}",
        )
        relatorio.conferir(
            "Steam: o jogo (classe spacewar_linux, ligado pelo reaper AppId=480) está em foco",
            tarefa is not None
            and tarefa.estado is EstadoDaTarefa.CONCLUIDA
            and _ativa() == id_do_jogo,
            f"{tarefa.estado if tarefa else '?'} {tarefa.resumo if tarefa else ''}",
        )
        relatorio.conferir(
            "Steam: demorou, então o fim vira aviso para o dono",
            "Spacewar abriu e está em foco" in avisos(),
            avisos(),
        )
        encerrar(resultado)

        # 3. duas janelas empatadas --------------------------------------------------------
        resultado, _ = abrir("Notas")
        tarefa = esperar_a_tarefa(resultado, 40)
        relatorio.conferir(
            "dúvida: duas janelas iguais do app: a tarefa pergunta qual, ninguém vai para a frente",
            tarefa is not None
            and "qual delas?" in tarefa.resumo
            and registradas.ativadas == []
            and _ativa() == id_do_dono,
            f"{tarefa.resumo if tarefa else ''}; ativa {hex(_ativa())}",
        )
        relatorio.conferir(
            "dúvida: a pergunta chega ao dono como aviso",
            any("qual delas?" in a for a in avisos()),
            avisos(),
        )
        encerrar(resultado)

        # 4. o prazo ----------------------------------------------------------------------
        ferramentas.prazo_do_foco_s = 10.0
        resultado, _ = abrir("Planilha")
        time.sleep(1.5)
        abertos.append(subprocess.Popen(_xterm("outra", "Planilha")))  # genérica, sem ligação
        tarefa = esperar_a_tarefa(resultado, 60)
        motivo = tarefa.motivo if tarefa is not None else ""
        relatorio.conferir(
            "prazo: a falha diz que a janela não apareceu e cita a genérica, sem ligação",
            tarefa is not None
            and tarefa.estado is EstadoDaTarefa.FALHOU
            and "esperei 10 s e a janela de Planilha não apareceu" in motivo
            and "«Planilha»" in motivo
            and "sem ligação" in motivo,
            f"{motivo} | títulos: {[t for _, _, t in _janelas()]}",
        )
        relatorio.conferir(
            "prazo: ninguém foi para a frente",
            registradas.ativadas == [] and _ativa() == id_do_dono,
            hex(_ativa()),
        )
        encerrar(resultado)

        ferramentas.tarefas.encerrar()
        for processo in abertos:
            processo.terminate()


# --- no host ------------------------------------------------------------------------------
def _podman() -> str:
    achado = shutil.which("podman")
    if achado is None:
        raise SystemExit("o podman não está no PATH: este roteiro só roda em contêiner")
    return achado


def _garantir_imagem(podman: str) -> None:
    if subprocess.run([podman, "image", "exists", IMAGEM], check=False).returncode == 0:
        return
    print(f"construindo {IMAGEM} (fedora:44 + Xvfb + openbox + wmctrl + xterm)…", flush=True)
    with tempfile.TemporaryDirectory() as contexto:
        subprocess.run(
            [podman, "build", "-t", IMAGEM, "-f", "-", contexto],
            input=CONTAINERFILE,
            text=True,
            check=True,
        )


def rodar_no_conteiner(podman: str) -> dict[str, Any]:
    python = RAIZ / ".venv" / "bin" / "python"
    pythons_do_uv = Path(sys.base_prefix).parent  # o `.venv` aponta para cá (cpython-3.12…)
    comando = [
        podman,
        "run",
        "--rm",
        "--name",
        f"jarvis-janelas-{int(time.time())}",
        "--timeout",
        str(SEGUNDOS),
        "--network",
        "none",
        "--userns=keep-id",
        "-v",
        f"{RAIZ}:{RAIZ}:ro",
        "-v",
        f"{pythons_do_uv}:{pythons_do_uv}:ro",
        IMAGEM,
        str(python),
        str(RAIZ / "tools" / "harness_janelas.py"),
        "--dentro",
    ]
    feito = subprocess.run(
        comando, capture_output=True, text=True, check=False, timeout=SEGUNDOS + 60
    )
    for linha in feito.stdout.splitlines():
        if linha.startswith(MARCA):
            dados: dict[str, Any] = json.loads(linha[len(MARCA) :])
            return dados
    return {
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
    analisador.add_argument("--dentro", action="store_true", help=argparse.SUPPRESS)
    analisador.add_argument(
        "--detalhes", action="store_true", help="mostra o detalhe também das que passaram"
    )
    args = analisador.parse_args(argumentos)
    if args.dentro:
        return dentro()
    podman = _podman()
    _garantir_imagem(podman)
    print("\n== janelas (X virtual com openbox, contêiner sem rede, HOME descartável) ==")
    relatorio = rodar_no_conteiner(podman)
    print(f"   {relatorio.get('versao') or 'versão desconhecida'}")
    for conferencia in relatorio["conferencias"]:
        print(f"   {'ok ' if conferencia['ok'] else 'FALHOU'} {conferencia['nome']}")
        if not conferencia["ok"] or args.detalhes:
            print(f"          {conferencia['detalhe']}")
    return 0 if all(c["ok"] for c in relatorio["conferencias"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
