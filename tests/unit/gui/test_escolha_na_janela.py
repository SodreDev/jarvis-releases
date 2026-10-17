"""A escolha de modelo e de voz **pela janela**: o clique chega ao arquivo e a tela desenha.

Os cliques são os mesmos slots que o QML chama (`definirCampo`, `ligarNuvem`,
`buscarVozes`, `salvarConfiguracao`); a lista de vozes vem do `ServicoFalso`, em porta
efêmera, sob `CI=1` — nenhuma conta de verdade é consultada. A captura sai em
`/tmp/jarvis-telas/teste/` (ou `JARVIS_TELAS`), fora do repositório.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui` (`uv sync --group gui`)")

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtQuick import QQuickView

from jarvis.gui import chaveiro, principal
from jarvis.gui import ponte as modulo_da_ponte
from jarvis.gui.ponte import Ponte
from jarvis.voz.chaves import VARIAVEL_ELEVENLABS
from jarvis.voz.config import TTS_ELEVENLABS, Configuracao, escrever, ler
from jarvis.voz.elevenlabs import listar_vozes
from tests.unit.gui import test_janela as base
from tests.unit.voz.servidor_falso import Roteiro, ServicoFalso

GROQ_V3 = "asr-groq-whisper-large-v3"
SEGREDO = "sk_chave_de_teste_que_nao_pode_vazar_0123456789"


@pytest.fixture
def app_qt() -> QGuiApplication:
    existente = QGuiApplication.instance()
    return existente if isinstance(existente, QGuiApplication) else QGuiApplication([])


@pytest.fixture
def chaveiro_vazio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste conversa com o chaveiro do dono."""
    monkeypatch.setattr(chaveiro, "_modulo", base.ChaveiroFalso)


@pytest.fixture
def janela_de(app_qt: QGuiApplication) -> Iterator[Callable[[Ponte], QQuickView]]:
    """Abre a janela como o `test_janela` abre, e a segura viva até o fim do processo pelo
    mesmo motivo de lá (desmontar a vista com ligações para a ponte derruba o interpretador)."""
    vivas: list[tuple[QQuickView, Ponte]] = []

    def _abrir(ponte: Ponte) -> QQuickView:
        janela = QQuickView()
        janela.rootContext().setContextProperty("ponte", ponte)
        qml = Path(principal.__file__).resolve().parent / "qml"
        janela.engine().addImportPath(str(qml))
        janela.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        janela.setSource(QUrl.fromLocalFile(str(qml / "JarvisUI" / "Principal.qml")))
        janela.resize(*principal.TAMANHO)
        vivas.append((janela, ponte))
        return janela

    yield _abrir

    for janela, _ponte in vivas:
        janela.close()
    app_qt.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)
    base.PRESAS.extend(vivas)


def _esperar(app_qt: QGuiApplication, condicao: Callable[[], bool], limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao() and time.monotonic() < fim:
        app_qt.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.01)


def _ponte(tmp_path: Path, configuracao: Configuracao | None = None) -> Ponte:
    arquivo = tmp_path / "jarvis-voz.toml"
    if configuracao is not None:
        escrever(configuracao, arquivo)
    return Ponte(raiz=tmp_path / "sessao", caminho_da_configuracao=arquivo)


def test_escolher_o_modelo_da_groq_pela_janela_chega_ao_arquivo(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    ponte = _ponte(tmp_path)
    tela = cast(Any, ponte)
    groq = next(p for p in tela.provedoresAsr if p["nome"] == "Groq")
    assert [m["modelo"] for m in groq["modelos"]] == [
        "whisper-large-v3-turbo",
        "whisper-large-v3",
    ]

    tela.escolherProvedor("asr", groq["chave"])
    v3 = next(m for m in groq["modelos"] if m["modelo"] == "whisper-large-v3")
    tela.definirCampo(v3["campo"], v3["valor"])
    tela.ligarNuvem(GROQ_V3, True)
    tela.salvarConfiguracao()

    gravada = ler(tmp_path / "jarvis-voz.toml")
    assert gravada.asr == GROQ_V3 and gravada.nuvem_ligada == (GROQ_V3,)
    groq = next(p for p in tela.provedoresAsr if p["nome"] == "Groq")
    assert groq["escolhido"] and groq["ligado"]


def test_escolher_modelo_e_voz_da_elevenlabs_pela_janela_chega_ao_arquivo(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    ponte = _ponte(tmp_path)
    tela = cast(Any, ponte)

    tela.escolherProvedor("tts", "nuvem:ElevenLabs")
    tela.definirCampo("modelo_elevenlabs", "eleven_flash_v2_5")
    tela.definirCampo("voz_elevenlabs", "vozDoDono42")
    tela.salvarConfiguracao()

    gravada = ler(tmp_path / "jarvis-voz.toml")
    assert gravada.tts == TTS_ELEVENLABS
    assert (gravada.modelo_elevenlabs, gravada.voz_elevenlabs) == (
        "eleven_flash_v2_5",
        "vozDoDono42",
    )
    assert gravada.nuvem_ligada == (), "escolher não liga"


def test_buscar_vozes_preenche_a_lista_sem_a_chave_na_tela(
    app_qt: QGuiApplication,
    tmp_path: Path,
    chaveiro_vazio: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpo = json.dumps(
        {
            "voices": [{"voice_id": "ptVoz2", "name": "Clara", "labels": {"language": "pt"}}],
            "has_more": False,
        }
    ).encode()
    with ServicoFalso(Roteiro(corpo=corpo)) as servico:
        monkeypatch.setattr(
            modulo_da_ponte,
            "vozes_da_elevenlabs",
            lambda ambiente: [
                v.para_dict()
                for v in listar_vozes(
                    base=servico.base, ambiente={"CI": "1", VARIAVEL_ELEVENLABS: SEGREDO}
                )
            ],
        )
        tela = cast(Any, _ponte(tmp_path))
        tela.buscarVozes()
        _esperar(app_qt, lambda: bool(tela.vozesDaConta))

    assert [v["id"] for v in tela.vozesDaConta] == ["ptVoz2"]
    assert "1 voz(es) na conta, 1 com português" in tela.vozesFrase
    assert SEGREDO not in json.dumps(tela.vozesDaConta) + tela.vozesFrase


def test_a_captura_da_configuracao_mostra_os_seletores(
    app_qt: QGuiApplication,
    janela_de: Callable[[Ponte], QQuickView],
    tmp_path: Path,
    chaveiro_vazio: None,
) -> None:
    """O retrato que o dono pediu: Groq com os dois modelos, ElevenLabs com modelo e voz."""
    ponte = _ponte(
        tmp_path,
        Configuracao(
            asr=GROQ_V3,
            tts=TTS_ELEVENLABS,
            voz_elevenlabs="ptVoz2",
            modelo_elevenlabs="eleven_flash_v2_5",
            nuvem_ligada=(GROQ_V3,),
        ),
    )
    janela = janela_de(ponte)
    tela = cast(Any, ponte)
    ponte._vozes = [  # a lista que a busca devolveria — sem rede no retrato
        {"id": "ptVoz2", "nome": "Clara", "categoria": "", "idiomas": ["pt"], "portugues": True},
        {"id": "enVoz1", "nome": "Zed", "categoria": "", "idiomas": ["en"], "portugues": False},
    ]
    ponte._vozes_frase = "2 voz(es) na conta, 1 com português declarado"
    ponte.vozesMudaram.emit()
    janela.show()
    tela.abrirPainel("configuracao")
    principal._esperar(app_qt, principal.ESPERA_DA_ANIMACAO_MS)

    destino = base.TELAS / "jarvis-configuracao-modelos.png"
    base.TELAS.mkdir(parents=True, exist_ok=True)
    janela.grabWindow().save(str(destino))

    assert [str(erro) for erro in janela.errors()] == []
    imagem = QImage(str(destino))
    assert imagem.width() == principal.TAMANHO[0]
    cores = {
        imagem.pixel(x, y)
        for x in range(0, imagem.width(), 23)
        for y in range(0, imagem.height(), 19)
    }
    assert len(cores) > 12, "a captura saiu quase vazia"


JEV = "decisao-jev-openrouter"


def test_escolher_e_ligar_o_detector_de_enderecamento_chega_ao_arquivo(
    tmp_path: Path, chaveiro_vazio: None
) -> None:
    """ "É comigo?" (ADR-0029): escolher não liga, ligar é outro clique, clicar de novo tira."""
    ponte = _ponte(tmp_path)
    tela = cast(Any, ponte)
    (jev,) = tela.provedoresDecisao
    assert jev["onde"] == "nuvem" and not jev["escolhido"] and not jev["ligado"]
    assert "sai desta máquina" in jev["aviso"] and jev["variavelDaChave"] == "OPENROUTER_API_KEY"

    tela.escolherProvedor("decisao", jev["chave"])
    (jev,) = tela.provedoresDecisao
    assert jev["escolhido"] and not jev["ligado"], "escolher não liga a nuvem"
    tela.ligarNuvem(JEV, True)
    tela.salvarConfiguracao()
    gravada = ler(tmp_path / "jarvis-voz.toml")
    assert gravada.enderecamento == JEV and gravada.nuvem_ligada == (JEV,)

    tela.escolherProvedor("decisao", jev["chave"])  # clicar no escolhido tira a escolha
    tela.salvarConfiguracao()
    assert ler(tmp_path / "jarvis-voz.toml").enderecamento == ""
