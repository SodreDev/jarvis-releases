# comandos/ocr_ctrl.py — J.A.R.V.I.S.
# OCR de tela — extrai texto de imagens/tela usando easyocr ou pytesseract
# Prioridade: easyocr (sem binário externo) → pytesseract → fallback visão LLM
# Instalar: pip install easyocr  (ou pip install pytesseract + Tesseract OCR)
# -*- coding: utf-8 -*-

from __future__ import annotations
import os
import re
import io
import time
import ctypes
import ctypes.wintypes
import tempfile
from typing import Optional

_DIR  = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_DIR)


# ── Captura de tela ───────────────────────────────────────────────────────────

def _capturar_tela(regiao: Optional[tuple[int, int, int, int]] = None) -> bytes:
    """
    Captura a tela e retorna PNG em bytes.
    regiao: (x, y, largura, altura) — None = tela toda
    """
    try:
        import mss
        with mss.mss() as sct:
            if regiao:
                x, y, w, h = regiao
                monitor = {"top": y, "left": x, "width": w, "height": h}
            else:
                monitor = sct.monitors[0]
            img = sct.grab(monitor)
            import mss.tools
            return mss.tools.to_png(img.rgb, img.size)
    except ImportError:
        pass

    # Fallback: PIL
    try:
        from PIL import ImageGrab
        import io as _io
        img = ImageGrab.grab(bbox=regiao)
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        pass

    # Fallback: win32 via ctypes
    user32  = ctypes.windll.user32
    gdi32   = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    width  = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    hdc_screen = user32.GetDC(None)
    hdc_mem    = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp       = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
    gdi32.SelectObject(hdc_mem, hbmp)
    gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, 0x00CC0020)

    # Salvar como BMP temporário
    tmp = tempfile.NamedTemporaryFile(suffix=".bmp", delete=False)
    tmp.close()
    # BITMAPFILEHEADER + pixel data — simplificado: usar PIL se disponível
    try:
        from PIL import Image
        import ctypes as ct
        class BITMAPINFOHEADER(ct.Structure):
            _fields_ = [
                ("biSize", ct.c_uint32), ("biWidth", ct.c_int32), ("biHeight", ct.c_int32),
                ("biPlanes", ct.c_uint16), ("biBitCount", ct.c_uint16),
                ("biCompression", ct.c_uint32), ("biSizeImage", ct.c_uint32),
                ("biXPelsPerMeter", ct.c_int32), ("biYPelsPerMeter", ct.c_int32),
                ("biClrUsed", ct.c_uint32), ("biClrImportant", ct.c_uint32),
            ]
        SRCCOPY = 0x00CC0020
        stride = ((width * 24 + 31) // 32) * 4
        bmi = BITMAPINFOHEADER(40, width, -height, 1, 24, 0, stride * height, 0, 0, 0, 0)
        buf_data = ct.create_string_buffer(stride * height)
        gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buf_data, ct.byref(bmi), 0)
        img2 = Image.frombytes("RGB", (width, height), buf_data.raw, "raw", "BGR", stride)
        out = io.BytesIO()
        img2.save(out, format="PNG")
        return out.getvalue()
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)


# ── OCR ───────────────────────────────────────────────────────────────────────

def _ocr_easyocr(img_bytes: bytes, idiomas: list[str]) -> Optional[str]:
    try:
        import easyocr
        import numpy as np
        from PIL import Image
        reader = easyocr.Reader(idiomas, gpu=False, verbose=False)
        img = Image.open(io.BytesIO(img_bytes))
        np_img = np.array(img)
        resultados = reader.readtext(np_img, detail=0, paragraph=True)
        return "\n".join(resultados)
    except ImportError:
        return None
    except Exception:
        return None


def _ocr_tesseract(img_bytes: bytes, idiomas: list[str]) -> Optional[str]:
    try:
        import pytesseract
        from PIL import Image
        lang_str = "+".join(idiomas)
        # Mapeamento de idiomas ISO → Tesseract
        _MAP = {"pt": "por", "en": "eng", "por": "por", "eng": "eng"}
        lang_tess = "+".join(_MAP.get(l, l) for l in idiomas)
        img = Image.open(io.BytesIO(img_bytes))
        texto = pytesseract.image_to_string(img, lang=lang_tess)
        return texto.strip()
    except ImportError:
        return None
    except Exception:
        return None


def _limpar_texto(texto: str) -> str:
    """Remove linhas em branco excessivas e espaços desnecessários."""
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


# ── API Pública ──────────────────────────────────────────────────────────────

def ler_tela(
    regiao: Optional[tuple[int, int, int, int]] = None,
    idiomas: Optional[list[str]] = None,
) -> str:
    """
    Captura a tela e extrai texto via OCR.
    Tenta easyocr → pytesseract → retorna erro orientativo.
    """
    if idiomas is None:
        idiomas = ["pt", "en"]

    try:
        img_bytes = _capturar_tela(regiao)
    except Exception as e:
        return f"Não foi possível capturar a tela: {e}"

    # Tenta easyocr primeiro
    texto = _ocr_easyocr(img_bytes, idiomas)
    if texto is None:
        texto = _ocr_tesseract(img_bytes, idiomas)

    if texto is None:
        return (
            "OCR não disponível, senhor.\n"
            "Instale: pip install easyocr\n"
            "Ou: pip install pytesseract + Tesseract OCR (https://github.com/UB-Mannheim/tesseract/wiki)"
        )

    if not texto.strip():
        return "Nenhum texto detectado na tela, senhor."

    texto = _limpar_texto(texto)
    # Limita para TTS (2000 chars)
    if len(texto) > 2000:
        texto = texto[:2000] + "\n[... texto truncado]"

    return f"Texto detectado na tela:\n{texto}"


def ler_regiao(x: int, y: int, largura: int, altura: int,
               idiomas: Optional[list[str]] = None) -> str:
    """Lê texto de uma região específica da tela."""
    return ler_tela(regiao=(x, y, largura, altura), idiomas=idiomas)


# ── Regiões verbais ──────────────────────────────────────────────────────────

def _get_screen_size() -> tuple[int, int]:
    """Retorna (largura, altura) da tela principal."""
    try:
        import mss
        with mss.mss() as sct:
            m = sct.monitors[0]
            return m["width"], m["height"]
    except Exception:
        pass
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    return w, h


def _resolver_regiao_verbal(descricao: str) -> Optional[tuple[int, int, int, int]]:
    """Converte um descritor verbal de região em (x, y, largura, altura) em pixels.

    Exemplos:
        "canto superior direito"  → quadrante superior direito
        "metade esquerda"         → metade esquerda da tela
        "terço inferior"          → terço inferior
        "centro"                  → 40-60% da tela em cada dimensão
        "tela toda"               → None (tela inteira)
    Retorna None se a descrição envolver "tela toda" ou não for reconhecida.
    """
    d = descricao.lower()
    d = re.sub(r"[áàâã]", "a", d)
    d = re.sub(r"[éèê]", "e", d)
    d = re.sub(r"[íì]", "i", d)
    d = re.sub(r"[óòôõ]", "o", d)
    d = re.sub(r"[úù]", "u", d)

    sw, sh = _get_screen_size()

    # Tela toda
    if re.search(r"\b(tela\s+(toda|inteira)|completa)\b", d):
        return None  # None → captura tela inteira

    # Canto (quadrante)
    if re.search(r"\bcanto\b", d):
        left  = re.search(r"\besquerd[ao]\b", d) is not None
        top   = re.search(r"\b(superior|cima)\b", d) is not None
        x = 0 if left else sw // 2
        y = 0 if top  else sh // 2
        return (x, y, sw // 2, sh // 2)

    # Metades
    if re.search(r"\b(metade|meio)\b", d):
        if re.search(r"\b(esquerda|esquerdo)\b", d):
            return (0, 0, sw // 2, sh)
        if re.search(r"\b(direita|direito)\b", d):
            return (sw // 2, 0, sw // 2, sh)
        if re.search(r"\b(superior|cima|topo)\b", d):
            return (0, 0, sw, sh // 2)
        if re.search(r"\b(inferior|baixo|base)\b", d):
            return (0, sh // 2, sw, sh // 2)

    # Terços
    if re.search(r"\bterce?[oi]\b", d):
        if re.search(r"\b(esquerda|esquerdo)\b", d):
            return (0, 0, sw // 3, sh)
        if re.search(r"\b(direita|direito)\b", d):
            return (sw * 2 // 3, 0, sw // 3, sh)
        if re.search(r"\b(superior|cima|topo)\b", d):
            return (0, 0, sw, sh // 3)
        if re.search(r"\b(inferior|baixo|base)\b", d):
            return (0, sh * 2 // 3, sw, sh // 3)
        if re.search(r"\b(central|centro|meio)\b", d):
            return (sw // 3, 0, sw // 3, sh)

    # Centro
    if re.search(r"\b(centro|central)\b", d):
        margin_x = sw // 5
        margin_y = sh // 5
        return (margin_x, margin_y, sw - 2 * margin_x, sh - 2 * margin_y)

    # Direções simples sem prefixo "metade"
    if re.search(r"\bsuperior\b|\bcima\b|\btopo\b", d):
        return (0, 0, sw, sh // 2)
    if re.search(r"\binferior\b|\bbaixo\b|\bbase\b", d):
        return (0, sh // 2, sw, sh // 2)
    if re.search(r"\besquerda\b|\besquerdo\b", d):
        return (0, 0, sw // 2, sh)
    if re.search(r"\bdireita\b|\bdireito\b", d):
        return (sw // 2, 0, sw // 2, sh)

    return None  # descrição não reconhecida → tela toda


def ler_regiao_verbal(descricao: str, idiomas: Optional[list[str]] = None) -> str:
    """Faz OCR em uma região da tela descrita verbalmente.

    Args:
        descricao: e.g. "canto superior direito", "metade esquerda", "centro"
        idiomas: lista de idiomas para OCR (padrão: ["pt", "en"])
    """
    regiao = _resolver_regiao_verbal(descricao)
    return ler_tela(regiao=regiao, idiomas=idiomas)


def ler_tela_traduzir(idioma_origem: str = "auto", idioma_destino: str = "pt") -> str:
    """Lê texto da tela e retorna o texto puro para tradução pelo LLM."""
    texto = ler_tela()
    if texto.startswith("Nenhum") or texto.startswith("OCR") or texto.startswith("Não"):
        return texto
    return texto


def salvar_ocr(caminho: Optional[str] = None) -> str:
    """Faz OCR da tela e salva o texto em arquivo."""
    texto = ler_tela()
    if not caminho:
        ts = time.strftime("%Y%m%d_%H%M%S")
        caminho = os.path.join(_ROOT, f"ocr_{ts}.txt")
    try:
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(texto)
        return f"Texto salvo em: {caminho}, senhor."
    except Exception as e:
        return f"Erro ao salvar arquivo OCR: {e}"
