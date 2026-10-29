import QtQuick
import JarvisUI

// Um módulo flutuante: moldura técnica, cabeçalho de uma linha e a vista do componente.
//
// O dono manda nele: arrastar pelo cabeçalho move, o alfinete fixa (e aí a IA não mexe mais),
// o quadrado maximiza e o × fecha — fechar guarda, não apaga. Os botões só aparecem quando o
// ponteiro está em cima, para a tela parada não ter nada piscando.
Item {
    id: modulo
    property string widgetId: ""
    property string titulo: ""
    property string vista: "texto"
    property string estado: "visto"
    property var dados: ({})
    property bool fixado: false
    property bool foco: false
    property bool demonstracao: false
    property bool maximizado: false
    property real celulaLargura: 80
    property real celulaAltura: 80
    property int coluna: 0
    property int linha: 0

    Behavior on x { NumberAnimation { duration: Tema.duracao; easing.type: Easing.OutCubic } }
    Behavior on y { NumberAnimation { duration: Tema.duracao; easing.type: Easing.OutCubic } }
    Behavior on width { NumberAnimation { duration: Tema.duracao; easing.type: Easing.OutCubic } }
    Behavior on height { NumberAnimation { duration: Tema.duracao; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: 180 } }

    Moldura {
        id: moldura
        anchors.fill: parent
        realce: modulo.foco || area.containsMouse
        opacity: modulo.maximizado ? 1 : 0.97
    }

    Item {
        id: cabecalho
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: 30

        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            property real inicioX: 0
            property real inicioY: 0
            onPressed: function (evento) { inicioX = evento.x; inicioY = evento.y }
            onReleased: function (evento) {
                var dColuna = Math.round((evento.x - inicioX) / modulo.celulaLargura)
                var dLinha = Math.round((evento.y - inicioY) / modulo.celulaAltura)
                if (dColuna !== 0 || dLinha !== 0)
                    ponte.moverModulo(modulo.widgetId, modulo.coluna + dColuna, modulo.linha + dLinha)
            }
            onDoubleClicked: ponte.maximizarModulo(modulo.widgetId)
            cursorShape: Qt.OpenHandCursor
        }

        Row {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 9
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                width: 4; height: 4; radius: 2
                color: modulo.estado === "executando" ? Tema.alerta
                     : modulo.estado === "resultado" ? Tema.positivo : Tema.cianoFraco
                SequentialAnimation on opacity {
                    running: modulo.estado === "executando"
                    loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 0.3; duration: 750 }
                    NumberAnimation { from: 0.3; to: 1; duration: 750 }
                }
            }
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: modulo.titulo
                color: Tema.texto
            }
            Rectangle {
                anchors.verticalCenter: parent.verticalCenter
                visible: modulo.demonstracao
                width: selo.width + 10; height: 15
                color: "transparent"
                border.width: 1
                border.color: Tema.linhaForte
                Rotulo { id: selo; anchors.centerIn: parent; text: "demonstração" }
            }
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            opacity: area.containsMouse || botoes.containsMouse || modulo.fixado ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 140 } }

            MouseArea {
                id: botoes
                width: 0; height: 0
                hoverEnabled: true
            }
            Text {
                textFormat: Text.PlainText
                text: "✛"
                color: modulo.fixado ? Tema.ciano : Tema.textoFraco
                font.pixelSize: 12
                renderType: Text.NativeRendering
                MouseArea {
                    anchors.fill: parent; anchors.margins: -6
                    hoverEnabled: true
                    onClicked: ponte.fixarModulo(modulo.widgetId, !modulo.fixado)
                }
            }
            Text {
                textFormat: Text.PlainText
                text: modulo.maximizado ? "⤡" : "⤢"
                color: Tema.textoFraco
                font.pixelSize: 12
                renderType: Text.NativeRendering
                MouseArea {
                    anchors.fill: parent; anchors.margins: -6
                    onClicked: ponte.maximizarModulo(modulo.widgetId)
                }
            }
            Text {
                textFormat: Text.PlainText
                text: "✕"
                color: Tema.textoFraco
                font.pixelSize: 11
                renderType: Text.NativeRendering
                MouseArea {
                    anchors.fill: parent; anchors.margins: -6
                    onClicked: ponte.fecharModulo(modulo.widgetId)
                }
            }
        }

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Tema.linha
        }
    }

    Loader {
        anchors.top: cabecalho.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        anchors.topMargin: 12
        anchors.bottomMargin: 12
        clip: true
        sourceComponent: {
            switch (modulo.vista) {
            case "lista": return cLista
            case "notificacoes": return cNotificacoes
            case "itens_com_imagem": return cItens
            case "console": return cConsole
            case "tarefas": return cTarefas
            case "medidores": return cMedidores
            case "conversa": return cConversa
            case "configuracao": return cConfiguracao
            case "diagnostico": return cDiagnostico
            case "conteudo": return cConteudo
            default: return cTexto
            }
        }
    }

    Component { id: cLista; VistaLista { dados: modulo.dados } }
    Component { id: cNotificacoes; VistaNotificacoes { dados: modulo.dados } }
    Component { id: cItens; VistaItens { dados: modulo.dados } }
    Component { id: cTexto; VistaTexto { dados: modulo.dados } }
    Component { id: cConsole; VistaConsole { dados: modulo.dados; numerar: modulo.componenteCodigo } }
    Component { id: cTarefas; VistaTarefas { dados: modulo.dados } }
    Component { id: cMedidores; VistaMedidores { dados: modulo.dados } }
    Component { id: cConversa; VistaConversa { dados: modulo.dados } }
    Component { id: cConfiguracao; VistaConfiguracao { dados: modulo.dados } }
    Component { id: cDiagnostico; VistaDiagnostico { dados: modulo.dados } }
    Component { id: cConteudo; VistaConteudo { dados: modulo.dados } }

    property bool componenteCodigo: false
}
