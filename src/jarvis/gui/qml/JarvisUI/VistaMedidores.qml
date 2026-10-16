import QtQuick
import JarvisUI

// Medidores: barra fina, número à direita. Os valores vêm de /proc — medidos, não inventados.
Column {
    id: vista
    property var dados: ({})
    property var medidas: (dados.medidas && dados.medidas.length) ? dados.medidas : (ponte ? ponte.medidas : [])
    spacing: 14

    Repeater {
        model: vista.medidas
        Column {
            width: vista.width
            spacing: 6
            Row {
                width: parent.width
                Rotulo { text: modelData.rotulo; width: 52 }
                Item { width: parent.width - 52 - detalhe.width; height: 1 }
                Rotulo { id: detalhe; text: modelData.detalhe; color: Tema.texto }
            }
            Rectangle {
                width: parent.width
                height: 2
                color: Tema.linha
                Rectangle {
                    width: parent.width * Math.min(1, Math.max(0, modelData.fracao))
                    height: parent.height
                    color: modelData.fracao > 0.85 ? Tema.alerta : Tema.ciano
                    Behavior on width { NumberAnimation { duration: 420; easing.type: Easing.OutCubic } }
                }
            }
        }
    }
}
