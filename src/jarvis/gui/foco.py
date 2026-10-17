"""O foco do teclado volta para a tela a cada clique — é a tela que ouve o atalho de falar.

Bug do dono (2026-10-16): um clique no campo de texto prendia o foco nele, e a barra de espaço
passava a digitar; um clique num módulo (que aceita o clique) não devolvia nada. Um
`MouseArea` de fundo no QML não resolve, porque o módulo aceita o clique antes dele. Este filtro
fica na **janela**: a cada aperto de botão, devolve o foco ao item raiz **antes** de o clique
ser entregue; se o clique for no campo, o próprio campo pega o foco de volta no mesmo clique.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtQuick import QQuickView


class FocoNaTela(QObject):
    def __init__(self, janela: QQuickView) -> None:
        super().__init__(janela)
        self._janela = janela

    def eventFilter(self, alvo: QObject, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.MouseButtonPress:
            raiz = self._janela.rootObject()
            if raiz is not None:
                raiz.forceActiveFocus()
        return False


def ligar(janela: QQuickView) -> FocoNaTela:
    filtro = FocoNaTela(janela)
    janela.installEventFilter(filtro)
    return filtro
