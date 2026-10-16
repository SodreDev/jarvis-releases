import QtQuick
import JarvisUI

// Botão sem cara de botão: moldura de 1 px, texto pequeno, realce só no ciano da borda.
Rectangle {
    id: botao
    property alias texto: rotulo.text
    property bool ativo: false
    signal apertado()
    signal solto()

    implicitWidth: rotulo.implicitWidth + 28
    implicitHeight: 30
    radius: Tema.raioModulo
    color: area.pressed || ativo ? Qt.rgba(0.22, 0.78, 0.91, 0.10) : "transparent"
    border.width: 1
    border.color: area.containsMouse || ativo ? Tema.cianoFraco : Tema.linha
    Behavior on border.color { ColorAnimation { duration: 120 } }

    Text {
        id: rotulo
        anchors.centerIn: parent
        color: botao.ativo ? Tema.textoForte : Tema.texto
        font.pixelSize: Tema.tamanhoRotulo + 1
        font.letterSpacing: Tema.espacoEntreLetras
        font.capitalization: Font.AllUppercase
        renderType: Text.NativeRendering
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        onPressed: botao.apertado()
        onReleased: botao.solto()
    }
}
