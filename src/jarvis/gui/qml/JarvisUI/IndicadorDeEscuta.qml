import QtQuick
import JarvisUI

// "Mic fechado · atalho de teclas": a fonte como ela **está** e quando o que ela ouve vira
// pedido. A marca acende em ciano só com a fonte aberta de verdade (o arquivo que o laço
// escreve, F1-13) e em âmbar quando a palavra de ativação armou a escuta (ADR-0021). Não há
// aqui booleano que a tela possa acender por conta própria.
Row {
    id: indicador
    property var microfone: ({})
    readonly property bool aberta: microfone.aberta === true
    readonly property bool armado: microfone.armado === true
    spacing: 7

    Rectangle {
        anchors.verticalCenter: parent.verticalCenter
        width: 5; height: 5; radius: 2.5
        color: indicador.armado ? Tema.alerta : indicador.aberta ? Tema.ciano : "transparent"
        border.width: 1
        border.color: indicador.armado ? Tema.alerta
                      : indicador.aberta ? Tema.ciano : Tema.textoFraco
    }
    Rotulo {
        anchors.verticalCenter: parent.verticalCenter
        text: (indicador.aberta ? "mic aberto" : "mic fechado")
              + (indicador.armado ? " · chamado"
                 : indicador.microfone.modoFrase ? " · " + indicador.microfone.modoFrase : "")
        color: indicador.armado ? Tema.alerta
               : indicador.aberta ? Tema.ciano : Tema.textoFraco
    }
}
