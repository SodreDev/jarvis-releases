# comandos/wikipedia_ctrl.py — J.A.R.V.I.S.
# Busca enciclopédica na Wikipedia (PT)
# -*- coding: utf-8 -*-

from __future__ import annotations
import urllib.request, urllib.parse, json, re

_API = "https://pt.wikipedia.org/w/api.php"
_HEADERS = {"User-Agent": "JARVIS/1.0 (jarvis@localhost)"}


def _fetch(params: dict, timeout: int = 8) -> dict:
    url = f"{_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def buscar_wikipedia(query: str) -> str:
    """Busca termo na Wikipedia PT e retorna resumo formatado."""
    query = query.strip()
    if not query:
        return "Sobre o que deseja saber, senhor?"

    # Busca pelo titulo
    try:
        data = _fetch({
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
            "srnamespace": 0,
        })
    except Exception as e:
        return f"Erro ao acessar Wikipedia: {e}"

    results = data.get("query", {}).get("search", [])
    if not results:
        # Tenta em inglês como fallback
        return _buscar_en(query)

    page_id = results[0]["pageid"]
    titulo  = results[0]["title"]

    # Extrai resumo da página
    try:
        data2 = _fetch({
            "action": "query",
            "pageids": page_id,
            "prop": "extracts",
            "exintro": True,
            "explaintext": True,
            "format": "json",
            "exsectionformat": "plain",
        })
        pages   = data2.get("query", {}).get("pages", {})
        extract = ""
        for page in pages.values():
            extract = page.get("extract", "").strip()
            titulo  = page.get("title", titulo)
            break
    except Exception:
        extract = ""

    if not extract:
        snippet = re.sub(r"<[^>]+>", "", results[0].get("snippet", ""))
        return f"📖 Wikipedia — {titulo}:\n{snippet}"

    # Trunca para não sobrecarregar o TTS
    if len(extract) > 1200:
        extract = extract[:1200].rsplit(".", 1)[0] + "."

    return f"📖 Wikipedia — {titulo}:\n{extract}"


def _buscar_en(query: str) -> str:
    """Fallback: busca na Wikipedia EN."""
    try:
        api_en = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": 1,
        }
        url = f"{api_en}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        results = data.get("query", {}).get("search", [])
        if results:
            snippet = re.sub(r"<[^>]+>", "", results[0].get("snippet", ""))
            titulo  = results[0]["title"]
            return f"📖 Wikipedia (EN) — {titulo}:\n{snippet}"
    except Exception:
        pass
    return f"Não encontrei nada sobre '{query}' na Wikipedia, senhor."
