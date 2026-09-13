# -*- coding: utf-8 -*-
"""documents.image_fetcher — Busca imagens gratuitas para documentos JARVIS.

Usa Lorem Picsum (https://picsum.photos) — sem API key, sem rate-limit agressivo.
Imagens são cacheadas em data/img_cache/ para evitar re-downloads.
"""

from __future__ import annotations

import hashlib
import os
import sys
from typing import Optional


def _cache_dir() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data", "img_cache")
    os.makedirs(d, exist_ok=True)
    return d


def fetch_for_keyword(
    keyword: str,
    width: int = 800,
    height: int = 450,
    *,
    timeout: int = 8,
) -> Optional[str]:
    """Retorna caminho local de uma imagem associada ao keyword.

    Usa Lorem Picsum com seed derivado do keyword — mesma keyword sempre
    devolve a mesma imagem (determinístico), sem API key.
    Retorna None se download falhar (sem exceção).
    """
    if not keyword:
        return None

    slug = hashlib.md5(keyword.lower().strip().encode()).hexdigest()[:12]
    dest = os.path.join(_cache_dir(), f"{slug}_{width}x{height}.jpg")

    if os.path.exists(dest) and os.path.getsize(dest) > 4096:
        return dest

    try:
        import urllib.request

        seed = hashlib.md5(keyword.lower().strip().encode()).hexdigest()[:8]
        url = f"https://picsum.photos/seed/{seed}/{width}/{height}.jpg"
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()

        if len(data) < 4096:
            return None  # resposta de erro / redirect vazio

        with open(dest, "wb") as fh:
            fh.write(data)
        return dest

    except Exception:
        return None


__all__ = ["fetch_for_keyword"]
