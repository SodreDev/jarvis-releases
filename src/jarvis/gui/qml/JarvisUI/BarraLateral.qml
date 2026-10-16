import QtQuick
import JarvisUI

// A barra lateral fica escondida: 56 px de ícones, 200 px com o ponteiro em cima (ou Ctrl+B).
//
// É o pedido do dono — "barra lateral escondida, expande com mouse ou atalho" — e tem um
// motivo além do gosto: espaço vazio é o que faz o núcleo central ser o assunto da tela.
Rectangle {
    id: barra
    property bool presa: false
    property string modo: "assistente"
    // `semPonteiro` é declarado por quem sabe que não há mouse nenhum (a captura offscreen):
    // sem ele, a barra "escondida" aparece **aberta** no retrato, porque o Qt considera o
    // ponteiro parado em cima dela. Fixar com Ctrl+B continua valendo em qualquer caso.
    property bool semPonteiro: false
    readonly property bool aberta: presa || (!semPonteiro && area.containsMouse)
    property var entradas: [
        { chave: "assistente", glifo: "◎", rotulo: "assistente" },
        { chave: "pesquisa", glifo: "⌕", rotulo: "pesquisa" },
        { chave: "execucao", glifo: "▦", rotulo: "execução" },
        { chave: "configuracao", glifo: "⚙", rotulo: "provedores" },
        { chave: "diagnostico", glifo: "⏿", rotulo: "diagnóstico" }
    ]
    signal escolhido(string chave)

    width: aberta ? 196 : 56
    Behavior on width { NumberAnimation { duration: Tema.duracao; easing.type: Easing.OutCubic } }
    color: Tema.fundoProfundo

    Rectangle {
        anchors.right: parent.right
        width: 1; height: parent.height
        color: Tema.linha
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
    }

    Column {
        anchors.top: parent.top
        anchors.topMargin: 26
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 6

        Repeater {
            model: barra.entradas
            Item {
                width: barra.width
                height: 46
                readonly property bool atual: modelData.chave === barra.modo
                Rectangle {
                    anchors.left: parent.left
                    width: 2; height: parent.height
                    color: atual ? Tema.ciano : "transparent"
                }
                Text {
                    textFormat: Text.PlainText
                    x: 20
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.glifo
                    color: atual ? Tema.ciano : (linha.containsMouse ? Tema.texto : Tema.textoFraco)
                    font.pixelSize: 15
                    renderType: Text.NativeRendering
                }
                Rotulo {
                    x: 56
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.rotulo
                    color: atual ? Tema.texto : Tema.textoFraco
                    opacity: barra.aberta ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 160 } }
                }
                MouseArea {
                    id: linha
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: barra.escolhido(modelData.chave)
                }
            }
        }
    }

    Rotulo {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 20
        anchors.horizontalCenter: parent.horizontalCenter
        text: barra.aberta ? "ctrl+b fixa a barra" : ""
        opacity: barra.aberta ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 160 } }
    }
}
