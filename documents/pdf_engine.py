# -*- coding: utf-8 -*-
"""documents.pdf_engine — Gera PDFs estilizados (Stark light por padrão).

Usa reportlab puro (sem dependência de browser/playwright).
"""

from __future__ import annotations
import os
import sys
import time
from typing import List, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak,
    HRFlowable,
)
from reportlab.platypus.flowables import KeepTogether

from .design_system import get_theme, hex_to_rgb


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out_dir() -> str:
    d = os.path.join(_base(), "data", "documents")
    os.makedirs(d, exist_ok=True)
    return d


def _hexcol(h: str) -> colors.Color:
    r, g, b = hex_to_rgb(h)
    return colors.Color(r / 255, g / 255, b / 255)


def gerar_pdf(
    titulo: str,
    secoes: List[dict],
    *,
    subtitulo: str = "",
    autor: str = "J.A.R.V.I.S",
    theme_name: str = "stark_light",
    filename: Optional[str] = None,
) -> str:
    """
    `secoes` = [{"heading": str, "paragraphs": [str,...], "image": path?, "table": [[...],...]?}]
    """
    theme = get_theme(theme_name)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (filename or titulo))[:60].strip() or "relatorio"
    out = os.path.join(_out_dir(), f"{safe}_{int(time.time())}.pdf")

    doc = SimpleDocTemplate(
        out, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=titulo, author=autor,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "T", parent=styles["Title"], fontSize=26,
        textColor=_hexcol(theme.accent), alignment=TA_CENTER, spaceAfter=8,
    )
    style_sub = ParagraphStyle(
        "S", parent=styles["Normal"], fontSize=13,
        textColor=_hexcol("#6a7fa5"), alignment=TA_CENTER, spaceAfter=4,
    )
    style_meta = ParagraphStyle(
        "M", parent=styles["Normal"], fontSize=9,
        textColor=_hexcol("#6a7fa5"), alignment=TA_CENTER, spaceAfter=20,
    )
    # Heading dentro de banner colorido
    style_h_banner = ParagraphStyle(
        "HB", parent=styles["Heading1"], fontSize=15,
        textColor=colors.white, spaceBefore=0, spaceAfter=0,
        leftIndent=6,
    )
    style_body = ParagraphStyle(
        "B", parent=styles["BodyText"], fontSize=11,
        textColor=_hexcol(theme.text), alignment=TA_LEFT, leading=15,
    )

    usable_w = A4[0] - 4 * cm  # largura útil

    def _section_banner(heading: str, icon: str = "") -> Table:
        """Banner colorido para cabeçalho de seção com ícone emoji opcional."""
        label = f"{icon}  {heading}" if icon else heading
        tbl = Table(
            [[Paragraph(label, style_h_banner)]],
            colWidths=[usable_w],
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, -1), _hexcol(theme.accent)),
            ("TOPPADDING",  (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ]))
        return tbl

    story: list = []
    story.append(Paragraph(titulo, style_title))
    if subtitulo:
        story.append(Paragraph(subtitulo, style_sub))
    story.append(Paragraph(f"{autor} • {time.strftime('%d/%m/%Y')}", style_meta))
    story.append(HRFlowable(width="100%", thickness=1.5, color=_hexcol(theme.accent),
                             spaceAfter=16))

    for sec in secoes:
        heading = sec.get("heading", "")
        icon = sec.get("icon", "")

        # Banner de seção com ícone
        story.append(Spacer(1, 10))
        story.append(_section_banner(heading, icon))
        story.append(Spacer(1, 8))

        # Parágrafos de texto
        for para in sec.get("paragraphs", []) or []:
            story.append(Paragraph(para, style_body))
            story.append(Spacer(1, 5))

        # Imagem explícita (opcional — já não busca automaticamente via Picsum)
        img_path = sec.get("image")
        if img_path and os.path.exists(img_path):
            try:
                img_h = min(8 * cm, usable_w * 350 / 700)
                story.append(Spacer(1, 6))
                story.append(Image(img_path, width=usable_w, height=img_h))
                story.append(Spacer(1, 8))
            except Exception:
                pass

        # Tabela opcional
        tbl_data = sec.get("table")
        if tbl_data:
            t = Table(tbl_data, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), _hexcol(theme.accent)),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, -1), 9),
                ("GRID",       (0, 0), (-1, -1), 0.4, _hexcol("#cfd8e4")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_hexcol("#ffffff"), _hexcol("#f5f8fc")]),
                ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING",    (0, 0), (-1, -1), 6),
            ]))
            story.append(t)
            story.append(Spacer(1, 10))

        story.append(Spacer(1, 6))

    doc.build(story)
    return out


__all__ = ["gerar_pdf"]
