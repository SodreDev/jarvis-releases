import QtQuick
import JarvisUI

// Provedores e chaves como **módulos do workspace**, não como formulário.
//
// Duas regras daqui, e nenhuma é de estilo: escolher um motor de nuvem **não** o liga (o aviso
// montado do registro aparece e o dono decide), e a chave de API só aparece como
// "definida/ausente" — o valor não é lido nem para desenhar esta tela.
//
// A disposição é em caixas por assunto — ouvir, falar, escuta, chaves — porque uma pilha de
// linhas de mesmo peso não diz o que é escolha de quem ouve e o que é escolha de quem fala.
Item {
    id: vista
    property var dados: ({})

    readonly property var motoresDeAsr: ponte
        ? ponte.motores.filter(function (m) { return m.papel === "asr" }) : []
    readonly property var motoresDeTts: ponte
        ? ponte.motores.filter(function (m) { return m.papel === "tts" }) : []

    // --- uma linha de motor -----------------------------------------------------------------
    component LinhaDeMotor: Rectangle {
        id: linha
        property var motor: ({})
        width: parent ? parent.width : 0
        height: 32
        color: motor.escolhido ? Qt.rgba(0.22, 0.78, 0.91, 0.06) : "transparent"

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 2
            height: parent.height - 8
            color: linha.motor.escolhido ? Tema.ciano : "transparent"
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            text: linha.motor.escolhido ? "▸" : ""
            color: Tema.ciano
            font.pixelSize: 10
            renderType: Text.NativeRendering
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            text: linha.motor.id || ""
            color: linha.motor.escolhido ? Tema.textoForte : Tema.texto
            font.family: Tema.fonteDados
            font.pixelSize: Tema.tamanhoTexto - 2
            renderType: Text.NativeRendering
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            spacing: 12
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: linha.motor.onde === "nuvem" && !linha.motor.ligado ? "desligado" : ""
            }
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: linha.motor.onde || ""
                color: Tema.textoFraco
                opacity: linha.motor.onde === "nuvem" ? 0.95 : 0.7
            }
        }
        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width; height: 1
            color: Tema.linha
            opacity: 0.6
        }
        MouseArea {
            anchors.fill: parent
            onClicked: ponte.escolherMotor(linha.motor.papel, linha.motor.id)
        }
    }

    // --- as caixas -----------------------------------------------------------------------
    Row {
        anchors.fill: parent
        spacing: Tema.espacamento

        Column {
            width: (parent.width - Tema.espacamento) * 0.56
            spacing: Tema.espacamento

            Painel {
                width: parent.width
                titulo: "voz — ouvir"
                dica: "quem transcreve o que você fala"
                Column {
                    width: parent.width
                    Repeater {
                        model: vista.motoresDeAsr
                        LinhaDeMotor { motor: modelData }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "voz — falar"
                dica: "quem dá voz à resposta"
                Column {
                    width: parent.width
                    Repeater {
                        model: vista.motoresDeTts
                        LinhaDeMotor { motor: modelData }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "arquivo"
                dica: ponte ? ponte.configuracao.caminho : ""
                Row {
                    spacing: 12
                    Botao { texto: "salvar configuração"; onApertado: ponte.salvarConfiguracao() }
                    Rotulo {
                        anchors.verticalCenter: parent.verticalCenter
                        text: "escolher não liga nuvem nenhuma: ligar é outra confirmação"
                    }
                }
            }
        }

        Column {
            width: (parent.width - Tema.espacamento) * 0.44
            spacing: Tema.espacamento

            Painel {
                width: parent.width
                titulo: "escuta"
                dica: ponte && ponte.configuracao.escuta === "ptt" ? "tecla" : "voz"
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

            Painel {
                width: parent.width
                titulo: "resposta"
                dica: "provisório até a F2"
                Row {
                    spacing: 10
                    Repeater {
                        model: ponte ? ponte.geradores : []
                        Botao {
                            texto: modelData === "eco" ? "eco da transcrição" : modelData
                            ativo: ponte && ponte.configuracao.s2 === modelData
                            onApertado: ponte.definirCampo("s2", modelData)
                        }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "voz local"
                dica: ponte ? ponte.configuracao.voz : ""
                Column {
                    width: parent.width
                    spacing: 10
                    Rotulo {
                        width: parent.width
                        text: ponte && ponte.vozFaltando !== ""
                              ? ponte.vozFaltando
                              : "o peso da voz já está no disco — nada a baixar"
                        color: ponte && ponte.vozFaltando !== "" ? Tema.alerta : Tema.textoFraco
                        wrapMode: Text.WordWrap
                    }
                    Botao {
                        visible: ponte && ponte.vozFaltando !== ""
                        texto: "baixar a voz"
                        onApertado: ponte.baixarVoz()
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "chaves de api"
                dica: ponte ? ponte.chaveiroFrase : ""
                Column {
                    width: parent.width
                    spacing: 12
                    Repeater {
                        model: ponte ? ponte.chaves : []
                        Column {
                            width: parent.width
                            spacing: 6
                            Row {
                                width: parent.width
                                spacing: 12
                                Text {
                                    text: modelData.variavel
                                    color: Tema.texto
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 3
                                    renderType: Text.NativeRendering
                                }
                                Rotulo {
                                    text: modelData.estado
                                    color: modelData.estado.indexOf("AUSENTE") >= 0
                                           ? Tema.alerta : Tema.positivo
                                }
                            }
                            Row {
                                width: parent.width
                                spacing: 8
                                Rectangle {
                                    width: parent.width - 170
                                    height: 28
                                    color: "transparent"
                                    border.width: 1
                                    border.color: campo.activeFocus ? Tema.cianoFraco : Tema.linha
                                    TextInput {
                                        id: campo
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        echoMode: TextInput.Password
                                        color: Tema.texto
                                        font.family: Tema.fonteDados
                                        font.pixelSize: Tema.tamanhoTexto - 3
                                        clip: true
                                    }
                                    Rotulo {
                                        anchors.left: parent.left
                                        anchors.leftMargin: 8
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "cole aqui — vai para o chaveiro"
                                        visible: campo.text === "" && !campo.activeFocus
                                    }
                                }
                                Botao {
                                    texto: "guardar"
                                    onApertado: {
                                        ponte.guardarChave(modelData.variavel, campo.text)
                                        campo.text = ""
                                    }
                                }
                                Botao {
                                    texto: "limpar"
                                    onApertado: ponte.esquecerChave(modelData.variavel)
                                }
                            }
                        }
                    }
                    Rotulo {
                        width: parent.width
                        text: "o valor nunca aparece aqui, nem no arquivo de configuração"
                        color: Tema.textoFraco
                        wrapMode: Text.WordWrap
                    }
                }
            }

        }
    }
}
