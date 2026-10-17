"""`jarvis`: abre a janela (ADR-0019). O mesmo binário também responde sem abrir tela.

    uv run jarvis                     # a janela
    uv run jarvis --versao            # a versão, para o pacote conferir que subiu
    uv run jarvis --diagnostico       # o mesmo diagnóstico do terminal, sem abrir janela
    uv run jarvis --capturar PASTA    # desenha as telas num PNG por modo e sai (offscreen)

As três últimas existem por um motivo prático de empacotamento (ADR-0020): dentro de um
contêiner não há tela, e um aplicativo que **só** sabe abrir janela não pode ser verificado
antes de chegar na máquina do dono.

`jarvis-voz` continua existindo e continua sendo o terminal. A janela não o substitui: ela usa
o mesmo núcleo.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickView

    from jarvis.gui.ponte import Ponte

from jarvis.gui.recursos import ICONE_SVG, ID_DO_APLICATIVO, NOME

MODOS: Final[tuple[str, ...]] = ("assistente", "pesquisa", "execucao")
TAMANHO: Final[tuple[int, int]] = (1600, 1000)
ESPERA_DA_ANIMACAO_MS: Final = 900
"""As transições levam de 200 a 500 ms; a captura espera o dobro para pegar a tela parada."""

MODELO_DE_ATALHO: Final = (
    Path(__file__).resolve().parents[3] / "packaging" / "linux" / f"{ID_DO_APLICATIVO}.desktop"
)
ATALHO: Final = (
    "[Desktop Entry]\nType=Application\nName=Jarvis\n"
    "Comment=Fale com o Jarvis: voz local, nuvem desligada por padrão\n"
    "Exec=jarvis %U\nTryExec=jarvis\nIcon=dev.sodredev.Jarvis\nTerminal=false\n"
    "Categories=Utility;Audio;\nStartupWMClass=dev.sodredev.Jarvis\n"
)
"""O atalho que vale quando o `packaging/` não veio junto (instalação por pacote)."""


def versao() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("jarvis")
    except PackageNotFoundError:  # pragma: no cover — árvore sem instalação
        return "0.0.0"


def _preparar_ambiente_sem_tela() -> None:
    """Sem servidor gráfico, o Qt tem de saber disso **antes** de o aplicativo existir."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QUICK_BACKEND", "software")


def _raiz_de_sessao(ambiente: Mapping[str, str] | None = None) -> Path:
    from jarvis.voz.cli import _raiz_de_sessao as raiz

    return raiz(ambiente)


def _analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="jarvis",
        description="Abre o Jarvis (ADR-0019). Sem opção nenhuma, abre a janela.",
    )
    analisador.add_argument("--versao", action="store_true", help="imprime a versão e sai")
    analisador.add_argument(
        "--diagnostico", action="store_true", help="o diagnóstico do terminal, sem abrir janela"
    )
    analisador.add_argument(
        "--modo", choices=MODOS, default="assistente", help="o modo em que a janela abre"
    )
    analisador.add_argument(
        "--capturar",
        type=Path,
        default=None,
        help="desenha um PNG por modo nesta pasta e sai (não precisa de tela)",
    )
    analisador.add_argument(
        "--segundos",
        type=float,
        default=0.0,
        help="fecha sozinha depois de N segundos (fumaça de empacotamento)",
    )
    analisador.add_argument(
        "--instalar-atalho",
        action="store_true",
        help="põe o Jarvis no menu de aplicativos deste usuário (nada de sudo)",
    )
    analisador.add_argument(
        "--config", type=Path, default=None, help="outro arquivo de configuração"
    )
    return analisador


def comando_desta_instalacao() -> str:
    """O comando que o atalho deve executar, descoberto de como este processo subiu.

    De um pacote, é o próprio `jarvis` do `PATH`; da árvore, com `uv run jarvis`, é o
    executável do ambiente virtual — caminho absoluto, porque o menu de aplicativos não herda
    o `PATH` do shell do dono.
    """
    executavel = Path(sys.argv[0]).resolve()
    if executavel.name == "jarvis" and executavel.exists():
        return str(executavel)
    return f"{sys.executable} -m jarvis.gui.principal"


def instalar_atalho(base: Path | None = None) -> list[Path]:
    """Escreve o `.desktop` e o ícone na pasta deste usuário. Não precisa de sudo.

    É o caminho de hoje: o dono abre o Jarvis pelo menu sem esperar o pacote. O pacote
    (ADR-0020) instala os mesmos dois arquivos, só que em `/usr/share`.
    """
    raiz = base or Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    atalho = raiz / "applications" / f"{ID_DO_APLICATIVO}.desktop"
    icone = raiz / "icons" / "hicolor" / "scalable" / "apps" / f"{ID_DO_APLICATIVO}.svg"
    atalho.parent.mkdir(parents=True, exist_ok=True)
    icone.parent.mkdir(parents=True, exist_ok=True)
    comando = comando_desta_instalacao()
    texto = MODELO_DE_ATALHO.read_text(encoding="utf-8") if MODELO_DE_ATALHO.exists() else ATALHO
    texto = texto.replace("Exec=jarvis %U", f"Exec={comando} %U")
    texto = texto.replace("TryExec=jarvis", f"TryExec={comando.split(' ')[0]}")
    atalho.write_text(texto, encoding="utf-8")
    icone.write_bytes(ICONE_SVG.read_bytes())
    return [atalho, icone]


def main(argv: Sequence[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    args = _analisador().parse_args(argumentos)

    if args.versao:
        print(f"{NOME} {versao()}")
        return 0

    if args.diagnostico:
        from jarvis.voz.cli import diagnosticar

        return diagnosticar(print, caminho=args.config)

    if args.instalar_atalho:
        for caminho in instalar_atalho():
            print(caminho)
        print("pronto: o Jarvis está no menu de aplicativos deste usuário.")
        return 0

    if args.capturar is not None:
        _preparar_ambiente_sem_tela()

    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQuick import QQuickView

    from jarvis.gui import foco
    from jarvis.gui.ponte import Ponte

    aplicativo = QGuiApplication(sys.argv[:1])
    aplicativo.setApplicationName(NOME)
    aplicativo.setApplicationDisplayName(NOME)
    aplicativo.setDesktopFileName(ID_DO_APLICATIVO)
    aplicativo.setWindowIcon(QIcon(str(ICONE_SVG)))

    ponte = Ponte(raiz=_raiz_de_sessao(), caminho_da_configuracao=args.config)
    janela = QQuickView()
    janela.setTitle(NOME)
    janela.setIcon(QIcon(str(ICONE_SVG)))
    janela.rootContext().setContextProperty("ponte", ponte)
    janela.engine().addImportPath(str(Path(__file__).resolve().parent / "qml"))
    janela.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    janela.setSource(
        QUrl.fromLocalFile(
            str(Path(__file__).resolve().parent / "qml" / "JarvisUI" / "Principal.qml")
        )
    )
    if janela.status() is QQuickView.Status.Error:
        for erro in janela.errors():
            print(f"QML: {erro}", file=sys.stderr)
        return 3
    janela.resize(*TAMANHO)
    foco.ligar(janela)
    ponte.definirModo(args.modo)

    if args.capturar is not None:
        for destino in capturar(aplicativo, janela, ponte, args.capturar):
            print(destino)
        return 0

    janela.show()
    if args.segundos > 0:
        QTimer.singleShot(int(args.segundos * 1000), aplicativo.quit)
    return int(aplicativo.exec())


def _esperar(aplicativo: QGuiApplication, milissegundos: int) -> None:
    """Deixa a tela assentar sem bloquear o Qt: processa eventos até o tempo passar."""
    from PySide6.QtCore import QEventLoop

    fim = time.monotonic() + milissegundos / 1000.0
    while time.monotonic() < fim:
        aplicativo.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.005)


def capturar(
    aplicativo: QGuiApplication,
    janela: QQuickView,
    ponte: Ponte,
    pasta: Path,
    *,
    com_diagnostico: bool = True,
) -> list[Path]:
    """Um PNG por modo, mais os dois painéis. É o que o dono abre para julgar o acabamento.

    `com_diagnostico=False` pula a varredura de motores e dispositivos: ela roda numa thread
    própria, e numa suíte de teste essa thread sobreviveria ao fim do teste — a janela seria
    desmontada embaixo dela.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    raiz = janela.rootObject()
    if raiz is not None:
        raiz.setProperty("semPonteiro", True)
    janela.show()
    _esperar(aplicativo, 600)
    salvos: list[Path] = []
    for modo in MODOS:
        ponte.definirModo(modo)
        _esperar(aplicativo, ESPERA_DA_ANIMACAO_MS)
        pendentes = ponte.pendencias_abertas()
        # Com pendência aberta, a composição **ainda não está inteira**: o que encosta na
        # máquina do dono espera o sim dele. Então o retrato do modo é o de depois da
        # autorização, e o pedido ganha uma imagem própria — nenhuma das duas esconde nada.
        primeiro = pasta / (f"jarvis-{modo}-confirmar.png" if pendentes else f"jarvis-{modo}.png")
        janela.grabWindow().save(str(primeiro))
        salvos.append(primeiro)
        if not pendentes:
            continue
        for pendencia in pendentes:
            ponte.responderPendencia(pendencia["id"], True)
        _esperar(aplicativo, ESPERA_DA_ANIMACAO_MS)
        destino = pasta / f"jarvis-{modo}.png"
        janela.grabWindow().save(str(destino))
        salvos.append(destino)
    # Um retrato do núcleo **pensando**: os anéis só giram em processamento, e o dono não tem
    # como ver isso num retrato de tela parada.
    ponte.definirModo("assistente")
    ponte.encenar_estado("pensando")
    _esperar(aplicativo, ESPERA_DA_ANIMACAO_MS)
    destino = pasta / "jarvis-nucleo-pensando.png"
    janela.grabWindow().save(str(destino))
    salvos.append(destino)
    ponte.encenar_estado("parado")

    for painel in ("configuracao", "diagnostico"):
        ponte.definirModo("assistente")
        ponte.abrirPainel(painel)
        if painel == "diagnostico" and com_diagnostico:
            # Painel de diagnóstico vazio não diz nada: a captura roda o diagnóstico de
            # verdade (o mesmo do terminal) e espera a resposta chegar da thread dele.
            ponte.rodarDiagnostico()
            _esperar(aplicativo, 6000)
        _esperar(aplicativo, ESPERA_DA_ANIMACAO_MS)
        destino = pasta / f"jarvis-{painel}.png"
        janela.grabWindow().save(str(destino))
        salvos.append(destino)
        if painel == "configuracao":
            salvos += _capturar_escutas(aplicativo, janela, ponte, pasta)
    return salvos


def _capturar_escutas(
    aplicativo: QGuiApplication, janela: QQuickView, ponte: Ponte, pasta: Path
) -> list[Path]:
    """A caixa de escuta em cada modo (ADR-0021). O modo do dono volta no fim: só se retrata,
    nada é gravado no arquivo dele."""
    original = str(ponte.estado_da_escuta()["modo"])
    salvos: list[Path] = []
    for modo in ("ptt", "palavra", "vad"):
        ponte.definirEscuta(modo)
        _esperar(aplicativo, 400)
        destino = pasta / f"jarvis-configuracao-escuta-{modo}.png"
        janela.grabWindow().save(str(destino))
        salvos.append(destino)
    ponte.definirEscuta(original)
    return salvos


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
