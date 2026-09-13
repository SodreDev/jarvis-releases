# jarvis/agents/router.py — J.A.R.V.I.S.
# Roteador SEMÂNTICO de domínio (roadmap/15 Fase 3). Decide, em ~5ms e 100%
# LOCAL, qual SUB-AGENTE (domínio) atende o turno — para o cérebro receber só as
# ~5-8 tools daquele domínio em vez de 44 (mata o 413 + melhora a seleção).
# Reusa o MESMO MiniLM já carregado (classifiers.embeddings) — ZERO 2º load.
# Padrão idêntico a jarvis/memory/router.py. Best-effort: em falha → (None, 0, 0).
# -*- coding: utf-8 -*-
from __future__ import annotations
import threading

from . import registry as _registry

_lock = threading.Lock()
_router = None  # singleton


class _DomainRouter:
    def __init__(self, model) -> None:
        import numpy as np
        self._np = np
        self._model = model
        self._labels: list[str] = []
        texts: list[str] = []
        for dom, spec in _registry.DOMAINS.items():
            for ex in spec.get("anchors", []):
                self._labels.append(dom)
                texts.append(ex)
        self._emb = model.encode(texts, normalize_embeddings=True)

    def route(self, text: str) -> tuple[str | None, float, float]:
        """(domínio, confiança, margem top1-top2). Quem decide o corte é o caller."""
        if not (text or "").strip():
            return None, 0.0, 0.0
        q = self._model.encode([text], normalize_embeddings=True)
        scores = (self._emb @ q.T).flatten()
        order = self._np.argsort(-scores)
        top1 = int(order[0])
        conf = float(scores[top1])
        # margem vs o melhor de OUTRO domínio (não só o 2º exemplo do mesmo)
        dom1 = self._labels[top1]
        second = 0.0
        for idx in order[1:]:
            if self._labels[int(idx)] != dom1:
                second = float(scores[int(idx)])
                break
        return dom1, conf, conf - second


def get_router(model=None):
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                if model is None:
                    from classifiers import embeddings as _emb
                    model = _emb.get_classifier()._model
                _router = _DomainRouter(model)
    return _router


def route(text: str, threshold: float = 0.42) -> tuple[str | None, float, float]:
    """Conveniência. Retorna (domínio|None, conf, margem). Nunca levanta."""
    try:
        return get_router().route(text)
    except Exception as e:
        print(f"[SUBAGENTE] router falhou: {e}")
        return None, 0.0, 0.0
