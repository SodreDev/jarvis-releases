"""A janela reabre com a conversa de antes e tem o botão "nova conversa" (dono, 2026-10-18).

Pela janela real (QML offscreen): a transcrição volta ao abrir, o botão aparece só quando há o que
recomeçar, e apertá-lo limpa a tela e vale no disco. A captura sai em
`/tmp/jarvis-telas/conversa/` para o dono olhar.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui.ponte import Ponte
from jarvis.memoryd.cofre import CofreFernet, nova_chave
from jarvis.memoryd.conversa import ConversaPersistente, abrir_conversa
from jarvis.memoryd.indice import IndiceEmMemoria
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    CONFIGURACAO,
    abrir,
    aplicativo,
    sem_chaveiro,
)
from tests.unit.gui.test_ponte_cerebro import _esperar

TELAS = Path(os.environ.get("JARVIS_TELAS_CONVERSA", "/tmp/jarvis-telas/conversa"))  # noqa: S108
CHAVE = nova_chave()


def _conversa(raiz: Path) -> ConversaPersistente:
    return abrir_conversa(raiz, cofre=lambda: CofreFernet(CHAVE), indice=IndiceEmMemoria())


def _ponte(tmp_path: Path, conversa: ConversaPersistente) -> Ponte:
    return Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
        ambiente={"JARVIS_AUDIO_BACKEND": "arquivo"},
        conversa=conversa,
    )


def _gravar_conversa_anterior(raiz: Path) -> None:
    antes = _conversa(raiz)
    assert antes.livro is not None
    for dono, jarvis in (
        ("que horas são em Lisboa?", "Em Lisboa são quatro da tarde."),
        ("e em Tóquio?", "Em Tóquio já é meia-noite."),
    ):
        antes.livro.gravar_turno(
            session_id=antes.conversa_id, papel="dono", texto=dono, trust="user_voice"
        )
        antes.livro.gravar_turno(
            session_id=antes.conversa_id,
            papel="jarvis",
            texto=jarvis,
            trust="system",
            played_ms=1500,
        )
    antes.fechar()


def test_a_janela_reabre_com_a_conversa_de_antes_e_o_botao_recomeca(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    raiz = tmp_path / "sessao"
    _gravar_conversa_anterior(raiz)
    conversa = _conversa(raiz)
    ponte = _ponte(tmp_path, conversa)
    tela = cast(Any, ponte)  # as propriedades do Qt são `Property` para o mypy
    janela = abrir(ponte)
    janela.show()
    _esperar(aplicativo, 0.6)

    assert [(l["quem"], l["texto"]) for l in tela.transcricao] == [  # noqa: E741
        ("dono", "que horas são em Lisboa?"),
        ("jarvis", "Em Lisboa são quatro da tarde."),
        ("dono", "e em Tóquio?"),
        ("jarvis", "Em Tóquio já é meia-noite."),
    ]
    botao = cast(Any, janela.rootObject()).findChild(QObject, "botaoNovaConversa")
    assert botao is not None and botao.property("visible") is True
    TELAS.mkdir(parents=True, exist_ok=True)
    assert janela.grabWindow().save(str(TELAS / "reaberta-com-a-conversa.png"))

    tela.novaConversa()
    _esperar(aplicativo, 0.4)

    assert tela.transcricao == []
    assert botao.property("visible") is False
    assert janela.grabWindow().save(str(TELAS / "depois-de-nova-conversa.png"))
    conversa.fechar()
    assert _conversa(raiz).recentes() == [], (
        "fechar e reabrir depois de recomeçar não traz a antiga"
    )


def test_sem_historico_a_janela_abre_vazia_como_sempre(
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    ponte = Ponte(
        raiz=tmp_path / "sessao",
        configuracao=CONFIGURACAO,
        caminho_da_configuracao=tmp_path / "jarvis-voz.toml",
    )

    abrir(ponte)

    assert cast(Any, ponte).transcricao == []
