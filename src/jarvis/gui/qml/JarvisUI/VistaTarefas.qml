import QtQuick
import JarvisUI

// Tarefas: visto × em execução × resultado, que é a distinção que o dono pediu para enxergar.
// As tarefas em segundo plano (ADR-0022) trazem `id` e `progresso`: ganham a barra e o "parar".
ListView {
    id: lista
    property var dados: ({})
    model: dados.itens || []
    clip: true
    spacing: 0
    boundsBehavior: Flickable.StopAtBounds

    delegate: Item {
        width: lista.width
        height: temProgresso ? 52 : 40
        readonly property string estado: modelData.estado || "visto"
        readonly property bool temProgresso: (modelData.progresso || "") !== ""
        readonly property bool podeParar: (modelData.id || "") !== ""
                                          && (estado === "executando" || estado === "espera")
        readonly property color corDoEstado: estado === "resultado" ? Tema.positivo
                                           : estado === "executando" ? Tema.alerta
                                           : estado === "falhou" ? Tema.perigo
                                           : Tema.linhaForte
        Rectangle {
            id: marca
            anchors.verticalCenter: parent.verticalCenter
            width: 14; height: 14; radius: 2
            color: "transparent"
            border.width: 1
            border.color: corDoEstado
            Text {
                textFormat: Text.PlainText
                anchors.centerIn: parent
                text: estado === "resultado" ? "✓" : estado === "executando" ? "›"
                      : estado === "falhou" ? "×" : estado === "cancelada" ? "–" : ""
                color: parent.border.color
                font.pixelSize: 11
                renderType: Text.NativeRendering
            }
            SequentialAnimation on opacity {
                running: estado === "executando"
                loops: Animation.Infinite
                NumberAnimation { from: 1; to: 0.4; duration: 800 }
                NumberAnimation { from: 0.4; to: 1; duration: 800 }
            }
        }
        Column {
            anchors.left: marca.right
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            anchors.right: pararTarefa.visible ? pararTarefa.left : parent.right
            anchors.rightMargin: pararTarefa.visible ? 10 : 0
            spacing: 3
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: modelData.titulo || ""
                color: estado === "espera" ? Tema.textoFraco : Tema.texto
                font.pixelSize: Tema.tamanhoTexto - 1
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Rectangle {
                visible: temProgresso
                width: parent.width
                height: 3
                radius: 1
                color: Tema.linha
                Rectangle {
                    objectName: "barraDeProgresso"
                    width: parent.width * Math.max(0, Math.min(100, Number(modelData.progresso || 0))) / 100
                    height: parent.height
                    radius: 1
                    color: corDoEstado
                    Behavior on width { NumberAnimation { duration: 200 } }
                }
            }
            Rotulo {
                width: parent.width
                elide: Text.ElideRight
                text: modelData.detalhe || ""
                visible: text !== ""
            }
        }
        Botao {
            id: pararTarefa
            objectName: "pararTarefa"
            visible: podeParar
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            texto: "parar"
            onApertado: ponte.pararTarefa(modelData.id)
        }
    }
}
