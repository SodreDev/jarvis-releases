import QtQuick
import JarvisUI

// Resultados com mídia: o primeiro item manda, os outros viram linha. Sem grade fixa — a
// composição segue a importância, que é o que o dono pediu para o modo de pesquisa.
Flickable {
    id: vista
    property var dados: ({})
    readonly property var itens: dados.itens || []
    contentHeight: coluna.height
    clip: true
    boundsBehavior: Flickable.StopAtBounds

    Column {
        id: coluna
        width: vista.width
        spacing: 14

        // destaque
        Column {
            width: parent.width
            spacing: 10
            visible: vista.itens.length > 0
            Rectangle {
                width: parent.width
                height: Math.min(170, vista.height * 0.42)
                color: "#060b11"
                border.width: 1
                border.color: Tema.linha
                Image {
                    anchors.fill: parent
                    fillMode: Image.PreserveAspectCrop
                    source: vista.itens.length && vista.itens[0].imagem ? "file://" + vista.itens[0].imagem : ""
                    visible: status === Image.Ready
                }
                // sem imagem de verdade: um alvo técnico, nunca uma foto inventada
                Item {
                    anchors.fill: parent
                    visible: !(vista.itens.length && vista.itens[0].imagem)
                    Rectangle { anchors.centerIn: parent; width: 54; height: 1; color: Tema.linhaForte }
                    Rectangle { anchors.centerIn: parent; width: 1; height: 54; color: Tema.linhaForte }
                    Rectangle {
                        anchors.centerIn: parent
                        width: 54; height: 54; radius: 27
                        color: "transparent"; border.width: 1; border.color: Tema.cianoFraco
                    }
                    Rotulo {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.verticalCenter
                        anchors.topMargin: 38
                        text: "mídia"
                    }
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: vista.itens.length ? (vista.itens[0].titulo || "") : ""
                color: Tema.textoForte
                font.pixelSize: Tema.tamanhoTexto + 3
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: vista.itens.length ? (vista.itens[0].detalhe || "") : ""
                color: Tema.textoFraco
                font.pixelSize: Tema.tamanhoTexto - 1
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Row {
                spacing: 8
                Rotulo { text: vista.itens.length ? (vista.itens[0].fonte || "") : ""; destaque: true }
                Rotulo { text: vista.itens.length ? (vista.itens[0].instante || "") : "" }
            }
        }

        Rectangle { width: parent.width; height: 1; color: Tema.linha; visible: vista.itens.length > 1 }

        Repeater {
            model: vista.itens.length > 1 ? vista.itens.slice(1) : []
            Column {
                width: coluna.width
                spacing: 4
                Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: modelData.titulo || ""
                    color: Tema.texto
                    font.pixelSize: Tema.tamanhoTexto - 1
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    renderType: Text.NativeRendering
                }
                Text {
                    textFormat: Text.PlainText
                    width: parent.width
                    text: modelData.detalhe || ""
                    color: Tema.textoFraco
                    font.pixelSize: Tema.tamanhoRotulo + 1
                    wrapMode: Text.WordWrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    visible: text !== ""
                    renderType: Text.NativeRendering
                }
                Row {
                    spacing: 8
                    Rotulo { text: modelData.fonte || ""; destaque: true }
                    Rotulo { text: modelData.instante || "" }
                }
            }
        }
    }
}
