import QtQuick
import JarvisUI

// Uma frase de explicação: caixa normal, pequena, quebrando linha. Caixa alta é para rótulo
// curto (`Rotulo`); frase inteira em maiúsculas espaçadas cansa a leitura e grita.
Text {
    textFormat: Text.PlainText
    property bool alerta: false
    color: alerta ? Tema.alerta : Tema.textoFraco
    font.pixelSize: Tema.tamanhoTexto - 2
    lineHeight: 1.2
    wrapMode: Text.WordWrap
    renderType: Text.NativeRendering
}
