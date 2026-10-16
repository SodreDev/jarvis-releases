import QtQuick
import JarvisUI

// Os indicadores do topo: relógio, data e as medidas desta máquina (lidas de /proc).
Row {
    id: indicadores
    property var medidas: []
    spacing: 26

    Repeater {
        model: indicadores.medidas
        Column {
            spacing: 5
            Row {
                spacing: 8
                Rotulo { text: modelData.rotulo }
                Rotulo { text: modelData.detalhe; color: Tema.texto }
            }
            Rectangle {
                width: 92; height: 2
                color: Tema.linha
                Rectangle {
                    width: parent.width * Math.min(1, Math.max(0, modelData.fracao))
                    height: parent.height
                    color: modelData.fracao > 0.85 ? Tema.alerta : Tema.cianoFraco
                    Behavior on width { NumberAnimation { duration: 420 } }
                }
            }
        }
    }
}
