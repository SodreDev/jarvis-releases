import QtQuick
import JarvisUI

// A moldura dos módulos: fundo quase preto, 1 px de linha e cantos marcados em ciano.
//
// Os quatro cantos são o que dá a cara técnica sem borda grossa, sombra ou brilho — e é o que
// a referência mostra. Nada de cartão com raio grande: isto não é um painel de SaaS.
Rectangle {
    id: moldura
    property color corDoCanto: Tema.cianoFraco
    property int tamanhoDoCanto: 10
    property bool realce: false

    color: Tema.fundoModulo
    opacity: 0.97
    radius: Tema.raioModulo
    border.width: 1
    border.color: realce ? Tema.cianoFraco : Tema.linha
    Behavior on border.color { ColorAnimation { duration: 160 } }

    Repeater {
        model: [[0, 0, 1, 1], [1, 0, -1, 1], [0, 1, 1, -1], [1, 1, -1, -1]]
        Item {
            readonly property var canto: modelData
            x: canto[0] === 0 ? 0 : moldura.width
            y: canto[1] === 0 ? 0 : moldura.height
            Rectangle {
                width: moldura.tamanhoDoCanto; height: 1
                color: moldura.corDoCanto
                x: canto[2] > 0 ? 0 : -width
                y: canto[3] > 0 ? 0 : -1
            }
            Rectangle {
                width: 1; height: moldura.tamanhoDoCanto
                color: moldura.corDoCanto
                x: canto[2] > 0 ? 0 : -1
                y: canto[3] > 0 ? 0 : -height
            }
        }
    }
}
