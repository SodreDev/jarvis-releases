"""A janela **sempre** abre (bug do dono, 2026-11-14: «o Jarvis não abre» depois de atualizar).

Configuração antiga, nova, parcial ou quebrada — `jarvis-voz.toml`, `presets.toml`, `redes.toml`,
`memorias-fixas.toml`, `tts-endpoints.toml`, o vocabulário — vira padrão com aviso, nunca uma
exceção na abertura. Cada caso monta a `Ponte` como a `principal.main` monta e carrega o QML
sem tela. Nenhum teste lê `~/.config` do dono: tudo mora em `tmp_path`.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui import chaveiro, principal
from jarvis.gui.ponte import Ponte
from jarvis.voz.config import Configuracao, ler, ler_tolerante
from jarvis.voz.vocabulario import RepositorioDoVocabulario

PRESAS: list[tuple[QQuickView, Ponte]] = []

ANTIGO = """
asr = "asr-whisper-local"
tts = "tts-piper-epitran"
s2 = "eco"
voz = "pt_BR-faber-medium"
modelo_do_asr = "small"
escuta = "ptt"
laco_max_passos = 12
"""
"""Um arquivo de antes do teto novo, do STT «auto» e do endpoint: abre como sempre abriu."""

NOVO = """
asr = "asr-whisper-local"
tts = "tts-endpoint"
s2 = "eco"
modelo_do_asr = "auto"
permissao = "automatico"
laco_max_passos = 50
tarefa_prazo_s = 900.0
nuvem_ligada = ["tts-endpoint"]
endpoint_tts = "JARVIS-BR (phonon-web)"
voz_endpoint = "jarvis-br"
estilo_endpoint = "cordial"
reserva_do_endpoint = "tts-piper-epitran"
"""

QUEBRADOS: dict[str, str] = {
    "toml-que-nem-analisa": 'asr = "asr-whisper-local\ntts = [',
    "tipo-errado": 'laco_max_passos = "cinquenta"\nescuta = 3\natalho_global = "sim"\n',
    "motor-desconhecido": 'tts = "tts-que-nao-existe"\nasr = "asr-inventado"\n',
    "modo-desconhecido": 'escuta = "telepatia"\npermissao = "talvez"\n',
    "endpoint-recusado": 'endpoint_tts = "\\u0000mau"\nreserva_do_endpoint = "tts-endpoint"\n',
    "segredo-no-arquivo": 'tts = "tts-piper-epitran"\napi_key_da_voz = "abc123segredo"\n',
    "chave-que-nao-existe": 'chave_do_futuro = 1\n[secao_nova]\nqualquer = "coisa"\n',
}


class ChaveiroFalso:
    def get_keyring(self) -> object:
        return self

    def get_password(self, servico: str, conta: str) -> str | None:
        return None


@pytest.fixture(scope="module")
def aplicativo() -> Iterator[QGuiApplication]:
    existente = QGuiApplication.instance()
    yield existente if isinstance(existente, QGuiApplication) else QGuiApplication([])


@pytest.fixture(autouse=True)
def sem_chaveiro(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chaveiro, "_modulo", ChaveiroFalso)


@pytest.fixture
def abrir(aplicativo: QGuiApplication) -> Iterator[Callable[[Path], tuple[Ponte, QQuickView]]]:
    vivas: list[tuple[QQuickView, Ponte]] = []

    def _abrir(pasta: Path) -> tuple[Ponte, QQuickView]:
        ambiente = {"XDG_CONFIG_HOME": str(pasta.parent), "HOME": str(pasta.parent)}
        ponte = Ponte(
            raiz=pasta / "sessao",
            caminho_da_configuracao=pasta / "jarvis-voz.toml",
            ambiente=ambiente,
            vocabulario=RepositorioDoVocabulario(pasta),
        )
        janela = QQuickView()
        janela.rootContext().setContextProperty("ponte", ponte)
        qml = Path(principal.__file__).resolve().parent / "qml"
        janela.engine().addImportPath(str(qml))
        janela.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        janela.setSource(QUrl.fromLocalFile(str(qml / "JarvisUI" / "Principal.qml")))
        aplicativo.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
        vivas.append((janela, ponte))
        return ponte, janela

    yield _abrir
    for janela, _ponte in vivas:
        janela.close()
    aplicativo.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    PRESAS.extend(vivas)


def _avisos(ponte: Ponte) -> list[str]:
    return list(cast(Any, ponte).avisosDaAbertura)


def _pasta(tmp_path: Path) -> Path:
    pasta = tmp_path / "jarvis"
    pasta.mkdir(parents=True)
    return pasta


@pytest.mark.parametrize("texto", [ANTIGO, NOVO], ids=["antigo", "novo"])
def test_arquivo_antigo_e_novo_abrem_sem_aviso(
    texto: str, tmp_path: Path, abrir: Callable[[Path], tuple[Ponte, QQuickView]]
) -> None:
    pasta = _pasta(tmp_path)
    (pasta / "jarvis-voz.toml").write_text(texto, encoding="utf-8")

    ponte, janela = abrir(pasta)

    assert janela.status() is QQuickView.Status.Ready
    assert _avisos(ponte) == []
    assert ler(pasta / "jarvis-voz.toml") == ponte._configuracao


@pytest.mark.parametrize("caso", sorted(QUEBRADOS))
def test_configuracao_quebrada_abre_com_o_padrao_e_um_aviso(
    caso: str, tmp_path: Path, abrir: Callable[[Path], tuple[Ponte, QQuickView]]
) -> None:
    pasta = _pasta(tmp_path)
    arquivo = pasta / "jarvis-voz.toml"
    arquivo.write_text(QUEBRADOS[caso], encoding="utf-8")
    antes = arquivo.read_bytes()

    ponte, janela = abrir(pasta)

    assert janela.status() is QQuickView.Status.Ready
    assert [str(e) for e in janela.errors()] == []
    if caso != "chave-que-nao-existe":  # chave desconhecida é ignorada, como sempre foi
        assert _avisos(ponte), caso
        assert "padr" in " ".join(_avisos(ponte))
    # O segredo nunca volta na frase, e o arquivo do dono não é mexido ao abrir.
    assert "abc123segredo" not in " ".join(_avisos(ponte))
    assert arquivo.read_bytes() == antes


def test_so_a_chave_ruim_volta_ao_padrao(tmp_path: Path) -> None:
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text(
        'escuta = "vad"\npalavra = "sexta"\nlaco_max_passos = "muitos"\ntts = "tts-inexistente"\n',
        encoding="utf-8",
    )

    configuracao, avisos = ler_tolerante(arquivo)

    assert configuracao.escuta == "vad"
    assert configuracao.palavra == "sexta"
    assert configuracao.laco_max_passos == Configuracao().laco_max_passos
    assert configuracao.tts == Configuracao().tts
    assert len(avisos) == 2
    assert any("laco_max_passos" in a for a in avisos)
    assert any("«tts»" in a for a in avisos)


def test_chave_que_depende_de_outra_mais_abaixo_e_aceita(tmp_path: Path) -> None:
    """A segunda volta: uma chave que só vale junto de outra que vem depois no arquivo."""
    arquivo = tmp_path / "jarvis-voz.toml"
    arquivo.write_text(
        'reserva_do_endpoint = "tts-piper-epitran"\ntts = "tts-endpoint"\nescuta = "nada"\n',
        encoding="utf-8",
    )

    configuracao, avisos = ler_tolerante(arquivo)

    assert configuracao.tts == "tts-endpoint"
    assert configuracao.reserva_do_endpoint == "tts-piper-epitran"
    assert [a for a in avisos if "escuta" in a] and len(avisos) == 1


@pytest.mark.parametrize(
    ("nome", "texto"),
    [
        ("presets.toml", "[[preset]]\nnome = 3\npapel = [\n"),
        ("presets.toml", '[ativos]\ncerebro = "nao-existe"\n[[preset]]\nnome = "x"\n'),
        ("redes.toml", "[redes.whatsapp\nmonitorar = talvez\n"),
        ("memorias-fixas.toml", "[[memoria]]\nnome = \n"),
        ("tts-endpoints.toml", "[[endpoint]]\nnome = 1\nbase = [\n"),
        ("tts-endpoints.toml", '[[endpoint]]\nnome = "meu"\nbase = "ftp://x"\n'),
        ("vocabulario.toml", "[[termo]]\nescrita = \n"),
        ("vocabulario-aprendido.toml", "isto não é toml"),
    ],
    ids=lambda v: v if v.endswith(".toml") else "",
)
def test_arquivo_vizinho_quebrado_nao_impede_a_abertura(
    nome: str, texto: str, tmp_path: Path, abrir: Callable[[Path], tuple[Ponte, QQuickView]]
) -> None:
    pasta = _pasta(tmp_path)
    (pasta / "jarvis-voz.toml").write_text(NOVO, encoding="utf-8")
    (pasta / nome).write_text(texto, encoding="utf-8")

    ponte, janela = abrir(pasta)

    assert janela.status() is QQuickView.Status.Ready
    assert janela.rootObject() is not None
    # As propriedades que a tela lê logo ao abrir respondem (sem exceção do lado do Python).
    assert isinstance(ponte.endpointTts, dict)
    assert isinstance(ponte.aviso, str)
