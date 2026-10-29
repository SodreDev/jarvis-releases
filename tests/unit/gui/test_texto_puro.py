"""Texto na janela é texto, nunca HTML (ADR-0019, P6) — com uma exceção medida (ADR-0055).

O `Text` do QML vem com `textFormat: Text.AutoText`, que **adivinha** rich text: uma resposta
do modelo, um aviso de tarefa ou um título vindo de proposta com `<img src="http://…">`
seria desenhado como HTML — e o Qt buscaria a imagem. Todo `Text` da janela fixa
`Text.PlainText`; este teste cobra isso arquivo por arquivo.

A exceção é a `VistaConteudo.qml`, e só um `Text` nela: o conteúdo que o Jarvis monta na tela
(`tela.mostrar`), que chega pelo campo `html` do componente `conteudo` — limpo pela allowlist de
`jarvis.tela` na porta **e** de novo em `componentes.validar_dados`, que ainda confere, por outra
regra, que nada aponta para fora. Nenhum outro arquivo pode ter texto rico, nem por `TextEdit` ou
`TextArea`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

QML = Path(__file__).resolve().parents[3] / "src" / "jarvis" / "gui" / "qml" / "JarvisUI"
ABRE_TEXT = re.compile(r"^\s*Text\s*\{\s*$", re.MULTILINE)
TEXTO_PURO = re.compile(r"^\s*textFormat:\s*Text\.PlainText\s*$", re.MULTILINE)
TEXTO_RICO = re.compile(r"^\s*textFormat:\s*Text\.RichText\s*$", re.MULTILINE)
QUALQUER_RICO = re.compile(r"RichText|StyledText|MarkdownText")
A_EXCECAO = "VistaConteudo.qml"


@pytest.mark.parametrize("arquivo", sorted(QML.glob("*.qml")), ids=lambda c: c.name)
def test_todo_text_da_janela_e_texto_puro(arquivo: Path) -> None:
    fonte = arquivo.read_text(encoding="utf-8")
    assert not re.search(r"Text\s*\{[^}\n]*\S[^}\n]*\}", fonte), "Text de uma linha escapa da regra"
    ricos = len(TEXTO_RICO.findall(fonte)) if arquivo.name == A_EXCECAO else 0
    assert len(ABRE_TEXT.findall(fonte)) == len(TEXTO_PURO.findall(fonte)) + ricos, (
        f"{arquivo.name}: há Text sem `textFormat: Text.PlainText` — texto do modelo viraria HTML"
    )
    if arquivo.name == A_EXCECAO:
        assert ricos == 1, "a vista do conteúdo tem exatamente um Text rico"
        assert len(QUALQUER_RICO.findall(fonte)) == 1, "rico só no Text do conteúdo"
        assert "text: vista.dados.html" in fonte, "o rico só mostra o campo `html` do componente"
        assert "onLinkActivated" not in fonte, "o conteúdo da tela não segue link"
    else:
        assert not QUALQUER_RICO.search(fonte), f"{arquivo.name}: texto rico fora da exceção"
