"""Texto na janela é texto, nunca HTML (ADR-0019, P6).

O `Text` do QML vem com `textFormat: Text.AutoText`, que **adivinha** rich text: uma resposta
do modelo, um aviso de tarefa ou um título vindo de proposta com `<img src="http://…">`
seria desenhado como HTML — e o Qt buscaria a imagem. Todo `Text` da janela fixa
`Text.PlainText`; este teste cobra isso arquivo por arquivo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

QML = Path(__file__).resolve().parents[3] / "src" / "jarvis" / "gui" / "qml" / "JarvisUI"
ABRE_TEXT = re.compile(r"^\s*Text\s*\{\s*$", re.MULTILINE)
TEXTO_PURO = re.compile(r"^\s*textFormat:\s*Text\.PlainText\s*$", re.MULTILINE)


@pytest.mark.parametrize("arquivo", sorted(QML.glob("*.qml")), ids=lambda c: c.name)
def test_todo_text_da_janela_e_texto_puro(arquivo: Path) -> None:
    fonte = arquivo.read_text(encoding="utf-8")
    assert not re.search(r"Text\s*\{[^}\n]*\S[^}\n]*\}", fonte), "Text de uma linha escapa da regra"
    assert len(ABRE_TEXT.findall(fonte)) == len(TEXTO_PURO.findall(fonte)), (
        f"{arquivo.name}: há Text sem `textFormat: Text.PlainText` — texto do modelo viraria HTML"
    )
    assert "Text.RichText" not in fonte and "Text.StyledText" not in fonte
