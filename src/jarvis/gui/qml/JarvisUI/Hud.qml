import QtQuick
import QtQuick.Shapes
import JarvisUI

// O núcleo: anéis concêntricos, marcadores em duas escalas e um arco de estado (ADR-0019).
//
// Regra do dono, e ela está na estrutura: **nada gira sem processamento**. Parado é parado —
// animação decorativa permanente transforma um painel técnico em protetor de tela e tira do
// movimento qualquer significado. Sem brilho, sem sombra, sem partícula: a "vida" vem da
// precisão dos marcadores, não de efeito.
//
// Duas escalas, como num instrumento de verdade: uma régua fina de 3 em 3 graus na borda, e
// uma escala maior de 15 em 15 por dentro, com os quatro pontos cardeais mais longos. O arco
// de estado é o único traço colorido, e a cor diz o estado.
Item {
    id: hud
    property bool processando: false
    property string estadoFrase: ""
    property string estado: "parado"
    property real escala: Math.min(width, height) / 2

    readonly property color corDoEstado: estado === "falando" ? Tema.positivo
        : estado === "pensando" ? Tema.alerta
        : estado === "ouvindo" ? Tema.ciano
        : Tema.cianoFraco
    readonly property bool detalhado: escala > 70

    // --- escala fina da borda: 120 marcas, 3 em 3 graus ------------------------------------
    Item {
        id: reguaFina
        anchors.centerIn: parent
        width: hud.escala * 2
        height: width
        visible: hud.detalhado

        Repeater {
            model: 120
            Rectangle {
                readonly property real ang: index * (Math.PI * 2 / 120)
                width: 4
                height: 1
                color: Tema.linhaClara
                opacity: 0.6
                x: reguaFina.width / 2 + Math.cos(ang) * (hud.escala - 5) - width / 2
                y: reguaFina.height / 2 + Math.sin(ang) * (hud.escala - 5) - height / 2
                transform: Rotation {
                    origin.x: width / 2; origin.y: height / 2
                    angle: index * 3
                }
            }
        }
    }

    // --- escala maior: 24 marcas de 15 em 15, com os cardeais longos -----------------------
    Item {
        id: reguaMaior
        anchors.centerIn: parent
        width: hud.escala * 2
        height: width
        visible: hud.escala > 44

        Repeater {
            model: 24
            Rectangle {
                readonly property bool cardeal: index % 6 === 0
                readonly property real ang: index * (Math.PI * 2 / 24)
                width: cardeal ? 14 : 7
                height: 1
                color: cardeal ? Tema.cianoFraco : Tema.linhaClara
                x: reguaMaior.width / 2 + Math.cos(ang) * (hud.escala - 20) - width / 2
                y: reguaMaior.height / 2 + Math.sin(ang) * (hud.escala - 20) - height / 2
                transform: Rotation {
                    origin.x: width / 2; origin.y: height / 2
                    angle: index * 15
                }
            }
        }
        // o anel gira **devagar** e só em processamento
        RotationAnimation on rotation {
            running: hud.processando
            from: 0; to: 360; duration: 28000; loops: Animation.Infinite
        }
    }

    // --- arco de estado: o único traço colorido, com a marca na ponta ----------------------
    Item {
        id: arcoDeEstado
        anchors.centerIn: parent
        width: hud.escala * 1.56
        height: width

        Shape {
            anchors.fill: parent
            ShapePath {
                strokeColor: hud.corDoEstado
                strokeWidth: 2
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: arcoDeEstado.width / 2; centerY: arcoDeEstado.height / 2
                    radiusX: arcoDeEstado.width / 2; radiusY: arcoDeEstado.height / 2
                    startAngle: -58; sweepAngle: 96
                }
            }
            ShapePath {
                strokeColor: Tema.linhaForte
                strokeWidth: 1
                fillColor: "transparent"
                PathAngleArc {
                    centerX: arcoDeEstado.width / 2; centerY: arcoDeEstado.height / 2
                    radiusX: arcoDeEstado.width / 2; radiusY: arcoDeEstado.height / 2
                    startAngle: 64; sweepAngle: 234
                }
            }
        }
        Rectangle {
            readonly property real ang: 38 * Math.PI / 180
            width: 5; height: 5; radius: 2.5
            color: hud.corDoEstado
            visible: hud.detalhado
            x: arcoDeEstado.width / 2 + Math.cos(ang) * arcoDeEstado.width / 2 - width / 2
            y: arcoDeEstado.height / 2 + Math.sin(ang) * arcoDeEstado.height / 2 - height / 2
        }
        RotationAnimation on rotation {
            running: hud.processando
            from: 360; to: 0; duration: 11000; loops: Animation.Infinite
        }
    }

    // --- anel interno -----------------------------------------------------------------------
    Shape {
        anchors.centerIn: parent
        width: hud.escala * 1.04
        height: width
        ShapePath {
            strokeColor: Tema.linhaClara
            strokeWidth: 1
            fillColor: "transparent"
            PathAngleArc {
                centerX: hud.escala * 0.52; centerY: hud.escala * 0.52
                radiusX: hud.escala * 0.52; radiusY: hud.escala * 0.52
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    // --- pulso radial: nasce no centro e some na borda, só em processamento -----------------
    Rectangle {
        id: pulso
        anchors.centerIn: parent
        width: 0; height: width; radius: width / 2
        color: "transparent"
        border.width: 1
        border.color: hud.corDoEstado
        opacity: 0
        SequentialAnimation on width {
            running: hud.processando
            loops: Animation.Infinite
            NumberAnimation { from: hud.escala * 0.4; to: hud.escala * 1.9; duration: 2400;
                              easing.type: Easing.OutCubic }
            PauseAnimation { duration: 400 }
        }
        SequentialAnimation on opacity {
            running: hud.processando
            loops: Animation.Infinite
            NumberAnimation { from: 0.35; to: 0.0; duration: 2400 }
            PauseAnimation { duration: 400 }
        }
    }

    // --- nome e estado ----------------------------------------------------------------------
    Column {
        anchors.centerIn: parent
        spacing: hud.detalhado ? 8 : 5
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "JARVIS"
            color: Tema.textoForte
            font.pixelSize: Math.max(11, Math.min(hud.escala * 0.18, 34))
            font.letterSpacing: Math.max(3, hud.escala * 0.05)
            renderType: Text.NativeRendering
            visible: hud.escala > 40
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 7
            visible: hud.escala > 40
            Rectangle {
                width: 5; height: 5; radius: 2.5
                anchors.verticalCenter: parent.verticalCenter
                color: hud.corDoEstado
                SequentialAnimation on opacity {
                    running: hud.processando
                    loops: Animation.Infinite
                    NumberAnimation { from: 1; to: 0.25; duration: 700 }
                    NumberAnimation { from: 0.25; to: 1; duration: 700 }
                }
            }
            Rotulo {
                anchors.verticalCenter: parent.verticalCenter
                text: hud.estadoFrase
                color: Tema.textoFraco
            }
        }
    }
}
