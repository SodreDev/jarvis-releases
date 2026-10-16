import QtQuick
import JarvisUI

// A tela inteira (ADR-0019): um workspace conduzido pela IA, não um painel de widgets.
//
// A composição é sempre a mesma — barra escondida à esquerda, relógio e indicadores no topo,
// núcleo no meio, conversa embaixo —; o que muda com o modo é **o tamanho do núcleo e o que
// ocupa a grade**. Nenhum módulo é desenhado aqui: eles vêm do modelo que o gerente de
// workspace publica, e a posição de cada um é a que ele decidiu.
Rectangle {
    id: tela
    width: 1440
    height: 900
    color: Tema.fundo
    focus: true

    // Verdadeiro quando ninguém está com o mouse nisto (a captura das telas).
    property bool semPonteiro: false

    readonly property int colunas: 12
    readonly property int linhas: 8
    readonly property real celulaLargura: (area.width + Tema.espacamento) / colunas
    readonly property real celulaAltura: (area.height + Tema.espacamento) / linhas

    function posX(coluna) { return coluna * celulaLargura }
    function posY(linha) { return linha * celulaAltura }
    function medida(quantidade, celula) { return quantidade * celula - Tema.espacamento }

    // --- fundo: linhas técnicas finas, quase invisíveis ---------------------------------
    Item {
        anchors.fill: parent
        opacity: 0.5
        Repeater {
            model: 24
            Rectangle {
                width: 1; height: tela.height
                x: (index + 1) * tela.width / 25
                color: Tema.linha
                opacity: 0.25
            }
        }
        Repeater {
            model: 12
            Rectangle {
                height: 1; width: tela.width
                y: (index + 1) * tela.height / 13
                color: Tema.linha
                opacity: 0.18
            }
        }
    }

    BarraLateral {
        id: lateral
        height: parent.height
        semPonteiro: tela.semPonteiro
        modo: ponte ? ponte.modo : "assistente"
        onEscolhido: function (chave) {
            if (chave === "configuracao" || chave === "diagnostico")
                ponte.abrirPainel(chave)
            else
                ponte.definirModo(chave)
        }
    }

    // --- topo ----------------------------------------------------------------------------
    Column {
        id: relogio
        anchors.top: parent.top
        anchors.topMargin: Tema.margem
        anchors.left: lateral.right
        anchors.leftMargin: Tema.margem + 4
        spacing: 2
        Text {
            textFormat: Text.PlainText
            text: ponte ? ponte.relogio : "--:--"
            color: Tema.textoForte
            font.pixelSize: 30
            font.letterSpacing: 2
            renderType: Text.NativeRendering
        }
        Rotulo { text: ponte ? ponte.data : "" }
    }

    Indicadores {
        id: indicadores
        anchors.top: parent.top
        anchors.topMargin: Tema.margem + 6
        anchors.right: parent.right
        anchors.rightMargin: Tema.margem
        medidas: ponte ? ponte.medidas : []
    }

    Row {
        anchors.verticalCenter: relogio.verticalCenter
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 12
        Rotulo { text: "modo"; }
        Rotulo { text: ponte ? ponte.modoFrase : ""; destaque: true }
        Rectangle { width: 1; height: 12; color: Tema.linha; anchors.verticalCenter: parent.verticalCenter }
        Rotulo { text: ponte ? ponte.estadoFrase : "" }
        // O microfone como a fonte **está** (arquivo do F1-13) e o modo de escuta vivo
        // (ADR-0021). Mora no núcleo quando ele é grande; quando encolhe, sobe para cá —
        // um lugar só de cada vez, para não repetir a mesma frase na tela.
        Rectangle {
            visible: !hud.amplo
            width: 1; height: 12; color: Tema.linha; anchors.verticalCenter: parent.verticalCenter
        }
        IndicadorDeEscuta {
            objectName: "indicadorNoCabecalho"
            visible: !hud.amplo
            microfone: ponte ? ponte.microfone : ({})
        }
    }

    // --- área de trabalho -----------------------------------------------------------------
    Item {
        id: area
        anchors.left: lateral.right
        anchors.leftMargin: Tema.margem
        anchors.right: parent.right
        anchors.rightMargin: Tema.margem
        anchors.top: relogio.bottom
        anchors.topMargin: Tema.margem
        anchors.bottom: rodape.top
        anchors.bottomMargin: Tema.margem

        // a consulta em curso, no modo de pesquisa: uma faixa fina, não uma caixa de busca
        Rectangle {
            id: faixaDeConsulta
            visible: ponte && ponte.modo === "pesquisa" && ponte.consulta !== ""
            x: tela.posX(2)
            y: tela.posY(0)
            width: tela.medida(10, tela.celulaLargura)
            height: 46
            color: Tema.fundoModulo
            opacity: 0.97
            radius: Tema.raioModulo
            border.width: 1
            border.color: Tema.linha
            Text {
                textFormat: Text.PlainText
                id: lupa
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "⌕"
                color: Tema.ciano
                font.pixelSize: 15
                renderType: Text.NativeRendering
            }
            Rotulo {
                id: criterio
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "organizado por importância"
            }
            Text {
                textFormat: Text.PlainText
                anchors.left: lupa.right
                anchors.leftMargin: 14
                anchors.right: criterio.left
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: ponte ? ponte.consulta : ""
                color: Tema.texto
                font.pixelSize: Tema.tamanhoTexto
                elide: Text.ElideRight
                renderType: Text.NativeRendering
            }
        }

        Hud {
            id: hud
            x: tela.posX(ponte ? ponte.nucleo.coluna : 4)
            y: tela.posY(ponte ? ponte.nucleo.linha : 1)
            width: tela.medida(ponte ? ponte.nucleo.colunas : 4, tela.celulaLargura)
            height: tela.medida(ponte ? ponte.nucleo.linhas : 4, tela.celulaAltura)
            processando: ponte ? ponte.processando : false
            estado: ponte ? ponte.estado : "parado"
            estadoFrase: ponte ? ponte.estadoFrase : ""
            microfone: ponte ? ponte.microfone : ({})
            Behavior on x { NumberAnimation { duration: 420; easing.type: Easing.InOutCubic } }
            Behavior on y { NumberAnimation { duration: 420; easing.type: Easing.InOutCubic } }
            Behavior on width { NumberAnimation { duration: 420; easing.type: Easing.InOutCubic } }
            Behavior on height { NumberAnimation { duration: 420; easing.type: Easing.InOutCubic } }
        }

        // as últimas falas, flutuando ao lado do núcleo (só no modo assistente)
        Column {
            id: falas
            visible: ponte && ponte.modo === "assistente"
            anchors.left: hud.right
            anchors.leftMargin: Tema.espacamento * 2
            anchors.verticalCenter: hud.verticalCenter
            width: Math.max(200, tela.celulaLargura * 3)
            spacing: 10
            Repeater {
                model: ponte ? ponte.transcricao.slice(-3) : []
                Rectangle {
                    width: falas.width
                    height: Math.max(38, textoDaFala.implicitHeight + 22)
                    color: Tema.fundoModulo
                    opacity: 0.95
                    radius: Tema.raioModulo
                    border.width: 1
                    border.color: Tema.linha
                    Text {
                        textFormat: Text.PlainText
                        id: textoDaFala
                        anchors.fill: parent
                        anchors.margins: 11
                        text: modelData.texto
                        color: modelData.quem === "dono" ? Tema.textoFraco : Tema.texto
                        font.pixelSize: Tema.tamanhoTexto - 2
                        wrapMode: Text.WordWrap
                        maximumLineCount: 3
                        elide: Text.ElideRight
                        renderType: Text.NativeRendering
                    }
                }
            }
        }

        Repeater {
            model: ponte ? ponte.modulos : null
            Modulo {
                widgetId: model.widgetId
                titulo: model.titulo
                vista: model.vista
                estado: model.estado
                dados: model.dados
                fixado: model.fixado
                foco: model.foco
                demonstracao: model.demonstracao
                maximizado: model.maximizado
                componenteCodigo: model.componente === "codigo"
                coluna: model.coluna
                linha: model.linha
                celulaLargura: tela.celulaLargura
                celulaAltura: tela.celulaAltura
                x: tela.posX(model.coluna)
                y: tela.posY(model.linha)
                width: tela.medida(model.colunas, tela.celulaLargura)
                height: tela.medida(model.linhas, tela.celulaAltura)
                opacity: model.minimizado ? 0 : 1
                visible: opacity > 0.01
                z: model.maximizado ? 30 : (model.foco ? 20 : 10)
            }
        }
    }

    // --- rodapé ---------------------------------------------------------------------------
    Column {
        id: rodape
        anchors.left: lateral.right
        anchors.leftMargin: Tema.margem
        anchors.right: parent.right
        anchors.rightMargin: Tema.margem
        anchors.bottom: parent.bottom
        anchors.bottomMargin: Tema.margem
        spacing: 10

        Row {
            spacing: 10
            visible: ponte && ponte.fechados.length > 0
            Rotulo { anchors.verticalCenter: parent.verticalCenter; text: "fechados" }
            Repeater {
                model: ponte ? ponte.fechados : []
                Botao { texto: modelData.titulo; onApertado: ponte.recuperarModulo(modelData.id) }
            }
        }

        Pendencias {
            width: parent.width
            pendentes: ponte ? ponte.pendentes : []
        }

        // A linha de estado: uma frase curta em português, que aparece quando algo muda e
        // **some sozinha**. Nada de nome de ação interna, e nada que fique parado na tela.
        // Um Item de altura fixa em volta: o Column não posiciona item com opacidade 0, e a
        // linha entrava e saía do layout a cada frase — a grade de cima pulava junto.
        Item {
            objectName: "linhaDeEstado"
            width: parent.width
            height: 18
            Row {
                spacing: 14
                opacity: 0
                height: 18
                Behavior on opacity { NumberAnimation { duration: 260 } }

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 4; height: 4; radius: 2
                    color: Tema.cianoFraco
                    // Sem frase, sem marca: um ponto solto acima da barra é enfeite sem dono.
                    visible: mudanca.text !== ""
                }
                Rotulo {
                    id: mudanca
                    anchors.verticalCenter: parent.verticalCenter
                    text: ponte ? ponte.ultimaMudanca : ""
                    color: Tema.textoFraco
                    // `mudanca.text`, não `text`: o sinal traz um parâmetro com esse nome, e usá-lo
                    // direto é injeção de parâmetro — depreciada, e um aviso no console.
                    onTextChanged: if (mudanca.text !== "") sumir.restart()
                }
                Rotulo {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ponte ? ponte.aviso : ""
                    color: Tema.ciano
                    visible: text !== ""
                }

                Timer {
                    id: sumir
                    interval: 6000
                    onTriggered: parent.opacity = 0
                    onRunningChanged: if (running) parent.opacity = 1
                }
            }
        }

        BarraDeConversa {
            id: conversa
            width: parent.width
            conversaViva: ponte ? ponte.conversaViva : false
            estado: ponte ? ponte.estado : "parado"
            microfone: ponte ? ponte.microfone : ({})
            atalho: ponte ? ponte.escuta.atalho : ""
            onEnviou: function (texto) { ponte.enviarTexto(texto) }
            onSegurou: ponte.segurar()
            onSoltou: ponte.soltar()
            onParou: ponte.pararConversa()
            onComecou: ponte.iniciarConversa()
        }
    }

    // --- teclado --------------------------------------------------------------------------
    Keys.onPressed: function (evento) {
        if (evento.isAutoRepeat)
            return
        if (evento.key === Qt.Key_B && (evento.modifiers & Qt.ControlModifier)) {
            lateral.presa = !lateral.presa
            evento.accepted = true
        } else if (ehOAtalho(evento)) {
            if (!ponte.conversaViva)
                ponte.iniciarConversa()
            ponte.segurar()
            evento.accepted = true
        } else if (evento.key === Qt.Key_Escape) {
            ponte.interromper()
            evento.accepted = true
        } else if (evento.key === Qt.Key_1) {
            ponte.definirModo("assistente")
        } else if (evento.key === Qt.Key_2) {
            ponte.definirModo("pesquisa")
        } else if (evento.key === Qt.Key_3) {
            ponte.definirModo("execucao")
        }
    }
    // O atalho de segurar-para-falar com a janela em foco: a combinação que o dono capturou, ou
    // a barra de espaço. Com a janela fora de foco, só o portal do sistema (ADR-0021).
    function ehOAtalho(evento) {
        if (!ponte || ponte.atalhoTecla === 0)
            return evento.key === Qt.Key_Space
        var mascara = Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier
        return evento.key === ponte.atalhoTecla
               && (evento.modifiers & mascara) === ponte.atalhoModificadores
    }
    Keys.onReleased: function (evento) {
        var tecla = ponte && ponte.atalhoTecla !== 0 ? ponte.atalhoTecla : Qt.Key_Space
        if (!evento.isAutoRepeat && evento.key === tecla) {
            ponte.soltar()
            evento.accepted = true
        }
    }
}
