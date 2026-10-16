import QtQuick
import JarvisUI

// Console e código: monoespaçado, numerado quando é código, com cursor na última linha.
ListView {
    id: lista
    property var dados: ({})
    property bool numerar: false
    model: dados.linhas || []
    clip: true
    spacing: 2
    boundsBehavior: Flickable.StopAtBounds

    delegate: Row {
        width: lista.width
        spacing: 12
        Text {
            textFormat: Text.PlainText
            text: String(index + 1).padStart(2, "0")
            color: Tema.linhaClara
            font.family: Tema.fonteDados
            font.pixelSize: Tema.tamanhoTexto - 2
            visible: lista.numerar
            renderType: Text.NativeRendering
        }
        Text {
            textFormat: Text.PlainText
            width: lista.width - (lista.numerar ? 36 : 0)
            text: modelData
            color: index === lista.count - 1 ? Tema.textoForte : Tema.texto
            font.family: Tema.fonteDados
            font.pixelSize: Tema.tamanhoTexto - 2
            elide: Text.ElideRight
            renderType: Text.NativeRendering
        }
    }
}
