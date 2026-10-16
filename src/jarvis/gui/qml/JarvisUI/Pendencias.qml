import QtQuick
import JarvisUI

// Confirmação: nada que encoste na máquina do dono entra sem ele dizer que sim (SPEC §5.4).
Column {
    id: faixa
    property var pendentes: []
    spacing: 8
    visible: pendentes.length > 0

    Repeater {
        model: faixa.pendentes
        Rectangle {
            width: faixa.width
            height: 46
            color: Qt.rgba(0.88, 0.64, 0.29, 0.06)
            border.width: 1
            border.color: Tema.alerta
            radius: Tema.raioModulo

            Row {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                anchors.right: botoes.left
                anchors.rightMargin: 16
                spacing: 12
                Rotulo {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "confirmar"
                    color: Tema.alerta
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - 120
                    text: modelData.motivo
                    color: Tema.texto
                    font.pixelSize: Tema.tamanhoTexto - 2
                    elide: Text.ElideRight
                    renderType: Text.NativeRendering
                }
            }
            Row {
                id: botoes
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                Botao { texto: "permitir"; onApertado: ponte.responderPendencia(modelData.id, true) }
                Botao { texto: "não"; onApertado: ponte.responderPendencia(modelData.id, false) }
            }
        }
    }
}
