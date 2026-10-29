"""A folha de estilo do Jarvis para o conteúdo da tela (ADR-0055): a mesma paleta da janela.

As cores são as de `gui/qml/JarvisUI/Tema.qml` (fundo quase preto, texto `#c6d5e0`, título
`#e8f4fb`, linhas finas `#13202b`/`#1c3344`, ciano `#39c7e8` só em detalhe) — o que o dono aprovou
nas capturas: nada de neon, sombra nem gradiente. Ela vai **antes** da folha do modelo: o que ele
pedir ("tema claro", "o título em azul") vale por cima, como num navegador. O fundo do módulo é o
da janela; o tema claro pede o dele pelo `body` (`HtmlSeguro.fundo`).

As classes prontas (`.fraco`, `.destaque`, `.positivo`, `.alerta`, `.perigo`, `.num`) são as que o
guia de design (`jarvis.tela.guia`) oferece ao modelo: com elas ele não precisa inventar cor.
"""

from __future__ import annotations

from typing import Final

TEXTO: Final = "#c6d5e0"
TEXTO_FORTE: Final = "#e8f4fb"
TEXTO_FRACO: Final = "#71879a"
LINHA: Final = "#13202b"
LINHA_FORTE: Final = "#1c3344"
CIANO: Final = "#39c7e8"
CABECALHO: Final = "#0e1822"
POSITIVO: Final = "#5fd3a0"
ALERTA: Final = "#e0a44a"
PERIGO: Final = "#e5736a"

CSS_DO_TEMA: Final = " ".join(
    (
        f"body {{ color: {TEXTO}; font-size: 14px }}",
        f"h1 {{ color: {TEXTO_FORTE}; font-size: 18px; font-weight: 600; margin-top: 2px;"
        " margin-bottom: 10px }",
        f"h2 {{ color: {TEXTO_FORTE}; font-size: 15px; font-weight: 600; margin-top: 14px;"
        " margin-bottom: 6px }",
        f"h3 {{ color: {TEXTO_FORTE}; font-size: 14px; font-weight: 600; margin-top: 10px;"
        " margin-bottom: 4px }",
        "p { margin-top: 0px; margin-bottom: 8px }",
        "li { margin-bottom: 4px }",
        # A grade é a do atributo `border` da tabela (o Qt não desenha a borda de célula por CSS,
        # medido): aqui, só a cor dela e o cabeçalho.
        f"table {{ border-collapse: collapse; border-color: {LINHA_FORTE}; margin-top: 4px;"
        " margin-bottom: 12px }",
        f"th {{ color: {TEXTO_FORTE}; background-color: {CABECALHO}; font-weight: 600 }}",
        f"code, tt, pre {{ color: {CIANO} }}",
        f"blockquote {{ color: {TEXTO_FRACO}; margin-left: 12px }}",
        f".fraco {{ color: {TEXTO_FRACO} }}",
        f".destaque {{ color: {CIANO} }}",
        f".positivo {{ color: {POSITIVO} }}",
        f".alerta {{ color: {ALERTA} }}",
        f".perigo {{ color: {PERIGO} }}",
        ".num { text-align: right }",
    )
)
"""A folha do tema. Passa inteira pelo sanitizador (o teste cobra): nem o nosso CSS tem exceção."""

__all__ = ["CSS_DO_TEMA"]
