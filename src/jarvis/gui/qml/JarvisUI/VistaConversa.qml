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

    // A nota do dono (ADR-0063): 👍/👎 só na última resposta do Jarvis, depois do turno acabar.
    // O botão aceso é a nota que vale; nada é treinado com ela.
    readonly property var nota: ponte ? ponte.notaDoTurno : ({})

    delegate: Row {
        id: linha
        width: lista.width
        spacing: 12
        readonly property bool comNota: index === lista.count - 1 && modelData.quem !== "dono"
                                        && lista.nota.pode === true
        Rotulo {
            width: 52
            text: modelData.quem === "dono" ? "você" : "jarvis"
            destaque: modelData.quem !== "dono"
        }
        Text {
            textFormat: Text.PlainText
            width: lista.width - 64 - (linha.comNota ? notas.width + 12 : 0)
            text: modelData.texto
            color: modelData.quem === "dono" ? Tema.texto : Tema.textoForte
            font.pixelSize: Tema.tamanhoTexto - 1
            wrapMode: Text.WordWrap
            renderType: Text.NativeRendering
        }
        Row {
            id: notas
            visible: linha.comNota
            spacing: 6
            Botao {
                objectName: "notaBoa"
                texto: "👍"
                ativo: lista.nota.nota === "boa"
                onApertado: ponte.notarTurno(true)
            }
            Botao {
                objectName: "notaRuim"
                texto: "👎"
                ativo: lista.nota.nota === "ruim"
                onApertado: ponte.notarTurno(false)
            }
        }
    }
}
