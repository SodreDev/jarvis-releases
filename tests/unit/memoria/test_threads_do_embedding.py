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


def test_aquecer_em_segundo_plano_abre_o_modelo_uma_vez_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auditoria da memória (2026-10-30): o app passou a aquecer o e5 ao abrir o livro; a 1ª
    consulta que chega junto não abre outra sessão ONNX."""
    import threading
    import time

    from jarvis.memoryd.embedding import EmbedderE5

    aberturas: list[int] = []

    def abrir_devagar(self: EmbedderE5) -> None:
        aberturas.append(1)
        time.sleep(0.05)
        self._sessao = object()

    monkeypatch.setattr(EmbedderE5, "_abrir", abrir_devagar)
    embedder = EmbedderE5()
    linha = embedder.aquecer_em_segundo_plano()
    concorrentes = [threading.Thread(target=embedder.abrir) for _ in range(4)]
    for outra in concorrentes:
        outra.start()
    for outra in (linha, *concorrentes):
        outra.join(5.0)
    assert aberturas == [1]
