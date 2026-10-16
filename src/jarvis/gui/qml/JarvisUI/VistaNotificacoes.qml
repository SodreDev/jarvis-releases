import QtQuick
import JarvisUI

// O card de notificações (ADR-0025): o que chegou, de onde, e o que foi feito do aviso.
//
// Três coisas de cada aviso, nesta ordem de leitura: o tipo (uma marca e uma palavra — "pede
// decisão" é o único em âmbar, porque é o único que espera o dono), o resumo, e embaixo a
// origem, quando chegou e a entrega (na fila, falado, só card, calado). Aviso calado pelo
// modelo continua aqui: nada some sem rastro. Conteúdo de tarefa é de terceiros e a linha diz.
ListView {
    id: lista
    property var dados: ({})
    model: dados.avisos || []
    clip: true
    spacing: 0
    boundsBehavior: Flickable.StopAtBounds

    readonly property var nomeDoTipo: ({
        "precisa_decisao": "pede decisão",
        "falhou": "falhou",
        "concluida": "concluída",
        "evento": "evento"
    })
    readonly property var nomeDaEntrega: ({
        "na_fila": "na fila para falar",
        "falado": "falado",
        "so_card": "só no card",
        "calado": "calado — continua aqui"
    })

    function corDoTipo(tipo) {
        return tipo === "precisa_decisao" ? Tema.alerta
             : tipo === "concluida" ? Tema.positivo
             : tipo === "falhou" ? Tema.texto
             : Tema.cianoFraco
    }

    delegate: Item {
        width: lista.width
        height: corpo.implicitHeight + 18

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: Tema.linha
            visible: index < lista.count - 1
        }
        // A marca do tipo: traço de 2 px à esquerda, na cor do tipo. Sem preenchimento.
        Rectangle {
            x: 0
            y: 9
            width: 2
            height: corpo.implicitHeight
            color: lista.corDoTipo(modelData.tipo)
            opacity: modelData.tipo === "evento" ? 0.6 : 0.9
        }
        Column {
            id: corpo
            x: 12
            y: 9
            width: parent.width - 12
            spacing: 4
            Row {
                spacing: 8
                Rotulo {
                    text: lista.nomeDoTipo[modelData.tipo] || modelData.tipo
                    color: lista.corDoTipo(modelData.tipo)
                }
                Rotulo {
                    visible: modelData.confianca === "terceiros"
                    text: "conteúdo de terceiros"
                    color: Tema.textoFraco
                }
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: modelData.resumo || ""
                color: modelData.entrega === "calado" ? Tema.textoFraco : Tema.texto
                font.pixelSize: Tema.tamanhoTexto - 1
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: [modelData.origem || "", modelData.instante || "",
                       lista.nomeDaEntrega[modelData.entrega] || ""]
                      .filter(function (parte) { return parte !== "" }).join("  ·  ")
                color: Tema.textoFraco
                font.pixelSize: Tema.tamanhoRotulo + 1
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
        }
    }
}
