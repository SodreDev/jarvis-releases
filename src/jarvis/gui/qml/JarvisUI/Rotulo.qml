import QtQuick
import JarvisUI

// Rótulo técnico: caixa alta, pequeno, espaçado. É a tipografia da referência.
Text {
    property bool destaque: false
    color: destaque ? Tema.ciano : Tema.textoFraco
    font.pixelSize: Tema.tamanhoRotulo
    font.letterSpacing: Tema.espacoEntreLetras
    font.capitalization: Font.AllUppercase
    renderType: Text.NativeRendering
}
