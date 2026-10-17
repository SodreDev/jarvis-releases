import QtQuick
import JarvisUI

// Um provedor de voz — quem ouve ou quem fala — e, quando escolhido, o que se escolhe dentro
// dele: o modelo, o interruptor da nuvem e (na ElevenLabs) a voz da conta.
//
// Provedor e modelo são duas decisões, e por isso duas linhas: "Groq" diz para onde o áudio
// vai; "turbo ou v3" diz quanto custa e quanto acerta. O que cada clique escreve vem pronto do
// Python (`jarvis.voz.provedores`): esta tela não sabe qual campo guarda o modelo de quem.
//
// Ligar nuvem continua sendo outra confirmação: o aviso montado do registro aparece inteiro
// **antes** do botão, e escolher provedor ou modelo não liga nada.
Column {
    id: linha
    property var provedor: ({})
    readonly property bool aberto: provedor.escolhido === true
    readonly property bool naNuvem: provedor.onde === "nuvem"
    readonly property bool daElevenLabs: provedor.chave === "nuvem:ElevenLabs"
    readonly property var modelos: provedor.modelos || []
    width: parent ? parent.width : 0

    // Uma ficha sem caixa alta: nome de modelo e de voz são dados, e "WHISPER-LARGE-V3"
    // em maiúsculas é um nome que não existe.
    component Ficha: Rectangle {
        id: ficha
        property string texto: ""
        property string nota: ""
        property bool ativo: false
        signal escolhida()
        implicitWidth: conteudo.implicitWidth + 20
        implicitHeight: 26
        radius: Tema.raioModulo
        color: ativo ? Qt.rgba(0.22, 0.78, 0.91, 0.10) : "transparent"
        border.width: 1
        border.color: ativo || toque.containsMouse ? Tema.cianoFraco : Tema.linha
        Row {
            id: conteudo
            anchors.centerIn: parent
            spacing: 8
            Text {
                textFormat: Text.PlainText
                text: ficha.texto
                color: ficha.ativo ? Tema.textoForte : Tema.texto
                font.family: Tema.fonteDados
                font.pixelSize: Tema.tamanhoTexto - 3
                renderType: Text.NativeRendering
            }
            Text {
                textFormat: Text.PlainText
                visible: ficha.nota !== ""
                text: ficha.nota
                color: Tema.textoFraco
                font.pixelSize: Tema.tamanhoTexto - 4
                renderType: Text.NativeRendering
            }
        }
        MouseArea {
            id: toque
            anchors.fill: parent
            hoverEnabled: true
            onClicked: ficha.escolhida()
        }
    }

    // --- a linha do provedor ---------------------------------------------------------------
    Rectangle {
        width: parent.width
        height: 32
        color: linha.aberto ? Qt.rgba(0.22, 0.78, 0.91, 0.06) : "transparent"

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 2
            height: parent.height - 8
            color: linha.aberto ? Tema.ciano : "transparent"
        }
        Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.verticalCenter: parent.verticalCenter
            text: linha.aberto ? "▸" : ""
            color: Tema.ciano
            font.pixelSize: 10
            renderType: Text.NativeRendering
        }
        Text {
            textFormat: Text.PlainText
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            text: linha.provedor.nome || ""
            color: linha.aberto ? Tema.textoForte : Tema.texto
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
                visible: linha.naNuvem
                text: linha.provedor.ligado ? "ligado" : "desligado"
                color: linha.provedor.ligado ? Tema.positivo : Tema.textoFraco
            }
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: linha.provedor.onde || ""
                opacity: linha.naNuvem ? 0.95 : 0.7
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
            onClicked: ponte.escolherProvedor(linha.provedor.papel, linha.provedor.chave)
        }
    }

    // --- o que se escolhe dentro dele ---------------------------------------------------------
    Column {
        visible: linha.aberto && (linha.modelos.length > 0 || linha.naNuvem)
        x: 28
        width: parent.width - 38
        topPadding: 10
        bottomPadding: 12
        spacing: 10

        Flow {
            width: parent.width
            spacing: 8
            visible: linha.modelos.length > 0
            Rotulo { text: "modelo"; height: 26; verticalAlignment: Text.AlignVCenter }
            Repeater {
                model: linha.modelos
                Ficha {
                    texto: modelData.modelo
                    nota: modelData.nota
                    ativo: modelData.escolhido
                    onEscolhida: ponte.definirCampo(modelData.campo, modelData.valor)
                }
            }
        }

        // A voz da conta (ElevenLabs): o id escrito à mão, ou escolhido da lista que a conta
        // devolve. A consulta leva só a chave — nenhum texto do dono sai por ela.
        Column {
            visible: linha.daElevenLabs
            width: parent.width
            spacing: 8
            Row {
                spacing: 8
                Rotulo { text: "voz"; height: 28; verticalAlignment: Text.AlignVCenter }
                Rectangle {
                    width: 220
                    height: 28
                    color: "transparent"
                    border.width: 1
                    border.color: campoDaVoz.activeFocus ? Tema.cianoFraco : Tema.linha
                    TextInput {
                        id: campoDaVoz
                        anchors.fill: parent
                        anchors.margins: 7
                        text: ponte ? ponte.configuracao.voz_elevenlabs : ""
                        color: Tema.texto
                        font.family: Tema.fonteDados
                        font.pixelSize: Tema.tamanhoTexto - 3
                        clip: true
                        onEditingFinished: ponte.definirCampo("voz_elevenlabs", text.trim())
                    }
                    Rotulo {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: "voice_id"
                        visible: campoDaVoz.text === "" && !campoDaVoz.activeFocus
                    }
                }
                Botao { texto: "buscar vozes da conta"; onApertado: ponte.buscarVozes() }
            }
            Nota {
                width: parent.width
                text: ponte && ponte.vozesFrase !== ""
                      ? ponte.vozesFrase
                      : "a busca manda só a sua chave à elevenlabs — nenhum texto seu sai"
                wrapMode: Text.WordWrap
            }
            Flow {
                width: parent.width
                spacing: 6
                visible: ponte && ponte.vozesDaConta.length > 0
                Repeater {
                    model: ponte ? ponte.vozesDaConta.slice(0, 18) : []
                    Ficha {
                        texto: modelData.nome
                        nota: modelData.portugues ? "pt" : ""
                        ativo: ponte.configuracao.voz_elevenlabs === modelData.id
                        onEscolhida: ponte.definirCampo("voz_elevenlabs", modelData.id)
                    }
                }
            }
        }

        // O interruptor. Desligado: o aviso, e só depois o botão. O aviso vem do registro e é
        // longo (termos, retenção, treino, uso comercial): numa caixa de altura limitada, em
        // frases separadas e legíveis, ele não empurra o botão para fora da tela — e "ler tudo"
        // abre o resto sem tirar o botão do lugar.
        Rectangle {
            id: caixaDoAviso
            objectName: "caixaDoAviso"
            property bool inteiro: false
            readonly property var frases: (linha.provedor.aviso || "")
                .split(/\.\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])/)
                .filter(function (f) { return f.trim() !== "" })
            readonly property int frasesRecolhido: 2
            readonly property real tetoInteiro: 300
            visible: linha.naNuvem && !linha.provedor.ligado && frases.length > 0
            width: parent.width
            height: cabecalhoDoAviso.height + rolagemDoAviso.height + 18
            color: "transparent"
            border.width: 1
            border.color: Tema.linha
            radius: Tema.raioModulo

            Rectangle {
                width: 2
                height: parent.height
                color: Tema.alerta
                opacity: 0.85
            }
            Item {
                id: cabecalhoDoAviso
                x: 14
                y: 8
                width: parent.width - 26
                height: 18
                Rotulo {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "o que sai da máquina com " + (linha.provedor.nome || "")
                    color: Tema.alerta
                }
                Rotulo {
                    id: alternar
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    visible: caixaDoAviso.frases.length > caixaDoAviso.frasesRecolhido
                    text: caixaDoAviso.inteiro
                          ? "recolher"
                          : "ler tudo (+" + (caixaDoAviso.frases.length
                                             - caixaDoAviso.frasesRecolhido) + ")"
                    destaque: toqueDoAlternar.containsMouse
                    MouseArea {
                        id: toqueDoAlternar
                        anchors.fill: parent
                        anchors.margins: -6
                        hoverEnabled: true
                        onClicked: caixaDoAviso.inteiro = !caixaDoAviso.inteiro
                    }
                }
            }
            Flickable {
                id: rolagemDoAviso
                x: 14
                anchors.top: cabecalhoDoAviso.bottom
                anchors.topMargin: 6
                width: parent.width - 26
                // Recolhido mostra frases **inteiras** (as primeiras); aberto, todas, com teto e
                // rolagem por dentro. Cortar no meio de uma linha parecia defeito.
                height: Math.min(corpoDoAviso.implicitHeight, caixaDoAviso.tetoInteiro)
                contentHeight: corpoDoAviso.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                interactive: contentHeight > height
                Behavior on height { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                Column {
                    id: corpoDoAviso
                    width: rolagemDoAviso.width
                    spacing: 5
                    Repeater {
                        model: caixaDoAviso.inteiro
                               ? caixaDoAviso.frases
                               : caixaDoAviso.frases.slice(0, caixaDoAviso.frasesRecolhido)
                        Row {
                            width: corpoDoAviso.width
                            spacing: 8
                            Text {
                                textFormat: Text.PlainText
                                text: "—"
                                color: Tema.textoFraco
                                font.pixelSize: Tema.tamanhoTexto - 2
                                renderType: Text.NativeRendering
                            }
                            Text {
                                textFormat: Text.PlainText
                                width: parent.width - 18
                                text: modelData.trim() + (/[.!?)]$/.test(modelData.trim()) ? "" : ".")
                                color: Tema.texto
                                font.pixelSize: Tema.tamanhoTexto - 2
                                lineHeight: 1.25
                                wrapMode: Text.WordWrap
                                renderType: Text.NativeRendering
                            }
                        }
                    }
                }
            }
            // Quando há mais texto embaixo, uma linha fina diz isso — sem sombra nem degradê.
            Rectangle {
                visible: rolagemDoAviso.interactive && !rolagemDoAviso.atYEnd
                x: 14
                anchors.top: rolagemDoAviso.bottom
                width: rolagemDoAviso.width
                height: 1
                color: Tema.alerta
                opacity: 0.4
            }
        }
        Row {
            visible: linha.naNuvem
            spacing: 12
            Botao {
                objectName: "botaoDaNuvem"
                texto: linha.provedor.ligado ? "desligar" : "li o aviso — ligar " + linha.provedor.nome
                onApertado: ponte.ligarNuvem(linha.provedor.motor, !linha.provedor.ligado)
            }
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: linha.provedor.ligado
                      ? "ligado: " + linha.provedor.motor + " — salvar guarda no arquivo"
                      : "escolhido e desligado: nada sai daqui"
            }
        }
    }
}
