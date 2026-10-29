import QtQuick
import JarvisUI

// Presets de modelo (ADR-0056): em cima, o preset ativo de cada papel; embaixo, um preset novo —
// provedor → modelo (com o que ele faz) → esforço → nome e papel.
//
// As regras são as da caixa de voz. Escolher, salvar e ativar **não** ligam nuvem: o aviso
// montado do registro aparece inteiro antes do botão de ligar, e ligar vale nesta sessão até o
// "salvar configuração". Id, nome e preço de modelo vêm do provedor — dado de terceiros, por isso
// todo texto aqui é puro e nada vira marcação. O que cada clique grava e o que cada frase diz vêm
// prontos do Python (`jarvis.gui.modelos`): esta tela só desenha e repassa.
Column {
    id: painel
    objectName: "painelDeModelos"
    width: parent ? parent.width : 0
    spacing: 16

    readonly property var modelos: ponte ? ponte.modelos : null
    readonly property var presets: modelos ? modelos.presets : []
    readonly property var ativos: modelos ? modelos.ativos : ({})
    readonly property var provedores: modelos ? modelos.provedores : []
    readonly property var listagem: modelos ? modelos.listagem : ({})
    readonly property var arquivo: modelos ? modelos.arquivo : ({})
    readonly property string aberto: listagem.provedor || ""
    readonly property var provedor: provedorDe(aberto)
    readonly property bool naNuvem: provedor.onde === "nuvem"
    readonly property bool daDecisao: (provedor.papeis || []).indexOf("jev") >= 0
    // O preset novo. Modelo vazio = o padrão do provedor; esforço vazio = o provedor decide.
    property string modelo: ""
    property string esforco: ""
    property string papel: ""
    // O campo do filtro também aceita um id escrito à mão: o modelo não precisa estar numa lista
    // para ser chamado — quem diz se ele existe é o provedor (ADR-0056, seção 2).
    readonly property string escrito: campoFiltro.text.trim()
    readonly property string filtro: escrito.toLowerCase()
    readonly property bool escritoNaLista: (listagem.modelos || []).some(function (m) {
        return m.id === painel.escrito
    })
    // Uma lista de provedor tem centenas de modelos (o OpenRouter): a tela mostra os primeiros e
    // o filtro acha o resto, sem uma rolagem dentro da outra.
    readonly property int teto: 12
    readonly property var nomes: ({
        "cerebro": "cérebro",
        "jev": "jev",
        "visao": "visão",
        "resumo": "resumo"
    })
    readonly property var semPreset: ({
        "jev": "nenhum: vale o modelo do registro de motores",
        "visao": "nenhum: com um cérebro que não vê, a imagem não vai",
        "resumo": "nenhum preset"
    })
    readonly property var filtrados: {
        var lista = painel.listagem.modelos || []
        var procura = painel.filtro
        if (procura === "")
            return lista
        return lista.filter(function (m) {
            return m.id.toLowerCase().indexOf(procura) >= 0
                   || (m.nome || "").toLowerCase().indexOf(procura) >= 0
        })
    }
    // Só os esforços que o modelo aceita, quando ele diz; senão todos. Relidos quando a lista
    // muda (a de agora pode dizer o que a do registro não dizia).
    readonly property var esforcosAceitos: {
        var lista = painel.listagem
        if (!painel.modelos || painel.aberto === "" || !lista)
            return []
        return painel.modelos.esforcosDe(painel.aberto, painel.modelo)
    }
    // O nome digitado já é de um preset: salvar o substitui. Relido depois de salvar ou apagar.
    readonly property string existente: {
        var lista = painel.presets
        var nome = campoNome.text.trim()
        return painel.modelos && lista && nome !== "" ? painel.modelos.nomeExistente(nome) : ""
    }

    function provedorDe(id) {
        for (var i = 0; i < painel.provedores.length; ++i) {
            if (painel.provedores[i].id === id)
                return painel.provedores[i]
        }
        return ({})
    }

    function nomeDoPapel(id) {
        return painel.nomes[id] || id
    }

    onAbertoChanged: {
        var papeis = provedorDe(aberto).papeis || []
        modelo = ""
        esforco = ""
        campoFiltro.text = ""
        if (papeis.indexOf(papel) < 0)
            papel = papeis.length > 0 ? papeis[0] : ""
    }
    onEsforcosAceitosChanged: {
        if (esforcosAceitos.indexOf(esforco) < 0)
            esforco = ""
    }

    // Um modelo da lista: o id (dado do provedor, sem caixa alta) e o que ele faz.
    component LinhaDeModelo: Rectangle {
        id: linhaDeModelo
        property string ident: ""
        property string nome: ""
        property string resumo: ""
        property bool escolhido: false
        signal escolhida()
        width: parent ? parent.width : 0
        height: textos.implicitHeight + 10
        radius: Tema.raioModulo
        color: escolhido ? Qt.rgba(0.22, 0.78, 0.91, 0.08) : "transparent"
        border.width: 1
        border.color: escolhido || toque.containsMouse ? Tema.cianoFraco : "transparent"
        Column {
            id: textos
            x: 10
            y: 5
            width: parent.width - 20
            spacing: 2
            Text {
                textFormat: Text.PlainText
                width: parent.width
                text: linhaDeModelo.ident
                      + (linhaDeModelo.nome !== "" && linhaDeModelo.nome !== linhaDeModelo.ident
                         ? "  ·  " + linhaDeModelo.nome : "")
                elide: Text.ElideRight
                color: linhaDeModelo.escolhido ? Tema.textoForte : Tema.texto
                font.family: Tema.fonteDados
                font.pixelSize: Tema.tamanhoTexto - 3
                renderType: Text.NativeRendering
            }
            Text {
                textFormat: Text.PlainText
                width: parent.width
                visible: linhaDeModelo.resumo !== ""
                text: linhaDeModelo.resumo
                wrapMode: Text.WordWrap
                color: Tema.textoFraco
                font.pixelSize: Tema.tamanhoTexto - 4
                renderType: Text.NativeRendering
            }
        }
        MouseArea {
            id: toque
            anchors.fill: parent
            hoverEnabled: true
            onClicked: linhaDeModelo.escolhida()
        }
    }

    // --- onde os presets moram -------------------------------------------------------------------
    Column {
        width: parent.width
        spacing: 4
        Text {
            textFormat: Text.PlainText
            width: parent.width
            text: painel.arquivo.caminho
                  ? "presets em " + painel.arquivo.caminho
                    + (painel.arquivo.doDono ? "" : " (ainda os do Jarvis: o arquivo nasce ao salvar)")
                  : "sem pasta de configuração: valem os presets do Jarvis, e nada se grava"
            color: Tema.textoFraco
            font.family: Tema.fonteDados
            font.pixelSize: Tema.tamanhoTexto - 4
            wrapMode: Text.WrapAnywhere
            renderType: Text.NativeRendering
        }
        Repeater {
            model: painel.arquivo.avisos || []
            Nota {
                width: parent.width
                alerta: true
                text: modelData
            }
        }
    }

    // --- o ativo de cada papel -------------------------------------------------------------------
    Column {
        objectName: "ativosPorPapel"
        width: parent.width
        spacing: 10
        Repeater {
            model: painel.modelos ? painel.modelos.papeis : []
            Column {
                id: linhaDoPapel
                readonly property string papel: modelData
                readonly property var doPapel: painel.presets.filter(function (p) {
                    return p.papel === linhaDoPapel.papel
                })
                readonly property string ativo: painel.ativos[papel] || ""
                readonly property var escolhido: {
                    for (var i = 0; i < doPapel.length; ++i) {
                        if (doPapel[i].nome === ativo)
                            return doPapel[i]
                    }
                    return null
                }
                // Apagar pede dois cliques: o primeiro só pergunta, e a pergunta é presa ao nome —
                // trocar o ativo no meio não passa a confirmação para outro preset.
                property string apagando: ""
                readonly property bool confirmando: escolhido !== null && apagando === escolhido.nome
                width: parent.width
                spacing: 4
                Flow {
                    width: parent.width
                    spacing: 6
                    Rotulo {
                        width: 64
                        height: 30
                        verticalAlignment: Text.AlignVCenter
                        text: painel.nomeDoPapel(linhaDoPapel.papel)
                        color: Tema.texto
                    }
                    Repeater {
                        model: linhaDoPapel.doPapel
                        Botao {
                            objectName: "preset:" + modelData.nome
                            texto: modelData.nome
                            ativo: modelData.nome === linhaDoPapel.ativo
                            onApertado: {
                                linhaDoPapel.apagando = ""
                                painel.modelos.ativar(linhaDoPapel.papel,
                                                      modelData.daConfiguracao ? "" : modelData.nome)
                            }
                        }
                    }
                    Botao {
                        visible: linhaDoPapel.papel !== "cerebro"
                        texto: "nenhum"
                        ativo: linhaDoPapel.ativo === ""
                        onApertado: {
                            linhaDoPapel.apagando = ""
                            painel.modelos.ativar(linhaDoPapel.papel, "")
                        }
                    }
                }
                Item {
                    x: 70
                    width: parent.width - 70
                    height: resumoDoAtivo.implicitHeight
                    Nota {
                        id: resumoDoAtivo
                        width: parent.width - (apagar.visible ? apagar.width + 12 : 0)
                        text: linhaDoPapel.escolhido !== null
                              ? linhaDoPapel.escolhido.resumo
                                + (linhaDoPapel.escolhido.ligado
                                   ? "" : " — desligado: ligue o provedor abaixo, depois do aviso")
                              : (painel.semPreset[linhaDoPapel.papel] || "")
                        alerta: linhaDoPapel.escolhido !== null && !linhaDoPapel.escolhido.ligado
                    }
                    Rotulo {
                        id: apagar
                        anchors.right: parent.right
                        visible: linhaDoPapel.escolhido !== null
                                 && !linhaDoPapel.escolhido.daConfiguracao
                        text: linhaDoPapel.confirmando
                              ? "apagar «" + (linhaDoPapel.escolhido ? linhaDoPapel.escolhido.nome : "") + "»?"
                              : "apagar"
                        color: linhaDoPapel.confirmando ? Tema.perigo : Tema.textoFraco
                        destaque: toqueDoApagar.containsMouse && !linhaDoPapel.confirmando
                        MouseArea {
                            id: toqueDoApagar
                            anchors.fill: parent
                            anchors.margins: -6
                            hoverEnabled: true
                            onClicked: {
                                var nome = linhaDoPapel.escolhido.nome
                                if (!linhaDoPapel.confirmando) {
                                    linhaDoPapel.apagando = nome
                                    return
                                }
                                linhaDoPapel.apagando = ""
                                painel.modelos.apagarPreset(nome)
                            }
                        }
                    }
                }
            }
        }
    }

    // --- um preset novo: provedor → modelo → esforço → nome e papel --------------------------------
    Column {
        width: parent.width
        spacing: 10

        Rectangle {
            width: parent.width
            height: 1
            color: Tema.linha
        }
        Rotulo {
            text: "novo preset"
            color: Tema.texto
        }
        Flow {
            width: parent.width
            spacing: 6
            Repeater {
                objectName: "provedoresDeModelo"
                model: painel.provedores
                Botao {
                    objectName: "provedor:" + modelData.id
                    texto: modelData.apelido
                    ativo: painel.aberto === modelData.id
                    onApertado: painel.modelos.abrirProvedor(painel.aberto === modelData.id
                                                             ? "" : modelData.id)
                }
            }
        }
        Nota {
            width: parent.width
            visible: painel.aberto === ""
            text: "escolha o provedor: a lista de modelos abre sem rede (a guardada ou a do registro)"
        }

        // --- o provedor aberto --------------------------------------------------------------------
        Column {
            objectName: "provedorAberto"
            visible: painel.aberto !== ""
            width: parent.width
            spacing: 10

            Nota {
                width: parent.width
                color: Tema.texto
                text: (painel.provedor.servico || "") + " · " + (painel.provedor.onde || "")
                      + (painel.provedor.variavelDaChave
                         ? " · chave " + painel.provedor.variavelDaChave : "")
            }
            Nota {
                objectName: "faltaDoProvedorDeModelo"
                width: parent.width
                visible: text !== ""
                alerta: true
                text: painel.modelos && painel.modelos.falta !== ""
                      ? "não roda agora: " + painel.modelos.falta : ""
            }

            // Desligado: o aviso montado do registro, e só depois o botão. Recolhido nas primeiras
            // linhas para não empurrar o botão para fora da tela; "ler tudo" abre o resto.
            Rectangle {
                id: caixaDoAviso
                objectName: "avisoDoProvedorDeModelo"
                property bool inteiro: false
                visible: painel.naNuvem && painel.provedor.ligado !== true
                width: parent.width
                height: corpoDoAviso.implicitHeight + 20
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
                Column {
                    id: corpoDoAviso
                    x: 14
                    y: 10
                    width: parent.width - 26
                    spacing: 8
                    Item {
                        width: parent.width
                        height: 18
                        Rotulo {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "o que sai da máquina com " + (painel.provedor.nome || "")
                            color: Tema.alerta
                        }
                        Rotulo {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            text: caixaDoAviso.inteiro ? "recolher" : "ler tudo"
                            destaque: toqueDoAviso.containsMouse
                            MouseArea {
                                id: toqueDoAviso
                                anchors.fill: parent
                                anchors.margins: -6
                                hoverEnabled: true
                                onClicked: caixaDoAviso.inteiro = !caixaDoAviso.inteiro
                            }
                        }
                    }
                    Nota {
                        width: parent.width
                        color: Tema.texto
                        text: painel.provedor.aviso || ""
                        maximumLineCount: caixaDoAviso.inteiro ? 400 : 3
                        elide: Text.ElideRight
                    }
                    Botao {
                        objectName: "ligarProvedorDeModelo"
                        texto: "li o aviso — ligar " + (painel.provedor.nome || "")
                        onApertado: painel.modelos.ligarProvedor(painel.aberto, true)
                    }
                }
            }
            Flow {
                visible: painel.naNuvem && painel.provedor.ligado === true
                width: parent.width
                spacing: 10
                Rotulo {
                    height: 30
                    verticalAlignment: Text.AlignVCenter
                    text: "ligado"
                    color: Tema.positivo
                }
                Botao {
                    texto: "desligar"
                    onApertado: painel.modelos.ligarProvedor(painel.aberto, false)
                }
                Nota {
                    width: parent.width
                    text: "vale nesta sessão; «salvar configuração», no alto desta coluna, guarda no arquivo"
                }
            }

            // --- os modelos -------------------------------------------------------------------
            Flow {
                width: parent.width
                spacing: 10
                Botao {
                    objectName: "buscarModelos"
                    visible: painel.provedor.listaAoVivo === true
                    enabled: !(painel.modelos && painel.modelos.carregando)
                    opacity: enabled ? 1 : 0.5
                    texto: enabled ? "buscar a lista do provedor" : "buscando…"
                    onApertado: painel.modelos.buscarModelos(painel.aberto)
                }
            }
            Nota {
                objectName: "origemDaLista"
                width: parent.width
                text: painel.listagem.frase || ""
            }
            Nota {
                width: parent.width
                visible: text !== ""
                alerta: true
                text: painel.listagem.aviso || ""
            }
            Rectangle {
                visible: !painel.daDecisao
                width: Math.min(300, parent.width)
                height: 28
                color: "transparent"
                radius: Tema.raioModulo
                border.width: 1
                border.color: campoFiltro.activeFocus ? Tema.cianoFraco : Tema.linha
                TextInput {
                    id: campoFiltro
                    objectName: "filtroDeModelos"
                    anchors.fill: parent
                    anchors.margins: 7
                    color: Tema.texto
                    font.family: Tema.fonteDados
                    font.pixelSize: Tema.tamanhoTexto - 3
                    clip: true
                }
                Rotulo {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: "filtrar, ou escrever o id"
                    visible: campoFiltro.text === "" && !campoFiltro.activeFocus
                }
            }
            Column {
                width: parent.width
                spacing: 2
                LinhaDeModelo {
                    ident: "padrão do provedor"
                    resumo: painel.listagem.padrao
                            ? "o do registro: " + painel.listagem.padrao
                            : "sem padrão no registro: a CLI usa o dela; nas APIs, escolha um modelo"
                    escolhido: painel.modelo === ""
                    onEscolhida: painel.modelo = ""
                }
                Repeater {
                    objectName: "modelosDoProvedor"
                    model: painel.filtrados.slice(0, painel.teto)
                    LinhaDeModelo {
                        ident: modelData.id
                        nome: modelData.nome || ""
                        resumo: modelData.resumo || ""
                        escolhido: painel.modelo === modelData.id
                        onEscolhida: painel.modelo = modelData.id
                    }
                }
                Nota {
                    width: parent.width
                    visible: painel.filtrados.length > painel.teto
                    text: "mais " + (painel.filtrados.length - painel.teto) + " — filtre pelo nome"
                }
                LinhaDeModelo {
                    objectName: "modeloEscrito"
                    visible: painel.escrito !== "" && !painel.escritoNaLista && !painel.daDecisao
                    ident: painel.escrito
                    resumo: "fora da lista: o id vai como você escreveu, e quem diz se ele existe é o provedor"
                    escolhido: painel.modelo !== "" && painel.modelo === painel.escrito
                    onEscolhida: painel.modelo = painel.escrito
                }
            }

            // --- esforço, papel e nome ----------------------------------------------------------
            Flow {
                width: parent.width
                spacing: 6
                visible: !painel.daDecisao
                Rotulo {
                    width: 64
                    height: 30
                    verticalAlignment: Text.AlignVCenter
                    text: "esforço"
                }
                Botao {
                    texto: "do provedor"
                    ativo: painel.esforco === ""
                    onApertado: painel.esforco = ""
                }
                Repeater {
                    objectName: "esforcosDoModelo"
                    model: painel.esforcosAceitos
                    Botao {
                        texto: modelData
                        ativo: painel.esforco === modelData
                        onApertado: painel.esforco = modelData
                    }
                }
            }
            Flow {
                width: parent.width
                spacing: 6
                Rotulo {
                    width: 64
                    height: 30
                    verticalAlignment: Text.AlignVCenter
                    text: "papel"
                }
                Repeater {
                    model: painel.provedor.papeis || []
                    Botao {
                        texto: painel.nomeDoPapel(modelData)
                        ativo: painel.papel === modelData
                        onApertado: painel.papel = modelData
                    }
                }
            }
            Flow {
                width: parent.width
                spacing: 8
                Rectangle {
                    width: Math.min(240, parent.width)
                    height: 30
                    color: "transparent"
                    radius: Tema.raioModulo
                    border.width: 1
                    border.color: campoNome.activeFocus ? Tema.cianoFraco : Tema.linha
                    TextInput {
                        id: campoNome
                        objectName: "nomeDoPreset"
                        anchors.fill: parent
                        anchors.margins: 8
                        maximumLength: 40
                        color: Tema.textoForte
                        font.family: Tema.fonteDados
                        font.pixelSize: Tema.tamanhoTexto - 2
                        clip: true
                    }
                    Rotulo {
                        anchors.left: parent.left
                        anchors.leftMargin: 8
                        anchors.verticalCenter: parent.verticalCenter
                        text: "nome do preset"
                        visible: campoNome.text === "" && !campoNome.activeFocus
                    }
                }
                Botao {
                    objectName: "salvarPreset"
                    enabled: campoNome.text.trim() !== "" && painel.papel !== ""
                    opacity: enabled ? 1 : 0.45
                    texto: painel.existente !== ""
                           ? "substituir «" + painel.existente + "»" : "salvar preset"
                    onApertado: painel.modelos.salvarPreset(campoNome.text.trim(), painel.papel,
                                                            painel.aberto, painel.modelo,
                                                            painel.esforco)
                }
            }
            Nota {
                width: parent.width
                text: "vai salvar: " + (painel.provedor.apelido || "") + " · "
                      + (painel.modelo || "modelo padrão") + " · "
                      + (painel.esforco ? "esforço " + painel.esforco : "esforço do provedor")
                      + (painel.papel ? " · para " + painel.nomeDoPapel(painel.papel) : "")
                      + ". Salvar não ativa nem liga nada: escolha-o em cima."
            }
        }
    }

    Nota {
        objectName: "avisoDosModelos"
        width: parent.width
        visible: text !== ""
        text: painel.modelos ? painel.modelos.aviso : ""
        alerta: text.indexOf("não deu") === 0
        color: alerta ? Tema.alerta : Tema.texto
    }
}
