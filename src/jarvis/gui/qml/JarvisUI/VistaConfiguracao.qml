import QtQuick
import JarvisUI

// Provedores e chaves como **módulo do workspace**, não como aba de formulário.
//
// Duas regras daqui, e nenhuma é de estilo: escolher um motor de nuvem **não** o liga (o aviso
// montado do registro aparece e o dono decide), e a chave de API só aparece como
// "definida/ausente" — o valor não é lido nem para desenhar esta tela.
Item {
    id: vista
    property var dados: ({})

    Flickable {
        id: rolagem
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: rodape.top
        anchors.bottomMargin: 14
        contentHeight: coluna.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds

    Column {
        id: coluna
        width: rolagem.width
        spacing: 18

        Repeater {
            model: [{ papel: "asr", titulo: "quem ouve" }, { papel: "tts", titulo: "quem fala" }]
            Column {
                width: coluna.width
                spacing: 8
                readonly property string papel: modelData.papel
                Rotulo { text: modelData.titulo; destaque: true }
                Repeater {
                    model: ponte ? ponte.motores.filter(function (m) { return m.papel === papel }) : []
                    Rectangle {
                        width: coluna.width
                        height: 38
                        color: modelData.escolhido ? Qt.rgba(0.22, 0.78, 0.91, 0.07) : "transparent"
                        border.width: 1
                        border.color: modelData.escolhido ? Tema.cianoFraco : Tema.linha
                        Row {
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 10
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.id
                                color: modelData.escolhido ? Tema.textoForte : Tema.texto
                                font.pixelSize: Tema.tamanhoTexto - 1
                                font.family: Tema.fonteDados
                                renderType: Text.NativeRendering
                            }
                            Rotulo {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.onde
                                color: modelData.onde === "nuvem" ? Tema.alerta : Tema.textoFraco
                            }
                            Rotulo {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.onde === "nuvem"
                                      ? (modelData.ligado ? "ligado" : "desligado") : ""
                                color: modelData.ligado ? Tema.positivo : Tema.textoFraco
                            }
                        }
                        MouseArea {
                            anchors.fill: parent
                            onClicked: ponte.escolherMotor(modelData.papel, modelData.id)
                        }
                    }
                }
            }
        }

        Column {
            width: coluna.width
            spacing: 8
            Rotulo { text: "escuta"; destaque: true }
            Row {
                spacing: 10
                Botao {
                    texto: "segurar para falar"
                    ativo: ponte && ponte.configuracao.escuta === "ptt"
                    onApertado: ponte.definirCampo("escuta", "ptt")
                }
                Botao {
                    texto: "escuta contínua"
                    ativo: ponte && ponte.configuracao.escuta === "vad"
                    onApertado: ponte.definirCampo("escuta", "vad")
                }
            }
        }

        Column {
            width: coluna.width
            spacing: 10
            Rotulo { text: "chaves de api"; destaque: true }
            Rotulo { text: ponte ? ponte.chaveiroFrase : ""; color: Tema.textoFraco }
            Repeater {
                model: ponte ? ponte.chaves : []
                Column {
                    width: coluna.width
                    spacing: 6
                    Row {
                        width: parent.width
                        spacing: 12
                        Text {
                            text: modelData.variavel
                            color: Tema.texto
                            font.family: Tema.fonteDados
                            font.pixelSize: Tema.tamanhoTexto - 2
                            renderType: Text.NativeRendering
                        }
                        Rotulo {
                            text: modelData.estado
                            color: modelData.estado.indexOf("AUSENTE") >= 0 ? Tema.alerta : Tema.positivo
                        }
                    }
                    Row {
                        width: parent.width
                        spacing: 10
                        Rectangle {
                            width: parent.width - 240
                            height: 30
                            color: "transparent"
                            border.width: 1
                            border.color: campo.activeFocus ? Tema.cianoFraco : Tema.linha
                            TextInput {
                                id: campo
                                anchors.fill: parent
                                anchors.margins: 9
                                echoMode: TextInput.Password
                                color: Tema.texto
                                font.family: Tema.fonteDados
                                font.pixelSize: Tema.tamanhoTexto - 2
                                clip: true
                            }
                            Rotulo {
                                anchors.left: parent.left
                                anchors.leftMargin: 9
                                anchors.verticalCenter: parent.verticalCenter
                                text: "cole a chave aqui — ela vai para o chaveiro do sistema"
                                visible: campo.text === "" && !campo.activeFocus
                            }
                        }
                        Botao {
                            texto: "guardar"
                            onApertado: { ponte.guardarChave(modelData.variavel, campo.text); campo.text = "" }
                        }
                        Botao {
                            texto: "esquecer"
                            onApertado: ponte.esquecerChave(modelData.variavel)
                        }
                    }
                }
            }
        }

    }
    }

    Row {
        id: rodape
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 14
        Botao { texto: "salvar configuração"; onApertado: ponte.salvarConfiguracao() }
        Rotulo {
            anchors.verticalCenter: parent.verticalCenter
            text: ponte ? ponte.configuracao.caminho : ""
            color: Tema.textoFraco
        }
    }
}
