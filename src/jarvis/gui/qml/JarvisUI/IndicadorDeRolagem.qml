import QtQuick
import JarvisUI

// Diz que há mais conteúdo, e onde se está nele: um trilho de 1 px e um cursor de 2 px na
// borda direita. Some quando tudo cabe. Sem barra de rolagem de formulário, sem sombra.
Item {
    id: indicador
    property Flickable alvo
    readonly property bool necessario: alvo && alvo.contentHeight > alvo.height + 1
    width: 3
    visible: necessario

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: 1
        height: parent.height
        color: Tema.linha
    }
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        width: 2
        radius: 1
        color: Tema.cianoFraco
        height: indicador.alvo
                ? Math.max(24, parent.height * indicador.alvo.height / indicador.alvo.contentHeight)
                : 0
        y: indicador.alvo && indicador.alvo.contentHeight > indicador.alvo.height
           ? (parent.height - height) * indicador.alvo.contentY
             / (indicador.alvo.contentHeight - indicador.alvo.height)
           : 0
    }
}
