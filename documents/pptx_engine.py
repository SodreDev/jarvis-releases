# -*- coding: utf-8 -*-
"""documents.pptx_engine — geração de apresentações PowerPoint Stark."""

from __future__ import annotations
import os
import sys
import time
import tempfile
import urllib.request
from typing import List, Optional
from lxml import etree

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

from .design_system import get_theme, hex_to_rgb, PALETTE

# ── Namespaces PPTX ──────────────────────────────────────────────────────────
_PPTX_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DRAW_NS  = "http://schemas.openxmlformats.org/drawingml/2006/main"

# Mapeia nome amigável → atributo XML de p:transition
_TRANSITIONS: dict[str, dict] = {
    "fade":  {"type": "fade",  "advTm": "1200"},
    "push":  {"type": "push",  "advTm": "800",  "dir": "l"},
    "wipe":  {"type": "wipe",  "advTm": "800",  "dir": "l"},
    "zoom":  {"type": "zoom",  "advTm": "1000", "in": "1"},
    "split": {"type": "split", "advTm": "800"},
    "none":  {},
}


def _base() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Geração de imagem via Pollinations.ai ───────────────────────────────────

_IMG_STYLE = ("professional presentation illustration, clean minimal flat "
              "editorial design, soft gradient, vibrant colors, no text")


def gen_image(prompt: str, width: int = 1152, height: int = 768,
              aspect: str = "16:9") -> str:
    """Gera uma imagem e retorna o path (ou '' em falha). Roteamento (roadmap/13):
    1) modelo de imagem do OpenRouter (se OPENROUTER_API_KEY + image_render);
    2) Pollinations (grátis, com token+backoff).  Groq NÃO gera imagem."""
    import os as _os
    try:
        import config as _cfg
        try:
            provider = _cfg.get_image_provider()
        except Exception:
            provider = "auto"
        if provider != "pollinations":
            key = (getattr(_cfg, "OPENROUTER_API_KEY", "") or
                   _os.environ.get("OPENROUTER_API_KEY", "")).strip()
            try:
                model = _cfg.get_openrouter_model("image_render")
            except Exception:
                model = (getattr(_cfg, "OPENROUTER_MODELS", {}) or {}).get("image_render", "")
            if key and model:
                p = _openrouter_image(prompt, model, key, aspect,
                                      getattr(_cfg, "OPENROUTER_BASE_URL",
                                              "https://openrouter.ai/api/v1"))
                if p:
                    return p
            elif provider == "openrouter":
                print("[IMG] provider=openrouter sem chave/modelo — usando Pollinations")
    except Exception as exc:
        print(f"[IMG] OpenRouter indisponível: {exc}")
    return _download_visual(prompt, width, height)


def _openrouter_image(prompt: str, model: str, key: str, aspect: str,
                      base_url: str) -> str:
    """Gera imagem via OpenRouter /chat/completions (modalities=['image','text'])."""
    import json as _json
    import base64 as _b64
    body = {
        "model": model,
        "messages": [{"role": "user", "content": f"{prompt}, {_IMG_STYLE}"}],
        "modalities": ["image", "text"],
    }
    if aspect:
        body["image_config"] = {"aspect_ratio": aspect}
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=_json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/NinjaZinS2",
            "X-Title": "JARVIS",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = _json.loads(resp.read())
    imgs = (data.get("choices") or [{}])[0].get("message", {}).get("images") or []
    if not imgs:
        return ""
    url = imgs[0].get("image_url", {}).get("url", "")
    if not url:
        return ""
    b64 = url.split(",", 1)[1] if "," in url else url
    raw = _b64.b64decode(b64)
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    with open(tmp.name, "wb") as fh:
        fh.write(raw)
    print(f"[IMG] OpenRouter ({model}) → {os.path.basename(tmp.name)}")
    return tmp.name


def _download_visual(prompt: str, width: int = 1152, height: int = 768) -> str:
    """Pollinations.ai → arquivo temp. Token (tier Seed) + backoff em 429."""
    from urllib.parse import quote
    import urllib.error as _uerr
    import time as _t
    import os as _os
    full_prompt = f"{prompt}, {_IMG_STYLE}"
    token = ""
    try:
        import config as _cfg2
        token = (getattr(_cfg2, "POLLINATIONS_TOKEN", "")
                 or _os.environ.get("POLLINATIONS_TOKEN", "")).strip()
    except Exception:
        token = (_os.environ.get("POLLINATIONS_TOKEN", "") or "").strip()
    url = (f"https://image.pollinations.ai/prompt/{quote(full_prompt)}"
           f"?model=flux&width={width}&height={height}&enhance=true")
    headers = {"User-Agent": "JARVIS-DocEngine/2.0"}
    if token:
        url += "&nologo=true"
        headers["Authorization"] = f"Bearer {token}"
    for delay in (0, 1, 2, 4, 8):
        if delay:
            _t.sleep(delay)
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(tmp.name, "wb") as fh:
                    fh.write(resp.read())
            return tmp.name
        except _uerr.HTTPError as e:
            if e.code == 429 and delay != 8:
                print(f"[PPTX-VISUAL] 429 (rate-limit) — backoff {delay or 1}s")
                continue
            print(f"[PPTX-VISUAL] Falha HTTP {e.code}")
            return ""
        except Exception as exc:
            print(f"[PPTX-VISUAL] Falha ao baixar imagem: {exc}")
            return ""
    return ""





def _out_dir() -> str:
    d = os.path.join(_base(), "data", "documents")
    os.makedirs(d, exist_ok=True)
    return d


def _rgb(hex_color: str) -> RGBColor:
    r, g, b = hex_to_rgb(hex_color)
    return RGBColor(r, g, b)


def _set_bg(slide, color_hex: str) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(color_hex)


def _add_text(slide, text: str, *, left: float, top: float, width: float, height: float,
              font_size: int = 18, bold: bool = False, color_hex: str = "#d9e7ff",
              align: str = "left") -> None:
    tb = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = {"left": PP_ALIGN.LEFT, "center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.LEFT)
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = _rgb(color_hex)
    run.font.name = "Segoe UI"


def _add_accent_bar(slide, theme) -> None:
    """Barra ciano vertical à esquerda como acento HUD."""
    from pptx.util import Inches
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                   Inches(0), Inches(0), Inches(0.08), Inches(7.5))
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(theme.accent)
    shape.line.fill.background()


def _add_transition(slide, transition: str = "fade") -> None:
    """Injeta elemento XML <p:transition> no slide para animação de entrada.

    Suporte: fade, push, wipe, zoom, split, none.
    Funciona diretamente no XML OOXML — python-pptx não expõe esta API.
    """
    cfg = _TRANSITIONS.get(transition.lower(), _TRANSITIONS["fade"])
    if not cfg:
        return  # "none" → sem elemento

    spTree = slide._element
    # Remove qualquer transição anterior para evitar duplicata
    for old in spTree.findall(f"{{{_PPTX_NS}}}transition"):
        spTree.remove(old)

    trans_el = etree.SubElement(spTree, f"{{{_PPTX_NS}}}transition")
    trans_el.set("spd", "med")          # velocidade: slow | med | fast
    trans_el.set("advTm", cfg.get("advTm", "1000"))

    t = cfg["type"]
    child_tag = f"{{{_PPTX_NS}}}{t}"
    child = etree.SubElement(trans_el, child_tag)
    if "dir" in cfg:
        child.set("dir", cfg["dir"])
    if "in" in cfg:
        child.set("in", cfg["in"])


def _add_right_panel(slide, icon: str, theme, *, x: float = 7.5,
                     image_path: str = "") -> None:
    """Painel decorativo direito: imagem AI (se disponível) ou halos + emoji.

    Quando `image_path` aponta para um arquivo válido, exibe a imagem gerada
    preenchendo o painel — visual similar ao Canva. Caso contrário, usa o
    fallback de halos concêntricos + emoji.
    """
    panel_w = 13.33 - x
    cx = x + panel_w / 2
    cy = 3.75  # centro vertical do slide

    # Fundo do painel (sempre presente, fica atrás da imagem se houver)
    panel = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                   Inches(x), Inches(0), Inches(panel_w), Inches(7.5))
    panel.fill.solid()
    panel.fill.fore_color.rgb = _rgb(theme.panel)
    panel.line.fill.background()

    # ── Imagem AI (Pollinations) ──────────────────────────────────────────
    if image_path and os.path.exists(image_path):
        try:
            slide.shapes.add_picture(
                image_path,
                Inches(x), Inches(0),
                Inches(panel_w), Inches(7.5),
            )
            # Faixa semitransparente na base com accent color (branding sutil)
            _bar_h = 0.30
            bar = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(x), Inches(7.5 - _bar_h), Inches(panel_w), Inches(_bar_h),
            )
            bar.fill.solid()
            r_a, g_a, b_a = hex_to_rgb(theme.accent)
            bar.fill.fore_color.rgb = RGBColor(r_a, g_a, b_a)
            bar.line.fill.background()
            return  # ← imagem OK, encerra sem desenhar emoji
        except Exception as exc:
            print(f"[PPTX-PANEL] Erro ao inserir imagem: {exc}")
            # Fallback para emoji abaixo

    # ── Fallback: halos concêntricos + emoji ─────────────────────────────
    for r_in, alpha in ((2.8, 0.06), (2.0, 0.11), (1.3, 0.18)):
        circ = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(cx - r_in), Inches(cy - r_in),
            Inches(r_in * 2), Inches(r_in * 2),
        )
        circ.fill.solid()
        r_bg, g_bg, b_bg = hex_to_rgb(theme.panel)
        r_ac, g_ac, b_ac = hex_to_rgb(theme.accent)
        blended = (
            int(r_bg + (r_ac - r_bg) * alpha),
            int(g_bg + (g_ac - g_bg) * alpha),
            int(b_bg + (b_ac - b_bg) * alpha),
        )
        circ.fill.fore_color.rgb = RGBColor(*blended)
        circ.line.fill.background()

    # Círculo central em accent color (base do ícone)
    badge_r = 1.05
    badge = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(cx - badge_r), Inches(cy - badge_r),
        Inches(badge_r * 2), Inches(badge_r * 2),
    )
    badge.fill.solid()
    badge.fill.fore_color.rgb = _rgb(theme.accent)
    badge.line.fill.background()

    # Emoji grande no centro
    icon_char = (icon or "").strip() or "✦"
    tb = slide.shapes.add_textbox(
        Inches(cx - badge_r), Inches(cy - 0.70),
        Inches(badge_r * 2), Inches(1.40),
    )
    tf = tb.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = icon_char
    run.font.size = Pt(64)
    run.font.name = "Segoe UI Emoji"


def _title_slide(prs, title: str, subtitle: str, theme,
                 icon: str = "",
                 transition: str = "fade",
                 image: str = "") -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_bg(slide, theme.bg)

    # Painel decorativo direito com ícone / imagem AI
    _add_right_panel(slide, icon, theme, x=7.5, image_path=image)

    _add_accent_bar(slide, theme)
    _add_text(slide, title, left=0.6, top=2.2, width=7, height=2.0,
              font_size=48, bold=True, color_hex=theme.accent)
    if subtitle:
        _add_text(slide, subtitle, left=0.6, top=4.0, width=7, height=1,
                  font_size=20, color_hex=PALETTE["text_dim"])
    _add_text(slide, f"J.A.R.V.I.S • {time.strftime('%d/%m/%Y')}",
              left=0.6, top=6.8, width=7, height=0.4,
              font_size=11, color_hex=PALETTE["text_dim"])
    _add_transition(slide, transition)


def _content_slide(prs, title: str, bullets: List[str], theme,
                   icon: str = "",
                   transition: str = "fade",
                   image: str = "") -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, theme.bg)

    # Painel direito com imagem AI / ícone emoji
    _add_right_panel(slide, icon, theme, x=7.3, image_path=image)

    _add_accent_bar(slide, theme)
    _add_text(slide, title, left=0.6, top=0.25, width=6.5, height=0.9,
              font_size=30, bold=True, color_hex=theme.accent)
    # Linha decorativa sob o título
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0.6), Inches(1.15), Inches(2.8), Inches(0.04))
    line.fill.solid()
    line.fill.fore_color.rgb = _rgb(theme.accent_dim)
    line.line.fill.background()

    # Bullets com marcador numérico colorido
    y_off = 1.45
    for i, b in enumerate(bullets):
        # Círculo numerado
        badge = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(0.62), Inches(y_off + 0.04), Inches(0.30), Inches(0.30),
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = _rgb(theme.accent)
        badge.line.fill.background()
        badge_tf = badge.text_frame
        badge_tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        badge_run = badge_tf.paragraphs[0].add_run()
        badge_run.text = str(i + 1)
        badge_run.font.size = Pt(9)
        badge_run.font.bold = True
        badge_run.font.color.rgb = _rgb(theme.bg)
        badge_run.font.name = "Segoe UI"

        # Texto do bullet
        tb = slide.shapes.add_textbox(
            Inches(1.05), Inches(y_off), Inches(5.75), Inches(0.42),
        )
        tf = tb.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.LEFT
        run = p.add_run()
        run.text = b
        run.font.size = Pt(16)
        run.font.color.rgb = _rgb(theme.text)
        run.font.name = "Segoe UI"

        y_off += 0.55
        if y_off > 6.8:
            break

    _add_transition(slide, transition)


def gerar_apresentacao(
    titulo: str,
    slides_content: List[dict],
    *,
    subtitulo: str = "",
    theme_name: str = "stark_dark",
    transition: str = "fade",
    filename: Optional[str] = None,
    gen_visuals: bool = False,
) -> str:
    """
    Gera um .pptx com tema Stark.

    `slides_content` = lista de dicts {"title": ..., "bullets": [...], "image": path?, "icon": emoji?}
    `transition`     = "fade" | "push" | "wipe" | "zoom" | "split" | "none"
    `gen_visuals`    = True → baixa imagem temática do Pollinations.ai para cada slide
    """
    theme = get_theme(theme_name)
    prs = Presentation()
    prs.slide_width = Inches(13.33)
    prs.slide_height = Inches(7.5)

    # Ícone padrão para slide de título
    title_icon = slides_content[0].get("icon", "") if slides_content else ""

    # ── Geração paralela de imagens AI ───────────────────────────────────
    slide_images: dict[int, str] = {}  # índice (0=capa) → path temp
    if gen_visuals:
        import concurrent.futures as _cf

        def _make_prompt(idx: int, sc: dict) -> tuple[int, str]:
            if idx == -1:  # capa
                return idx, _download_visual(
                    f"{titulo} {subtitulo} cover art cinematic professional", 1152, 768)
            title_s = sc.get("title", "")
            kw = " ".join(str(b) for b in (sc.get("bullets") or [])[:2])
            return idx, _download_visual(f"{title_s} {kw}", 1152, 768)

        jobs = [(-1, {"title": titulo, "bullets": []})] + list(enumerate(slides_content))
        with _cf.ThreadPoolExecutor(max_workers=5) as ex:
            for idx, path in ex.map(lambda j: _make_prompt(j[0], j[1]), jobs):
                if path:
                    slide_images[idx] = path
        print(f"[PPTX-VISUAL] {len(slide_images)}/{len(jobs)} imagens geradas")

    _title_slide(prs, titulo, subtitulo, theme, icon=title_icon,
                 transition=transition, image=slide_images.get(-1, ""))

    for i, sc in enumerate(slides_content):
        img = sc.get("image") or slide_images.get(i, "")
        _content_slide(
            prs,
            sc.get("title", ""),
            list(sc.get("bullets", [])),
            theme,
            icon=sc.get("icon", ""),
            transition=transition,
            image=img,
        )

    # Limpa arquivos temporários gerados
    for p in slide_images.values():
        try:
            if p and os.path.exists(p):
                os.unlink(p)
        except Exception:
            pass

    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (filename or titulo))[:60].strip() or "apresentacao"
    out = os.path.join(_out_dir(), f"{safe}_{int(time.time())}.pptx")
    prs.save(out)
    return out


__all__ = ["gerar_apresentacao"]
