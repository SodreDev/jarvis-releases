import QtQuick
import JarvisUI

// A conversa, compacta, na base da tela: campo de texto e microfone. Nada de caixa de chat.
Item {
    id: barra
    property bool conversaViva: false
    property string estado: "parado"
    property var microfone: ({})
    property string atalho: ""
    signal enviou(string texto)
    signal segurou()
    signal soltou()
    signal parou()
    signal comecou()

    implicitHeight: 54

    Rectangle {
        anchors.fill: parent
        color: Tema.fundoModulo
        opacity: 0.97
        radius: Tema.raioModulo
        border.width: 1
        border.color: campo.activeFocus ? Tema.cianoFraco : Tema.linha
        Behavior on border.color { ColorAnimation { duration: 140 } }
    }

    Rectangle {
        id: marcaDoMicrofone
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        width: 6; height: 6; radius: 3
        // Armado (ele disse só o nome) acende em âmbar: o próximo trecho já é pedido.
        color: barra.microfone.armado ? Tema.alerta
               : barra.microfone.aberta ? Tema.ciano : Tema.linhaForte
        SequentialAnimation on opacity {
            running: barra.microfone.aberta === true
            loops: Animation.Infinite
            NumberAnimation { from: 1; to: 0.35; duration: 900 }
            NumberAnimation { from: 0.35; to: 1; duration: 900 }
        }
    }

    TextInput {
        id: campo
        anchors.left: marcaDoMicrofone.right
        anchors.leftMargin: 16
        anchors.right: estadoDoMicrofone.left
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        color: Tema.texto
        font.pixelSize: Tema.tamanhoTexto
        selectByMouse: true
        clip: true
        onAccepted: {
            if (text.trim() !== "") {
                barra.enviou(text)
                text = ""
            }
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            // O que o Jarvis está esperando para ouvir, do estado vivo da escuta (ADR-0021).
            text: !barra.conversaViva ? "escreva para começar — ou aperte “falar”"
                  : barra.microfone.modo === "ptt"
                    ? "segure " + (barra.atalho !== "" ? barra.atalho : "a barra de espaço")
                      + " para falar, ou escreva aqui"
                    : (barra.microfone.escuta || "") + " — ou escreva aqui"
            color: Tema.textoFraco
            font.pixelSize: Tema.tamanhoTexto - 1
            visible: campo.text === ""
            renderType: Text.NativeRendering
        }
    }

    // O indicador por extenso: a fonte como ela está (F1-13) e quando o que ela ouve vira
    // pedido (ADR-0021). Sempre à vista, com ou sem conversa aberta.
    Rotulo {
        id: estadoDoMicrofone
        anchors.right: acoes.left
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        text: (barra.microfone.frase || "microfone fechado")
              + (barra.microfone.armado ? " · chamado: pode falar"
                 : barra.microfone.modoFrase ? " · " + barra.microfone.modoFrase : "")
        color: barra.microfone.armado ? Tema.alerta
               : barra.microfone.aberta ? Tema.ciano : Tema.textoFraco
    }

    Row {
        id: acoes
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10

        Botao {
            texto: barra.estado === "falando" ? "interromper" : "falar"
            ativo: barra.microfone.aberta === true && barra.estado === "ouvindo"
            onApertado: { if (!barra.conversaViva) barra.comecou(); barra.segurou() }
            onSolto: barra.soltou()
        }
        Botao {
            texto: barra.conversaViva ? "encerrar" : "começar"
            onApertado: barra.conversaViva ? barra.parou() : barra.comecou()
        }
    }
}
