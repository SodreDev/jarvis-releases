import QtQuick
import JarvisUI

// A transcrição: quem falou à esquerda, o que foi dito à direita. Sem balão, sem avatar.
ListView {
    id: lista
    property var dados: ({})
    model: ponte ? ponte.transcricao : []
    clip: true
    spacing: 10
    boundsBehavior: Flickable.StopAtBounds
    onCountChanged: positionViewAtEnd()

    delegate: Row {
        width: lista.width
        spacing: 12
        Rotulo {
            width: 52
            text: modelData.quem === "dono" ? "você" : "jarvis"
            destaque: modelData.quem !== "dono"
        }
        Text {
            textFormat: Text.PlainText
            width: lista.width - 64
            text: modelData.texto
            color: modelData.quem === "dono" ? Tema.texto : Tema.textoForte
            font.pixelSize: Tema.tamanhoTexto - 1
            wrapMode: Text.WordWrap
            renderType: Text.NativeRendering
        }
    }
}
