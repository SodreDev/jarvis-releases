"""A regra de decisão da §8.2 como o harness a aplica — sem modelo e sem rede."""

from __future__ import annotations

import pytest
from tools.harness_recuperacao import decidir


def _q(
    recall: float, ndcg: float = 0.5, abstencao: float = 0.7, **extra: float
) -> dict[str, float]:
    return {
        "recall20_C2bc": recall,
        "ndcg10_C2bc": ndcg,
        "abstencao_correta": abstencao,
        "vencido_nas_evidencias": 0.0,
        "sem_caminho": 0.0,
        **extra,
    }


@pytest.mark.parametrize(
    ("c", "p95", "comeca"),
    [
        (_q(0.80), 30.0, "regra 2"),
        (_q(0.73), 30.0, "regra 3"),
        (_q(0.71), 30.0, "regra 4"),
        (_q(0.80, abstencao=0.6), 30.0, "inconclusivo"),
        (_q(0.90), 300.0, "regra 1"),
        (_q(0.90, vencido_nas_evidencias=1.0), 30.0, "regra 1"),
    ],
)
def test_regra_da_8_2(c: dict[str, float], p95: float, comeca: str) -> None:
    b = _q(0.70)
    assert decidir(b, c, {"C": p95}, "C").startswith(comeca)
