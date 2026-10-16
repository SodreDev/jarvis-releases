import QtQuick
import JarvisUI

// Tarefas: visto × em execução × resultado, que é a distinção que o dono pediu para enxergar.
ListView {
    id: lista
    property var dados: ({})
    model: dados.itens || []
    clip: true
    spacing: 0
    boundsBehavior: Flickable.StopAtBounds

    delegate: Item {
        width: lista.width
        height: 40
        readonly property string estado: modelData.estado || "visto"
        Rectangle {
            id: marca
            anchors.verticalCenter: parent.verticalCenter
            width: 14; height: 14; radius: 2
            color: "transparent"
            border.width: 1
            border.color: estado === "resultado" ? Tema.positivo
                        : estado === "executando" ? Tema.alerta : Tema.linhaForte
            Text {
                anchors.centerIn: parent
                text: estado === "resultado" ? "✓" : estado === "executando" ? "›" : ""
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
            anchors.right: parent.right
            spacing: 2
            Text {
                width: parent.width
                text: modelData.titulo || ""
                color: estado === "espera" ? Tema.textoFraco : Tema.texto
                font.pixelSize: Tema.tamanhoTexto - 1
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
            Rotulo { text: modelData.detalhe || ""; visible: text !== "" }
        }
    }
}
