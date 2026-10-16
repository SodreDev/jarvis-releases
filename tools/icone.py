"""Gera os PNGs do ícone a partir do SVG, com o próprio Qt (ADR-0019, ADR-0020).

    uv run --frozen python tools/icone.py /tmp/jarvis-dist/AppDir/usr/share/icons/...

Por que com o Qt e não com `rsvg-convert`/ImageMagick: o Qt já está no ambiente (é a janela),
então não entra ferramenta nova no empacotamento, não há binário de sistema para registrar na
porta de licença, e o que é rasterizado é exatamente o que a janela desenha.

Nenhum PNG é versionado: eles nascem no empacotamento e morrem com ele. O que fica no
repositório é o SVG, que é a fonte.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Final

TAMANHOS: Final[tuple[int, ...]] = (16, 24, 32, 48, 64, 128, 256, 512)


def gerar(svg: Path, pasta: Path, tamanhos: tuple[int, ...] = TAMANHOS) -> list[Path]:
    """Um PNG por tamanho, no padrão de ícones do freedesktop (`<n>x<n>/apps/`)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    if QGuiApplication.instance() is None:
        QGuiApplication(sys.argv[:1])
    desenhista = QSvgRenderer(str(svg))
    if not desenhista.isValid():
        raise SystemExit(f"{svg} não é um SVG que o Qt consiga ler")
    escritos: list[Path] = []
    for tamanho in tamanhos:
        imagem = QImage(tamanho, tamanho, QImage.Format.Format_ARGB32)
        imagem.fill(QColor(0, 0, 0, 0))
        pincel = QPainter(imagem)
        pincel.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        desenhista.render(pincel)
        pincel.end()
        destino = pasta / f"{tamanho}x{tamanho}" / "apps" / "dev.sodredev.Jarvis.png"
        destino.parent.mkdir(parents=True, exist_ok=True)
        # O formato vem da extensão: passar o formato à mão quebra no PySide6 6.9.
        if not imagem.save(str(destino)):
            raise SystemExit(f"não deu para escrever {destino}")
        escritos.append(destino)
    _ = Qt  # o import existe para o Qt inicializar o módulo de imagem
    return escritos


def main(argv: list[str] | None = None) -> int:
    from jarvis.gui.recursos import ICONE_SVG

    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("pasta", type=Path, help="raiz de ícones (padrão hicolor)")
    analisador.add_argument("--svg", type=Path, default=ICONE_SVG)
    args = analisador.parse_args(argv)
    for caminho in gerar(args.svg, args.pasta):
        print(caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main())
