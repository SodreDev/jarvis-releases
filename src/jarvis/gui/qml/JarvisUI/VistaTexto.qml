import QtQuick
import JarvisUI

// Texto com tópicos: o resumo do Jarvis. Traço fino no lugar de marcador redondo.
Flickable {
    id: vista
    property var dados: ({})
    contentHeight: coluna.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
        id: coluna
        width: vista.width
        spacing: 14
        Text {
            textFormat: Text.PlainText
            width: parent.width
            text: vista.dados.texto || ""
            color: Tema.texto
            font.pixelSize: Tema.tamanhoTexto
            lineHeight: 1.35
            wrapMode: Text.WordWrap
            visible: text !== ""
            renderType: Text.NativeRendering
        }
        Repeater {
            model: vista.dados.topicos || []
            Row {
                width: coluna.width
                spacing: 10
                Rectangle {
                    width: 10; height: 1
                    color: Tema.ciano
                    anchors.verticalCenter: undefined
                    y: 9
                }
                Text {
                    textFormat: Text.PlainText
                    width: coluna.width - 20
                    text: modelData
                    color: Tema.textoFraco
                    font.pixelSize: Tema.tamanhoTexto - 1
                    wrapMode: Text.WordWrap
                    renderType: Text.NativeRendering
                }
            }
        }
    }
}
