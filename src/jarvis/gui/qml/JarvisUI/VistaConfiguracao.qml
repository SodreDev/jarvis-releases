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
    // Quatro folhas, cada uma cabe numa tela e nenhuma rola dentro de outra: o que o Jarvis ouve
    // e fala, e o que ele pode tocar (pastas, programas, navegadores).
    property string aba: "voz"

    Flow {
        id: abas
        z: 3
        width: parent.width
        spacing: 8
        height: implicitHeight + 8
        Botao {
            objectName: "abaVoz"
            texto: "voz e escuta"
            ativo: vista.aba === "voz"
            onApertado: vista.aba = "voz"
        }
        Botao {
            objectName: "abaPastas"
            texto: "pastas e arquivos"
            ativo: vista.aba === "pastas"
            onApertado: vista.aba = "pastas"
        }
        Botao {
            objectName: "abaApps"
            texto: "aplicativos"
            ativo: vista.aba === "apps"
            onApertado: vista.aba = "apps"
        }
        Botao {
            objectName: "abaNavegadores"
            texto: "navegadores"
            ativo: vista.aba === "navegadores"
            onApertado: vista.aba = "navegadores"
        }
    }

    VistaAcesso {
        objectName: "vistaAcesso"
        secao: vista.aba
        anchors.top: abas.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        visible: vista.aba !== "voz"
    }

    // --- as caixas -----------------------------------------------------------------------
    // Rola quando o conteúdo passa da altura: o provedor escolhido abre modelo, aviso e voz.
    IndicadorDeRolagem {
        id: indicadorDeRolagem
        visible: vista.aba === "voz" && necessario
        anchors.right: parent.right
        anchors.top: abas.bottom
        anchors.bottom: parent.bottom
        alvo: rolagem
        z: 2
    }

    Flickable {
        id: rolagem
        visible: vista.aba === "voz"
        anchors.top: abas.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.rightMargin: indicadorDeRolagem.visible ? 10 : 0
        contentWidth: width
        contentHeight: caixas.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true

    Row {
        id: caixas
        width: rolagem.width
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
                        model: ponte ? ponte.provedoresAsr : []
                        LinhaDeProvedor { provedor: modelData }
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
                        model: ponte ? ponte.provedoresTts : []
                        LinhaDeProvedor { provedor: modelData }
                    }
                }
            }

            Painel {
                width: parent.width
                titulo: "é comigo?"
                dica: "na escuta contínua, separa o que é para o Jarvis do resto"
                Column {
                    width: parent.width
                    Repeater {
                        objectName: "provedoresDecisao"
                        model: ponte ? ponte.provedoresDecisao : []
                        LinhaDeProvedor { provedor: modelData }
                    }
                    Nota {
                        width: parent.width
                        text: "Opcional e desligado. Ligado, o texto de cada fala que o microfone transcrever vai à nuvem para decidir se é com o Jarvis; na dúvida ele não age. Só vale no modo de escuta contínua."
                    }
                }
            }
        }

        Column {
            width: (parent.width - Tema.espacamento) * 0.44
            spacing: Tema.espacamento

            // No alto da coluna da direita: com um provedor aberto a da esquerda rola, e o
            // botão de salvar não pode sumir junto.
            Painel {
                width: parent.width
                titulo: "arquivo"
                Column {
                    width: parent.width
                    spacing: 8
                    Botao { texto: "salvar configuração"; onApertado: ponte.salvarConfiguracao() }
                    Nota {
                        width: parent.width
                        text: "escolher não liga nuvem nenhuma: ligar é outra confirmação"
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        textFormat: Text.PlainText
                        width: parent.width
                        text: ponte ? ponte.configuracao.caminho : ""
                        color: Tema.textoFraco
                        font.family: Tema.fonteDados
                        font.pixelSize: Tema.tamanhoTexto - 4
                        wrapMode: Text.WrapAnywhere
                        renderType: Text.NativeRendering
                    }
                }
            }

            // Quando o Jarvis sabe que é com ele (ADR-0021). Os três modos trocam com a conversa
            // aberta; a frase de baixo diz o alcance do atalho sem prometer o que não há.
            Painel {
                id: caixaEscuta
                width: parent.width
                titulo: "escuta"
                dica: ponte ? ponte.escuta.modoFrase : ""
                property string modo: ponte ? ponte.escuta.modo : "ptt"
                Column {
                    width: parent.width
                    spacing: 10
                    Flow {
                        width: parent.width
                        spacing: 8
                        Botao {
                            texto: "atalho de teclas"
                            ativo: caixaEscuta.modo === "ptt"
                            onApertado: ponte.definirEscuta("ptt")
                        }
                        Botao {
                            texto: "palavra de ativação"
                            ativo: caixaEscuta.modo === "palavra"
                            onApertado: ponte.definirEscuta("palavra")
                        }
                        Botao {
                            texto: "escuta contínua"
                            ativo: caixaEscuta.modo === "vad"
                            onApertado: ponte.definirEscuta("vad")
                        }
                    }
                    Nota {
                        width: parent.width
                        text: ponte ? ponte.escuta.frase : ""
                        color: Tema.texto
                        wrapMode: Text.WordWrap
                    }

                    // --- atalho ---------------------------------------------------------
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: caixaEscuta.modo === "ptt"
                        Row {
                            spacing: 8
                            Rectangle {
                                id: capturador
                                property bool ouvindo: false
                                width: 190
                                height: 30
                                color: "transparent"
                                radius: Tema.raioModulo
                                border.width: 1
                                border.color: ouvindo ? Tema.ciano : Tema.linha
                                focus: ouvindo
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.centerIn: parent
                                    text: capturador.ouvindo
                                          ? "aperte a combinação…"
                                          : (ponte && ponte.escuta.atalho !== ""
                                             ? ponte.escuta.atalho : "barra de espaço")
                                    color: capturador.ouvindo ? Tema.ciano : Tema.textoForte
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 2
                                    renderType: Text.NativeRendering
                                }
                                Keys.onPressed: function (evento) {
                                    if (!capturador.ouvindo)
                                        return
                                    evento.accepted = true
                                    if (evento.key === Qt.Key_Escape) {
                                        capturador.ouvindo = false
                                        return
                                    }
                                    // Modificador sozinho ainda não é combinação: espera a tecla.
                                    if ([Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta,
                                         Qt.Key_Super_L, Qt.Key_Super_R].indexOf(evento.key) >= 0)
                                        return
                                    ponte.capturarAtalho(evento.key, evento.modifiers)
                                    capturador.ouvindo = false
                                }
                            }
                            Botao {
                                texto: capturador.ouvindo ? "cancelar" : "capturar"
                                onApertado: {
                                    capturador.ouvindo = !capturador.ouvindo
                                    if (capturador.ouvindo)
                                        capturador.forceActiveFocus()
                                }
                            }
                            Botao {
                                texto: "barra de espaço"
                                visible: ponte && ponte.escuta.atalho !== ""
                                onApertado: ponte.limparAtalho()
                            }
                        }
                        Botao {
                            texto: "usar como atalho global"
                            visible: ponte && ponte.portalDisponivel && !ponte.escuta.atalhoGlobal
                            onApertado: ponte.ativarAtalhoGlobal()
                        }
                        Nota {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            color: ponte && ponte.escuta.atalhoGlobal ? Tema.positivo : Tema.alerta
                            text: !ponte ? ""
                                  : ponte.escuta.atalhoGlobal
                                    ? "global: vale com a janela fora de foco — " + ponte.portalFrase
                                    : ponte.portalDisponivel
                                      ? "por enquanto só com a janela em foco. “Usar como atalho "
                                        + "global” pede ao sistema, que mostra um diálogo seu."
                                      : "sem portal de atalhos nesta sessão: o atalho vale só "
                                        + "com a janela em foco (" + ponte.portalFrase + ")"
                        }
                    }

                    // --- palavra --------------------------------------------------------
                    Column {
                        width: parent.width
                        spacing: 8
                        visible: caixaEscuta.modo === "palavra"
                        Row {
                            spacing: 8
                            Rectangle {
                                width: 150
                                height: 30
                                color: "transparent"
                                radius: Tema.raioModulo
                                border.width: 1
                                border.color: campoPalavra.activeFocus ? Tema.cianoFraco : Tema.linha
                                TextInput {
                                    id: campoPalavra
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    text: ponte ? ponte.escuta.palavra : "jarvis"
                                    color: Tema.textoForte
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 2
                                    clip: true
                                }
                            }
                            Rectangle {
                                width: 70
                                height: 30
                                color: "transparent"
                                radius: Tema.raioModulo
                                border.width: 1
                                border.color: campoLimiar.activeFocus ? Tema.cianoFraco : Tema.linha
                                TextInput {
                                    id: campoLimiar
                                    anchors.fill: parent
                                    anchors.margins: 8
                                    text: ponte ? ponte.escuta.limiar.toFixed(2) : "0.75"
                                    color: Tema.textoForte
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 2
                                    clip: true
                                }
                            }
                            Botao {
                                texto: "aplicar"
                                onApertado: ponte.definirPalavra(campoPalavra.text, campoLimiar.text)
                            }
                        }
                        Nota {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            text: "reconhecida no computador, sobre o que o ASR transcreve, e "
                                  + "tolerante a pronúncias parecidas. Limiar de 0,50 a 1,0 — "
                                  + "mais alto exige pronúncia mais fiel."
                        }
                        Nota {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            visible: ponte && ponte.escuta.asrNaNuvem
                            color: Tema.alerta
                            text: "com o ASR na nuvem, cada trecho que o microfone abrir sai da "
                                  + "máquina para saber se você chamou"
                        }
                    }

                    // --- contínua -------------------------------------------------------
                    Nota {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        visible: caixaEscuta.modo === "vad"
                        color: ponte && ponte.escuta.asrNaNuvem ? Tema.alerta : Tema.textoFraco
                        text: ponte && ponte.escuta.asrNaNuvem
                              ? "com o ASR na nuvem, cada trecho de fala sai da máquina"
                              : "o VAD abre o trecho e o silêncio fecha; nada sai da máquina com "
                                + "o ASR local"
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
                    Nota {
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
                                    textFormat: Text.PlainText
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
                    Nota {
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
}
