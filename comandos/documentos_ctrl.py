# -*- coding: utf-8 -*-
"""
comandos.documentos_ctrl — Fachada de geração de documentos para o JARVIS.

Funções de alto nível que combinam dados + chart_builder + engines.
"""

from __future__ import annotations
from typing import List, Optional


def gerar_apresentacao(titulo: str, slides: List[dict], **kw) -> str:
    """Gera .pptx Stark.

    `slides` aceita dicts {title, bullets, image?, chart?, icon?}.
    `gen_visuals=True` (kwarg) → gera imagens temáticas via Pollinations.ai para cada slide.
    Se `chart` for um dict {type, labels, values, title?}, é renderizado via chart_builder
    e injetado como imagem.
    """
    from documents import pptx_engine, chart_builder

    prepared: list[dict] = []
    for s in slides:
        item = dict(s)
        chart = item.pop("chart", None)
        if chart and not item.get("image"):
            try:
                ctype = chart.get("type", "bar")
                if ctype == "line":
                    series = chart.get("series") or {"valores": chart.get("values", [])}
                    item["image"] = chart_builder.line_chart(
                        chart.get("labels", []), series, title=chart.get("title", ""))
                elif ctype == "pie":
                    item["image"] = chart_builder.pie_chart(
                        chart.get("labels", []), chart.get("values", []), title=chart.get("title", ""))
                else:
                    item["image"] = chart_builder.bar_chart(
                        chart.get("labels", []), chart.get("values", []), title=chart.get("title", ""))
            except Exception:
                pass
        prepared.append(item)
    return pptx_engine.gerar_apresentacao(titulo, prepared, **kw)


def gerar_relatorio_pdf(titulo: str, secoes: List[dict], **kw) -> str:
    from documents import pdf_engine
    return pdf_engine.gerar_pdf(titulo, secoes, **kw)


def gerar_relatorio_word(titulo: str, secoes: List[dict], **kw) -> str:
    from documents import docx_engine
    return docx_engine.gerar_relatorio(titulo, secoes, **kw)


def gerar_planilha(nome: str, abas: List[dict], **kw) -> str:
    from documents import xlsx_engine
    return xlsx_engine.gerar_planilha(nome, abas, **kw)


def gerar_grafico(tipo: str, labels: list, values: list, *,
                  title: str = "", series: Optional[dict] = None) -> str:
    """Gera gráfico standalone (PNG). Útil para anexar em chat/painel."""
    from documents import chart_builder
    if tipo == "line":
        return chart_builder.line_chart(labels, series or {"valores": values}, title=title)
    if tipo == "pie":
        return chart_builder.pie_chart(labels, values, title=title)
    return chart_builder.bar_chart(labels, values, title=title)


__all__ = [
    "gerar_apresentacao",
    "gerar_relatorio_pdf",
    "gerar_relatorio_word",
    "gerar_planilha",
    "gerar_grafico",
]
