"""O conteúdo que o Jarvis monta, na janela de verdade (ADR-0055), offscreen.

Três coisas que só a janela prova: o módulo `conteudo` aparece com o HTML limpo desenhado pelo texto
rico do Qt (e a captura mostra); trocar e fechar pela porta mexem no módulo certo, e o X do dono
chega à porta; e **nenhuma requisição sai** — o HTML com imagem e `url()` apontando para um
servidor em 127.0.0.1 passa pela porta e pela fronteira da janela e chega desenhado sem um pedido
sequer. O controle — o mesmo HTML cru num `Text` rico busca as três coisas — é a sonda
`tools/sonda_rede_da_tela.py`, num processo à parte (ver o comentário no teste).
"""

from __future__ import annotations

import http.server
import os
import socketserver
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickView

from jarvis.gui import principal
from jarvis.gui.ponte import Ponte
from jarvis.tela import PortaDaTela
from tests.unit.gui.test_janela import PRESAS, aplicativo, sem_chaveiro  # noqa: F401 — fixtures
from tests.unit.gui.test_polimento import assentar, visiveis

TABELA = (
    '<h1>Celulares até R$ 1.500</h1><p class="fraco">Preços de hoje, à vista.</p>'
    '<table width="100%"><tr><th>Modelo</th><th>Bateria</th><th class="num">Preço (R$)</th></tr>'
    '<tr><td>Galaxy A15</td><td>5000 mAh</td><td class="num">1.299</td></tr>'
    '<tr><td>Moto G54</td><td>5000 mAh</td><td class="num">1.199</td></tr>'
    '<tr><td>Redmi 13</td><td>5030 mAh</td><td class="num destaque">999</td></tr></table>'
    '<ul><li><b>Mais barato:</b> Redmi 13</li><li>Todos com 5G <span class="alerta">exceto o '
    'A15</span></li></ul><script>alert(1)</script><img src="http://127.0.0.1:9/x.png">'
)
CAPTURAS = (
    Path(os.environ.get("JARVIS_CAPTURAS_DE_TESTE", ""))
    if os.environ.get("JARVIS_CAPTURAS_DE_TESTE")
    else None
)


def _abrir(ponte: Ponte) -> QQuickView:
    """A janela como `principal.main` a monta."""
    janela = QQuickView()
    janela.rootContext().setContextProperty("ponte", ponte)
    qml = Path(principal.__file__).resolve().parent / "qml"
    janela.engine().addImportPath(str(qml))
    janela.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    janela.setSource(QUrl.fromLocalFile(str(qml / "JarvisUI" / "Principal.qml")))
    janela.resize(*principal.TAMANHO)
    PRESAS.append((janela, ponte))
    return janela


def _avaliar(item: QObject, expressao: str) -> object:
    """Uma expressão QML no contexto do item (o enum do `textFormat` não converte para Python)."""
    contexto = QQmlEngine.contextForObject(item)
    assert contexto is not None
    valor, indefinido = QQmlExpression(contexto, item, expressao).evaluate()
    assert not indefinido, expressao
    return valor


def _porta(ponte: Ponte) -> PortaDaTela:
    """A porta como o laço a liga pela sessão (sinais da ponte: o Qt entrega na linha da janela)."""
    return PortaDaTela(
        ao_mostrar=lambda e: ponte.conteudoMostrado.emit(e.id, e.titulo, e.documento, e.fundo),
        ao_fechar=ponte.conteudoFechado.emit,
    )


def _modulos(ponte: Ponte) -> list[Any]:
    espaco = cast(Any, ponte)._espaco
    return [w for w in espaco.widgets.values() if w.componente == "conteudo"]


def test_o_conteudo_montado_aparece_num_modulo_com_texto_rico(
    aplicativo: QGuiApplication,  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    janela = _abrir(ponte)
    janela.show()
    assentar(aplicativo, 500)
    porta = _porta(ponte)
    assert cast(Any, ponte).modo == "assistente"

    exibicao = porta.mostrar(TABELA, titulo="Celulares")
    assentar(aplicativo, 700)
    # O centro do assistente é do núcleo: o conteúdo pede o modo pesquisa ("o conteúdo manda").
    assert cast(Any, ponte).modo == "pesquisa"

    assert [str(erro) for erro in janela.errors()] == []
    textos = visiveis(janela, "conteudoDaTela")
    assert len(textos) == 1, "o módulo do conteúdo não apareceu"
    texto = textos[0]
    assert _avaliar(texto, "textFormat === Text.RichText") is True
    desenhado = str(texto.property("text"))
    assert "Redmi 13" in desenhado and "<table" in desenhado
    assert "<script" not in desenhado and "127.0.0.1" not in desenhado
    assert float(texto.property("paintedHeight")) > 120, "a tabela não foi desenhada"
    (modulo,) = _modulos(ponte)
    assert modulo.titulo == "Celulares" and not modulo.demonstracao
    assert exibicao.removidos == ("script", "imagem")

    imagem = janela.grabWindow()
    assert not imagem.isNull()
    caminho = (CAPTURAS or tmp_path) / "jarvis-conteudo-na-tela.png"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    assert imagem.save(str(caminho))

    # Mudar pelo mesmo id troca o conteúdo do mesmo módulo; fechar pela porta o tira da tela.
    porta.mostrar("<h1>Celulares</h1><p>Só o Redmi 13.</p>", identificador=exibicao.id)
    assentar(aplicativo, 400)
    assert len(_modulos(ponte)) == 1
    assert "Só o Redmi 13" in str(visiveis(janela, "conteudoDaTela")[0].property("text"))
    assert porta.fechar() == [exibicao.id]
    assentar(aplicativo, 400)
    assert _modulos(ponte) == [] and visiveis(janela, "conteudoDaTela") == []
    assert cast(Any, ponte).modo == "assistente", "fechado o conteúdo, o modo de antes volta"


class SessaoQueAnota:
    """No lugar da sessão de voz: anota o que a janela avisou."""

    def __init__(self) -> None:
        self.fechadas: list[str] = []
        self.viva = False

    def conteudo_fechado_pelo_dono(self, identificador: str) -> None:
        self.fechadas.append(identificador)


def test_o_x_do_dono_no_modulo_chega_a_porta(
    aplicativo: QGuiApplication,  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    sessao = SessaoQueAnota()
    cast(Any, ponte)._sessao = sessao
    janela = _abrir(ponte)
    janela.show()
    porta = _porta(ponte)
    exibicao = porta.mostrar("<p>lista</p>", identificador="lista")
    assentar(aplicativo, 400)
    (modulo,) = _modulos(ponte)

    ponte.fecharModulo(modulo.id)
    assentar(aplicativo, 200)

    assert sessao.fechadas == [exibicao.id]


# --- a rede -----------------------------------------------------------------------------------
@pytest.fixture
def servidor_local() -> Iterator[tuple[str, list[str]]]:
    """Um servidor em 127.0.0.1 que só conta os pedidos (404 para todos)."""
    pedidos: list[str] = []

    class Contador(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            pedidos.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *_args: object) -> None:
            return

    servidor = socketserver.TCPServer(("127.0.0.1", 0), Contador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{servidor.server_address[1]}", pedidos
    finally:
        servidor.shutdown()
        servidor.server_close()


def _html_com_recursos(base: str) -> str:
    """Imagem e dois `url()` apontando para o servidor local: o que o sanitizador tira."""
    return (
        f"<html><head><style>p {{ background-image: url({base}/folha.png) }}</style></head><body>"
        f'<h1>Lista</h1><p style="background-image: url({base}/inline.png)">oi</p>'
        f'<img src="{base}/imagem.png" width="10" height="10"></body></html>'
    )


def test_do_modelo_a_janela_nenhuma_requisicao_sai(
    aplicativo: QGuiApplication,  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
    servidor_local: tuple[str, list[str]],
) -> None:
    base, pedidos = servidor_local
    ponte = Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=tmp_path / "jarvis-voz.toml")
    janela = _abrir(ponte)
    janela.show()

    exibicao = _porta(ponte).mostrar(_html_com_recursos(base), titulo="Lista")
    assentar(aplicativo, 1500)

    assert len(visiveis(janela, "conteudoDaTela")) == 1, "o conteúdo não chegou à janela"
    assert pedidos == [], "a tela buscou algo na rede"
    assert set(exibicao.removidos) >= {"url", "imagem"}
    # O controle (o mesmo HTML cru num Text rico busca as três coisas) mora em
    # `tools/sonda_rede_da_tela.py`, num processo só dele: a carga de imagem remota do QML derruba o
    # processo de vez em quando com outras janelas abertas (PySide6 6.9.3, medido em 2026-10-29) —
    # é mais um motivo para nada remoto chegar à tela, não um teste que possa morar aqui.


def test_a_fronteira_da_janela_recusa_html_que_aponta_para_fora_mesmo_sem_a_limpeza(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A segunda regra é independente da allowlist: com o sanitizador quebrado (aqui, trocado por
    um que devolve tudo), o documento que ainda aponta para fora não chega à tela."""
    from jarvis.gui import componentes
    from jarvis.tela.sanitizar import HtmlSeguro

    monkeypatch.setattr(componentes, "sanitizar", lambda bruto, **_k: HtmlSeguro(corpo=bruto))
    alvo = componentes.componente("conteudo")
    for vazado in (
        '<img src="http://x/a.png">',
        '<p style="background: url(http://x)">a</p>',
        '<a href="http://x">a</a>',
        "<style>@import 'http://x/a.css';</style>",
    ):
        with pytest.raises(componentes.ComponenteNaoAutorizado, match="aponta para fora"):
            componentes.validar_dados(alvo, {"html": vazado})
    assert componentes.validar_dados(alvo, {"html": "<p>ok</p>"})["html"].endswith("</html>")
