import QtQuick
import JarvisUI

// Chamadas (ADR-0074): o TOTP que reconhece o dono numa ligação e os limites do agente.
//
// O segredo é gerado aqui e guardado no chaveiro do sistema; a URI `otpauth://` e a chave em
// grupos aparecem UMA vez, até o dono tocar «já cadastrei» — depois a tela nunca mais as lê.
// Os limites (5 min, 30 turnos, 5 frases) viram aviso ao agente, nunca corte automático.
Item {
    id: vista
    readonly property var chamada: ponte ? ponte.chamada : null
    readonly property var ajustes: chamada ? chamada.ajustes : ({})

    // Sair da aba esconde o segredo: ele não fica na tela esperando alguém olhar.
    onVisibleChanged: if (!visible && chamada) chamada.esconderSegredo()

    Item {
        id: frase
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: texto.text === "" ? 0 : texto.implicitHeight + 8
        Text {
            id: texto
            objectName: "fraseDaChamada"
            textFormat: Text.PlainText
            width: parent.width
            text: vista.chamada ? vista.chamada.frase : ""
            color: text.indexOf("não deu") === 0 ? Tema.alerta : Tema.positivo
            font.pixelSize: Tema.tamanhoTexto - 2
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            renderType: Text.NativeRendering
        }
    }

    IndicadorDeRolagem {
        id: indicador
        anchors.right: parent.right
        anchors.top: frase.bottom
        anchors.bottom: parent.bottom
        alvo: rolagem
        z: 2
    }

    Flickable {
        id: rolagem
        objectName: "rolagemDaChamada"
        anchors.top: frase.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: indicador.visible ? 10 : 0
        contentWidth: width
        contentHeight: coluna.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Column {
            id: coluna
            width: rolagem.width
            spacing: Tema.espacamento

            Painel {
                width: parent.width
                titulo: "código do dono (TOTP)"
                dica: vista.chamada && vista.chamada.configurado
                      ? (vista.chamada.bloqueado ? "bloqueado por erros" : "configurado")
                      : "não configurado"
                Column {
                    width: parent.width
                    spacing: 8
                    Nota {
                        width: parent.width
                        text: "Numa ligação, quem disser ser você terá de dizer o código de 6 dígitos "
                              + "do seu app autenticador — em toda chamada. Mesmo reconhecido, o "
                              + "Jarvis na ligação só anota recado: qualquer ação espera a sua "
                              + "confirmação aqui no PC."
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Botao {
                            objectName: "gerarSegredo"
                            texto: vista.chamada && vista.chamada.configurado
                                   ? "gerar novo (troca o antigo)" : "gerar segredo"
                            onApertado: vista.chamada.gerarSegredo()
                        }
                        Botao {
                            objectName: "apagarSegredo"
                            visible: vista.chamada !== null && vista.chamada.configurado
                            texto: "apagar"
                            onApertado: vista.chamada.apagarSegredo()
                        }
                        Botao {
                            objectName: "liberarBloqueio"
                            visible: vista.chamada !== null && vista.chamada.bloqueado
                            texto: "liberar bloqueio"
                            onApertado: vista.chamada.liberarBloqueio()
                        }
                    }
                    // Uma vez só: a URI e a chave para digitar no autenticador.
                    Column {
                        objectName: "segredoUmaVez"
                        width: parent.width
                        spacing: 6
                        visible: vista.chamada !== null && vista.chamada.uri !== ""
                        Nota {
                            width: parent.width
                            alerta: true
                            text: "Cadastre agora no autenticador (Aegis, Google Authenticator, "
                                  + "2FAS…): «inserir chave» com a chave abaixo, ou cole a URI. "
                                  + "Não tire foto nem guarde em nota: isto não volta a aparecer."
                        }
                        TextEdit {
                            objectName: "chaveDoSegredo"
                            width: parent.width
                            readOnly: true
                            selectByMouse: true
                            textFormat: TextEdit.PlainText
                            text: vista.chamada ? vista.chamada.chave : ""
                            color: Tema.textoForte
                            font.family: "monospace"
                            font.pixelSize: Tema.tamanhoTexto
                            wrapMode: TextEdit.WrapAnywhere
                        }
                        TextEdit {
                            objectName: "uriDoSegredo"
                            width: parent.width
                            readOnly: true
                            selectByMouse: true
                            textFormat: TextEdit.PlainText
                            text: vista.chamada ? vista.chamada.uri : ""
                            color: Tema.texto
                            font.family: "monospace"
                            font.pixelSize: Tema.tamanhoTexto - 4
                            wrapMode: TextEdit.WrapAnywhere
                        }
                        Botao {
                            objectName: "jaCadastrei"
                            texto: "já cadastrei"
                            onApertado: vista.chamada.esconderSegredo()
                        }
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        visible: vista.chamada !== null && vista.chamada.configurado
                        Rectangle {
                            width: 120
                            height: 28
                            color: "transparent"
                            border.width: 1
                            border.color: campoCodigo.activeFocus ? Tema.cianoFraco : Tema.linha
                            TextInput {
                                id: campoCodigo
                                objectName: "campoDoCodigo"
                                anchors.fill: parent
                                anchors.margins: 6
                                color: Tema.texto
                                font.pixelSize: Tema.tamanhoTexto - 3
                                maximumLength: 8
                                inputMethodHints: Qt.ImhDigitsOnly
                                clip: true
                                onAccepted: {
                                    vista.chamada.conferirCodigo(text)
                                    text = ""
                                }
                            }
                            Rotulo {
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: "123456"
                                visible: campoCodigo.text === "" && !campoCodigo.activeFocus
                            }
                        }
                        Botao {
                            objectName: "conferirCodigo"
                            texto: "conferir"
                            onApertado: {
                                vista.chamada.conferirCodigo(campoCodigo.text)
                                campoCodigo.text = ""
                            }
                        }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "limites do agente na ligação"
                dica: "passar do limite vira aviso ao agente — nada desliga sozinho"
                Column {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: [
                            { campo: "duracao_para_aviso_min", rotulo: "minutos até o aviso" },
                            { campo: "turnos", rotulo: "turnos" },
                            { campo: "frases_por_fala", rotulo: "frases por fala" },
                            { campo: "tentativas_de_codigo", rotulo: "códigos errados por chamada" },
                            { campo: "retencao_do_recado_dias", rotulo: "dias que o recado fica" },
                            { campo: "retencao_da_memoria_dias", rotulo: "dias que lembra de quem ligou" }
                        ]
                        Row {
                            spacing: 8
                            Rectangle {
                                width: 70
                                height: 28
                                color: "transparent"
                                border.width: 1
                                border.color: campoNumero.activeFocus ? Tema.cianoFraco : Tema.linha
                                TextInput {
                                    id: campoNumero
                                    objectName: "limite-" + modelData.campo
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    color: Tema.texto
                                    font.pixelSize: Tema.tamanhoTexto - 3
                                    inputMethodHints: Qt.ImhDigitsOnly
                                    text: vista.ajustes[modelData.campo] !== undefined
                                          ? String(vista.ajustes[modelData.campo]) : ""
                                    onEditingFinished: vista.chamada.definir(modelData.campo, text)
                                }
                            }
                            Rotulo {
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.rotulo
                            }
                        }
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Botao {
                            objectName: "lembrarInterlocutor"
                            texto: vista.ajustes.lembrar_interlocutor
                                   ? "lembra de quem ligou" : "não lembra de quem ligou"
                            ativo: vista.ajustes.lembrar_interlocutor === true
                            onApertado: vista.chamada.definir("lembrar_interlocutor",
                                                              vista.ajustes.lembrar_interlocutor
                                                              ? "false" : "true")
                        }
                        Botao {
                            objectName: "usaFone"
                            texto: vista.ajustes.usa_fone ? "uso fone" : "sem fone"
                            ativo: vista.ajustes.usa_fone === true
                            onApertado: vista.chamada.definir("usa_fone",
                                                              vista.ajustes.usa_fone
                                                              ? "false" : "true")
                        }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "o que o Jarvis pode dizer"
                dica: "quem liga ouve só isto sobre você"
                Column {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: [
                            { campo: "pode_dizer", dica: "pode dizer (ex.: em reunião até as 15h)" },
                            { campo: "nunca_dizer", dica: "nunca dizer" }
                        ]
                        Rectangle {
                            width: coluna.width - 24
                            height: 28
                            color: "transparent"
                            border.width: 1
                            border.color: campoTexto.activeFocus ? Tema.cianoFraco : Tema.linha
                            TextInput {
                                id: campoTexto
                                objectName: "texto-" + modelData.campo
                                anchors.fill: parent
                                anchors.margins: 6
                                color: Tema.texto
                                font.pixelSize: Tema.tamanhoTexto - 3
                                maximumLength: 400
                                clip: true
                                text: vista.ajustes[modelData.campo] || ""
                                onEditingFinished: vista.chamada.definir(modelData.campo, text)
                            }
                            Rotulo {
                                anchors.left: parent.left
                                anchors.leftMargin: 6
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.dica
                                visible: campoTexto.text === "" && !campoTexto.activeFocus
                            }
                        }
                    }
                    Nota {
                        width: parent.width
                        text: "Ação pedida numa ligação só com a sua confirmação aqui no PC. "
                              + "Palavra de coação: " + (vista.ajustes.coacao_ligada
                                                          ? "ligada." : "desligada.")
                        color: Tema.textoFraco
                    }
                }
            }
        }
    }
}
