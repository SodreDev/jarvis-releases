import QtQuick
import JarvisUI

// Redes sociais (ADR-0060): o navegador em que elas rodam e um cartão por rede.
//
// Cada cartão é a «aba de monitoramento» daquela rede no painel: liga e desliga o monitor, diz o
// estado que a extensão informou e mostra as notificações só daquela rede. Sem vídeo, sem
// captura de tela. Cada clique grava `redes.toml` na hora; a frase do topo diz o que aconteceu.
// Tudo nasce desligado: o Jarvis não abre nem lê rede nenhuma até o dono ligar aqui.
Item {
    id: vista
    readonly property var redes: ponte ? ponte.redes : null

    Item {
        id: frase
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: texto.text === "" ? 0 : texto.implicitHeight + 8
        Text {
            id: texto
            objectName: "fraseDasRedes"
            textFormat: Text.PlainText
            width: parent.width
            text: vista.redes ? vista.redes.frase : ""
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
                titulo: "navegador preferido"
                dica: "onde as abas das redes abrem — em segundo plano, na sua janela"
                Column {
                    width: parent.width
                    spacing: 8
                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: vista.redes ? vista.redes.navegadores : []
                            Botao {
                                objectName: "navegadorPreferido-" + (modelData.familia || "principal")
                                texto: modelData.nome
                                ativo: modelData.escolhido
                                onApertado: vista.redes.definirNavegadorPreferido(modelData.familia)
                            }
                        }
                    }
                    Nota {
                        width: parent.width
                        text: "Usa o navegador e o perfil em que você já está logado. Cada rede "
                              + "ligada vira uma aba de fundo na sua janela: nunca outra janela, "
                              + "outra instância ou outro perfil."
                    }
                }
            }

            Repeater {
                model: vista.redes ? vista.redes.redes : []
                Painel {
                    id: cartao
                    property var rede: modelData
                    objectName: "rede-" + rede.id
                    width: coluna.width
                    titulo: rede.nome
                    dica: rede.naoLidas > 0 ? rede.naoLidas + " não lida(s)" : rede.estado
                    Column {
                        width: parent.width
                        spacing: 8
                        Flow {
                            width: parent.width
                            spacing: 8
                            Botao {
                                objectName: "monitorar-" + cartao.rede.id
                                texto: cartao.rede.monitorar ? "monitorando" : "monitorar"
                                ativo: cartao.rede.monitorar
                                onApertado: vista.redes.definirMonitorar(cartao.rede.id,
                                                                         !cartao.rede.monitorar)
                            }
                            Botao {
                                objectName: "notificar-" + cartao.rede.id
                                visible: cartao.rede.monitorar
                                texto: cartao.rede.notificar ? "avisa quando chega" : "não avisa"
                                ativo: cartao.rede.notificar
                                onApertado: vista.redes.definirNotificar(cartao.rede.id,
                                                                         !cartao.rede.notificar)
                            }
                        }
                        Nota {
                            objectName: "estado-" + cartao.rede.id
                            width: parent.width
                            text: cartao.rede.frase
                            color: Tema.texto
                        }
                        Repeater {
                            model: cartao.rede.notificacoes
                            Nota {
                                width: parent.width
                                text: modelData.hora + " · " + modelData.texto
                                color: Tema.textoForte
                            }
                        }
                    }
                }
            }

            Nota {
                width: parent.width
                text: vista.redes ? "salvo em " + vista.redes.caminho + " (só você lê)" : ""
                color: Tema.textoFraco
            }
        }
    }
}
