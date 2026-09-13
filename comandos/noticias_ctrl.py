# comandos/noticias_ctrl.py — J.A.R.V.I.S.
# Notícias via RSS feeds (sem API key)
# -*- coding: utf-8 -*-

from __future__ import annotations
import urllib.request
import xml.etree.ElementTree as ET
import re
import html

# Feeds RSS confiáveis — CNN Brasil, R7 (Record), Jovem Pan
_FEEDS = {
    "geral": [
        "https://www.cnnbrasil.com.br/feed/",
        "https://noticias.r7.com/feed.xml",
        "https://jovempan.com.br/feed",
    ],
    "tecnologia": [
        "https://www.cnnbrasil.com.br/tecnologia/feed/",
    ],
    "economia": [
        "https://www.cnnbrasil.com.br/economia/feed/",
    ],
    "mundo": [
        "https://www.cnnbrasil.com.br/internacional/feed/",
    ],
    "ciencia": [
        "https://www.cnnbrasil.com.br/saude/feed/",
    ],
    "esporte": [
        "https://www.cnnbrasil.com.br/esportes/feed/",
    ],
}


def _fetch_rss(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _limpar_html(texto: str) -> str:
    texto = html.unescape(texto)
    texto = re.sub(r"<[^>]+>", "", texto)
    return texto.strip()


def _parse_items(root) -> list:
    """Extrai items de RSS ou Atom feed."""
    items = root.findall(".//item")
    if items:
        return items
    # Atom format
    for tag in (".//entry", ".//{http://www.w3.org/2005/Atom}entry"):
        items = root.findall(tag)
        if items:
            return items
    return []


def _item_title(item) -> str:
    for tag in ("title", "{http://www.w3.org/2005/Atom}title"):
        t = item.findtext(tag)
        if t:
            return _limpar_html(t)
    return "Sem título"


def _item_desc(item) -> str:
    for tag in ("description", "summary",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content"):
        t = item.findtext(tag)
        if t:
            return _limpar_html(t)
    return ""


def _fetch_best_feed(urls: list[str], n: int = 5) -> list:
    """Tenta cada URL na lista até encontrar um feed com items."""
    for url in urls:
        try:
            xml_text = _fetch_rss(url)
            root = ET.fromstring(xml_text)
            items = _parse_items(root)[:n]
            if items:
                return items
        except Exception:
            continue
    return []


def buscar_noticias(categoria: str = "geral", n: int = 5) -> str:
    """Busca as últimas notícias de uma categoria."""
    cat = categoria.strip().lower()
    # Mapeamentos flexíveis
    if cat in ("tech", "tec", "computador"):
        cat = "tecnologia"
    elif cat in ("dinheiro", "mercado", "financ"):
        cat = "economia"
    elif cat in ("esportes", "futebol"):
        cat = "esporte"
    elif cat in ("saude", "saúde"):
        cat = "ciencia"

    urls = _FEEDS.get(cat, _FEEDS["geral"])
    try:
        items = _fetch_best_feed(urls, n)
        if not items:
            return "Não encontrei notícias no momento."

        linhas = [f"📰 Notícias — {cat.title()} ({len(items)}):"]
        for i, item in enumerate(items, 1):
            titulo = _item_title(item)
            descricao = _item_desc(item)
            if len(descricao) > 120:
                descricao = descricao[:120] + "…"
            linhas.append(f"\n  {i}. {titulo}")
            if descricao:
                linhas.append(f"     {descricao}")

        return "\n".join(linhas)
    except Exception as e:
        return f"Erro ao buscar notícias: {e}"


def categorias_disponiveis() -> str:
    cats = ", ".join(sorted(_FEEDS.keys()))
    return f"Categorias disponíveis: {cats}"


def manchetes_rapidas(n: int = 3) -> str:
    """Manchetes curtas para briefing."""
    try:
        items = _fetch_best_feed(_FEEDS["geral"], n)
        if not items:
            return "Sem manchetes no momento."
        linhas = []
        for item in items:
            linhas.append(f"  • {_item_title(item)}")
        return "\n".join(linhas)
    except Exception:
        return "  • Manchetes indisponíveis"
