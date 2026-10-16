"""A promessa da ADR-0019 verificada por `import`: a janela é só apresentação.

Prometer "a GUI não fala com ASR nem com o dispositivo" é fácil; o que impede isso de
envelhecer é um teste que lê os arquivos. Se alguém puser um `from jarvis.audio_io...` numa
tela daqui a três meses — porque era mais rápido —, este teste cai e a conversa acontece antes
do commit, não depois do bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from jarvis.gui.componentes import CATALOGO, Vista

PASTA = Path(__file__).resolve().parents[3] / "src" / "jarvis" / "gui"
QML = PASTA / "qml" / "JarvisUI"

PROIBIDOS = (
    "jarvis.agentd",
    "jarvis.audio_io",
    "jarvis.barramento",
    "jarvis.voz.groq",
    "jarvis.voz.elevenlabs",
    "jarvis.voz.edge",
    "jarvis.voz.fonemizador",
    "jarvis.memoryd",
    "jarvis.politica",
)
"""Motores, dispositivo, barramento e política: a janela chega a tudo isso **pelo laço**."""


def modulos() -> list[Path]:
    return sorted(PASTA.glob("*.py"))


def importados(arquivo: Path) -> set[str]:
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), filename=str(arquivo))
    nomes: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            nomes.update(alias.name for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.module:
            nomes.add(no.module)
    return nomes


@pytest.mark.parametrize("arquivo", modulos(), ids=lambda caminho: caminho.name)
def test_a_janela_nao_importa_motor_dispositivo_nem_barramento(arquivo: Path) -> None:
    achados = {
        modulo
        for modulo in importados(arquivo)
        for proibido in PROIBIDOS
        if modulo == proibido or modulo.startswith(proibido + ".")
    }

    assert not achados, (
        f"{arquivo.name} importa {sorted(achados)}: a janela fala com o laço "
        "(`jarvis.voz.app`), não com os motores (ADR-0019)"
    )


def test_o_nucleo_e_o_chaveiro_nao_dependem_de_qt() -> None:
    """A lógica da janela é testável sem `QApplication` — e estes testes são a prova."""
    for nome in ("nucleo.py", "chaveiro.py", "workspace.py", "acoes.py", "componentes.py"):
        assert not any(modulo.startswith("PySide6") for modulo in importados(PASTA / nome)), (
            f"{nome} passou a depender de Qt"
        )


def test_toda_vista_do_catalogo_tem_arquivo_qml() -> None:
    """Componente autorizado sem tela é módulo que nasce em branco na cara do dono."""
    for componente in CATALOGO.values():
        esperado = {
            Vista.LISTA: "VistaLista.qml",
            Vista.TEXTO: "VistaTexto.qml",
            Vista.ITENS_COM_IMAGEM: "VistaItens.qml",
            Vista.CONSOLE: "VistaConsole.qml",
            Vista.TAREFAS: "VistaTarefas.qml",
            Vista.MEDIDORES: "VistaMedidores.qml",
            Vista.CONVERSA: "VistaConversa.qml",
            Vista.CONFIGURACAO: "VistaConfiguracao.qml",
            Vista.DIAGNOSTICO: "VistaDiagnostico.qml",
            Vista.NOTIFICACOES: "VistaNotificacoes.qml",
        }[componente.vista]
        assert (QML / esperado).exists(), f"{componente.id} aponta para {esperado}, que não existe"


def test_nenhum_qml_cria_objeto_a_partir_de_texto() -> None:
    """`Qt.createQmlObject` e `eval` seriam a porta que o catálogo fecha pela frente."""
    for arquivo in QML.glob("*.qml"):
        texto = arquivo.read_text(encoding="utf-8")
        for proibido in ("Qt.createQmlObject", "Qt.createComponent", "eval(", "Function("):
            assert proibido not in texto, f"{arquivo.name} usa {proibido}"


def test_a_tela_nao_desenha_html() -> None:
    """Nenhuma vista aceita HTML: `Text.RichText` seria conteúdo virando marcação."""
    for arquivo in QML.glob("*.qml"):
        texto = arquivo.read_text(encoding="utf-8")
        assert "Text.RichText" not in texto, f"{arquivo.name} habilita HTML num Text"
        assert "WebEngine" not in texto, f"{arquivo.name} traz um navegador para dentro da tela"


def test_o_atalho_do_menu_aponta_para_esta_instalacao(tmp_path: Path) -> None:
    """O menu de aplicativos não herda o `PATH` do shell: o `Exec` tem de ser absoluto."""
    from jarvis.gui import principal

    atalho, icone = principal.instalar_atalho(tmp_path)

    texto = atalho.read_text(encoding="utf-8")
    assert atalho.name == "dev.sodredev.Jarvis.desktop"
    assert "[Desktop Entry]" in texto and "Name=Jarvis" in texto
    linha = next(x for x in texto.splitlines() if x.startswith("Exec="))
    assert linha.removeprefix("Exec=").startswith("/"), linha
    assert icone.read_text(encoding="utf-8").lstrip().startswith("<?xml")
    assert icone.parent.as_posix().endswith("icons/hicolor/scalable/apps")
