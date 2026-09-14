"""Oráculo golden: cópias LITERAIS de trechos do commit `31bc0ce` (fim da
fase 1 — base da fase 2, ver docs/linux-port/FILA-fase2-executor.md),
embrulhadas em funções que recebem fakes/parâmetros injetados em vez de
ler `os.environ`, `ctypes.windll` ou chamar as APIs do SO direto.

NUNCA editar este arquivo fora de uma emenda do arquiteto (mesma regra da
fase 1, FILA §Protocolo item 5: "tests/golden/ ... são do qa" e o
executor não edita). É o oráculo contra o qual os testes C/K de
F2-01 (hotkeys), F2-02 (tray), F2-03 (volume), F2-04 (clipboard),
F2-06 (open_path), F2-07 (session), F2-08 (media) e F2-09 (restart_self)
comparam o comportamento novo — cada função entra sob demanda, na tarefa
G-A/G-B/G-C correspondente (ver FILA), sempre ANTES do executor mexer no
código de produção daquela capacidade.

Ainda vazio nesta tarefa (T0): só o esqueleto. Preencher função por
função, citando a âncora exata em `main.py`/`comandos/*.py` de onde o
trecho foi copiado (linha e nome), igual a `legacy_1c32e38.py` da fase 1.
"""
from __future__ import annotations

__all__: list[str] = []
