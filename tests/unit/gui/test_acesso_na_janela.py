"""Pastas, aplicativos e navegadores **pela janela**: o clique chega ao arquivo e à tela.

Pedido do dono (2026-10-17): na janela ele não conseguia configurar nada disso. Aqui o QML é o
de verdade (offscreen) e o clique é do mouse, no lugar onde o botão está; só o seletor de
arquivo nativo fica de fora (um diálogo do sistema não abre sem tela) — o que ele devolveria é
passado ao mesmo slot que o QML chama. Capturas em `/tmp/jarvis-telas/audio/` (ou
`JARVIS_TELAS`), para o dono olhar.
"""

# ruff: noqa: F811 — as fixtures vêm de `test_janela` e são parâmetros aqui
from __future__ import annotations

import os
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QEventLoop, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest

from jarvis.gui.ponte import Ponte
from jarvis.navegador.estado import EstadoDaPonte
from jarvis.voz.config import Configuracao, ler
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)

TELAS = Path(os.environ.get("JARVIS_TELAS", "/tmp/jarvis-telas")) / "audio"  # noqa: S108


def _esperar(app: QGuiApplication, segundos: float, ate: Callable[[], bool] | None = None) -> None:
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if ate is not None and ate():
            return
        time.sleep(0.005)


def _procurar(item: QQuickItem, nome: str) -> QQuickItem | None:
    """Busca pela árvore **visual**: o que um `Loader` carrega não é filho QObject do pai."""
    if item.objectName() == nome:
        return item
    for filho in item.childItems():
        achado = _procurar(filho, nome)
        if achado is not None:
            return achado
    return None


def _item(janela: QQuickView, nome: str) -> QQuickItem:
    achado = _procurar(janela.rootObject(), nome)
    assert achado is not None, f"não achei {nome} na tela"
    return achado


def _clicar(
    janela: QQuickView, app: QGuiApplication, item: QQuickItem, dx: int = 0, dy: int = 0
) -> None:
    centro = item.mapToScene(item.boundingRect().center())
    ponto = QPoint(round(centro.x()) + dx, round(centro.y()) + dy)
    QTest.mouseClick(janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    _esperar(app, 0.25)


def _aba(janela: QQuickView, app: QGuiApplication, nome: str) -> None:
    _clicar(janela, app, _item(janela, f"aba{nome}"))


def _capturar(janela: QQuickView, nome: str) -> Path:
    TELAS.mkdir(parents=True, exist_ok=True)
    destino = TELAS / nome
    assert janela.grabWindow().save(str(destino)), destino
    return destino


@pytest.fixture
def maquina(tmp_path: Path) -> dict[str, Path]:
    """Uma máquina de mentira: apps, binários, a casa do dono e a configuração."""
    apps = tmp_path / "applications"
    bins = tmp_path / "bin"
    lar = tmp_path / "casa"
    for pasta in (apps, bins, lar / "Projetos" / "jarvis", lar / "Livros", lar / ".ssh"):
        pasta.mkdir(parents=True)
    https = "MimeType=x-scheme-handler/http;x-scheme-handler/https;\n"
    (apps / "brave-browser.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Brave Web Browser\n"
        f"Exec={bins}/brave-stable %U\n{https}",
        "utf-8",
    )
    (apps / "brave-browser-beta.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Brave Web Browser (Beta)\n"
        f"Exec={bins}/brave-beta %U\n{https}",
        "utf-8",
    )
    (apps / "org.mozilla.firefox.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName=Firefox\nExec={bins}/firefox %u\n{https}", "utf-8"
    )
    for id_, nome in (
        ("org.kde.kate", "Kate"),
        ("org.kde.dolphin", "Dolphin"),
        ("org.kde.kcalc", "Calculadora"),
        ("org.gnome.Calendar", "Calendário"),
        ("blender", "Blender"),
    ):
        (apps / f"{id_}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName={nome}\nExec={id_.split('.')[-1]}\n", "utf-8"
        )
    for nome in ("brave-stable", "brave-beta", "firefox", "meu-editor"):
        binario = bins / nome
        binario.write_text("#!/bin/true\n", "utf-8")
        binario.chmod(binario.stat().st_mode | stat.S_IXUSR)
    return {"apps": apps, "bins": bins, "lar": lar, "config": tmp_path / "jarvis-voz.toml"}


@pytest.fixture
def tela_de_acesso(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
    sem_chaveiro: None,
) -> tuple[QQuickView, Any, Ponte]:
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        lar=maquina["lar"],
    )
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    tela = cast(Any, ponte)
    tela.abrirPainel("configuracao")
    _esperar(aplicativo, 0.6)
    return janela, tela, ponte


def test_a_aba_de_acesso_abre_com_estado_vazio_que_explica(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], aplicativo: QGuiApplication
) -> None:
    janela, tela, _ = tela_de_acesso
    assert not _item(janela, "vistaAcesso").isVisible(), "a folha de voz é a primeira"
    _aba(janela, aplicativo, "Pastas")
    assert _item(janela, "vistaAcesso").isVisible()
    _capturar(janela, "acesso-1-pastas-vazio.png")
    _aba(janela, aplicativo, "Apps")
    _capturar(janela, "acesso-1-apps.png")
    _aba(janela, aplicativo, "Navegadores")
    _capturar(janela, "acesso-1-navegadores.png")
    assert tela.acesso.raizes == []
    nomes = [a["nome"] for a in tela.acesso.aplicativos]
    assert nomes == sorted(nomes, key=str.casefold) and "Kate" in nomes
    assert [n["familia"] for n in tela.acesso.navegadores] == ["brave", "firefox"]


def test_adicionar_pasta_vira_nivel_concedido_e_vai_para_o_arquivo(
    tela_de_acesso: tuple[QQuickView, Any, Ponte],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
) -> None:
    janela, tela, _ = tela_de_acesso
    _aba(janela, aplicativo, "Pastas")
    pasta = maquina["lar"] / "Projetos"

    # O que o seletor nativo entrega: uma URL file://.
    assert tela.acesso.adicionarRaiz(pasta.as_uri())
    _esperar(aplicativo, 0.3)

    gravada = ler(maquina["config"])
    assert gravada.raizes == (str(pasta),)
    assert gravada.acesso == "concedido", "pasta na lista num nível que a ignora seria mentira"
    assert tela.acesso.raizes[0]["nivel"] == "leitura"

    # O clique no botão de nível, no lugar dele na tela, alterna leitura ↔ escrita.
    _clicar(janela, aplicativo, _item(janela, "nivel-Projetos"))
    assert ler(maquina["config"]).raizes_escrita == (str(pasta),)
    _clicar(janela, aplicativo, _item(janela, "nivel-Projetos"))
    assert ler(maquina["config"]).raizes_escrita == ()
    _capturar(janela, "acesso-2-pasta.png")


@pytest.mark.parametrize("alvo", [".ssh", "nao-existe"])
def test_pasta_negada_ou_inexistente_e_recusada_com_o_motivo(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path], alvo: str
) -> None:
    _, tela, _ = tela_de_acesso
    assert not tela.acesso.adicionarRaiz(str(maquina["lar"] / alvo))
    assert tela.acesso.frase.startswith("não deu:")
    assert (alvo == ".ssh") == ("fica negada para sempre" in tela.acesso.frase)
    assert not maquina["config"].exists() or ler(maquina["config"]).raizes == ()


def test_arquivo_solto_nao_vira_raiz_e_a_frase_manda_escolher_a_pasta(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, tela, _ = tela_de_acesso
    arquivo = maquina["lar"] / "Livros" / "notas.txt"
    arquivo.write_text("x", "utf-8")
    assert not tela.acesso.adicionarRaiz(str(arquivo))
    assert "escolha a pasta que o contém" in tela.acesso.frase


def test_marcar_app_com_o_mouse_grava_e_a_lista_mostra(
    tela_de_acesso: tuple[QQuickView, Any, Ponte],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
) -> None:
    janela, tela, _ = tela_de_acesso
    _aba(janela, aplicativo, "Apps")
    lista = _item(janela, "listaDeApps")
    primeiro = tela.acesso.aplicativos[0]["id"]

    _clicar(janela, aplicativo, lista, dy=-int(lista.height() / 2) + 15)

    assert primeiro in ler(maquina["config"]).apps_autorizados
    assert tela.acesso.aplicativos[0]["autorizado"] is True
    _capturar(janela, "acesso-2-app-marcado.png")
    _clicar(janela, aplicativo, lista, dy=-int(lista.height() / 2) + 15)
    assert ler(maquina["config"]).apps_autorizados == ()


def test_app_escolhido_a_mao_e_binario_invalido_e_recusado(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, tela, _ = tela_de_acesso
    meu = maquina["bins"] / "meu-editor"
    assert tela.acesso.adicionarApp(meu.as_uri())
    assert ler(maquina["config"]).apps_extras == (str(meu),)
    assert tela.acesso.aplicativosExtras[0]["nome"] == "meu-editor"

    texto = maquina["lar"] / "Livros" / "so-texto.txt"
    texto.write_text("x", "utf-8")
    assert not tela.acesso.adicionarApp(str(texto))
    assert "não serve" in tela.acesso.frase


def test_escolher_o_binario_e_marcar_o_principal_com_o_mouse(
    tela_de_acesso: tuple[QQuickView, Any, Ponte],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
) -> None:
    janela, tela, _ = tela_de_acesso
    _aba(janela, aplicativo, "Navegadores")
    brave = next(n for n in tela.acesso.navegadores if n["familia"] == "brave")
    assert len(brave["opcoes"]) == 2, "estável e beta: o dono escolhe qual binário usar"
    beta = next(o for o in brave["opcoes"] if "beta" in o["entrada"])

    assert tela.acesso.escolherBinario("brave", beta["entrada"])
    gravada = ler(maquina["config"])
    assert gravada.navegadores == (f"brave={beta['entrada']}",)
    assert gravada.navegador_principal == "brave", "o primeiro navegador vira o principal"

    # Firefox: "tornar principal" pelo mouse escolhe o binário (único) e marca o principal.
    _clicar(janela, aplicativo, _item(janela, "principal-firefox"))
    gravada = ler(maquina["config"])
    assert gravada.navegador_principal == "firefox"
    assert {f.split("=")[0] for f in gravada.navegadores} == {"brave", "firefox"}
    _capturar(janela, "acesso-3-navegadores-escolhidos.png")


def test_navegador_incluido_a_mao_aparece_e_pode_ser_retirado(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, tela, _ = tela_de_acesso
    meu = maquina["bins"] / "meu-editor"
    assert tela.acesso.adicionarNavegador(str(meu))
    manual = next(n for n in tela.acesso.navegadores if n["manual"])
    assert manual["familia"] == "meueditor" or manual["familia"].startswith("meu")
    tela.acesso.retirarNavegador(manual["familia"])
    assert not any(n["manual"] for n in tela.acesso.navegadores)
    assert ler(maquina["config"]).navegadores == ()


def test_so_os_campos_de_acesso_vao_para_o_arquivo(
    tela_de_acesso: tuple[QQuickView, Any, Ponte], maquina: dict[str, Path]
) -> None:
    _, tela, _ = tela_de_acesso
    tela.definirCampo("saida", "pipewire")  # escolha da voz ainda não salva
    tela.acesso.marcarApp("org.kde.kate", True)
    assert ler(maquina["config"]).saida == "", "marcar um app não salva o que o dono não salvou"
    assert ler(maquina["config"]).apps_autorizados == ("org.kde.kate",)


def test_mexer_no_acesso_com_a_conversa_aberta_vale_no_proximo_pedido(
    tela_de_acesso: tuple[QQuickView, Any, Ponte],
) -> None:
    _, tela, ponte = tela_de_acesso
    recarregou: list[tuple[str, ...]] = []

    class Aplicativo:
        def atualizar_acesso(self, configuracao: Any) -> None:
            recarregou.append(configuracao.apps_autorizados)

    class Sessao:
        viva = True
        aplicativo = Aplicativo()

    ponte._sessao = Sessao()  # type: ignore[assignment]
    tela.acesso.marcarApp("org.kde.kate", True)
    assert recarregou == [("org.kde.kate",)]


def test_a_chave_do_navegador_controlado_liga_pelo_mouse_grava_e_diz_o_estado(
    abrir: Callable[[Ponte], QQuickView],
    aplicativo: QGuiApplication,
    maquina: dict[str, Path],
    tmp_path: Path,
    sem_chaveiro: None,
) -> None:
    """Ligar as `browser.*` era editar o TOML à mão (dono, 2026-10-19). Agora é um clique, vale
    na conversa aberta e a tela diz o estado da extensão — o estado que o teste dá, nunca os
    sockets do dono."""

    vivos: list[str] = []

    def sondar(configuracao: Configuracao) -> EstadoDaPonte:
        return EstadoDaPonte(
            ligado=configuracao.navegador_controlado,
            principal="brave",
            vivos=tuple(vivos),
            manifestos=(),
        )

    ponte = Ponte(
        raiz=tmp_path / "sessao",
        caminho_da_configuracao=maquina["config"],
        ambiente={"CI": "1"},
        pastas_de_apps=(str(maquina["apps"]),),
        lar=maquina["lar"],
        sondar_navegador=sondar,
    )
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.5)
    tela = cast(Any, ponte)
    tela.abrirPainel("configuracao")
    _esperar(aplicativo, 0.6)
    recarregou: list[bool] = []

    class Aplicativo:
        def atualizar_acesso(self, configuracao: Any) -> None:
            recarregou.append(configuracao.navegador_controlado)

    class Sessao:
        viva = True
        aplicativo = Aplicativo()

    ponte._sessao = Sessao()  # type: ignore[assignment]
    _aba(janela, aplicativo, "Navegadores")
    assert "desligado" in str(_item(janela, "estadoDaExtensao").property("text"))

    _clicar(janela, aplicativo, _item(janela, "navegadorControlado-ligado"))

    assert ler(maquina["config"]).navegador_controlado is True
    assert recarregou == [True], "vale já no próximo pedido, sem reiniciar"
    assert tela.acesso.navegadorControlado is True
    estado = str(_item(janela, "estadoDaExtensao").property("text"))
    assert "está ligado" in estado and "Falta o manifesto do host nativo para o brave" in estado
    _capturar(janela, "acesso-4-navegador-controlado.png")

    vivos.append("chromium")  # o dono carregou a extensão com a janela aberta
    _clicar(janela, aplicativo, _item(janela, "conferirExtensao"))
    assert "Conectado" in str(_item(janela, "estadoDaExtensao").property("text"))

    _clicar(janela, aplicativo, _item(janela, "navegadorControlado-desligado"))
    assert ler(maquina["config"]).navegador_controlado is False
    assert recarregou == [True, False]
