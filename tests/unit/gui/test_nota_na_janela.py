"""ADR-0063: o 👍/👎 na janela real (QML offscreen) — só na última resposta do Jarvis, só com um
turno para avaliar, e o botão aceso é a nota que vale. Sem microfone: a sessão é falsa."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
pytest.importorskip("PySide6", reason="a janela precisa do grupo `gui`")

from PySide6.QtGui import QGuiApplication
from PySide6.QtQuick import QQuickView

from jarvis.gui.ponte import Ponte
from tests.unit.gui.test_conversa_na_janela import _conversa, _gravar_conversa_anterior, _ponte
from tests.unit.gui.test_janela import (  # noqa: F401 — fixtures
    abrir,
    aplicativo,
    sem_chaveiro,
)
from tests.unit.gui.test_ponte_cerebro import _esperar
from tests.unit.gui.test_tarefas_na_janela import _itens_da_tela


class SessaoFalsa:
    """O que a ponte pergunta à sessão de voz, sem laço nem áudio."""

    viva = False
    modo_texto = True

    def __init__(self) -> None:
        self.notas: list[bool] = []
        self.turno = ""

    def estado_do_microfone(self) -> None:
        return None

    def nota_do_turno(self) -> dict[str, Any]:
        if not self.turno:
            return {"pode": False, "nota": ""}
        return {"pode": True, "nota": ("boa" if self.notas[-1] else "ruim") if self.notas else ""}

    def anotar_turno(self, boa: bool) -> bool:
        self.notas.append(boa)
        return True


def _botoes(janela: QQuickView) -> tuple[Any, Any]:
    raiz = janela.rootObject()
    boa = [b for b in _itens_da_tela(raiz, "notaBoa") if b.isVisible()]
    ruim = [b for b in _itens_da_tela(raiz, "notaRuim") if b.isVisible()]
    return (boa[0] if boa else None), (ruim[0] if ruim else None)


def test_o_polegar_aparece_na_ultima_resposta_e_acende_a_nota_que_vale(
    aplicativo: QGuiApplication,  # noqa: F811
    abrir: Callable[[Ponte], QQuickView],  # noqa: F811
    tmp_path: Path,
    sem_chaveiro: None,  # noqa: F811
) -> None:
    raiz = tmp_path / "sessao"
    _gravar_conversa_anterior(raiz)
    conversa = _conversa(raiz)
    ponte = _ponte(tmp_path, conversa)
    tela = cast(Any, ponte)
    sessao = SessaoFalsa()
    ponte._sessao = cast(Any, sessao)
    janela = abrir(ponte)
    janela.show()
    # O módulo da transcrição, pela proposta de sempre do workspace.
    ponte._espaco.propor(
        {"tipo": "createWidget", "componente": "conversa", "motivo": "teste", "dados": {}}
    )
    ponte._publicar()
    _esperar(aplicativo, 0.5)
    assert _itens_da_tela(janela.rootObject(), "notaBoa"), "a conversa abriu"

    assert _botoes(janela) == (None, None), "sem turno nesta sessão, não há o que avaliar"

    sessao.turno = "t-1"
    tela.conversaMudou.emit()
    _esperar(aplicativo, 0.3)
    boa, ruim = _botoes(janela)
    assert boa is not None and ruim is not None, "o polegar fica na última resposta"
    assert boa.property("ativo") is False and ruim.property("ativo") is False

    tela.notarTurno(False)
    _esperar(aplicativo, 0.3)
    assert sessao.notas == [False] and ruim.property("ativo") is True

    tela.notarTurno(True)
    _esperar(aplicativo, 0.3)
    assert boa.property("ativo") is True and ruim.property("ativo") is False
    conversa.fechar()
