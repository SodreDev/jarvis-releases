"""Roteiro do foco de janelas num KWin 6 de verdade, virtual, com dois monitores (dono, 2026-10-21).

    uv run --frozen python tools/harness_foco.py [--relatorio docs/medicoes/foco-kwin-virtual.md]

Sintoma do dono (KDE Plasma/KWin no Wayland, dois monitores, Brave): o Jarvis não identificou o
Brave em foco no monitor principal. A tela dele não se toca: este roteiro sobe um
`kwin_wayland --virtual --xwayland --output-count 2` — o mesmo KWin da máquina, numa sessão
isolada (D-Bus próprio via `dbus-run-session`, `HOME`, `XDG_*` e o soquete Wayland numa pasta
temporária; nada do ambiente do dono passa: `env` montado do zero) — e abre janelas de teste em Qt
(Wayland nativa e XWayland) com a classe do Brave (`brave-browser`) e a do Jarvis. Confere, com o
**código do produto** (`jarvis.executor.janelas`, `jarvis.executor.comandos`):

1. a leitura nova (`kdotool kwinscript`) diz os monitores (o principal primeiro), a ativa e a da
   frente de cada monitor — o Brave na frente do principal com o Jarvis ativo no segundo;
2. a leitura de antes (busca encadeada) **reproduz o sintoma**: o Brave só aparece como "segundo
   plano", sem monitor;
3. sem janela ativa (tudo minimizado) a leitura nova continua listando — a de antes voltava vazia;
4. o `kdotool` sem `KDE_SESSION_VERSION` recusa rodar, e o executor do Jarvis completa a variável;
5. o foco pelo KWin (`windowactivate`) traz o Brave para a frente com o Jarvis ativo noutro monitor
   (é o que o Jarvis usa quando a extensão não consegue: no Wayland o navegador não pega o foco);
6. os tempos: a leitura nova e a de antes, 30 vezes cada (p50/p95).

O que **não** prova: o KWin da sessão do dono (outros apps, a área de trabalho e o painel do
Plasma de verdade, os monitores físicos) nem o Brave de verdade — para isso,
`tools/diagnostico_foco.py` na sessão dele. Precisa de `kwin_wayland`, `dbus-run-session`,
`Xwayland`, do `kdotool` ≥ 0.3 e do PySide6 do ambiente do projeto.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

RAIZ: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

SOQUETE: Final = "wayland-jarvis-foco"
LARGURA, ALTURA = 1280, 720
VEZES: Final = 30
JANELA_QT: Final = r"""
import os, sys
titulo, app_id, plataforma, segundos = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
os.environ["QT_QPA_PLATFORM"] = plataforma
os.environ["RESOURCE_NAME"] = app_id
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([app_id])
app.setApplicationName(app_id)
QGuiApplication.setDesktopFileName(app_id)
janela = QWidget()
janela.setWindowTitle(titulo)
janela.resize(480, 300)
janela.show()
QTimer.singleShot(int(segundos * 1000), app.quit)
app.exec()
"""


@dataclass
class Relatorio:
    conferencias: list[dict[str, Any]] = field(default_factory=list)
    tempos: dict[str, list[float]] = field(default_factory=dict)

    def conferir(self, nome: str, ok: bool, detalhe: Any = "") -> None:
        self.conferencias.append({"nome": nome, "ok": bool(ok), "detalhe": detalhe})

    @property
    def ok(self) -> bool:
        return bool(self.conferencias) and all(c["ok"] for c in self.conferencias)


def _programa(nome: str) -> str:
    """O caminho inteiro do programa (nada de procurar no PATH na hora de executar)."""
    caminho = shutil.which(nome)
    if caminho is None:
        raise FileNotFoundError(nome)
    return caminho


def _p(valores: Sequence[float], quantil: float) -> float:
    ordenados = sorted(valores)
    return ordenados[min(len(ordenados) - 1, round(quantil * (len(ordenados) - 1)))]


# --- dentro do KWin virtual -------------------------------------------------------------------
def _dentro(saida: Path) -> int:
    from jarvis.executor.comandos import executar
    from jarvis.executor.janelas import JanelasPorKdotool, foco_para_o_modelo

    relatorio = Relatorio()
    filhos: list[subprocess.Popen[bytes]] = []
    script = Path(tempfile.mkdtemp()) / "janela.py"
    script.write_text(JANELA_QT, encoding="utf-8")

    def janela(titulo: str, app_id: str, plataforma: str) -> None:
        filhos.append(
            subprocess.Popen(
                [sys.executable, str(script), titulo, app_id, plataforma, "120"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    def kwin(js: str) -> str:
        saida = executar(["kdotool", "kwinscript", "--inline", js], 5.0, None)
        return saida.saida.strip()

    def esperar(condicao: Callable[[], bool], segundos: float = 10.0) -> bool:
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            if condicao():
                return True
            time.sleep(0.2)
        return False

    porta = JanelasPorKdotool()
    try:
        janela("YouTube - Brave", "brave-browser", "wayland")
        janela("G1 - Brave (XWayland)", "brave-browser", "xcb")
        janela("Jarvis", "jarvis", "wayland")
        abriram = esperar(lambda: len([j for j in porta.listar() if j.titulo]) >= 3, segundos=20.0)
        relatorio.conferir("as três janelas de teste abriram no KWin virtual", abriram)
        # O cenário do dono: o Brave na frente do principal, o Jarvis ativo no segundo monitor.
        kwin(
            "for (const w of workspace.windowList()) {"
            ' if (w.caption === "Jarvis") { workspace.sendClientToScreen(w, workspace.screens[1]);'
            " workspace.activeWindow = w; }"
            ' if (w.caption.startsWith("YouTube")) workspace.raiseWindow(w);'
            "} output_result('ok');"
        )
        esperar(
            lambda: (
                (e := porta.estado()) is not None
                and e.ativa is not None
                and e.ativa.titulo == "Jarvis"
            )
        )
        estado = porta.estado()
        assert estado is not None
        principal = estado.monitores[0].nome if estado.monitores else ""
        frente = estado.da_frente(principal) if principal else None
        relatorio.conferir(
            "a leitura nova diz os dois monitores, o principal primeiro",
            [m.principal for m in estado.monitores] == [True, False],
            [(m.nome, m.principal, m.largura, m.altura) for m in estado.monitores],
        )
        relatorio.conferir(
            "o Jarvis é a ativa (a do teclado), no segundo monitor",
            estado.ativa is not None
            and estado.ativa.titulo == "Jarvis"
            and not estado.ativa.principal,
            estado.ativa.monitor if estado.ativa else None,
        )
        relatorio.conferir(
            "o Brave (Wayland, classe brave-browser) é a da frente do monitor principal",
            frente is not None
            and frente.titulo == "YouTube - Brave"
            and frente.classe == "brave-browser",
            frente.titulo if frente else None,
        )
        xwayland = next((j for j in estado.janelas if j.titulo.startswith("G1")), None)
        relatorio.conferir(
            "a janela XWayland do Brave tem a classe brave-browser e o monitor dela",
            xwayland is not None and xwayland.classe == "brave-browser" and bool(xwayland.monitor),
            (xwayland.classe, xwayland.monitor) if xwayland else None,
        )
        resposta = foco_para_o_modelo(porta)
        relatorio.conferir(
            "window.focused responde a ativa e o Brave na frente do principal",
            resposta["foco"] is not None
            and resposta["foco"]["titulo"] == "Jarvis"
            and resposta["monitores"][0]["principal"]
            and (resposta["monitores"][0]["na_frente"] or {}).get("titulo") == "YouTube - Brave",
            resposta,
        )
        # A leitura de antes (a busca encadeada com a ativa no fim): o sintoma do dono.
        antes = executar(
            [
                "kdotool",
                "search",
                "--class",
                ".",
                *("getwindowname", "%@", "getwindowclassname", "%@"),
                "getactivewindow",
                "getwindowname",
            ],
            5.0,
            None,
        )
        relatorio.conferir(
            "ANTES: a leitura de antes só sabe a ativa — o Brave fica sem monitor e «atrás»",
            antes.ok and antes.saida.strip().splitlines()[-1] == "Jarvis",
            antes.saida.strip().splitlines()[-1:] if antes.ok else antes.erro.strip(),
        )
        # O foco pelo KWin: o Brave vem para a frente mesmo com o Jarvis ativo noutro monitor.
        brave = next(j for j in estado.janelas if j.titulo == "YouTube - Brave")
        relatorio.conferir("o KWin aceita o pedido de foco", porta.ativar(brave.id))
        relatorio.conferir(
            "o Brave ficou ativo pelo KWin (no Wayland o navegador não pega o foco sozinho)",
            esperar(
                lambda: (
                    (e := porta.estado()) is not None
                    and e.ativa is not None
                    and e.ativa.id == brave.id
                )
            ),
        )
        # Sem janela ativa: tudo minimizado.
        kwin("for (const w of workspace.windowList()) w.minimized = true; output_result('ok');")
        esperar(lambda: (e := porta.estado()) is not None and e.ativa is None)
        sem_ativa = porta.estado()
        relatorio.conferir(
            "sem janela ativa, a leitura nova continua listando e diz que não há foco",
            sem_ativa is not None
            and sem_ativa.ativa is None
            and len([j for j in sem_ativa.janelas if j.titulo]) >= 3
            and "sem_foco" in foco_para_o_modelo(porta),
            len(sem_ativa.janelas) if sem_ativa else None,
        )
        antes_sem_ativa = executar(
            ["kdotool", "search", "--class", ".", "getwindowid", "%@", "getactivewindow"], 5.0, None
        )
        relatorio.conferir(
            "ANTES: sem janela ativa, a busca encadeada falha inteira (a lista voltava vazia)",
            not antes_sem_ativa.ok,
            antes_sem_ativa.erro.strip()[:120],
        )
        kwin("for (const w of workspace.windowList()) w.minimized = false; output_result('ok');")
        # O kdotool sem KDE_SESSION_VERSION: cru recusa; pelo executor do Jarvis, roda.
        cru = subprocess.run(
            [_programa("kdotool"), "getactivewindow"],
            capture_output=True,
            text=True,
            env={k: v for k, v in os.environ.items() if k != "KDE_SESSION_VERSION"},
            check=False,
            timeout=5,
        )
        relatorio.conferir(
            "o kdotool cru, sem KDE_SESSION_VERSION, recusa rodar (o Jarvis completa a variável)",
            cru.returncode != 0
            and "Unsupported KDE version" in cru.stderr
            and "KDE_SESSION_VERSION" not in os.environ
            and porta.estado() is not None,
            cru.stderr.strip()[:120],
        )
        # Os tempos: a leitura nova e a de antes, intercaladas.
        novas: list[float] = []
        velhas: list[float] = []
        for _ in range(VEZES):
            comeco = time.perf_counter()
            porta.estado()
            novas.append((time.perf_counter() - comeco) * 1000.0)
            comeco = time.perf_counter()
            executar(
                [
                    "kdotool",
                    "search",
                    "--class",
                    ".",
                    *("getwindowid", "%@", "getwindowname", "%@"),
                    *("getwindowclassname", "%@", "getwindowpid", "%@"),
                    "getactivewindow",
                ],
                5.0,
                None,
            )
            velhas.append((time.perf_counter() - comeco) * 1000.0)
        relatorio.tempos = {"leitura_nova_ms": novas, "leitura_de_antes_ms": velhas}
        # O diagnóstico de 1 comando roda aqui também (sem a extensão: não há navegador).
        from tools.diagnostico_foco import principal as diagnostico

        linhas: list[str] = []
        diagnostico(["--sem-navegador"], escrever=linhas.append)
        relatorio.conferir(
            "o diagnóstico de 1 comando mostra a ativa e a da frente de cada monitor",
            any(linha.startswith("na frente de cada monitor") for linha in linhas)
            and any("(principal)" in linha for linha in linhas),
            linhas,
        )
    except Exception as erro:  # quebrar no meio é resultado do roteiro: vai para o relatório
        relatorio.conferir("o roteiro chegou ao fim", False, f"{type(erro).__name__}: {erro}")
    finally:
        for filho in filhos:
            filho.terminate()
        for filho in filhos:
            try:
                filho.wait(5)
            except subprocess.TimeoutExpired:
                filho.kill()
        saida.write_text(json.dumps(relatorio.__dict__, ensure_ascii=False), encoding="utf-8")
    return 0


# --- fora: monta a sessão isolada -------------------------------------------------------------
def _faltando() -> list[str]:
    programas = ("kwin_wayland", "dbus-run-session", "Xwayland", "kdotool")
    faltam = [p for p in programas if shutil.which(p) is None]
    try:
        import PySide6  # noqa: F401
    except ImportError:
        faltam.append("PySide6")
    return faltam


def _rodar_a_sessao() -> Relatorio:
    base = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
    with tempfile.TemporaryDirectory(prefix="jf-", dir=base) as pasta:
        raiz = Path(pasta)
        # O soquete Wayland tem de caber em 108 bytes: a pasta de execução fica curta.
        execucao = Path(tempfile.mkdtemp(prefix="jfr-", dir=Path.home() / ".cache"))
        execucao.chmod(0o700)
        relatorio = raiz / "relatorio.json"
        dentro = raiz / "dentro.sh"
        dentro.write_text(
            f"#!/bin/sh\ncd {RAIZ}\n"
            f"exec {sys.executable} -m tools.harness_foco --dentro {relatorio}\n",
            encoding="utf-8",
        )
        dentro.chmod(0o700)
        for nome in ("casa", "config", "dados", "cache", "estado"):
            (raiz / nome).mkdir()
        kdotool = shutil.which("kdotool")
        assert kdotool is not None
        ambiente = {
            "HOME": str(raiz / "casa"),
            "XDG_RUNTIME_DIR": str(execucao),
            "XDG_CONFIG_HOME": str(raiz / "config"),
            "XDG_DATA_HOME": str(raiz / "dados"),
            "XDG_CACHE_HOME": str(raiz / "cache"),
            "XDG_STATE_HOME": str(raiz / "estado"),
            "PATH": os.pathsep.join(["/usr/bin", "/bin", str(Path(kdotool).parent)]),
            "LANG": "C.UTF-8",
            "KWIN_COMPOSE": "Q",
            "XDG_CURRENT_DESKTOP": "KDE",
            "XDG_SESSION_TYPE": "wayland",
            "PYTHONPATH": str(RAIZ),
            # Sem KDE_SESSION_VERSION de propósito: o executor do Jarvis tem de completá-la.
        }
        try:
            subprocess.run(
                [
                    _programa("dbus-run-session"),
                    "--",
                    _programa("kwin_wayland"),
                    "--virtual",
                    "--xwayland",
                    "--output-count",
                    "2",
                    "--width",
                    str(LARGURA),
                    "--height",
                    str(ALTURA),
                    "--socket",
                    SOQUETE,
                    "--no-lockscreen",
                    "--no-global-shortcuts",
                    "--no-kactivities",
                    "--exit-with-session",
                    str(dentro),
                ],
                env=ambiente,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=240,
                check=False,
            )
        finally:
            shutil.rmtree(execucao, ignore_errors=True)
        if not relatorio.exists():
            falhou = Relatorio()
            falhou.conferir("o KWin virtual subiu e rodou o roteiro", False, "sem relatório")
            return falhou
        dados = json.loads(relatorio.read_text(encoding="utf-8"))
        return Relatorio(dados["conferencias"], dados["tempos"])


def _markdown(relatorio: Relatorio) -> str:
    novas = relatorio.tempos.get("leitura_nova_ms", [])
    velhas = relatorio.tempos.get("leitura_de_antes_ms", [])
    linhas = [
        "# Foco de janelas num KWin 6 virtual com dois monitores",
        "",
        f"**Gerado por** `tools/harness_foco.py` (não editar à mão). **Data:** "
        f"{datetime.now():%Y-%m-%d}. KWin `{_versao_do_kwin()}`, kdotool `{_versao_do_kdotool()}`, "
        f"{LARGURA}×{ALTURA} em cada saída virtual.",
        "",
        "> KWin de verdade, mas **virtual**: janelas de teste em Qt, sem o painel nem a área de "
        "trabalho do Plasma, sem os monitores físicos e sem o Brave de verdade. Na sessão do dono, "
        "`tools/diagnostico_foco.py`.",
        "",
        "## Conferências",
        "",
        "| # | conferência | ok |",
        "|---:|---|:---:|",
    ]
    for i, c in enumerate(relatorio.conferencias, 1):
        linhas.append(f"| {i} | {c['nome']} | {'sim' if c['ok'] else '**não**'} |")
    if novas and velhas:
        linhas += [
            "",
            f"## Tempo de uma leitura ({len(novas)} vezes cada, intercaladas)",
            "",
            "| leitura | p50 | p95 | o que traz |",
            "|---|---:|---:|---|",
            f"| nova (`kdotool kwinscript`) | {statistics.median(novas):.1f} ms | "
            f"{_p(novas, 0.95):.1f} ms | ativa, monitores, pilha, área de trabalho, minimizada |",
            f"| de antes (busca encadeada) | {statistics.median(velhas):.1f} ms | "
            f"{_p(velhas, 0.95):.1f} ms | ativa (quebra sem ela), sem monitor nem pilha |",
        ]
    return "\n".join(linhas) + "\n"


def _versao_do_kwin() -> str:
    saida = subprocess.run(
        [_programa("kwin_wayland"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return saida.stdout.strip().split()[-1] if saida.stdout.strip() else "?"


def _versao_do_kdotool() -> str:
    saida = subprocess.run(
        [_programa("kdotool"), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
        env={**os.environ, "KDE_SESSION_VERSION": "6"},
    )
    return saida.stdout.strip().split()[-1] if saida.stdout.strip() else "?"


def main(argv: Sequence[str] | None = None) -> int:
    opcoes = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    opcoes.add_argument("--dentro", type=Path, help=argparse.SUPPRESS)
    opcoes.add_argument("--relatorio", type=Path, help="grava o resultado em Markdown aqui")
    args = opcoes.parse_args(argv)
    if args.dentro is not None:
        return _dentro(args.dentro)
    faltam = _faltando()
    if faltam:
        print(f"falta: {', '.join(faltam)}")
        return 2
    relatorio = _rodar_a_sessao()
    for c in relatorio.conferencias:
        print(f"{'ok ' if c['ok'] else 'FALHOU'} {c['nome']}")
    texto = _markdown(relatorio)
    if args.relatorio is not None:
        args.relatorio.write_text(texto, encoding="utf-8")
    print(texto)
    print(
        f"{sum(c['ok'] for c in relatorio.conferencias)}/{len(relatorio.conferencias)} conferências"
    )
    return 0 if relatorio.ok else 1


if __name__ == "__main__":
    sys.exit(main())
