# -*- coding: utf-8 -*-
"""documents.deck_builder — Apresentações spec→render (roadmap/13, Fase 2, v2).

O LLM compõe uma SPEC (deck + slides; cada slide escolhe um LAYOUT de um
catálogo curado, estilo Gamma). Este módulo valida/normaliza a spec (com
limites de conteúdo que impedem overflow na origem), faz seleção adaptativa de
layout quando preciso, e renderiza um .pptx com qualidade "designed" usando:
  • grid de 12 colunas + escala tipográfica modular (design_system)
  • cards arredondados, eyebrow (kicker), regras de acento
  • crop-to-fill de imagens (sem distorção) + scrim p/ legibilidade

Efeitos "fancy" (alpha/sombra/gradiente) são best-effort com fallback seguro —
nunca quebram a renderização.

Catálogo de layouts (campo "layout"):
  capa, hero, secao, agenda, topicos, duas_colunas, comparativo, kpi, bento,
  timeline, citacao, destaque, imagem, imagem_lateral, fechamento
"""
from __future__ import annotations

import os
import time
from typing import Optional

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE

from .design_system import (
    get_theme, build_custom_theme, parse_color_from_text, THEMES, PALETTE,
    hex_to_rgb, SLIDE_W, SLIDE_H, GRID, TYPE, SPACE,
    col_x, col_w, span_w, text_dim_of, card_of,
    ROWS, row_y, row_h_unit, row_span_h, cell,
)
from .pptx_engine import gen_image, _download_visual, _out_dir, _add_transition, _rgb

_ALIGN = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}


# ─────────────────────────────────────────────────────────────────────────
# Primitivos de baixo nível
# ─────────────────────────────────────────────────────────────────────────
def _bg(slide, color_hex):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(color_hex)


def _set_alpha(shape, alpha_pct: float):
    """Aplica transparência (0-100) ao preenchimento sólido via XML."""
    from pptx.oxml.ns import qn
    srgb = shape._element.spPr.find(".//" + qn("a:srgbClr"))
    if srgb is None:
        return
    a = srgb.makeelement(qn("a:alpha"), {"val": str(int(alpha_pct * 1000))})
    srgb.append(a)


def _add_shadow(shape):
    """Sombra externa suave via XML (best-effort)."""
    from pptx.oxml.ns import qn
    spPr = shape._element.spPr
    for e in spPr.findall(qn("a:effectLst")):
        spPr.remove(e)
    eff = spPr.makeelement(qn("a:effectLst"), {})
    shdw = eff.makeelement(qn("a:outerShdw"),
                           {"blurRad": "90000", "dist": "38100",
                            "dir": "5400000", "rotWithShape": "0"})
    clr = shdw.makeelement(qn("a:srgbClr"), {"val": "000000"})
    clr.append(clr.makeelement(qn("a:alpha"), {"val": "28000"}))
    shdw.append(clr)
    eff.append(shdw)
    spPr.append(eff)


def _text(slide, text, x, y, w, h, *, style="body", color=None, bold=None,
          align="left", line_spacing=None):
    size = TYPE.get(style, TYPE["body"])
    if bold is None:
        bold = style in ("eyebrow", "lead", "h3", "h2", "h1", "display", "stat")
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    try:
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE  # encolhe texto p/ caber
    except Exception:
        pass
    p = tf.paragraphs[0]
    p.alignment = _ALIGN.get(align, PP_ALIGN.LEFT)
    if line_spacing:
        try:
            p.line_spacing = line_spacing
        except Exception:
            pass
    run = p.add_run()
    run.text = str(text)
    run.font.size = Pt(size)
    run.font.bold = bool(bold)
    run.font.name = "Segoe UI"
    if color:
        run.font.color.rgb = _rgb(color)
    return tb


def _eyebrow(slide, text, x, y, w, theme):
    if not text:
        return
    _text(slide, str(text).upper(), x, y, w, 0.35, style="eyebrow",
          color=theme.accent, bold=True)


def _rule(slide, x, y, theme, w=2.6, color=None):
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(x), Inches(y), Inches(w), Inches(0.045))
    line.fill.solid()
    line.fill.fore_color.rgb = _rgb(color or theme.accent_dim)
    line.line.fill.background()


def _card(slide, x, y, w, h, theme, *, fill=None, border=True, shadow=True, radius=0.08):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        shp.adjustments[0] = radius
    except Exception:
        pass
    shp.fill.solid()
    shp.fill.fore_color.rgb = _rgb(fill or card_of(theme))
    if border:
        try:
            shp.line.color.rgb = _rgb(theme.grid)
            shp.line.width = Pt(0.75)
        except Exception:
            shp.line.fill.background()
    else:
        shp.line.fill.background()
    if shadow:
        try:
            _add_shadow(shp)
        except Exception:
            pass
    return shp


def _image_cover(slide, path, x, y, w, h):
    """Coloca imagem preenchendo a região (object-fit: cover) sem distorção."""
    if not (path and os.path.exists(path)):
        return None
    pic = slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    try:
        from PIL import Image
        iw, ih = Image.open(path).size
        ai = iw / ih
        at = w / h
        if ai > at:           # imagem larga demais → corta laterais
            crop = (1 - at / ai) / 2
            pic.crop_left = crop
            pic.crop_right = crop
        elif ai < at:         # imagem alta demais → corta topo/base
            crop = (1 - ai / at) / 2
            pic.crop_top = crop
            pic.crop_bottom = crop
    except Exception:
        pass
    return pic


def _scrim(slide, x, y, w, h, color, alpha_pct=58):
    r = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                               Inches(x), Inches(y), Inches(w), Inches(h))
    r.fill.solid()
    r.fill.fore_color.rgb = _rgb(color)
    r.line.fill.background()
    try:
        _set_alpha(r, alpha_pct)
    except Exception:
        pass
    return r


def _gradient_bg(slide, c0, c1, angle=90):
    """Fundo em gradiente (best-effort; fallback = cor sólida c0)."""
    try:
        shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                     Inches(0), Inches(0), Inches(SLIDE_W), Inches(SLIDE_H))
        shp.line.fill.background()
        shp.fill.gradient()
        stops = shp.fill.gradient_stops
        stops[0].color.rgb = _rgb(c0)
        stops[0].position = 0.0
        stops[1].color.rgb = _rgb(c1)
        stops[1].position = 1.0
        try:
            shp.fill.gradient_angle = angle
        except Exception:
            pass
        # manda p/ trás
        sp = shp._element
        sp.getparent().remove(sp)
        slide.shapes._spTree.insert(2, sp)
        return True
    except Exception:
        _bg(slide, c0)
        return False


def _footer(slide, theme, label="J.A.R.V.I.S"):
    _text(slide, f"{label} • {time.strftime('%d/%m/%Y')}",
          col_x(0), GRID["footer"], span_w(8), 0.35,
          style="caption", color=text_dim_of(theme))


def _shrink_stat(value: str) -> int:
    """Tamanho de fonte p/ números/frases de destaque conforme comprimento."""
    n = len(str(value))
    if n <= 4:
        return TYPE["stat"]
    if n <= 7:
        return 96
    if n <= 12:
        return 64
    return 44


# ─────────────────────────────────────────────────────────────────────────
# Layouts (cada um recebe (prs, sc, theme, transition, image))
# ─────────────────────────────────────────────────────────────────────────
def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


def _accent_band(slide, theme, w=0.22):
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0), Inches(0), Inches(w), Inches(SLIDE_H))
    band.fill.solid()
    band.fill.fore_color.rgb = _rgb(theme.accent)
    band.line.fill.background()


def _header(slide, sc, theme):
    """Eyebrow + título + régua no topo (padrão dos slides de conteúdo)."""
    x = col_x(0)
    _eyebrow(slide, sc.get("eyebrow", ""), x, GRID["top"] - 0.02, span_w(10), theme)
    top = GRID["top"] + (0.32 if sc.get("eyebrow") else 0.0)
    _text(slide, sc.get("titulo", ""), x, top, span_w(11), 0.9,
          style="h1", color=theme.accent, line_spacing=1.05)
    _rule(slide, x, top + 0.92, theme)


def _l_capa(prs, sc, theme, transition, image):
    slide = _blank(prs)
    if image:
        _image_cover(slide, image, 0, 0, SLIDE_W, SLIDE_H)
        _scrim(slide, 0, 0, SLIDE_W, SLIDE_H, theme.bg, 62)
    else:
        _gradient_bg(slide, theme.bg, theme.panel, 90)
    _accent_band(slide, theme)
    x = col_x(0)
    _eyebrow(slide, sc.get("eyebrow", "Apresentação"), x, 2.0, span_w(10), theme)
    _text(slide, sc.get("titulo", ""), x, 2.5, span_w(11), 2.0,
          style="display", color=theme.accent, line_spacing=1.02)
    if sc.get("subtitulo"):
        _text(slide, sc["subtitulo"], x, 4.6, span_w(9), 1.0,
              style="lead", bold=False, color=text_dim_of(theme))
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_hero(prs, sc, theme, transition, image):
    slide = _blank(prs)
    if image:
        _image_cover(slide, image, 0, 0, SLIDE_W, SLIDE_H)
        _scrim(slide, 0, 0, SLIDE_W, SLIDE_H, theme.bg, 55)
    else:
        _gradient_bg(slide, theme.panel, theme.bg, 90)
    x = col_x(0)
    _eyebrow(slide, sc.get("eyebrow", ""), x, 4.5, span_w(10), theme)
    _text(slide, sc.get("titulo", ""), x, 4.9, span_w(11), 1.6,
          style="h1", color="#ffffff" if image else theme.accent, line_spacing=1.05)
    if sc.get("legenda"):
        _text(slide, sc["legenda"], x, 6.2, span_w(10), 0.6, style="body",
              bold=False, color="#e8eefc" if image else text_dim_of(theme))
    _add_transition(slide, transition)


def _l_secao(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _gradient_bg(slide, theme.bg, theme.panel, 45)
    _accent_band(slide, theme, w=0.3)
    num = str(sc.get("numero") or "").strip()
    if num:
        # número gigante e esmaecido ao fundo
        _text(slide, num, col_x(0), 1.2, span_w(6), 2.4, style="display",
              color=theme.accent_dim, align="left")
    _eyebrow(slide, sc.get("eyebrow", "Seção"), col_x(0), 3.6, span_w(8), theme)
    _text(slide, sc.get("titulo", ""), col_x(0), 4.0, span_w(11), 1.6,
          style="display", color=theme.accent, line_spacing=1.02)
    _add_transition(slide, transition)


def _l_agenda(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, {"titulo": sc.get("titulo", "Agenda"), "eyebrow": sc.get("eyebrow", "")}, theme)
    items = sc.get("bullets", []) or [it.get("titulo", "") if isinstance(it, dict) else it
                                      for it in (sc.get("items", []) or [])]
    y = GRID["body_top"] + 0.1
    for i, it in enumerate(items[:6]):
        _text(slide, f"{i+1:02d}", col_x(0), y, span_w(1), 0.6, style="h2",
              color=theme.accent)
        _text(slide, str(it), col_x(1), y + 0.04, span_w(10), 0.6, style="lead",
              bold=False, color=theme.text)
        y += 0.78
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_topicos(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _accent_band(slide, theme)
    has_img = bool(image)
    text_cols = 7 if has_img else 11
    _header(slide, sc, theme)
    bullets = sc.get("bullets", []) or []
    maxlen = max((len(str(b)) for b in bullets), default=0)
    # Densidade → tamanho de fonte + passo (pouco texto = maior; muito = compacto)
    if len(bullets) <= 4 and maxlen <= 64:
        bstyle, step = "lead", 0.82
    elif len(bullets) <= 6 and maxlen <= 130:
        bstyle, step = "body", 0.66
    else:
        bstyle, step = "body", 0.56
    y = GRID["body_top"]
    avail = GRID["body_bottom"] - GRID["body_top"]
    n = min(len(bullets), 8)
    if n and step * n > avail:           # compacta p/ caber todos sem cortar
        step = max(0.42, avail / n)
    for i, b in enumerate(bullets[:8]):
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                     Inches(col_x(0)), Inches(y + 0.06),
                                     Inches(0.30), Inches(0.30))
        dot.fill.solid()
        dot.fill.fore_color.rgb = _rgb(theme.accent)
        dot.line.fill.background()
        bt = dot.text_frame.paragraphs[0]
        bt.alignment = PP_ALIGN.CENTER
        r = bt.add_run()
        r.text = str(i + 1)
        r.font.size = Pt(9)
        r.font.bold = True
        r.font.color.rgb = _rgb(theme.bg)
        r.font.name = "Segoe UI"
        _text(slide, str(b), col_x(0) + 0.42, y, span_w(text_cols) - 0.42, step,
              style=bstyle, bold=False, color=theme.text, line_spacing=1.15)
        y += step
    if has_img:
        ix = col_x(8)
        _image_cover(slide, image, ix, GRID["body_top"] - 0.1, span_w(4), 4.6)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_texto(prs, sc, theme, transition, image):
    """Slide de CORPO DE TEXTO (médio/grande) — para conteúdo explicativo.
    Fonte escolhida pela densidade; word-wrap natural num único bloco."""
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _accent_band(slide, theme)
    _header(slide, sc, theme)
    corpo = sc.get("corpo") or sc.get("legenda") or sc.get("subtitulo") or ""
    n = len(str(corpo))
    style = "lead" if n < 260 else ("body" if n < 720 else "caption")
    has_img = bool(image)
    x = col_x(0)
    w = span_w(7 if has_img else 11)
    h = GRID["body_bottom"] - GRID["body_top"]
    tb = slide.shapes.add_textbox(Inches(x), Inches(GRID["body_top"]), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    paras = [p.strip() for p in str(corpo).split("\n") if p.strip()] or [str(corpo)]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        try:
            p.line_spacing = 1.4
            p.space_after = Pt(10)
        except Exception:
            pass
        run = p.add_run()
        run.text = para
        run.font.size = Pt(TYPE[style])
        run.font.name = "Segoe UI"
        run.font.color.rgb = _rgb(theme.text)
    if has_img:
        _image_cover(slide, image, col_x(8), GRID["body_top"] - 0.1, span_w(4), 4.6)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_duas_colunas(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _accent_band(slide, theme)
    _header(slide, sc, theme)
    cols = (
        (sc.get("esq_titulo", ""), sc.get("esquerda", []) or [], 0),
        (sc.get("dir_titulo", ""), sc.get("direita", []) or [], 6),
    )
    for col_title, items, c0 in cols:
        x = col_x(c0)
        if col_title:
            _text(slide, col_title, x, GRID["body_top"], span_w(5), 0.5,
                  style="h3", color=theme.accent)
        y = GRID["body_top"] + (0.6 if col_title else 0.0)
        for it in items[:6]:
            dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x),
                                         Inches(y + 0.07), Inches(0.15), Inches(0.15))
            dot.fill.solid()
            dot.fill.fore_color.rgb = _rgb(theme.accent)
            dot.line.fill.background()
            _text(slide, str(it), x + 0.3, y, span_w(5) - 0.3, 0.5, style="body",
                  bold=False, color=theme.text, line_spacing=1.12)
            y += 0.6
            if y > GRID["body_bottom"]:
                break
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_comparativo(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    panels = (
        (sc.get("esq_titulo", "Opção A"), sc.get("esquerda", []) or [], 0, theme.accent),
        (sc.get("dir_titulo", "Opção B"), sc.get("direita", []) or [], 6, theme.accent_dim),
    )
    for title, items, c0, hue in panels:
        x = col_x(c0)
        card = _card(slide, x, GRID["body_top"], span_w(6), 4.7, theme)
        _text(slide, title, x + 0.35, GRID["body_top"] + 0.3, span_w(6) - 0.7, 0.6,
              style="h3", color=hue)
        y = GRID["body_top"] + 1.05
        for it in items[:5]:
            _text(slide, "•  " + str(it), x + 0.35, y, span_w(6) - 0.7, 0.5,
                  style="body", bold=False, color=theme.text, line_spacing=1.12)
            y += 0.6
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_kpi(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = sc.get("items", []) or []
    n = max(1, min(4, len(items)))
    gap = SPACE["md"]
    total = span_w(12)
    cw = (total - (n - 1) * gap) / n
    y = 2.3
    for i, it in enumerate(items[:n]):
        if not isinstance(it, dict):
            it = {"valor": str(it)}
        x = col_x(0) + i * (cw + gap)
        _card(slide, x, y, cw, 3.0, theme)
        valor = str(it.get("valor", ""))
        _text(slide, valor, x, y + 0.55, cw, 1.4, style="stat", color=theme.accent,
              align="center")
        # ajuste de fonte do número conforme comprimento
        try:
            tb = slide.shapes[-1]
            tb.text_frame.paragraphs[0].runs[0].font.size = Pt(_shrink_stat(valor))
        except Exception:
            pass
        if it.get("titulo"):
            _text(slide, it["titulo"], x, y + 2.05, cw, 0.5, style="lead",
                  color=theme.text, align="center")
        if it.get("legenda"):
            _text(slide, it["legenda"], x, y + 2.55, cw, 0.4, style="caption",
                  bold=False, color=text_dim_of(theme), align="center")
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_bento(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = sc.get("items", []) or []
    n = len(items)
    cols = 2 if n <= 4 else 3
    rows = (min(n, 6) + cols - 1) // cols
    gap = SPACE["md"]
    area_top = GRID["body_top"]
    area_h = GRID["body_bottom"] - area_top
    cw = (span_w(12) - (cols - 1) * gap) / cols
    ch = (area_h - (rows - 1) * gap) / rows
    for i, it in enumerate(items[:cols * rows]):
        if not isinstance(it, dict):
            it = {"titulo": str(it)}
        r, c = divmod(i, cols)
        x = col_x(0) + c * (cw + gap)
        y = area_top + r * (ch + gap)
        _card(slide, x, y, cw, ch, theme)
        ttl = it.get("titulo", "") or it.get("valor", "")
        _text(slide, ttl, x + 0.28, y + 0.25, cw - 0.56, 0.6, style="h3",
              color=theme.accent)
        if it.get("legenda") or it.get("desc"):
            _text(slide, it.get("legenda") or it.get("desc", ""),
                  x + 0.28, y + 0.95, cw - 0.56, ch - 1.1, style="body",
                  bold=False, color=theme.text, line_spacing=1.15)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_timeline(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = (sc.get("items", []) or [])[:5]
    n = max(1, len(items))
    y_line = 4.0
    x0 = col_x(0)
    total = span_w(12)
    # linha base
    base = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x0), Inches(y_line),
                                  Inches(total), Inches(0.04))
    base.fill.solid()
    base.fill.fore_color.rgb = _rgb(theme.accent_dim)
    base.line.fill.background()
    step = total / n
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            it = {"titulo": str(it)}
        cx = x0 + step * i + step / 2
        node = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - 0.12),
                                      Inches(y_line - 0.08), Inches(0.24), Inches(0.24))
        node.fill.solid()
        node.fill.fore_color.rgb = _rgb(theme.accent)
        node.line.fill.background()
        up = (i % 2 == 0)
        ty = y_line - 1.5 if up else y_line + 0.4
        if it.get("quando"):
            _text(slide, str(it["quando"]), cx - step / 2 + 0.1, ty, step - 0.2, 0.4,
                  style="h3", color=theme.accent, align="center")
        _text(slide, str(it.get("titulo", "")), cx - step / 2 + 0.1, ty + 0.45,
              step - 0.2, 0.9, style="body", bold=False, color=theme.text,
              align="center", line_spacing=1.1)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_citacao(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _gradient_bg(slide, theme.bg, theme.panel, 90)
    _text(slide, "“", col_x(0), 1.1, span_w(3), 1.8, style="display",
          color=theme.accent_dim)
    quote = sc.get("valor") or sc.get("titulo", "")
    _text(slide, quote, col_x(1), 2.4, span_w(10), 2.6, style="h1", bold=False,
          color=theme.text, line_spacing=1.2)
    if sc.get("legenda"):
        _rule(slide, col_x(1), 5.3, theme, w=0.8)
        _text(slide, "— " + str(sc["legenda"]), col_x(1), 5.45, span_w(8), 0.5,
              style="lead", bold=False, color=text_dim_of(theme))
    _add_transition(slide, transition)


def _l_destaque(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _gradient_bg(slide, theme.bg, theme.panel, 90)
    if sc.get("titulo"):
        _text(slide, sc["titulo"], col_x(0), 1.2, span_w(12), 0.7, style="h3",
              color=text_dim_of(theme), align="center")
    valor = str(sc.get("valor", ""))
    tb = _text(slide, valor, col_x(0), 2.3, span_w(12), 2.4, style="stat",
               color=theme.accent, align="center")
    try:
        tb.text_frame.paragraphs[0].runs[0].font.size = Pt(_shrink_stat(valor))
    except Exception:
        pass
    if sc.get("legenda"):
        _text(slide, sc["legenda"], col_x(1), 5.1, span_w(10), 1.0, style="lead",
              bold=False, color=text_dim_of(theme), align="center")
    _add_transition(slide, transition)


def _l_imagem(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    if image:
        _image_cover(slide, image, 0, 0, SLIDE_W, SLIDE_H)
        _scrim(slide, 0, SLIDE_H - 2.0, SLIDE_W, 2.0, theme.bg, 60)
    _accent_band(slide, theme)
    if sc.get("titulo"):
        _text(slide, sc["titulo"], col_x(0), SLIDE_H - 1.65, span_w(11), 0.8,
              style="h1", color="#ffffff" if image else theme.accent)
    if sc.get("legenda"):
        _text(slide, sc["legenda"], col_x(0), SLIDE_H - 0.8, span_w(11), 0.5,
              style="body", bold=False, color="#e8eefc" if image else text_dim_of(theme))
    _add_transition(slide, transition)


def _l_imagem_lateral(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    # imagem ocupa metade direita (cover)
    half = SLIDE_W / 2
    if image:
        _image_cover(slide, image, half, 0, half, SLIDE_H)
    _accent_band(slide, theme)
    x = col_x(0)
    _eyebrow(slide, sc.get("eyebrow", ""), x, GRID["top"], span_w(5), theme)
    _text(slide, sc.get("titulo", ""), x, GRID["top"] + 0.35, span_w(5), 1.4,
          style="h1", color=theme.accent, line_spacing=1.05)
    y = 2.7
    for b in (sc.get("bullets", []) or [])[:5]:
        _text(slide, "•  " + str(b), x, y, span_w(5), 0.5, style="body",
              bold=False, color=theme.text, line_spacing=1.15)
        y += 0.6
    if sc.get("legenda") and not sc.get("bullets"):
        _text(slide, sc["legenda"], x, 2.7, span_w(5), 3.0, style="lead",
              bold=False, color=theme.text, line_spacing=1.3)
    _add_transition(slide, transition)


def _l_fechamento(prs, sc, theme, transition, image):
    slide = _blank(prs)
    if image:
        _image_cover(slide, image, 0, 0, SLIDE_W, SLIDE_H)
        _scrim(slide, 0, 0, SLIDE_W, SLIDE_H, theme.bg, 62)
    else:
        _gradient_bg(slide, theme.panel, theme.bg, 90)
    _accent_band(slide, theme)
    x = col_x(0)
    _text(slide, sc.get("titulo", "Obrigado"), x, 3.0, span_w(11), 1.4,
          style="display", color=theme.accent, line_spacing=1.05)
    if sc.get("subtitulo"):
        _text(slide, sc["subtitulo"], x, 4.7, span_w(9), 1.0, style="lead",
              bold=False, color=text_dim_of(theme) if not image else "#e8eefc")
    _footer(slide, theme)
    _add_transition(slide, transition)


# ─────────────────────────────────────────────────────────────────────────
# REGISTRY DE BLOCOS — primitivos componíveis para o layout 'livre' (compose).
# Cada bloco recebe (slide, theme, rect=(x,y,w,h), blk). Combinando blocos no
# grid 12×ROWS → variedade quase infinita (modelo Gamma/Presenton).
# ─────────────────────────────────────────────────────────────────────────
def _blk_titulo(slide, theme, rect, blk):
    x, y, w, h = rect
    _text(slide, blk.get("texto", blk.get("titulo", "")), x, y, w, max(h, 0.6),
          style=blk.get("style", "h2"), color=theme.accent, line_spacing=1.05)


def _blk_texto(slide, theme, rect, blk):
    x, y, w, h = rect
    t = str(blk.get("texto", blk.get("corpo", "")))
    style = "lead" if len(t) < 200 else ("body" if len(t) < 600 else "caption")
    _text(slide, t, x, y, w, h, style=style, bold=False, color=theme.text, line_spacing=1.35)


def _blk_bullets(slide, theme, rect, blk):
    x, y, w, h = rect
    items = blk.get("itens") or blk.get("bullets") or []
    n = max(1, len(items))
    step = min(0.62, h / n)
    yy = y
    for it in items[:8]:
        _text(slide, "•  " + str(it), x, yy, w, step, style="body", bold=False,
              color=theme.text, line_spacing=1.1)
        yy += step


def _blk_stat(slide, theme, rect, blk):
    x, y, w, h = rect
    _card(slide, x, y, w, h, theme)
    v = str(blk.get("valor", ""))
    tb = _text(slide, v, x, y + h * 0.16, w, h * 0.5, style="stat",
               color=theme.accent, align="center")
    try:
        tb.text_frame.paragraphs[0].runs[0].font.size = Pt(_shrink_stat(v))
    except Exception:
        pass
    if blk.get("titulo"):
        _text(slide, blk["titulo"], x, y + h * 0.64, w, 0.5, style="lead",
              color=theme.text, align="center")
    if blk.get("legenda"):
        _text(slide, blk["legenda"], x, y + h * 0.84, w, 0.4, style="caption",
              bold=False, color=text_dim_of(theme), align="center")


def _blk_card(slide, theme, rect, blk):
    x, y, w, h = rect
    _card(slide, x, y, w, h, theme)
    if blk.get("titulo"):
        _text(slide, blk["titulo"], x + 0.28, y + 0.22, w - 0.56, 0.6, style="h3",
              color=theme.accent)
    txt = blk.get("texto") or blk.get("legenda") or blk.get("desc") or ""
    if txt:
        _text(slide, txt, x + 0.28, y + 0.92, w - 0.56, h - 1.05, style="body",
              bold=False, color=theme.text, line_spacing=1.15)


def _blk_imagem(slide, theme, rect, blk):
    x, y, w, h = rect
    img = blk.get("_image", "")
    if img and os.path.exists(img):
        _image_cover(slide, img, x, y, w, h)
    else:
        _card(slide, x, y, w, h, theme, shadow=False)


def _blk_citacao(slide, theme, rect, blk):
    x, y, w, h = rect
    _text(slide, "“" + str(blk.get("texto", "")) + "”", x, y, w, h * 0.7,
          style="h2", bold=False, color=theme.text, line_spacing=1.2)
    autor = blk.get("autor") or blk.get("legenda")
    if autor:
        _text(slide, "— " + str(autor), x, y + h * 0.72, w, 0.5, style="lead",
              bold=False, color=text_dim_of(theme))


def _blk_divisor(slide, theme, rect, blk):
    x, y, w, h = rect
    _rule(slide, x, y + h / 2, theme, w=max(0.8, w * 0.4))


_BLOCKS = {
    "titulo": _blk_titulo, "texto": _blk_texto, "paragrafo": _blk_texto,
    "bullets": _blk_bullets, "lista": _blk_bullets, "stat": _blk_stat,
    "numero": _blk_stat, "kpi": _blk_stat, "card": _blk_card, "imagem": _blk_imagem,
    "citacao": _blk_citacao, "divisor": _blk_divisor,
}


def _l_livre(prs, sc, theme, transition, image):
    """Layout COMPOSE: o LLM emite blocks[] posicionados no grid 12×ROWS."""
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _accent_band(slide, theme)
    has_header = bool(sc.get("titulo"))
    if has_header:
        _header(slide, sc, theme)
    blocks = sc.get("blocks") or []
    run_row = 0
    for blk in blocks:
        if not isinstance(blk, dict):
            continue
        t = (blk.get("type") or blk.get("tipo") or "texto").strip().lower()
        try:
            col = int(blk.get("col", 0))
            span = int(blk.get("span", 12))
            row = int(blk["row"]) if "row" in blk else run_row
            rspan = int(blk.get("rspan", blk.get("row_span", 1)))
        except Exception:
            col, span, row, rspan = 0, 12, run_row, 1
        run_row = max(run_row, row + rspan)
        rect = cell(col, span, min(row, ROWS - 1), max(1, min(rspan, ROWS)))
        if t == "imagem":
            blk = dict(blk, _image=image)
        fn = _BLOCKS.get(t, _blk_texto)
        try:
            fn(slide, theme, rect, blk)
        except Exception as exc:
            print(f"[DECK] bloco '{t}' falhou: {exc}")
    _footer(slide, theme)
    _add_transition(slide, transition)


# ─────────────────────────────────────────────────────────────────────────
# Layouts nomeados adicionais (taxonomia consultoria/Gamma)
# ─────────────────────────────────────────────────────────────────────────
def _l_declaracao(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _gradient_bg(slide, theme.bg, theme.panel, 90)
    _accent_band(slide, theme)
    frase = sc.get("valor") or sc.get("titulo") or sc.get("corpo", "")
    n = len(str(frase))
    style = "display" if n < 90 else ("h1" if n < 200 else "h2")
    _text(slide, frase, col_x(0), 2.4, span_w(12), 3.0, style=style, bold=True,
          color=theme.accent, align="center", line_spacing=1.1)
    if sc.get("legenda"):
        _text(slide, sc["legenda"], col_x(1), 5.6, span_w(10), 0.8, style="lead",
              bold=False, color=text_dim_of(theme), align="center")
    _add_transition(slide, transition)


def _l_processo(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = (sc.get("items", []) or sc.get("bullets", []) or [])[:5]
    n = max(1, len(items))
    gap = SPACE["sm"]
    cw = (span_w(12) - (n - 1) * gap) / n
    y = GRID["body_top"] + 0.4
    ch = 3.2
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            it = {"titulo": str(it)}
        x = col_x(0) + i * (cw + gap)
        _card(slide, x, y, cw, ch, theme)
        badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + 0.25),
                                       Inches(y + 0.25), Inches(0.5), Inches(0.5))
        badge.fill.solid(); badge.fill.fore_color.rgb = _rgb(theme.accent)
        badge.line.fill.background()
        bp = badge.text_frame.paragraphs[0]; bp.alignment = PP_ALIGN.CENTER
        br = bp.add_run(); br.text = str(i + 1); br.font.bold = True
        br.font.size = Pt(16); br.font.color.rgb = _rgb(theme.bg); br.font.name = "Segoe UI"
        _text(slide, it.get("titulo", ""), x + 0.25, y + 0.95, cw - 0.5, 0.7,
              style="h3", color=theme.accent)
        if it.get("desc") or it.get("legenda"):
            _text(slide, it.get("desc") or it.get("legenda", ""), x + 0.25, y + 1.7,
                  cw - 0.5, ch - 1.85, style="body", bold=False, color=theme.text,
                  line_spacing=1.12)
        if i < n - 1:
            _text(slide, "→", x + cw - 0.05, y + ch / 2 - 0.4, gap + 0.1, 0.8,
                  style="h2", color=theme.accent_dim, align="center")
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_matriz(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = (sc.get("items", []) or [])[:4]
    while len(items) < 4:
        items.append({})
    gap = SPACE["md"]
    cw = (span_w(12) - gap) / 2
    ch = (GRID["body_bottom"] - GRID["body_top"] - gap) / 2
    pos = [(0, 0), (1, 0), (0, 1), (1, 1)]
    for i, (c, r) in enumerate(pos):
        it = items[i] if isinstance(items[i], dict) else {"titulo": str(items[i])}
        x = col_x(0) + c * (cw + gap)
        y = GRID["body_top"] + r * (ch + gap)
        _card(slide, x, y, cw, ch, theme)
        if it.get("titulo"):
            _text(slide, it["titulo"], x + 0.3, y + 0.25, cw - 0.6, 0.6, style="h3",
                  color=theme.accent)
        if it.get("legenda") or it.get("desc"):
            _text(slide, it.get("legenda") or it.get("desc", ""), x + 0.3, y + 0.95,
                  cw - 0.6, ch - 1.1, style="body", bold=False, color=theme.text,
                  line_spacing=1.15)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_tabela(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    headers = sc.get("headers") or []
    rows = sc.get("rows") or []
    if not headers and rows and isinstance(rows[0], list):
        headers = [f"Col {i+1}" for i in range(len(rows[0]))]
    ncol = max(1, len(headers) or (len(rows[0]) if rows and isinstance(rows[0], list) else 1))
    nrow = min(len(rows), 8) + 1
    x, y = col_x(0), GRID["body_top"] + 0.1
    w, h = span_w(12), min(GRID["body_bottom"] - GRID["body_top"] - 0.2, 0.55 * nrow)
    try:
        tbl = slide.shapes.add_table(nrow, ncol, Inches(x), Inches(y),
                                     Inches(w), Inches(h)).table
        for j in range(ncol):
            cellh = tbl.cell(0, j)
            cellh.text = str(headers[j] if j < len(headers) else "")
            cellh.fill.solid(); cellh.fill.fore_color.rgb = _rgb(theme.accent_dim)
            pr = cellh.text_frame.paragraphs[0]; pr.runs[0].font.bold = True if pr.runs else None
            for run in pr.runs:
                run.font.size = Pt(14); run.font.color.rgb = _rgb("#ffffff"); run.font.name = "Segoe UI"
        for ri, rowv in enumerate(rows[:nrow - 1], start=1):
            rowv = rowv if isinstance(rowv, list) else [rowv]
            for j in range(ncol):
                c = tbl.cell(ri, j)
                c.text = str(rowv[j]) if j < len(rowv) else ""
                c.fill.solid()
                c.fill.fore_color.rgb = _rgb(theme.panel if ri % 2 else theme.bg)
                for run in c.text_frame.paragraphs[0].runs:
                    run.font.size = Pt(12); run.font.color.rgb = _rgb(theme.text); run.font.name = "Segoe UI"
    except Exception as exc:
        print(f"[DECK] tabela falhou: {exc}")
        _l_topicos(prs, sc, theme, transition, image)
        return
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_equipe(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = (sc.get("items", []) or [])[:4]
    n = max(1, len(items))
    gap = SPACE["md"]
    cw = (span_w(12) - (n - 1) * gap) / n
    y = GRID["body_top"] + 0.5
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            it = {"titulo": str(it)}
        x = col_x(0) + i * (cw + gap)
        _card(slide, x, y, cw, 3.4, theme)
        cx = x + cw / 2
        av = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx - 0.7), Inches(y + 0.4),
                                    Inches(1.4), Inches(1.4))
        av.fill.solid(); av.fill.fore_color.rgb = _rgb(theme.accent_dim)
        av.line.fill.background()
        nome = it.get("titulo", "")
        ini = "".join(p[0] for p in str(nome).split()[:2]).upper()
        ap = av.text_frame.paragraphs[0]; ap.alignment = PP_ALIGN.CENTER
        ar = ap.add_run(); ar.text = ini or "•"; ar.font.size = Pt(28); ar.font.bold = True
        ar.font.color.rgb = _rgb(theme.bg); ar.font.name = "Segoe UI"
        _text(slide, nome, x + 0.1, y + 2.0, cw - 0.2, 0.5, style="lead",
              color=theme.text, align="center")
        if it.get("legenda"):
            _text(slide, it["legenda"], x + 0.1, y + 2.55, cw - 0.2, 0.6, style="caption",
                  bold=False, color=text_dim_of(theme), align="center")
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_numerado(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _accent_band(slide, theme)
    _header(slide, sc, theme)
    items = sc.get("bullets", []) or [it.get("titulo", "") if isinstance(it, dict) else it
                                      for it in (sc.get("items", []) or [])]
    n = max(1, min(len(items), 6))
    y = GRID["body_top"] + 0.1
    step = (GRID["body_bottom"] - y) / n
    for i, it in enumerate(items[:6]):
        num = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(col_x(0)),
                                     Inches(y + 0.05), Inches(0.55), Inches(0.55))
        num.fill.solid(); num.fill.fore_color.rgb = _rgb(theme.accent)
        num.line.fill.background()
        npp = num.text_frame.paragraphs[0]; npp.alignment = PP_ALIGN.CENTER
        nr = npp.add_run(); nr.text = str(i + 1); nr.font.bold = True
        nr.font.size = Pt(20); nr.font.color.rgb = _rgb(theme.bg); nr.font.name = "Segoe UI"
        _text(slide, str(it), col_x(1), y, span_w(10), step, style="lead", bold=False,
              color=theme.text, line_spacing=1.15)
        y += step
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_executivo(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    cols = (sc.get("items", []) or [])[:3]
    titulos_padrao = ["Situação", "Achados", "Recomendação"]
    gap = SPACE["md"]
    cw = (span_w(12) - 2 * gap) / 3
    y = GRID["body_top"]
    ch = GRID["body_bottom"] - y
    for i in range(3):
        it = cols[i] if i < len(cols) and isinstance(cols[i], dict) else {}
        x = col_x(0) + i * (cw + gap)
        _card(slide, x, y, cw, ch, theme)
        _text(slide, it.get("titulo") or titulos_padrao[i], x + 0.28, y + 0.3,
              cw - 0.56, 0.6, style="h3", color=theme.accent)
        body = it.get("desc") or it.get("legenda") or ""
        bullets = it.get("bullets") or []
        yy = y + 1.05
        if bullets:
            for b in bullets[:5]:
                _text(slide, "•  " + str(b), x + 0.28, yy, cw - 0.56, 0.5, style="body",
                      bold=False, color=theme.text, line_spacing=1.1)
                yy += 0.55
        elif body:
            _text(slide, body, x + 0.28, yy, cw - 0.56, ch - 1.3, style="body",
                  bold=False, color=theme.text, line_spacing=1.2)
    _footer(slide, theme)
    _add_transition(slide, transition)


def _l_galeria(prs, sc, theme, transition, image):
    slide = _blank(prs)
    _bg(slide, theme.bg)
    _header(slide, sc, theme)
    items = (sc.get("items", []) or [])[:4]
    n = max(1, len(items) or 2)
    cols = 2 if n <= 2 else (n if n <= 3 else 2)
    rows = (n + cols - 1) // cols
    gap = SPACE["md"]
    cw = (span_w(12) - (cols - 1) * gap) / cols
    area = GRID["body_bottom"] - GRID["body_top"]
    ch = (area - (rows - 1) * gap) / rows
    for i in range(n):
        it = items[i] if i < len(items) and isinstance(items[i], dict) else {}
        r, c = divmod(i, cols)
        x = col_x(0) + c * (cw + gap)
        y = GRID["body_top"] + r * (ch + gap)
        if i == 0 and image and os.path.exists(image):
            _image_cover(slide, image, x, y, cw, ch)
        else:
            _card(slide, x, y, cw, ch, theme, shadow=False)
        if it.get("titulo") or it.get("legenda"):
            _scrim(slide, x, y + ch - 0.7, cw, 0.7, theme.bg, 60)
            _text(slide, it.get("titulo") or it.get("legenda", ""), x + 0.2,
                  y + ch - 0.62, cw - 0.4, 0.5, style="body",
                  color="#ffffff" if i == 0 and image else theme.text)
    _footer(slide, theme)
    _add_transition(slide, transition)


LAYOUTS = {
    "capa": _l_capa, "hero": _l_hero, "secao": _l_secao, "agenda": _l_agenda,
    "topicos": _l_topicos, "texto": _l_texto, "duas_colunas": _l_duas_colunas,
    "comparativo": _l_comparativo, "kpi": _l_kpi, "bento": _l_bento,
    "timeline": _l_timeline, "citacao": _l_citacao, "destaque": _l_destaque,
    "imagem": _l_imagem, "imagem_lateral": _l_imagem_lateral, "fechamento": _l_fechamento,
    # novos
    "livre": _l_livre, "declaracao": _l_declaracao, "processo": _l_processo,
    "matriz": _l_matriz, "tabela": _l_tabela, "equipe": _l_equipe,
    "numerado": _l_numerado, "executivo": _l_executivo, "galeria": _l_galeria,
}
_IMAGE_LAYOUTS = {"capa", "hero", "topicos", "texto", "imagem", "imagem_lateral",
                  "fechamento", "livre", "galeria"}


# ─────────────────────────────────────────────────────────────────────────
# Limites de conteúdo (impedem overflow na origem) + manifesto
# ─────────────────────────────────────────────────────────────────────────
CAPS = {
    # Curtos (truncados se exagerarem) — precisam caber:
    "titulo": 72, "eyebrow": 28, "numero": 4, "valor": 16,
    "esq_titulo": 40, "dir_titulo": 40,
    "item_titulo": 48, "item_valor": 16, "item_quando": 18,
    # Texto longo (limites generosos — fonte encolhe p/ caber, NÃO trunca cedo):
    "subtitulo": 240, "legenda": 400, "corpo": 1600,
    "bullets_n": 8, "bullet_chars": 260,
    "col_n": 7, "col_chars": 200,
    "items_n": 6, "item_legenda": 200, "item_desc": 240,
}


def capability_manifest() -> dict:
    return {
        "temas": list(THEMES.keys()) + ["<nome de cor PT/EN>", "<hex #rrggbb>"],
        "transicoes": ["fade", "push", "wipe", "zoom", "split", "none"],
        "layouts": {
            "capa": "abertura grande (titulo, subtitulo?, eyebrow?, image_prompt?)",
            "hero": "imagem cheia + título sobreposto (titulo, legenda?, image_prompt)",
            "secao": "divisória de seção (titulo, numero?, eyebrow?)",
            "agenda": "índice/sumário (titulo, bullets[] OU items[])",
            "topicos": "título + bullets (titulo, bullets[], eyebrow?, image_prompt?)",
            "texto": "corpo de texto médio/grande, explicativo (titulo, corpo, image_prompt?)",
            "duas_colunas": "duas listas (titulo, esq_titulo, esquerda[], dir_titulo, direita[])",
            "comparativo": "comparação em 2 cards (titulo, esq_titulo, esquerda[], dir_titulo, direita[])",
            "kpi": "1-4 números grandes (titulo?, items[]={valor, titulo?, legenda?})",
            "bento": "grade de 3-6 cards (titulo, items[]={titulo, legenda?})",
            "timeline": "linha do tempo 3-5 marcos (titulo, items[]={quando, titulo})",
            "citacao": "citação grande (valor=frase, legenda=autor)",
            "destaque": "1 número/frase de impacto (valor, legenda?, titulo?)",
            "imagem": "imagem cheia c/ legenda (image_prompt, titulo?, legenda?)",
            "imagem_lateral": "imagem à direita + texto (titulo, bullets[] OU legenda, image_prompt)",
            "fechamento": "encerramento (titulo, subtitulo?, image_prompt?)",
            # novos
            "declaracao": "1 frase/afirmação grande de impacto (valor OU titulo, legenda?)",
            "processo": "passos em sequência c/ setas (titulo, items[]={titulo, desc?}, máx 5)",
            "matriz": "quadrante 2x2 (titulo, items[4]={titulo, legenda?})",
            "tabela": "tabela (titulo, headers[], rows[[...],...])",
            "equipe": "grade de pessoas (titulo, items[]={titulo=nome, legenda=cargo})",
            "numerado": "lista NUMERADA grande, passos ordenados (titulo, bullets[] OU items[])",
            "executivo": "resumo executivo 3 colunas (titulo, items[3]={titulo, bullets[]|desc})",
            "galeria": "grade de imagens/cards c/ legenda (titulo, items[]={titulo|legenda}, image_prompt)",
            "livre": "COMPOSE — você posiciona blocos no grid 12 colunas (titulo?, blocks[])",
        },
        "blocos_livre": {
            "grid": "12 colunas x 6 linhas. Cada bloco: {type, col(0-11), span(1-12), row(0-5), rspan(1-6), ...conteúdo}. Omita row p/ empilhar.",
            "tipos": {
                "titulo": "{texto}", "texto": "{texto}", "bullets": "{itens[]}",
                "stat": "{valor, titulo?, legenda?}", "card": "{titulo, texto?}",
                "imagem": "{} (usa a image_prompt do slide)", "citacao": "{texto, autor?}",
                "divisor": "{}",
            },
        },
        "decisao": {
            "1 número/métrica": "destaque ou kpi", "vários números": "kpi/bento",
            "1 frase forte": "declaracao", "explicação longa": "texto",
            "lista de pontos": "topicos", "passos em sequência": "processo/numerado",
            "comparar A vs B": "comparativo", "2 eixos/4 quadrantes": "matriz",
            "dados tabulares": "tabela", "linha do tempo": "timeline",
            "pessoas/time": "equipe", "citação": "citacao",
            "resumo executivo": "executivo", "muitas imagens": "galeria",
            "layout único/criativo": "livre (compose com blocks)",
        },
        "limites": {
            "titulo": f"<= {CAPS['titulo']} chars", "bullets": f"<= {CAPS['bullets_n']} itens, cada <= {CAPS['bullet_chars']} chars",
            "kpi.valor": f"<= {CAPS['item_valor']} chars (ex: '74%', 'R$ 5M')",
            "items": f"<= {CAPS['items_n']} itens",
        },
        "exemplos": [
            {"layout": "kpi", "titulo": "Resultados",
             "items": [{"valor": "+38%", "titulo": "Receita"}, {"valor": "12k", "titulo": "Usuários"}]},
            {"layout": "processo", "titulo": "Como funciona",
             "items": [{"titulo": "Coletar", "desc": "dados de origem"}, {"titulo": "Processar", "desc": "limpeza+ETL"}, {"titulo": "Entregar", "desc": "relatório"}]},
            {"layout": "livre", "titulo": "Visão",
             "blocks": [{"type": "stat", "col": 0, "span": 4, "row": 0, "rspan": 3, "valor": "74%", "titulo": "Acerto"},
                        {"type": "texto", "col": 4, "span": 8, "row": 0, "rspan": 3, "texto": "Explicação ao lado do número."}]},
        ],
        "regras": (
            "VARIE os layouts: adjacentes devem diferir; misture densos e visuais. "
            "Comece com 'capa', use 'secao' p/ dividir, termine com 'fechamento'. 1 ideia "
            "por slide. Use a tabela 'decisao' p/ escolher o layout pelo TIPO de conteúdo. "
            "Use 'texto' p/ explicações (não resuma a 3 bullets). 'livre' p/ composições "
            "criativas. image_prompt em INGLÊS, visual SEM texto. Títulos/valores curtos."
        ),
    }


def _clip(s, n):
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _clamp_item(it):
    if not isinstance(it, dict):
        return {"titulo": _clip(it, CAPS["item_titulo"])}
    out = {}
    if "valor" in it:
        out["valor"] = _clip(it["valor"], CAPS["item_valor"])
    if "titulo" in it:
        out["titulo"] = _clip(it["titulo"], CAPS["item_titulo"])
    if "legenda" in it:
        out["legenda"] = _clip(it["legenda"], CAPS["item_legenda"])
    if "quando" in it:
        out["quando"] = _clip(it["quando"], CAPS["item_quando"])
    if "desc" in it:
        out["desc"] = _clip(it["desc"], CAPS["item_desc"])
    return out


def _clamp(sc):
    for k in ("titulo", "subtitulo", "eyebrow", "numero", "valor", "legenda",
              "corpo", "esq_titulo", "dir_titulo"):
        if k in sc:
            cap = CAPS.get(k, 240)
            sc[k] = _clip(sc[k], cap)
    if "bullets" in sc and isinstance(sc["bullets"], list):
        sc["bullets"] = [_clip(b, CAPS["bullet_chars"]) for b in sc["bullets"][:CAPS["bullets_n"]]]
    for k in ("esquerda", "direita"):
        if k in sc and isinstance(sc[k], list):
            sc[k] = [_clip(b, CAPS["col_chars"]) for b in sc[k][:CAPS["col_n"]]]
    if "items" in sc and isinstance(sc["items"], list):
        sc["items"] = [_clamp_item(it) for it in sc["items"][:CAPS["items_n"]]]
    if "blocks" in sc and isinstance(sc["blocks"], list):
        sc["blocks"] = sc["blocks"][:14]
    if "rows" in sc and isinstance(sc["rows"], list):
        sc["rows"] = sc["rows"][:10]
    return sc


def pick_layout(sc) -> str:
    """Seleção adaptativa quando 'layout' falta/for inválido (heurística)."""
    if sc.get("blocks"):
        return "livre"
    if sc.get("headers") or sc.get("rows"):
        return "tabela"
    if sc.get("corpo"):
        return "texto"
    if sc.get("items"):
        items = sc["items"]
        if any(isinstance(i, dict) and "quando" in i for i in items):
            return "timeline"
        if any(isinstance(i, dict) and "valor" in i for i in items):
            return "kpi"
        return "bento"
    if sc.get("esquerda") or sc.get("direita"):
        return "comparativo"
    if sc.get("valor") and not sc.get("bullets"):
        return "citacao" if len(str(sc.get("valor", ""))) > 14 else "destaque"
    if sc.get("image_prompt") and not sc.get("bullets") and not sc.get("legenda"):
        return "imagem"
    if sc.get("bullets"):
        return "topicos"
    return "topicos"


# ─────────────────────────────────────────────────────────────────────────
# Tema + normalização + render
# ─────────────────────────────────────────────────────────────────────────
def _resolve_theme(tema: Optional[str]):
    if not tema:
        return get_theme("stark_dark")
    t = str(tema).strip()
    if t in THEMES:
        return get_theme(t)
    cor = parse_color_from_text(t)
    if cor:
        dark = not any(w in t.lower() for w in ("claro", "light", "branco", "white"))
        return build_custom_theme(cor, dark=dark)
    return get_theme("stark_dark")


def _normalize(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("spec deve ser um objeto")
    slides = spec.get("slides")
    if not isinstance(slides, list) or not slides:
        raise ValueError("spec.slides vazio")
    norm = []
    for sc in slides:
        if not isinstance(sc, dict):
            continue
        sc = {k: v for k, v in sc.items() if v is not None}  # remove None (strict)
        layout = (sc.get("layout") or "").strip().lower()
        if layout not in LAYOUTS:
            layout = pick_layout(sc)
        sc["layout"] = layout
        norm.append(_clamp(sc))
    if not norm:
        raise ValueError("nenhum slide válido")
    out = dict(spec)
    out["slides"] = norm
    return out


def gerar_deck(spec: dict, *, gen_visuals: bool = True,
               filename: Optional[str] = None) -> str:
    spec = _normalize(spec)
    theme = _resolve_theme(spec.get("tema"))
    transition = (spec.get("transicao") or "fade").strip().lower()

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    slides = spec["slides"]

    # imagens em paralelo p/ slides com image_prompt (router: OpenRouter→Pollinations)
    _ASPECT = {"capa": "16:9", "hero": "16:9", "imagem": "16:9", "fechamento": "16:9",
               "imagem_lateral": "3:4", "topicos": "1:1", "texto": "1:1"}
    images: dict[int, str] = {}
    if gen_visuals:
        import concurrent.futures as _cf
        import os as _os
        jobs = [(i, sc.get("image_prompt", ""), _ASPECT.get(sc.get("layout"), "16:9"))
                for i, sc in enumerate(slides)
                if sc.get("layout") in _IMAGE_LAYOUTS and sc.get("image_prompt")]
        if jobs:
            try:
                import config as _cfg
                or_img = bool((getattr(_cfg, "OPENROUTER_API_KEY", "")
                               or _os.environ.get("OPENROUTER_API_KEY", "")).strip())
            except Exception:
                or_img = False
            workers = 4 if or_img else 1  # Pollinations grátis: serializa p/ evitar 429

            def _one(j):
                i, prompt, aspect = j
                return i, gen_image(prompt, aspect=aspect)
            with _cf.ThreadPoolExecutor(max_workers=workers) as ex:
                for i, path in ex.map(_one, jobs):
                    if path:
                        images[i] = path
            print(f"[DECK] {len(images)}/{len(jobs)} imagens geradas "
                  f"(provider={'openrouter' if or_img else 'pollinations'})")

    for i, sc in enumerate(slides):
        fn = LAYOUTS.get(sc["layout"], _l_topicos)
        try:
            fn(prs, sc, theme, transition, images.get(i, ""))
        except Exception as exc:
            print(f"[DECK] slide {i} ({sc['layout']}) falhou: {exc} — fallback topicos")
            try:
                _l_topicos(prs, sc, theme, transition, images.get(i, ""))
            except Exception:
                pass

    for p in images.values():
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass

    base = filename or spec.get("titulo") or "apresentacao"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base)[:60].strip() or "apresentacao"
    out = os.path.join(_out_dir(), f"{safe}_{int(time.time())}.pptx")
    prs.save(out)
    return out


__all__ = ["gerar_deck", "capability_manifest", "LAYOUTS", "pick_layout"]
