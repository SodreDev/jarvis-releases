import QtQuick
import JarvisUI

// Lista densa: título, detalhe e um ponto de estado. É a vista de fontes, arquivos e avisos.
ListView {
    id: lista
    property var dados: ({})
    model: dados.itens || []
    clip: true
    spacing: 0
    boundsBehavior: Flickable.StopAtBounds

    delegate: Item {
        width: lista.width
        height: 44
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: Tema.linha
            visible: index < lista.count - 1
        }
        Rectangle {
            id: ponto
            anchors.verticalCenter: parent.verticalCenter
            x: 2
            width: 4; height: 4; radius: 2
            color: modelData.estado === "resultado" ? Tema.positivo
                 : modelData.estado === "executando" ? Tema.alerta
                 : Tema.cianoFraco
        }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: ponto.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            spacing: 3
            Text {
                width: parent.width
                text: modelData.titulo || ""
                color: Tema.texto
                font.pixelSize: Tema.tamanhoTexto - 1
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Text {
                width: parent.width
                text: modelData.detalhe || modelData.fonte || ""
                color: Tema.textoFraco
                font.pixelSize: Tema.tamanhoRotulo + 1
                elide: Text.ElideRight
                visible: text !== ""
                renderType: Text.NativeRendering
            }
        }
    }
}
