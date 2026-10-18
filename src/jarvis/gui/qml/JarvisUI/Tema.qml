pragma Singleton
import QtQuick

// O tema (ADR-0019): quase preto, linha técnica fina, ciano discreto.
//
// Os valores moram aqui porque "discreto" é uma decisão, não um gosto de cada tela: um ciano
// a mais em cada arquivo vira neon em três semanas. Quem quiser destacar algo usa `ciano`
// numa linha de 1 px ou num rótulo de 10 px — nunca num preenchimento grande.
QtObject {
    readonly property color fundo: "#05070b"
    readonly property color fundoProfundo: "#03050a"
    readonly property color fundoModulo: "#080d14"
    readonly property color linha: "#13202b"
    readonly property color linhaForte: "#1c3344"
    readonly property color linhaClara: "#1d3242"
    readonly property color ciano: "#39c7e8"
    readonly property color cianoFraco: "#1a5d76"
    readonly property color texto: "#c6d5e0"
    // 5,2:1 sobre o fundo dos módulos. Era #647b8c (4,4:1), abaixo do mínimo de 4,5:1 para
    // texto de 10–12 px — e é a cor de quase todo rótulo da janela.
    readonly property color textoFraco: "#71879a"
    readonly property color textoForte: "#e8f4fb"
    readonly property color alerta: "#e0a44a"
    readonly property color positivo: "#5fd3a0"
    readonly property color perigo: "#e5736a"

    readonly property int raioModulo: 2
    readonly property int espacamento: 14
    readonly property int margem: 22

    readonly property string fonteDados: "monospace"
    readonly property int tamanhoRotulo: 10
    readonly property int tamanhoTitulo: 12
    readonly property int tamanhoTexto: 13
    readonly property real espacoEntreLetras: 1.6
    readonly property int duracao: 260
}
