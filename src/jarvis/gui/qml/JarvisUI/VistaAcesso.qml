import QtQuick
import QtQuick.Dialogs
import JarvisUI

// O que o Jarvis pode tocar: pastas, aplicativos e navegadores — três caixas, uma por pergunta.
//
// Cada clique **grava na hora** (`ponte.acesso`): não há "salvar" para lembrar, e a frase de
// estado no topo diz o que aconteceu — salvo, ou recusado e por quê. O que a tela mostra como
// "sempre negado" é a lista de negação do PDP, que nenhum nível apaga.
Item {
    id: vista
    readonly property var acesso: ponte ? ponte.acesso : null
    // Qual caixa aparece: "pastas", "apps" ou "navegadores" (a aba escolhida na configuração).
    property string secao: "pastas"
    // Para qual navegador o seletor de arquivo está escolhendo o binário ("" = incluir novo).
    property string familiaAlvo: ""

    function filtrar(lista, busca) {
        var alvo = (busca || "").toLowerCase()
        if (alvo === "")
            return lista
        return lista.filter(function (a) {
            return a.nome.toLowerCase().indexOf(alvo) >= 0 || a.id.toLowerCase().indexOf(alvo) >= 0
        })
    }

    // O seletor de pasta é o do sistema (no KDE, o portal): o Qt só cai no dele sem portal.
    FolderDialog {
        id: dialogoDePasta
        title: "Escolha uma pasta para o Jarvis poder ler"
        onAccepted: vista.acesso.adicionarRaiz(selectedFolder.toString())
    }
    FileDialog {
        id: dialogoDePrograma
        title: "Escolha um programa ou um atalho .desktop"
        currentFolder: "file:///usr/share/applications"
        onAccepted: vista.acesso.adicionarApp(selectedFile.toString())
    }
    FileDialog {
        id: dialogoDeNavegador
        title: vista.familiaAlvo === ""
               ? "Escolha o programa do navegador"
               : "Escolha o binário de " + vista.familiaAlvo
        currentFolder: "file:///usr/bin"
        onAccepted: {
            if (vista.familiaAlvo === "")
                vista.acesso.adicionarNavegador(selectedFile.toString())
            else
                vista.acesso.escolherBinario(vista.familiaAlvo, selectedFile.toString())
        }
    }

    Item {
        id: frase
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: texto.text === "" ? 0 : texto.implicitHeight + 8
        Text {
            id: texto
            objectName: "fraseDeAcesso"
            textFormat: Text.PlainText
            anchors.top: parent.top
            width: parent.width
            text: vista.acesso ? vista.acesso.frase : ""
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
        contentHeight: colunas.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        clip: true

        Column {
            id: colunas
            width: rolagem.width
            spacing: Tema.espacamento

            // ---------------------------------------------------------------- pastas ------
            Painel {
                width: parent.width
                visible: vista.secao === "pastas"
                titulo: "pastas e arquivos"
                dica: vista.acesso ? "até onde o Jarvis lê" : ""
                Column {
                    width: parent.width
                    spacing: 10

                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: vista.acesso ? vista.acesso.modos : []
                            Botao {
                                objectName: "modo-" + modelData.id
                                texto: modelData.nome
                                ativo: modelData.ativo
                                onApertado: vista.acesso.definirModo(modelData.id)
                            }
                        }
                    }
                    Repeater {
                        model: vista.acesso ? vista.acesso.modos : []
                        Nota {
                            width: parent.width
                            visible: modelData.ativo
                            text: modelData.frase
                            color: Tema.texto
                        }
                    }

                    Rotulo { text: "pastas que você concedeu" }
                    Nota {
                        width: parent.width
                        visible: vista.acesso && vista.acesso.raizes.length === 0
                        text: "Nenhuma ainda. “Adicionar pasta” abre o seletor do sistema; o Jarvis "
                              + "passa a ler aquela pasta e o que há dentro dela. Arquivo solto "
                              + "não entra: escolha a pasta que o contém."
                    }
                    Repeater {
                        model: vista.acesso ? vista.acesso.raizes : []
                        Rectangle {
                            width: parent.width
                            height: 44
                            color: "transparent"
                            border.width: 1
                            border.color: Tema.linha
                            radius: Tema.raioModulo
                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: botoesDaPasta.left
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 2
                                Text {
                                    textFormat: Text.PlainText
                                    text: modelData.nome + (modelData.existe ? "" : "  — não existe mais")
                                    color: modelData.existe ? Tema.textoForte : Tema.alerta
                                    font.pixelSize: Tema.tamanhoTexto - 1
                                    renderType: Text.NativeRendering
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    width: parent.width
                                    text: modelData.caminho
                                    color: Tema.textoFraco
                                    elide: Text.ElideMiddle
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 4
                                    renderType: Text.NativeRendering
                                }
                            }
                            Row {
                                id: botoesDaPasta
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: 6
                                Botao {
                                    objectName: "nivel-" + modelData.nome
                                    texto: modelData.nivel === "escrita" ? "leitura e escrita" : "só leitura"
                                    ativo: modelData.nivel === "escrita"
                                    onApertado: vista.acesso.definirNivelDaRaiz(
                                                    modelData.caminho,
                                                    modelData.nivel === "escrita" ? "leitura" : "escrita")
                                }
                                Botao {
                                    texto: "retirar"
                                    onApertado: vista.acesso.removerRaiz(modelData.caminho)
                                }
                            }
                        }
                    }
                    Botao {
                        objectName: "adicionarPasta"
                        texto: "adicionar pasta…"
                        onApertado: dialogoDePasta.open()
                    }
                    Nota {
                        width: parent.width
                        visible: vista.acesso && vista.acesso.raizes.some(function (r) { return r.nivel === "escrita" })
                        text: "“Leitura e escrita” fica guardada, mas hoje o Jarvis só grava rascunhos "
                              + "na pasta dele, com a sua confirmação — nenhuma ferramenta escreve "
                              + "numa pasta sua ainda."
                    }
                    Nota {
                        width: parent.width
                        text: "Sempre negado, em qualquer nível: "
                              + (vista.acesso ? vista.acesso.negadas.slice(0, 9).join("  ·  ") : "")
                              + (vista.acesso && vista.acesso.negadas.length > 9
                                 ? "  e mais " + (vista.acesso.negadas.length - 9) : "")
                        color: Tema.textoFraco
                    }
                }
            }

            // ----------------------------------------------------------- aplicativos ------
            Painel {
                id: caixaDeApps
                width: parent.width
                visible: vista.secao === "apps"
                titulo: "aplicativos"
                dica: vista.acesso
                      ? vista.acesso.aplicativos.filter(function (a) { return a.autorizado }).length
                        + vista.acesso.aplicativosExtras.length + " liberados"
                      : ""
                Column {
                    width: parent.width
                    spacing: 10
                    Nota {
                        width: parent.width
                        text: "“Abra o Kate” só funciona para o que estiver marcado aqui. Clique para "
                              + "marcar ou desmarcar; vale já, sem salvar."
                    }
                    Rectangle {
                        width: parent.width
                        height: 30
                        color: "transparent"
                        border.width: 1
                        border.color: busca.activeFocus ? Tema.cianoFraco : Tema.linha
                        radius: Tema.raioModulo
                        TextInput {
                            id: busca
                            objectName: "buscaDeApps"
                            anchors.fill: parent
                            anchors.margins: 8
                            color: Tema.textoForte
                            font.pixelSize: Tema.tamanhoTexto - 1
                            clip: true
                        }
                        Rotulo {
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            text: "procurar entre os instalados"
                            visible: busca.text === "" && !busca.activeFocus
                        }
                    }
                    ListView {
                        id: listaDeApps
                        objectName: "listaDeApps"
                        width: parent.width
                        height: Math.max(180, vista.height - 360)
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        model: vista.acesso ? vista.filtrar(vista.acesso.aplicativos, busca.text) : []
                        delegate: Rectangle {
                            width: listaDeApps.width
                            height: 30
                            color: toqueDoApp.containsMouse ? Qt.rgba(0.22, 0.78, 0.91, 0.05) : "transparent"
                            Rectangle {
                                id: caixinha
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                width: 14
                                height: 14
                                color: modelData.autorizado ? Tema.cianoFraco : "transparent"
                                border.width: 1
                                border.color: modelData.autorizado ? Tema.ciano : Tema.linhaForte
                                radius: 2
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.centerIn: parent
                                    visible: modelData.autorizado
                                    text: "✓"
                                    color: Tema.textoForte
                                    font.pixelSize: 10
                                }
                            }
                            Text {
                                textFormat: Text.PlainText
                                anchors.left: caixinha.right
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.nome
                                color: modelData.autorizado ? Tema.textoForte : Tema.texto
                                font.pixelSize: Tema.tamanhoTexto - 1
                                renderType: Text.NativeRendering
                            }
                            Text {
                                textFormat: Text.PlainText
                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                text: modelData.id
                                color: Tema.textoFraco
                                font.family: Tema.fonteDados
                                font.pixelSize: Tema.tamanhoTexto - 4
                                renderType: Text.NativeRendering
                            }
                            MouseArea {
                                id: toqueDoApp
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: vista.acesso.marcarApp(modelData.id, !modelData.autorizado)
                            }
                        }
                    }
                    Rotulo { text: "escolhidos à mão"; visible: vista.acesso && vista.acesso.aplicativosExtras.length > 0 }
                    Repeater {
                        model: vista.acesso ? vista.acesso.aplicativosExtras : []
                        Rectangle {
                            width: parent.width
                            height: 34
                            color: "transparent"
                            border.width: 1
                            border.color: Tema.linha
                            radius: Tema.raioModulo
                            Column {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: tirarExtra.left
                                anchors.rightMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                Text {
                                    textFormat: Text.PlainText
                                    text: modelData.nome + (modelData.existe ? "" : "  — não abre mais")
                                    color: modelData.existe ? Tema.textoForte : Tema.alerta
                                    font.pixelSize: Tema.tamanhoTexto - 2
                                    renderType: Text.NativeRendering
                                }
                                Text {
                                    textFormat: Text.PlainText
                                    width: parent.width
                                    text: modelData.caminho
                                    color: Tema.textoFraco
                                    elide: Text.ElideMiddle
                                    font.family: Tema.fonteDados
                                    font.pixelSize: Tema.tamanhoTexto - 5
                                    renderType: Text.NativeRendering
                                }
                            }
                            Botao {
                                id: tirarExtra
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                anchors.verticalCenter: parent.verticalCenter
                                texto: "retirar"
                                onApertado: vista.acesso.removerApp(modelData.caminho)
                            }
                        }
                    }
                    Row {
                        spacing: 8
                        Botao {
                            objectName: "adicionarPrograma"
                            texto: "escolher programa…"
                            onApertado: dialogoDePrograma.open()
                        }
                        Botao {
                            texto: "atualizar a lista"
                            onApertado: vista.acesso.atualizar()
                        }
                    }
                }
            }

            // ----------------------------------------------------------- navegadores ------
            Painel {
                width: parent.width
                visible: vista.secao === "navegadores"
                titulo: "navegadores"
                dica: vista.acesso
                      ? (vista.acesso.navegadores.filter(function (n) { return n.principal }).map(
                             function (n) { return "principal: " + n.nome })[0] || "padrão do sistema")
                      : ""
                Column {
                    width: parent.width
                    spacing: 10
                    Nota {
                        width: parent.width
                        text: "Quando você pede para abrir um site, ele abre no principal. Com mais de "
                              + "um binário do mesmo navegador (o do pacote, o beta, o Flatpak), "
                              + "escolha qual usar. Sem nenhum escolhido, vale o padrão do sistema."
                    }
                    Nota {
                        width: parent.width
                        visible: vista.acesso && vista.acesso.navegadores.length === 0
                        text: "Nenhum navegador encontrado. “Incluir outro navegador” deixa você "
                              + "apontar o programa à mão."
                        alerta: true
                    }
                    Repeater {
                        model: vista.acesso ? vista.acesso.navegadores : []
                        Rectangle {
                            id: cartao
                            property var navegador: modelData
                            width: parent.width
                            height: topo.height + opcoesDoNavegador.height + 22
                            color: modelData.principal ? Qt.rgba(0.22, 0.78, 0.91, 0.05) : "transparent"
                            border.width: 1
                            border.color: modelData.principal ? Tema.cianoFraco : Tema.linha
                            radius: Tema.raioModulo
                            Item {
                                id: topo
                                anchors.top: parent.top
                                anchors.topMargin: 8
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                height: 30
                                Text {
                                    textFormat: Text.PlainText
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.nome
                                    color: Tema.textoForte
                                    font.pixelSize: Tema.tamanhoTexto
                                    renderType: Text.NativeRendering
                                }
                                Row {
                                    anchors.right: parent.right
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 6
                                    Rotulo {
                                        anchors.verticalCenter: parent.verticalCenter
                                        visible: modelData.principal
                                        destaque: true
                                        text: "principal"
                                    }
                                    Botao {
                                        objectName: "principal-" + modelData.familia
                                        visible: !modelData.principal
                                        texto: "tornar principal"
                                        onApertado: vista.acesso.tornarPrincipal(modelData.familia)
                                    }
                                    Botao {
                                        visible: modelData.manual
                                        texto: "retirar"
                                        onApertado: vista.acesso.retirarNavegador(modelData.familia)
                                    }
                                }
                            }
                            Flow {
                                id: opcoesDoNavegador
                                anchors.top: topo.bottom
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.right: parent.right
                                anchors.rightMargin: 8
                                spacing: 6
                                Rotulo {
                                    height: 26
                                    verticalAlignment: Text.AlignVCenter
                                    text: "binário"
                                }
                                Repeater {
                                    model: modelData.opcoes
                                    Botao {
                                        objectName: "binario-" + cartao.navegador.familia
                                        texto: modelData.rotulo
                                        ativo: modelData.escolhida
                                        onApertado: vista.acesso.escolherBinario(
                                                        cartao.navegador.familia, modelData.entrada)
                                    }
                                }
                                Botao {
                                    texto: "outro binário…"
                                    onApertado: {
                                        vista.familiaAlvo = cartao.navegador.familia
                                        dialogoDeNavegador.open()
                                    }
                                }
                            }
                        }
                    }
                    Botao {
                        objectName: "incluirNavegador"
                        texto: "incluir outro navegador…"
                        onApertado: {
                            vista.familiaAlvo = ""
                            dialogoDeNavegador.open()
                        }
                    }
                }
            }
        }
    }
}
