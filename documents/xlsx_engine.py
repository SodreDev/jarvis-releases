# -*- coding: utf-8 -*-
"""documents.xlsx_engine — Geração de planilhas Excel com tema Stark.

Usa xlsxwriter para suporte a formatação rica (cores, bordas, charts nativos).
"""

from __future__ import annotations
import os
import sys
import time
from typing import List, Optional

import xlsxwriter

from .design_system import get_theme


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _out_dir() -> str:
    d = os.path.join(_base(), "data", "documents")
    os.makedirs(d, exist_ok=True)
    return d


def gerar_planilha(
    nome: str,
    abas: List[dict],
    *,
    theme_name: str = "stark_dark",
    filename: Optional[str] = None,
) -> str:
    """
    Gera .xlsx com várias abas.

    `abas` = [{
        "nome": str,
        "headers": [str,...],
        "rows": [[val,...],...],
        "chart": {"type": "bar"|"line"|"pie", "title": str, "cols": [int,...]}?  # opcional
    }]
    """
    theme = get_theme(theme_name)
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (filename or nome))[:60].strip() or "planilha"
    out = os.path.join(_out_dir(), f"{safe}_{int(time.time())}.xlsx")

    wb = xlsxwriter.Workbook(out)

    header_fmt = wb.add_format({
        "bold": True,
        "bg_color": theme.accent,
        "font_color": theme.bg if theme.is_dark else "#ffffff",
        "border": 1,
        "border_color": theme.accent_dim,
        "align": "center",
        "valign": "vcenter",
        "font_name": "Segoe UI",
        "font_size": 11,
    })
    cell_fmt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.panel,
        "font_color": theme.text,
    })
    cell_fmt_alt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.bg,
        "font_color": theme.text,
    })
    title_fmt = wb.add_format({
        "bold": True,
        "font_size": 16,
        "font_color": theme.accent,
        "font_name": "Segoe UI",
    })

    num_fmt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.panel,
        "font_color": theme.text,
        "num_format": "#,##0.00",
    })
    num_fmt_alt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.bg,
        "font_color": theme.text,
        "num_format": "#,##0.00",
    })
    pct_fmt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.panel,
        "font_color": theme.text,
        "num_format": "0.00%",
    })
    pct_fmt_alt = wb.add_format({
        "border": 1,
        "border_color": theme.grid,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.bg,
        "font_color": theme.text,
        "num_format": "0.00%",
    })
    total_fmt = wb.add_format({
        "bold": True,
        "border": 2,
        "border_color": theme.accent,
        "font_name": "Segoe UI",
        "font_size": 10,
        "bg_color": theme.accent_dim if hasattr(theme, "accent_dim") else theme.accent,
        "font_color": "#ffffff",
        "num_format": "#,##0.00",
    })

    def _is_pct_col(h: str) -> bool:
        return any(k in str(h).lower() for k in ("%", "pct", "percent", "margem", "taxa"))

    def _is_num(v) -> bool:
        return isinstance(v, (int, float))

    for aba in abas:
        ws = wb.add_worksheet((aba.get("nome") or "Sheet")[:31])
        ws.set_tab_color(theme.accent)
        # Título
        nome_aba = aba.get("nome", "")
        headers = aba.get("headers", []) or []
        rows = aba.get("rows", []) or []
        header_row = 0

        if nome_aba:
            ws.merge_range(0, 0, 0, max(0, len(headers) - 1), nome_aba, title_fmt)
            ws.set_row(0, 30)
            header_row = 2

        for c, h in enumerate(headers):
            ws.write(header_row, c, str(h), header_fmt)
        ws.set_row(header_row, 22)

        # Detecta quais colunas são % (pelo header)
        pct_cols = {c for c, h in enumerate(headers) if _is_pct_col(h)}

        for ri, row in enumerate(rows):
            is_total = str(row[0]).lower().startswith(("total", "média", "media", "subtotal")) if row else False
            for ci, val in enumerate(row):
                is_alt = ri % 2 == 1
                if is_total:
                    fmt = total_fmt
                elif ci in pct_cols and _is_num(val):
                    fmt = pct_fmt_alt if is_alt else pct_fmt
                elif _is_num(val):
                    fmt = num_fmt_alt if is_alt else num_fmt
                else:
                    fmt = cell_fmt_alt if is_alt else cell_fmt
                ws.write(header_row + 1 + ri, ci, val, fmt)
            ws.set_row(header_row + 1 + ri, 18)

        # Freeze header
        ws.freeze_panes(header_row + 1, 0)

        # Auto column width (mínimo 12, máximo 40)
        for c, h in enumerate(headers):
            max_len = max(
                [len(str(h))] +
                [len(str(r[c])) if c < len(r) else 0 for r in rows]
            )
            ws.set_column(c, c, min(40, max(12, max_len + 4)))

        # Chart opcional
        chart_def = aba.get("chart")
        if chart_def and rows:
            ctype = chart_def.get("type", "bar")
            chart = wb.add_chart({"type": {"bar": "column", "line": "line", "pie": "pie"}.get(ctype, "column")})
            data_cols = chart_def.get("cols", list(range(1, len(headers))))
            sheet_name = (aba.get("nome") or "Sheet")[:31]
            for col in data_cols:
                chart.add_series({
                    "name":       [sheet_name, header_row, col],
                    "categories": [sheet_name, header_row + 1, 0, header_row + len(rows), 0],
                    "values":     [sheet_name, header_row + 1, col, header_row + len(rows), col],
                    "fill":       {"color": theme.accent},
                    "border":     {"color": theme.accent_dim},
                })
            chart.set_title({"name": chart_def.get("title", "")})
            chart.set_style(11)
            ws.insert_chart(header_row + len(rows) + 3, 0, chart,
                            {"x_scale": 1.3, "y_scale": 1.2})

    wb.close()
    return out


__all__ = ["gerar_planilha"]
