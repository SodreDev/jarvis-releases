import QtQuick
import QtQuick.Shapes
import JarvisUI

// O núcleo: anéis concêntricos, marcadores e um pulso radial (ADR-0019).
//
// Regra do dono, e ela está na estrutura: **os anéis só giram quando há processamento**.
// Animação decorativa permanente é o que transforma um painel técnico em protetor de tela —
// e, pior, tira do movimento qualquer significado. Parado é parado.
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

    // anel externo: tracejado por marcadores, gira devagar só em processamento
    Item {
        id: anelExterno
        anchors.centerIn: parent
        width: hud.escala * 2
        height: width
        // No modo de execução o núcleo cabe numa célula: marcador de 4 px ali vira sujeira.
        visible: hud.escala > 44
        Repeater {
            model: 72
            Rectangle {
                readonly property real ang: index * (Math.PI * 2 / 72)
                width: index % 6 === 0 ? 9 : 4
                height: 1
                color: index % 6 === 0 ? Tema.cianoFraco : Tema.linhaForte
                opacity: index % 6 === 0 ? 0.9 : 0.55
                x: anelExterno.width / 2 + Math.cos(ang) * (hud.escala - 10) - width / 2
                y: anelExterno.height / 2 + Math.sin(ang) * (hud.escala - 10) - height / 2
                transform: Rotation { origin.x: width / 2; origin.y: height / 2;
                                      angle: index * (360 / 72) }
            }
        }
        RotationAnimation on rotation {
            running: hud.processando
            from: 0; to: 360; duration: 24000; loops: Animation.Infinite
        }
    }

    // anel médio: arco aberto, gira no sentido contrário
    Shape {
        anchors.centerIn: parent
        width: hud.escala * 1.5
        height: width
        ShapePath {
            strokeColor: hud.corDoEstado
            strokeWidth: 1
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: hud.escala * 0.75; centerY: hud.escala * 0.75
                radiusX: hud.escala * 0.72; radiusY: hud.escala * 0.72
                startAngle: -60; sweepAngle: 150
            }
        }
        ShapePath {
            strokeColor: Tema.linhaForte
            strokeWidth: 1
            fillColor: "transparent"
            PathAngleArc {
                centerX: hud.escala * 0.75; centerY: hud.escala * 0.75
                radiusX: hud.escala * 0.72; radiusY: hud.escala * 0.72
                startAngle: 110; sweepAngle: 200
            }
        }
        RotationAnimation on rotation {
            running: hud.processando
            from: 360; to: 0; duration: 9000; loops: Animation.Infinite
        }
    }

    // anel interno fino
    Shape {
        anchors.centerIn: parent
        width: hud.escala
        height: width
        ShapePath {
            strokeColor: Tema.linhaClara
            strokeWidth: 1
            fillColor: "transparent"
            PathAngleArc {
                centerX: hud.escala * 0.5; centerY: hud.escala * 0.5
                radiusX: hud.escala * 0.48; radiusY: hud.escala * 0.48
                startAngle: 0; sweepAngle: 360
            }
        }
    }

    // pulso radial: um anel que nasce no centro e some na borda, só em processamento
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

    Column {
        anchors.centerIn: parent
        spacing: 8
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "JARVIS"
            color: Tema.textoForte
            font.pixelSize: Math.max(13, hud.escala * 0.18)
            font.letterSpacing: Math.max(4, hud.escala * 0.06)
            renderType: Text.NativeRendering
            visible: hud.escala > 48
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 7
            visible: hud.escala > 48
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
