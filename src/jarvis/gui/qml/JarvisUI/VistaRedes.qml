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
        objectName: "rolagemDasRedes"
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

            // Memórias fixas (ADR-0060, fatia C): o que o Jarvis sabe de antemão para responder —
            // contatos, prestadores de serviço e como responder. Editar grava ao sair do campo;
            // o telefone nunca vai ao modelo (é do código, para conferir o contato no envio).
            Painel {
                id: caixaDeMemorias
                objectName: "memoriasFixas"
                width: coluna.width
                titulo: "memórias fixas"
                dica: "o Jarvis só lê no assunto de mensagens, contatos e serviços"
                property string tipoNovo: "contato"
                Column {
                    width: parent.width
                    spacing: 8
                    Repeater {
                        model: vista.redes ? vista.redes.memorias : []
                        Column {
                            id: linhaDeMemoria
                            property var memoria: modelData
                            width: parent.width
                            spacing: 4
                            Rotulo { text: linhaDeMemoria.memoria.rotulo }
                            Row {
                                spacing: 8
                                Repeater {
                                    model: [
                                        { campo: "nome", largura: 160 },
                                        { campo: "texto", largura: 300 },
                                        { campo: "telefone", largura: 130 }
                                    ]
                                    Rectangle {
                                        visible: modelData.campo !== "telefone"
                                                 || linhaDeMemoria.memoria.tipo !== "instrucao"
                                        width: modelData.largura
                                        height: 28
                                        color: "transparent"
                                        border.width: 1
                                        border.color: campoDaMemoria.activeFocus ? Tema.cianoFraco : Tema.linha
                                        TextInput {
                                            id: campoDaMemoria
                                            objectName: "memoria-" + modelData.campo + "-"
                                                        + linhaDeMemoria.memoria.id
                                            anchors.fill: parent
                                            anchors.margins: 6
                                            text: linhaDeMemoria.memoria[modelData.campo]
                                            color: Tema.texto
                                            font.pixelSize: Tema.tamanhoTexto - 3
                                            clip: true
                                            onEditingFinished: {
                                                var m = linhaDeMemoria.memoria
                                                var novo = {
                                                    nome: m.nome, texto: m.texto, telefone: m.telefone
                                                }
                                                novo[modelData.campo] = text
                                                if (novo[modelData.campo] !== m[modelData.campo])
                                                    vista.redes.editarMemoria(m.id, novo.nome,
                                                                              novo.texto, novo.telefone)
                                            }
                                        }
                                    }
                                }
                                Botao {
                                    objectName: "removerMemoria-" + linhaDeMemoria.memoria.id
                                    texto: "apagar"
                                    onApertado: vista.redes.removerMemoria(linhaDeMemoria.memoria.id)
                                }
                            }
                        }
                    }
                    Nota {
                        width: parent.width
                        visible: vista.redes && vista.redes.memorias.length === 0
                        text: "Nenhuma ainda. Ex.: contato «Ana — colega do financeiro», serviço "
                              + "«João — encanador do prédio», instrução «responda curto e diga "
                              + "que eu retorno à tarde»."
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: vista.redes ? vista.redes.tiposDeMemoria : []
                            Botao {
                                objectName: "tipoDeMemoria-" + modelData.id
                                texto: modelData.id === "servico" ? "serviço"
                                       : (modelData.id === "instrucao" ? "instrução" : "contato")
                                ativo: caixaDeMemorias.tipoNovo === modelData.id
                                onApertado: caixaDeMemorias.tipoNovo = modelData.id
                            }
                        }
                    }
                    Row {
                        spacing: 8
                        Repeater {
                            id: camposNovos
                            model: [
                                { campo: "nome", largura: 160, dica: "nome" },
                                { campo: "texto", largura: 300, dica: "quem é / o que fazer" },
                                { campo: "telefone", largura: 130, dica: "telefone" }
                            ]
                            Rectangle {
                                property alias valor: campoNovo.text
                                visible: modelData.campo !== "telefone"
                                         || caixaDeMemorias.tipoNovo !== "instrucao"
                                width: modelData.largura
                                height: 28
                                color: "transparent"
                                border.width: 1
                                border.color: campoNovo.activeFocus ? Tema.cianoFraco : Tema.linha
                                TextInput {
                                    id: campoNovo
                                    objectName: "memoriaNova-" + modelData.campo
                                    anchors.fill: parent
                                    anchors.margins: 6
                                    color: Tema.texto
                                    font.pixelSize: Tema.tamanhoTexto - 3
                                    clip: true
                                }
                                Rotulo {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 6
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.dica
                                    visible: campoNovo.text === "" && !campoNovo.activeFocus
                                }
                            }
                        }
                        Botao {
                            objectName: "adicionarMemoria"
                            texto: "adicionar"
                            onApertado: {
                                var nome = camposNovos.itemAt(0).valor
                                var texto = camposNovos.itemAt(1).valor
                                var telefone = caixaDeMemorias.tipoNovo === "instrucao"
                                               ? "" : camposNovos.itemAt(2).valor
                                if (vista.redes.adicionarMemoria(caixaDeMemorias.tipoNovo, nome,
                                                                 texto, telefone)) {
                                    for (var i = 0; i < 3; i++)
                                        camposNovos.itemAt(i).valor = ""
                                }
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
