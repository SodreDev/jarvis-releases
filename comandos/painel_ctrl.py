# -*- coding: utf-8 -*-
"""
comandos.painel_ctrl — Painel Global J.A.R.V.I.S.

Orquestra o Painel Global: notícias, YouTube, portfolio, ticker,
resumos, imagens e chat bidirecional. Servido em /painel pelo FastAPI.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _now_ms() -> int:
    return int(time.time() * 1000)


def _extract_yt_id(url_ou_id: str) -> str:
    url_ou_id = url_ou_id.strip()
    m = re.search(
        r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|live/|shorts/))([A-Za-z0-9_\-]{8,16})",
        url_ou_id,
    )
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_\-]{8,16}", url_ou_id):
        return url_ou_id
    return url_ou_id


# ─────────────────────────────────────────────────────────────────────────────
# Controle do painel
# ─────────────────────────────────────────────────────────────────────────────

def abrir_painel(*, open_browser: bool = True) -> str:
    """Sobe o servidor e abre o Painel Global no navegador (/painel)."""
    from dashboard.server import start_dashboard, open_in_browser, url_painel
    start_dashboard()
    try:
        from ide.api import register as _ide_register
        _ide_register()
    except Exception:
        pass
    painel_url = url_painel()
    if open_browser:
        open_in_browser(painel_url)
    return painel_url


def fechar_painel() -> None:
    from dashboard.server import stop_dashboard
    stop_dashboard()


# ─────────────────────────────────────────────────────────────────────────────
# Cards genéricos
# ─────────────────────────────────────────────────────────────────────────────

def publicar_card(card_id: str, titulo: str, corpo: str = "", **extra) -> dict:
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    payload: Dict[str, Any] = {
        "id": card_id, "title": titulo, "type": "text",
        "body": corpo, "content": {"text": corpo}, "ts": _now_ms(),
        **extra,
    }
    push_card(payload)
    return payload


def remover_card(card_id: str) -> bool:
    from dashboard.server import remove_card
    return remove_card(card_id)


# ─────────────────────────────────────────────────────────────────────────────
# Notícias
# ─────────────────────────────────────────────────────────────────────────────

def adicionar_noticia(topico: str, max_items: int = 6) -> dict:
    """Busca notícias sobre *topico* via DuckDuckGo e publica card no painel."""
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    articles: List[Dict[str, Any]] = []
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            for r in ddgs.news(topico, max_results=max_items):
                articles.append({
                    "title":   r.get("title", ""),
                    "summary": r.get("body", ""),
                    "url":     r.get("url", ""),
                    "source":  r.get("source", ""),
                    "date":    r.get("date", ""),
                    "image":   r.get("image", ""),
                })
    except Exception as e:
        articles = [{"title": f"Erro ao buscar notícias: {e}", "url": "", "source": "JARVIS"}]

    card_id = "news_" + re.sub(r"[^a-z0-9]", "_", topico.lower())[:32]
    payload: Dict[str, Any] = {
        "id": card_id, "type": "news",
        "title": f"Notícias · {topico}",
        "cols": 5, "rows": 3,
        "ts": _now_ms(),
        "content": {"articles": articles},
    }
    push_card(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# YouTube
# ─────────────────────────────────────────────────────────────────────────────

def adicionar_youtube(url_ou_id: str, titulo: str = "", live: bool = False) -> dict:
    """Adiciona player YouTube ao painel. Aceita URL completa ou video_id."""
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    vid = _extract_yt_id(url_ou_id)
    card_id = f"yt_{vid[:16]}"
    payload: Dict[str, Any] = {
        "id": card_id, "type": "youtube",
        "title": titulo or ("🔴 Ao Vivo" if live else "YouTube"),
        "cols": 6, "rows": 3,
        "ts": _now_ms(),
        "video_id": vid,
        "content": {"video_id": vid, "live": live},
    }
    push_card(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Carteira de investimentos
# ─────────────────────────────────────────────────────────────────────────────

def montar_carteira(
    acoes: Optional[List[Dict[str, Any]]] = None,
    renda_fixa: Optional[List[Dict[str, Any]]] = None,
    card_id: str = "portfolio_main",
) -> dict:
    """Monta card de carteira de investimentos no painel.

    acoes: [{"symbol":"PETR4.SA","name":"Petrobras","price":38.5,"change_pct":1.2}, ...]
           Se price ausente, busca via yfinance automaticamente.
    renda_fixa: [{"nome":"CDB Nubank","taxa":"115% CDI","valor":5000,"emissor":"Nubank"}, ...]
    """
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    acoes      = acoes or []
    renda_fixa = renda_fixa or []
    if acoes:
        acoes = _enriquecer_acoes(acoes)
    payload: Dict[str, Any] = {
        "id": card_id, "type": "portfolio",
        "title": "Carteira de Investimentos",
        "cols": 6, "rows": 3,
        "ts": _now_ms(),
        "content": {"acoes": acoes, "renda_fixa": renda_fixa},
    }
    push_card(payload)
    return payload


def _enriquecer_acoes(acoes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        import yfinance as yf
        syms = [a.get("symbol") or a.get("simbolo", "") for a in acoes]
        syms_valid = [s for s in syms if s]
        if not syms_valid:
            return acoes
        tickers = yf.Tickers(" ".join(syms_valid))
        out = []
        for a in acoes:
            sym = a.get("symbol") or a.get("simbolo", "")
            try:
                info  = tickers.tickers[sym].fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                prev  = float(getattr(info, "previous_close", price) or price)
                chg   = ((price - prev) / prev * 100) if prev else 0.0
                a = {**a, "price": round(price, 2), "change_pct": round(chg, 2)}
            except Exception:
                pass
            out.append(a)
        return out
    except Exception:
        return acoes


# ─────────────────────────────────────────────────────────────────────────────
# Ticker de cotações
# ─────────────────────────────────────────────────────────────────────────────

def adicionar_ticker(
    simbolos: Optional[List[str]] = None,
    card_id: str = "ticker_main",
) -> dict:
    """Adiciona faixa de cotações rolante ao painel."""
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    simbolos = simbolos or ["^BVSP", "PETR4.SA", "VALE3.SA", "ITUB4.SA", "BTC-USD", "USDBRL=X"]
    items: List[Dict[str, Any]] = []
    try:
        import yfinance as yf
        for sym in simbolos:
            try:
                info  = yf.Ticker(sym).fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                prev  = float(getattr(info, "previous_close", price) or price)
                chg   = ((price - prev) / prev * 100) if prev else 0.0
                items.append({
                    "symbol": sym, "value": f"{price:,.2f}", "change_pct": round(chg, 2),
                })
            except Exception:
                items.append({"symbol": sym, "value": "—", "change_pct": 0})
    except ImportError:
        items = [{"symbol": s, "value": "—", "change_pct": 0} for s in simbolos]
    payload: Dict[str, Any] = {
        "id": card_id, "type": "ticker",
        "title": "Cotações ao vivo",
        "cols": 12, "rows": 1,
        "ts": _now_ms(),
        "content": {"items": items},
    }
    push_card(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Resumo
# ─────────────────────────────────────────────────────────────────────────────

def adicionar_resumo(
    texto: str,
    titulo: str = "Resumo",
    fontes: Optional[List[Dict[str, str]]] = None,
    card_id: Optional[str] = None,
) -> dict:
    """Publica card de resumo com texto e lista de fontes."""
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    cid = card_id or f"summary_{_now_ms()}"
    payload: Dict[str, Any] = {
        "id": cid, "type": "summary",
        "title": titulo,
        "cols": 6, "rows": 3,
        "ts": _now_ms(),
        "content": {"text": texto, "sources": fontes or []},
    }
    push_card(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Imagem
# ─────────────────────────────────────────────────────────────────────────────

def adicionar_imagem_card(
    caminho_ou_url: str,
    titulo: str = "Imagem Gerada",
    card_id: Optional[str] = None,
) -> dict:
    """Publica imagem como card no painel. Aceita caminho local ou URL."""
    from dashboard.server import push_card, start_dashboard
    start_dashboard()
    final_url: str = caminho_ou_url
    if not caminho_ou_url.startswith("http"):
        try:
            import os
            static_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "dashboard", "static"
            )
            rel = os.path.relpath(caminho_ou_url, static_dir).replace("\\", "/")
            if not rel.startswith(".."):
                from dashboard.server import url as srv_url
                final_url = srv_url(f"/static/{rel}")
        except Exception:
            pass
    cid = card_id or f"img_{_now_ms()}"
    payload: Dict[str, Any] = {
        "id": cid, "type": "image",
        "title": titulo,
        "cols": 4, "rows": 3,
        "ts": _now_ms(),
        "url": final_url,
        "content": {"url": final_url},
    }
    push_card(payload)
    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Janelas / monitores
# ─────────────────────────────────────────────────────────────────────────────

def listar_monitores() -> list:
    try:
        from core import screens
        return [m.to_dict() for m in screens.list_monitors()]
    except Exception:
        return []


def mover_janela(
    *,
    titulo: Optional[str] = None,
    hwnd: Optional[int] = None,
    monitor: int = 0,
    ratio: float = 1.0,
    fullscreen: bool = False,
    align: str = "center",
) -> bool:
    try:
        from core import screens
    except Exception:
        return False
    if hwnd is not None:
        return screens.move_window(int(hwnd), monitor, fullscreen=fullscreen, ratio=ratio, align=align)
    if titulo:
        return screens.move_window_by_title(titulo, monitor, fullscreen=fullscreen, ratio=ratio, align=align)
    return False


def log_painel(level: str, msg: str) -> None:
    from dashboard.server import push_log
    push_log(level, msg)


# ─────────────────────────────────────────────────────────────────────────────
# Chat bidirecional
# ─────────────────────────────────────────────────────────────────────────────

def chat_jarvis(mensagem: str) -> None:
    """Exibe mensagem do JARVIS no chat lateral do painel."""
    try:
        from dashboard.server import push_chat
        push_chat("jarvis", mensagem)
    except Exception:
        pass


def get_cmd_painel() -> Optional[Dict[str, Any]]:
    """Retorna e remove próximo comando enviado pelo usuário no painel (ou None)."""
    try:
        from dashboard.server import get_pending_cmd
        return get_pending_cmd()
    except Exception:
        return None


__all__ = [
    "abrir_painel", "fechar_painel",
    "publicar_card", "remover_card",
    "adicionar_noticia", "adicionar_youtube",
    "montar_carteira", "adicionar_ticker",
    "adicionar_resumo", "adicionar_imagem_card",
    "listar_monitores", "mover_janela", "log_painel",
    "chat_jarvis", "get_cmd_painel",
]

