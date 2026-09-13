# jarvis/memory/router.py — J.A.R.V.I.S.
# Roteador de POLÍTICA de recuperação por situação ("buscar a memória certa do
# jeito mais rápido para cada caso"). Reusa o MiniLM já carregado pelo
# classificador de intenção — zero rede, ~5ms. Classifica a query em uma de 5
# políticas e devolve os pesos/segmentos/k para o MemoryStore.retrieve().
# -*- coding: utf-8 -*-
from __future__ import annotations
import threading

# Frases-âncora por política (PT-BR). 6-10 por política bastam.
_POLICY_EXAMPLES: dict[str, list[str]] = {
    # Continuidade: refere-se ao que acabou de acontecer / "de novo".
    "continuidade": [
        "continua", "o que eu disse agora", "aquele", "esse aí",
        "manda pra ele", "de novo", "refaz isso", "o de antes",
        "como eu pedi", "aquilo que você fez", "o último", "esse mesmo",
        "repete", "faz igual", "o arquivo que você gerou",
        "refaz o PDF", "refaz o relatório", "refaz o documento",
        "o PDF que você gerou", "o relatório que você fez", "o documento de antes",
        "muda a cor", "muda as cores", "deixa mais escuro", "deixa mais claro",
        "gera de novo aquele", "aquele arquivo", "corrige aquilo", "ajusta o que fez",
    ],
    # Recall factual: pergunta um fato concreto.
    "factual": [
        "qual o meu", "onde fica", "quando é", "qual é o nome de",
        "que horas", "qual foi", "me lembra qual", "quanto custa",
        "qual o endereço", "qual o número de", "que dia",
    ],
    # Identidade / preferência: algo do usuário ("minha IDE", "como gosto").
    "identidade": [
        "minha IDE", "meu editor", "como eu gosto", "meu nome",
        "prefiro", "minha preferência", "meu site", "meu projeto",
        "minha conta", "do meu jeito", "meu tema favorito", "minha pasta",
    ],
    # Procedural: uma rotina/skill aprendida.
    "procedural": [
        "como faço de novo", "a rotina de", "do jeito que costumo",
        "o passo a passo", "como sempre", "a sequência que uso",
    ],
}

# policy → (pesos s/r/i/p, segmentos, k, usar_mmr)
POLICIES: dict[str, dict] = {
    "continuidade": {"weights": {"r": 0.75, "s": 0.15, "i": 0.05, "p": 0.05},
                     "segments": ["episodic"], "k": 3, "mmr": False},
    "factual":      {"weights": {"r": 0.10, "s": 0.80, "i": 0.10, "p": 0.00},
                     "segments": ["semantic"], "k": 5, "mmr": False},
    "identidade":   {"weights": {"r": 0.00, "s": 0.30, "i": 0.20, "p": 0.50},
                     "segments": ["semantic"], "k": 4, "mmr": False},
    "procedural":   {"weights": {"r": 0.10, "s": 0.70, "i": 0.20, "p": 0.00},
                     "segments": ["procedural", "episodic"], "k": 4, "mmr": False},
    # Aberto/ambíguo (default e fallback): híbrido sobre tudo + MMR.
    "hybrid":       {"weights": {"r": 0.30, "s": 0.45, "i": 0.20, "p": 0.05},
                     "segments": ["episodic", "semantic", "procedural"], "k": 6, "mmr": True},
}

_lock = threading.Lock()
_router = None  # singleton


class _QueryRouter:
    def __init__(self, model) -> None:
        import numpy as np
        self._np = np
        self._model = model
        self._labels: list[str] = []
        texts: list[str] = []
        for pol, exs in _POLICY_EXAMPLES.items():
            for e in exs:
                self._labels.append(pol)
                texts.append(e)
        self._emb = model.encode(texts, normalize_embeddings=True)

    def route(self, text: str, threshold: float = 0.35) -> tuple[str, float]:
        """Retorna (policy, confidence). Abaixo do threshold → 'hybrid'
        (nunca erra feio, só trabalha um pouco mais)."""
        q = self._model.encode([text], normalize_embeddings=True)
        scores = (self._emb @ q.T).flatten()
        bi = int(self._np.argmax(scores))
        conf = float(scores[bi])
        if conf < threshold:
            return "hybrid", conf
        return self._labels[bi], conf


def get_router(model=None):
    """Singleton. Reusa o MiniLM do classificador se `model` não for passado."""
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                if model is None:
                    from classifiers import embeddings as _emb
                    model = _emb.get_classifier()._model
                _router = _QueryRouter(model)
    return _router


def policy_for(text: str, threshold: float = 0.35) -> dict:
    """Conveniência: query → dict de política (com a chave 'policy' e 'conf')."""
    try:
        pol, conf = get_router().route(text, threshold)
    except Exception:
        pol, conf = "hybrid", 0.0
    out = dict(POLICIES.get(pol, POLICIES["hybrid"]))
    out["policy"] = pol
    out["conf"] = conf
    return out
