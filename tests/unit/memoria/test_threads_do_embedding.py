"""As threads do e5 pela máquina (dono, 2026-10-21: escalar pelo hardware, com piso e override)."""

from __future__ import annotations

import pytest

from jarvis.memoryd.embedding import VARIAVEL_DAS_THREADS, threads_da_maquina


@pytest.mark.parametrize(("fios", "threads"), [(1, 2), (4, 2), (8, 2), (12, 4), (32, 4)])
def test_piso_dois_teto_quatro_pela_quantidade_de_fios(fios: int, threads: int) -> None:
    """Medido: 2 threads 6 ms, 4 threads 4–5 ms, 6 threads igual a 4 (Ryzen 5 5600G, 12 fios)."""
    assert threads_da_maquina(fios, ambiente={}) == threads


def test_a_variavel_manda_dentro_do_limite() -> None:
    assert threads_da_maquina(12, ambiente={VARIAVEL_DAS_THREADS: "1"}) == 1
    assert threads_da_maquina(12, ambiente={VARIAVEL_DAS_THREADS: "64"}) == 16
    assert threads_da_maquina(12, ambiente={VARIAVEL_DAS_THREADS: "muitas"}) == 4
