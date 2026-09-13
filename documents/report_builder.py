# -*- coding: utf-8 -*-
"""documents.report_builder — Relatórios PDF spec→HTML→PDF (roadmap/13, Fase 2).

O LLM compõe uma SPEC (relatório + seções, cada uma escolhendo um BLOCO de um
catálogo curado). Python valida/clampa, gera UM HTML auto-contido dirigido pelos
design tokens do `design_system`, e o **Chromium do Playwright** (que o JARVIS já
empacota) converte HTML→PDF via `page.pdf()`. Ganha do reportlab: CSS3 completo
(flex/grid/multi-coluna), quebras de página reais, capa full-bleed, headers/footers.

Para converter arquivos NATIVOS (.docx/.xlsx/.pptx) → PDF, use `pdf_convert.to_pdf`
(MS Office COM → LibreOffice → fallback). Este módulo é o caminho de RELATÓRIO.

Spec:
  {
    "titulo": str, "subtitulo": str?, "tema": str?,
    "tipo_fonte": "executivo"|"financeiro"|"tecnico"|"generico"?,
    "page": "A4"|"Letter"?, "toc": bool?,
    "secoes": [ {block, ...conteúdo} ]
  }
Blocos: capa, secao, texto, bullets, kpi, tabela, callout, citacao,
        duas_colunas, imagem, grafico, divisor
"""
from __future__ import annotations

import os
import time
import html as _html
import base64 as _b64
from typing import Optional

from .design_system import (
    THEMES, PALETTE, get_theme, build_custom_theme, parse_color_from_text,
    tokens_to_css, text_dim_of,
)
from .pptx_engine import gen_image, _out_dir


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _resolve_theme(tema: Optional[str]):
    if not tema:
        return get_theme("stark_light")   # relatórios: claro por padrão
    t = str(tema).strip()
    if t in THEMES:
        return get_theme(t)
    cor = parse_color_from_text(t)
    if cor:
        dark = any(w in t.lower() for w in ("escuro", "dark", "preto", "black"))
        return build_custom_theme(cor, dark=dark)
    return get_theme("stark_light")


# ─────────────────────────────────────────────────────────────────────────
# Gráficos (matplotlib → data URI, offline e determinístico)
# ─────────────────────────────────────────────────────────────────────────
def _chart_data_uri(grafico: dict, theme) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io as _io
        tipo = (grafico.get("tipo") or "bar").lower()
        labels = grafico.get("labels") or grafico.get("x") or []
        valores = grafico.get("valores") or grafico.get("y") or []
        valores = [float(str(v).replace(",", ".").replace("%", "") or 0) for v in valores]
        accent = theme.accent
        grid = theme.grid
        txt = theme.text if theme.is_dark else "#0a0e1a"
        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=200)
        fig.patch.set_alpha(0.0); ax.set_facecolor("none")
        cyc = [accent, theme.accent_dim, PALETTE["ok"], PALETTE["warn"], PALETTE["crit"]]
        if tipo == "line":
            ax.plot(labels or range(len(valores)), valores, color=accent, linewidth=2.5, marker="o")
        elif tipo == "pie":
            ax.pie(valores, labels=labels, colors=cyc, autopct="%1.0f%%",
                   textprops={"color": txt})
        else:  # bar
            ax.bar(labels or [str(i) for i in range(len(valores))], valores,
                   color=[cyc[i % len(cyc)] for i in range(len(valores))])
        if tipo != "pie":
            for sp in ax.spines.values():
                sp.set_color(grid)
            ax.tick_params(colors=txt); ax.grid(axis="y", color=grid, alpha=0.4)
            for lbl in ax.get_xticklabels() + ax.get_yticklabels():
                lbl.set_color(txt)
        buf = _io.BytesIO()
        fig.savefig(buf, format="png", transparent=True, bbox_inches="tight")
        plt.close(fig)
        return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()
    except Exception as exc:
        print(f"[REPORT] gráfico falhou: {exc}")
        return ""


def _img_data_uri(path: str) -> str:
    try:
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
        with open(path, "rb") as f:
            return f"data:image/{ext};base64," + _b64.b64encode(f.read()).decode()
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────
# Catálogo de blocos → fragmentos HTML
# ─────────────────────────────────────────────────────────────────────────
def _b_capa(sc, ctx):
    eb = _esc(sc.get("eyebrow", "Relatório"))
    sub = f'<p class="cv-sub">{_esc(sc["subtitulo"])}</p>' if sc.get("subtitulo") else ""
    data = time.strftime("%d/%m/%Y")
    img = ctx.get("_images", {}).get(id(sc), "")
    bg = f'<img class="cv-img" src="{img}">' if img else ""
    return (f'<section class="cover">{bg}<div class="cv-inner">'
            f'<div class="eyebrow">{eb}</div>'
            f'<h1 class="cv-title">{_esc(sc.get("titulo",""))}</h1>{sub}'
            f'<div class="cv-foot">J.A.R.V.I.S • {data}</div></div></section>')


def _b_secao(sc, ctx):
    num = f'<div class="sec-num">{_esc(sc.get("numero",""))}</div>' if sc.get("numero") else ""
    return (f'<section class="section-divider">{num}'
            f'<h2 class="sec-title">{_esc(sc.get("titulo",""))}</h2></section>')


def _b_texto(sc, ctx):
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    corpo = sc.get("corpo") or sc.get("texto") or ""
    paras = "".join(f"<p>{_esc(p)}</p>" for p in str(corpo).split("\n") if p.strip())
    return f'<div class="blk texto">{h}{paras}</div>'


def _b_bullets(sc, ctx):
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    its = "".join(f"<li>{_esc(b)}</li>" for b in (sc.get("bullets") or sc.get("itens") or []))
    return f'<div class="blk"><｛h｝><ul class="bul">{its}</ul></div>'.replace("<｛h｝>", h)


def _b_kpi(sc, ctx):
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    cards = ""
    for it in (sc.get("items") or [])[:4]:
        if not isinstance(it, dict):
            it = {"valor": str(it)}
        cards += (f'<div class="kpi"><div class="kpi-v">{_esc(it.get("valor",""))}</div>'
                  f'<div class="kpi-t">{_esc(it.get("titulo",""))}</div>'
                  f'<div class="kpi-l">{_esc(it.get("legenda",""))}</div></div>')
    return f'<div class="blk">{h}<div class="kpi-row">{cards}</div></div>'


def _b_tabela(sc, ctx):
    headers = sc.get("headers") or []
    rows = sc.get("rows") or []
    if not headers and rows and isinstance(rows[0], list):
        headers = [f"Col {i+1}" for i in range(len(rows[0]))]
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    th = "".join(f"<th>{_esc(c)}</th>" for c in headers)
    trs = ""
    for r in rows:
        r = r if isinstance(r, list) else [r]
        trs += "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>"
    return (f'<div class="blk">{h}<table class="tbl"><thead><tr>{th}</tr></thead>'
            f'<tbody>{trs}</tbody></table></div>')


def _b_callout(sc, ctx):
    tipo = (sc.get("tipo") or "info").lower()
    return (f'<div class="callout co-{_esc(tipo)}"><b>{_esc(sc.get("titulo",""))}</b>'
            f'<div>{_esc(sc.get("texto") or sc.get("corpo",""))}</div></div>')


def _b_citacao(sc, ctx):
    aut = f'<cite>— {_esc(sc.get("legenda") or sc.get("autor"))}</cite>' if (sc.get("legenda") or sc.get("autor")) else ""
    return f'<blockquote class="quote">{_esc(sc.get("valor") or sc.get("texto",""))}{aut}</blockquote>'


def _b_duas_colunas(sc, ctx):
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    def col(t, items):
        ct = f'<h3>{_esc(t)}</h3>' if t else ""
        li = "".join(f"<li>{_esc(b)}</li>" for b in (items or []))
        return f'<div class="col">{ct}<ul class="bul">{li}</ul></div>'
    left = col(sc.get("esq_titulo", ""), sc.get("esquerda"))
    right = col(sc.get("dir_titulo", ""), sc.get("direita"))
    return f'<div class="blk">{h}<div class="cols2">{left}{right}</div></div>'


def _b_imagem(sc, ctx):
    img = ctx.get("_images", {}).get(id(sc), "")
    cap = f'<figcaption>{_esc(sc.get("legenda") or sc.get("titulo",""))}</figcaption>' if (sc.get("legenda") or sc.get("titulo")) else ""
    if not img:
        return f'<div class="blk figure ph">{cap}</div>'
    return f'<figure class="figure"><img src="{img}">{cap}</figure>'


def _b_grafico(sc, ctx):
    uri = _chart_data_uri(sc.get("grafico") or sc, ctx["theme"])
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    if not uri:
        return _b_tabela(sc, ctx)
    cap = f'<figcaption>{_esc(sc.get("legenda",""))}</figcaption>' if sc.get("legenda") else ""
    return f'<div class="blk">{h}<figure class="figure"><img src="{uri}">{cap}</figure></div>'


def _b_divisor(sc, ctx):
    return '<hr class="divisor">'


def _b_campos(sc, ctx):
    """Campos de PREENCHIMENTO (Nome: ____, Data: ____, assinatura)."""
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    linhas = ""
    for c in (sc.get("campos") or sc.get("items") or []):
        if isinstance(c, dict):
            lbl, largura = c.get("label") or c.get("titulo") or "", c.get("largura") or ""
        else:
            lbl, largura = str(c), ""
        st = f' style="min-width:{_esc(largura)}"' if largura else ""
        linhas += (f'<div class="campo"><span class="campo-lbl">{_esc(lbl)}</span>'
                   f'<span class="blank"{st}></span></div>')
    return f'<div class="blk campos">{h}{linhas}</div>'


def _b_questao(sc, ctx):
    """Questão de prova/simulado: enunciado + alternativas a)-e) + resposta? opcional."""
    num = _esc(sc.get("numero", ""))
    enun = _esc(sc.get("enunciado") or sc.get("corpo") or sc.get("titulo", ""))
    alts = sc.get("alternativas") or sc.get("opcoes") or sc.get("items") or []
    letras = "abcdefghij"
    opts = ""
    for i, a in enumerate(alts):
        txt = a.get("texto", "") if isinstance(a, dict) else str(a)
        opts += (f'<div class="alt"><span class="alt-l">{letras[i] if i < len(letras) else i})</span>'
                 f'<span>{_esc(txt)}</span></div>')
    resp = f'<div class="q-resp">Resposta: {_esc(sc["resposta"])}</div>' if sc.get("resposta") else ""
    nh = f'<span class="q-num">{num}.</span> ' if num else ""
    return (f'<div class="blk questao"><div class="q-enun">{nh}{enun}</div>'
            f'<div class="alternativas">{opts}</div>{resp}</div>')


def _b_gabarito(sc, ctx):
    """Gabarito (chave de respostas), compacto."""
    h = f'<h2>{_esc(sc.get("titulo") or "Gabarito")}</h2>'
    its = sc.get("respostas") or sc.get("gabarito") or sc.get("items") or []
    if isinstance(its, dict):
        its = [f"{k}-{v}" for k, v in its.items()]
    cells = ""
    for i, r in enumerate(its, 1):
        txt = f'{r.get("numero", i)}-{r.get("resposta", "")}' if isinstance(r, dict) else str(r)
        cells += f'<span class="gab-cell">{_esc(txt)}</span>'
    return f'<div class="blk gabarito">{h}<div class="gab-row">{cells}</div></div>'


def _b_equacao(sc, ctx):
    """Equação/MATEMÁTICA via KaTeX (selecionável). O LaTeX NÃO é escapado."""
    ctx["_has_math"] = True   # sinaliza p/ injetar o KaTeX no <head>
    h = f'<h2>{_esc(sc["titulo"])}</h2>' if sc.get("titulo") else ""
    tex = sc.get("latex") or sc.get("tex") or sc.get("corpo") or sc.get("equacao") or ""
    leg = f'<div class="eq-leg">{_esc(sc.get("legenda",""))}</div>' if sc.get("legenda") else ""
    return f'<div class="blk eq">{h}<div class="eq-body">$${tex}$$</div>{leg}</div>'


# KaTeX (CDN) — injetado no head SÓ quando há matemática. Selecionável/nítido.
# auto-render roda no DOMContentLoaded (após os scripts defer executarem); o
# page.set_content(wait_until="networkidle") espera os fetches do CDN.
_KATEX_HEAD = (
    '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>'
    '<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>'
    '<script>document.addEventListener("DOMContentLoaded",function(){try{renderMathInElement('
    'document.body,{delimiters:[{left:"$$",right:"$$",display:true},'
    '{left:"$",right:"$",display:false}],throwOnError:false});}catch(e){}});</script>'
)


BLOCKS = {
    "capa": _b_capa, "secao": _b_secao, "texto": _b_texto, "bullets": _b_bullets,
    "kpi": _b_kpi, "tabela": _b_tabela, "callout": _b_callout, "citacao": _b_citacao,
    "duas_colunas": _b_duas_colunas, "imagem": _b_imagem, "grafico": _b_grafico,
    "divisor": _b_divisor,
    "campos": _b_campos, "questao": _b_questao, "gabarito": _b_gabarito, "equacao": _b_equacao,
}
_IMG_BLOCKS = {"capa", "imagem"}


# ─────────────────────────────────────────────────────────────────────────
# CSS (estático; tokens via :root injetado por tokens_to_css)
# ─────────────────────────────────────────────────────────────────────────
_CSS = """
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
@page { size: %PAGE%; margin: 22mm 18mm 18mm 18mm; }
@page :first { margin: 0; }
html, body { margin:0; padding:0;
  font-family:'Segoe UI', Arial, 'Cambria Math', 'STIX Two Math', sans-serif;
  color: var(--text); background:#fff; font-size: var(--fs-body); line-height:1.5; }
p { orphans:3; widows:3; }
h1,h2,h3 { color: var(--accent); break-after: avoid; line-height:1.15; }
h2 { font-size: var(--fs-h2); margin:0 0 8pt; border-bottom:1.5pt solid var(--accent-dim); padding-bottom:4pt; }
h3 { font-size: var(--fs-h3); margin:0 0 6pt; }
.eyebrow { text-transform:uppercase; letter-spacing:2px; font-size:var(--fs-eyebrow);
  color: var(--accent); font-weight:700; }
.blk { margin: 0 0 16pt; break-inside: avoid; }
.cover { position:relative; min-height:78mm; background:var(--bg);
  color:var(--text); display:flex; align-items:flex-end; overflow:hidden; margin-bottom:14pt; }
.cover .cv-img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
.cv-inner { position:relative; padding:24mm 18mm; width:100%;
  background:linear-gradient(transparent, rgba(0,0,0,.55)); }
.cv-title { font-size:var(--fs-display); margin:6pt 0; color:var(--accent); }
.cv-sub { font-size:var(--fs-lead); color:var(--text-dim); margin:0; }
.cv-foot { margin-top:14pt; font-size:var(--fs-caption); color:var(--text-dim); }
.section-divider { padding-top:6pt; margin-top:16pt; break-after:avoid; }
.sec-num { font-size:var(--fs-display); color:var(--accent-dim); font-weight:800; }
.sec-title { font-size:var(--fs-h1); border:0; }
.bul { margin:0 0 0 4pt; padding:0 0 0 16pt; }
.bul li { margin:0 0 5pt; }
.kpi-row { display:flex; gap:12pt; }
.kpi { flex:1; border:1pt solid var(--grid); border-radius:8pt; padding:12pt;
  background:var(--card); text-align:center; }
.kpi-v { font-size:36pt; font-weight:800; color:var(--accent); }
.kpi-t { font-size:var(--fs-lead); color:var(--text); }
.kpi-l { font-size:var(--fs-caption); color:var(--text-dim); }
.tbl { width:100%; border-collapse:collapse; font-size:var(--fs-caption); }
.tbl thead { display:table-header-group; }
.tbl th { background:var(--accent-dim); color:#fff; text-align:left; padding:6pt 8pt; }
.tbl td { padding:5pt 8pt; border-bottom:.5pt solid var(--grid); }
.tbl tbody tr:nth-child(even) { background:var(--panel); }
.callout { border-left:4pt solid var(--accent); background:var(--panel);
  padding:10pt 12pt; border-radius:4pt; margin:0 0 14pt; break-inside:avoid; }
.callout.co-warn { border-color:var(--warn); } .callout.co-ok { border-color:var(--ok); }
.callout.co-crit { border-color:var(--crit); }
.quote { font-size:var(--fs-h3); color:var(--text); border:0; margin:14pt 0;
  padding-left:14pt; border-left:3pt solid var(--accent-dim); break-inside:avoid; }
.quote cite { display:block; margin-top:6pt; font-size:var(--fs-caption);
  color:var(--text-dim); font-style:normal; }
.cols2 { display:flex; gap:20pt; } .cols2 .col { flex:1; }
.figure { margin:0 0 14pt; break-inside:avoid; text-align:center; }
.figure img { max-width:100%; border-radius:6pt; }
.figure.ph { height:60mm; background:var(--panel); border:1pt dashed var(--grid); border-radius:6pt; }
figcaption { font-size:var(--fs-caption); color:var(--text-dim); margin-top:4pt; }
.divisor { border:0; border-top:1pt solid var(--grid); margin:14pt 0; }
nav.toc { margin-bottom:16pt; }
nav.toc a { color:var(--text); text-decoration:none; display:block; padding:5pt 0;
  border-bottom:.5pt solid var(--grid); }
/* skins por tipo de fonte */
body.report-financeiro .kpi-v { font-size:30pt; }
body.report-tecnico { font-size:11pt; }
body.report-tecnico code, body.report-tecnico pre { font-family:Consolas, monospace; }
/* campos de preenchimento */
.campos .campo { display:flex; align-items:baseline; gap:8pt; margin:0 0 11pt; }
.campo-lbl { color:var(--text); font-weight:600; white-space:nowrap; }
.blank { flex:1; min-width:120pt; border-bottom:1pt solid var(--text); height:1.05em; }
/* questão de prova/simulado */
.questao { break-inside:avoid; margin:0 0 14pt; }
.q-enun { font-weight:600; margin:0 0 6pt; }
.q-num { color:var(--accent); font-weight:800; }
.alternativas { margin:0 0 0 10pt; }
.alt { display:flex; gap:6pt; margin:0 0 3pt; }
.alt-l { color:var(--accent); font-weight:700; }
.q-resp { font-size:var(--fs-caption); color:var(--text-dim); margin-top:4pt; }
/* gabarito */
.gabarito .gab-row { display:flex; flex-wrap:wrap; gap:8pt; }
.gab-cell { border:1pt solid var(--grid); border-radius:4pt; padding:3pt 9pt;
  background:var(--card); font-weight:600; }
/* matemática (KaTeX) */
.eq { text-align:center; break-inside:avoid; }
.eq-body { margin:8pt 0; font-size:var(--fs-h3); }
.eq-leg { font-size:var(--fs-caption); color:var(--text-dim); }
"""


def _build_html(spec: dict, theme) -> str:
    page = (spec.get("page") or "A4")
    if page not in ("A4", "Letter", "Legal"):
        page = "A4"
    css = _CSS.replace("%PAGE%", page)
    root = tokens_to_css(theme)
    tipo = (spec.get("tipo_fonte") or "generico").lower()
    secoes = spec["secoes"]
    ctx = {"theme": theme, "_images": spec.get("_images", {})}

    # TOC opcional (links âncora — clicáveis no PDF; outline=True dá bookmarks)
    toc_html = ""
    if spec.get("toc"):
        links = ""
        for i, sc in enumerate(secoes):
            if sc.get("block") in ("secao",) and sc.get("titulo"):
                links += f'<a href="#sec{i}">{_esc(sc["titulo"])}</a>'
        if links:
            toc_html = f'<nav class="toc"><h2>Sumário</h2>{links}</nav>'

    body_parts = []
    for i, sc in enumerate(secoes):
        fn = BLOCKS.get(sc.get("block"), _b_texto)
        frag = fn(sc, ctx)
        if sc.get("block") == "secao":
            frag = frag.replace('<section class="section-divider">',
                                f'<section class="section-divider" id="sec{i}">')
        body_parts.append(frag)
    body = "".join(body_parts)
    # KaTeX só quando há matemática (bloco 'equacao' ou '$' inline) — não pesa PDFs sem math.
    _math = _KATEX_HEAD if (ctx.get("_has_math") or "$" in body) else ""
    return (f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            f"{_math}<style>{root}{css}</style></head>"
            f"<body class='report-{_esc(tipo)}'>{toc_html}{body}</body></html>")


# ─────────────────────────────────────────────────────────────────────────
# Normalização + render
# ─────────────────────────────────────────────────────────────────────────
def _normalize(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("spec deve ser objeto")
    secoes = spec.get("secoes") or spec.get("slides") or []
    if not isinstance(secoes, list) or not secoes:
        raise ValueError("spec.secoes vazio")
    norm = []
    for sc in secoes:
        if not isinstance(sc, dict):
            continue
        sc = {k: v for k, v in sc.items() if v is not None}
        b = (sc.get("block") or sc.get("layout") or "texto").strip().lower()
        if b not in BLOCKS:
            print(f"[REPORT] bloco desconhecido '{b}' → texto (revise a spec)")
            b = "texto"
        sc["block"] = b
        norm.append(sc)
    if not norm:
        raise ValueError("nenhuma seção válida")
    out = dict(spec)
    out["secoes"] = norm
    return out


def gerar_relatorio(spec: dict, *, gen_visuals: bool = True,
                    filename: Optional[str] = None) -> str:
    """Renderiza a spec → PDF (HTML→Chromium). Retorna o caminho do .pdf."""
    spec = _normalize(spec)
    theme = _resolve_theme(spec.get("tema"))

    # Imagens (capa/imagem com image_prompt) via gen_image → data URI
    images = {}
    if gen_visuals:
        for sc in spec["secoes"]:
            if sc.get("block") in _IMG_BLOCKS and sc.get("image_prompt"):
                aspect = "16:9" if sc["block"] == "capa" else "4:3"
                p = gen_image(sc["image_prompt"], aspect=aspect)
                if p:
                    uri = _img_data_uri(p)
                    if uri:
                        images[id(sc)] = uri
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
    spec["_images"] = images

    html = _build_html(spec, theme)

    base = filename or spec.get("titulo") or "relatorio"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base)[:60].strip() or "relatorio"
    out = os.path.join(_out_dir(), f"{safe}_{int(time.time())}.pdf")

    try:
        from jarvis.browser.playwright_setup import ensure_chromium_sync
        ensure_chromium_sync()
    except Exception:
        pass
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            try:
                page.evaluate("document.fonts && document.fonts.ready")
            except Exception:
                pass
            _hdr = ('<div style="font-size:8px;width:100%;padding:0 14mm;color:#888;'
                    'border-bottom:.5px solid #ccc;text-align:right">'
                    + _esc(spec.get("titulo", "")) + "</div>")
            _ftr = ('<div style="font-size:8px;width:100%;padding:0 14mm;color:#888;'
                    'text-align:center">Página <span class="pageNumber"></span> '
                    'de <span class="totalPages"></span></div>')
            page.pdf(path=out, prefer_css_page_size=True, print_background=True,
                     display_header_footer=True,
                     margin={"top": "22mm", "bottom": "16mm", "left": "0", "right": "0"},
                     header_template=_hdr, footer_template=_ftr, outline=True)
        finally:
            browser.close()
    return out


def capability_manifest() -> dict:
    return {
        "tipo_fonte": ["executivo", "financeiro", "tecnico", "generico"],
        "page": ["A4", "Letter", "Legal"],
        "blocos": {
            "capa": "capa full-bleed (titulo, subtitulo?, eyebrow?, image_prompt?)",
            "secao": "divisória de capítulo, nova página (titulo, numero?)",
            "texto": "título + parágrafos (titulo?, corpo)",
            "bullets": "lista (titulo?, bullets[])",
            "kpi": "linha de métricas (titulo?, items[]={valor,titulo,legenda?})",
            "tabela": "tabela (titulo?, headers[], rows[[...]])",
            "callout": "caixa destacada (tipo: info|warn|ok|crit, titulo, texto)",
            "citacao": "citação (valor, legenda=autor?)",
            "duas_colunas": "duas listas (titulo?, esq_titulo, esquerda[], dir_titulo, direita[])",
            "imagem": "figura (image_prompt, legenda?)",
            "grafico": "gráfico de dados (titulo?, grafico={tipo:bar|line|pie, labels[], valores[]}, legenda?)",
            "divisor": "linha divisória",
        },
        "regras": ("Comece com 'capa'. Use 'secao' p/ capítulos (quebra página). "
                   "'grafico' p/ dados numéricos, 'tabela' p/ dados tabulares, 'kpi' p/ "
                   "métricas-chave, 'texto' p/ explicações longas. tipo_fonte ajusta o estilo. "
                   "image_prompt em INGLÊS, visual SEM texto."),
    }


__all__ = ["gerar_relatorio", "capability_manifest", "BLOCKS"]
