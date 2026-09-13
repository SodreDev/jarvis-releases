# jarvis/memory/retrieval.py — J.A.R.V.I.S.
# Funções puras de pontuação para a memória vetorial (numpy, sem dependências
# extras). Score composto estilo Generative Agents (Park et al.) + MMR para
# diversidade. Tudo normalizado em [0,1] sobre o conjunto de candidatos.
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Sequence
import numpy as np


def _minmax(v: np.ndarray) -> np.ndarray:
    """Normaliza para [0,1]; se todos iguais, retorna zeros (sinal neutro)."""
    v = np.asarray(v, dtype=np.float32)
    if v.size == 0:
        return v
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        return np.zeros_like(v)
    return (v - lo) / (hi - lo)


def recency_decay(ts_last_access: np.ndarray, now: float, decay: float = 0.995) -> np.ndarray:
    """decay ^ (horas desde o último acesso). Mais recente → mais perto de 1."""
    ts = np.asarray(ts_last_access, dtype=np.float64)
    hours = np.maximum(0.0, (now - ts) / 3600.0)
    return np.power(float(decay), hours).astype(np.float32)


def composite_score(
    similarity: np.ndarray,
    recency: np.ndarray,
    importance: np.ndarray,
    pinned: np.ndarray,
    weights: dict,
) -> np.ndarray:
    """score = w_s·sim + w_r·recência + w_i·importância + w_p·pinned (cada um
    normalizado em [0,1] sobre os candidatos). `weights` usa chaves s/r/i/p."""
    s = _minmax(similarity) * float(weights.get("s", 0.0))
    r = _minmax(recency) * float(weights.get("r", 0.0))
    i = _minmax(importance) * float(weights.get("i", 0.0))
    # pinned é binário (0/1) — não normaliza, só pesa.
    p = np.asarray(pinned, dtype=np.float32) * float(weights.get("p", 0.0))
    return (s + r + i + p).astype(np.float32)


def mmr(
    query_vec: np.ndarray,
    cand_vecs: np.ndarray,
    base_scores: np.ndarray,
    lambda_: float = 0.6,
    k: int = 6,
) -> list[int]:
    """Maximal Marginal Relevance: equilibra relevância (base_scores) e
    diversidade (1 - sim máx aos já escolhidos). Retorna índices selecionados.

    cand_vecs: [N,D] normalizados. query_vec: [D] ou [1,D] normalizado.
    """
    n = cand_vecs.shape[0]
    if n == 0:
        return []
    k = min(k, n)
    base = _minmax(base_scores)
    selected: list[int] = []
    remaining = list(range(n))
    # similaridade entre candidatos (vetores normalizados → produto escalar)
    sim_cc = cand_vecs @ cand_vecs.T
    while remaining and len(selected) < k:
        if not selected:
            best = int(remaining[np.argmax(base[remaining])])
            selected.append(best)
            remaining.remove(best)
            continue
        best_idx, best_val = remaining[0], -1e9
        for idx in remaining:
            max_sim_to_sel = float(np.max(sim_cc[idx, selected]))
            mmr_val = lambda_ * float(base[idx]) - (1.0 - lambda_) * max_sim_to_sel
            if mmr_val > best_val:
                best_val, best_idx = mmr_val, idx
        selected.append(best_idx)
        remaining.remove(best_idx)
    return selected
