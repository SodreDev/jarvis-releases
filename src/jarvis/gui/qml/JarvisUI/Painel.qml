import QtQuick
import JarvisUI

// Um módulo **dentro** de um módulo: mesma moldura, mesmos cantos, mesma linha de cabeçalho.
//
// Existe para que a tela de provedores não seja uma pilha de linhas de mesmo peso: cada
// assunto ganha a sua caixa, com o mesmo vocabulário visual do resto da janela.
Item {
    id: painel
    property alias titulo: rotulo.text
    property string dica: ""
    default property alias conteudo: area.data

    implicitHeight: area.childrenRect.height + cabecalho.height + 26

    Moldura {
        anchors.fill: parent
        corDoCanto: Tema.linhaForte
        tamanhoDoCanto: 7
    }

    Item {
        id: cabecalho
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: 28

        Rotulo {
            id: rotulo
            anchors.left: parent.left
            anchors.leftMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            color: Tema.texto
        }
        Rotulo {
            anchors.right: parent.right
            anchors.rightMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            text: painel.dica
            visible: text !== ""
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Tema.linha
        }
    }

    Item {
        id: area
        anchors.top: cabecalho.bottom
        anchors.topMargin: 12
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        anchors.bottomMargin: 12
    }
}
