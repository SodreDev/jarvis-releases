import QtQuick
import JarvisUI

// O conteúdo que o Jarvis montou (ADR-0055): lista, tabela, resumo, comparativo. É a ÚNICA vista
// com texto rico (test_texto_puro cobra): o HTML chega só pelo campo `html` do componente
// `conteudo`, que `componentes.validar_dados` limpa de novo pela allowlist de `jarvis.tela` e
// confere que nada aponta para fora (o texto rico busca `<img src>` e `url()` na rede: medido). O
// Qt desenha o subconjunto dele (QTextDocument), sem motor de script; link nenhum é seguido (o
// `<a>` já virou texto, e esta vista não trata clique em link).
Item {
    id: vista
    property var dados: ({})

    Rectangle {
        // O fundo que o conteúdo pediu (o tema claro, se o dono quis); sem pedido, o do módulo.
        anchors.fill: parent
        color: vista.dados.fundo || "transparent"
        radius: Tema.raioModulo
    }

    Flickable {
        id: rolagem
        anchors.fill: parent
        anchors.margins: vista.dados.fundo ? 12 : 0
        anchors.rightMargin: (vista.dados.fundo ? 12 : 0) + 8
        contentHeight: conteudo.paintedHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Text {
            id: conteudo
            objectName: "conteudoDaTela"
            textFormat: Text.RichText
            width: rolagem.width
            text: vista.dados.html || ""
            color: Tema.texto
            font.pixelSize: Tema.tamanhoTexto + 1
            wrapMode: Text.Wrap
            renderType: Text.NativeRendering
        }
    }

    IndicadorDeRolagem {
        alvo: rolagem
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: parent.right
    }
}
