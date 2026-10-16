import QtQuick
import JarvisUI

// Diagnóstico: o que o `--diagnostico` mostra, mais os dois testes que só o dono pode fazer.
Item {
    id: vista
    property var dados: ({})

    Row {
        id: botoes
        spacing: 10
        Botao { texto: "rodar diagnóstico"; onApertado: ponte.rodarDiagnostico() }
        Botao { texto: "testar microfone"; onApertado: ponte.testarMicrofone() }
        Botao { texto: "testar voz"; onApertado: ponte.testarVoz() }
        Botao {
            // O peso da voz não vem no pacote: o botão só existe quando falta baixar, e o
            // texto já diz quanto pesa — ninguém começa um download sem saber o tamanho.
            visible: ponte && ponte.vozFaltando !== ""
            texto: "baixar a voz"
            onApertado: ponte.baixarVoz()
        }
    }

    Rotulo {
        anchors.top: botoes.bottom
        anchors.topMargin: 10
        width: parent.width
        text: ponte ? ponte.vozFaltando : ""
        color: Tema.alerta
        visible: text !== ""
    }

    Rectangle {
        id: barra
        anchors.top: botoes.bottom
        anchors.topMargin: 34
        width: parent.width
        height: 2
        color: Tema.linha
        Rectangle {
            width: parent.width * (ponte ? ponte.nivel : 0)
            height: parent.height
            color: Tema.ciano
            Behavior on width { NumberAnimation { duration: 90 } }
        }
    }

    Flickable {
        anchors.top: barra.bottom
        anchors.topMargin: 14
        anchors.bottom: licenca.top
        anchors.bottomMargin: 12
        width: parent.width
        contentHeight: saida.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Text {
            textFormat: Text.PlainText
            id: saida
            width: parent.width
            text: ponte && ponte.diagnostico !== "" ? ponte.diagnostico
                  : "aperte “rodar diagnóstico” para ver motores, chaves, dispositivos e o que falta."
            color: Tema.texto
            font.family: Tema.fonteDados
            font.pixelSize: Tema.tamanhoTexto - 2
            wrapMode: Text.WrapAnywhere
            renderType: Text.NativeRendering
        }
    }

    Text {
        textFormat: Text.PlainText
        id: licenca
        anchors.bottom: parent.bottom
        width: parent.width
        text: vista.dados.licenca || ""
        color: Tema.textoFraco
        font.pixelSize: Tema.tamanhoRotulo + 1
        wrapMode: Text.WordWrap
        renderType: Text.NativeRendering
    }
}
