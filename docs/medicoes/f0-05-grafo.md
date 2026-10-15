# F0-05 — harness da memória em grafo: números medidos

**Gerado por** `tools/harness_memoria.py` (não editar à mão). **Data:** 2026-10-15.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 31 GiB de RAM, Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43
- Python 3.12.14, SQLite 3.53.1, banco em memória
- 200 consultas por execução, 3 execuções independentes, orçamento da §6.8 em 40 ms
- grafo sintético determinístico (semente fixa), `n` base = 122 episódios: as memórias que o Orchestrator guarda para este projeto em 2026-10-15
- **[SUPOSIÇÃO]** razões do gerador: 3 entidades e 8 arestas por episódio (grau médio ~5). O cartão F0-08 troca isso pela contagem real do exportador.
- a lista densa da fusão é **simulada** (sobreposição de termos): isto mede custo, não qualidade de recuperação — qualidade é a medição da §8.1/§8.2, em F3

## Tamanho real de cada escala

| escala | episódios | entidades | arestas | unidades |
|---|---:|---:|---:|---:|
| 1x | 122 | 366 | 974 | 122 |
| 10x | 1220 | 3660 | 9758 | 1220 |
| 100x | 12200 | 36600 | 97599 | 12200 |

## SLO-11 — ativação de grafo (meta: p50 ≤ 15 ms, p95 ≤ 40 ms)

Mediana das três execuções, por escala, implementação e número de saltos.

| escala | implementação | saltos | p50 (ms) | p95 (ms) | p99 (ms) | nós | arestas | truncados |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 100x | memoria | 1 | 0.064 | 0.103 | 0.140 | 6.3 | 5.3 | 0/600 |
| 100x | memoria | 2 | 0.318 | 0.634 | 0.816 | 34.5 | 38.9 | 0/600 |
| 100x | sql-por-no | 1 | 0.102 | 0.164 | 0.201 | 6.3 | 5.3 | 0/600 |
| 100x | sql-por-no | 2 | 0.767 | 1.539 | 1.848 | 34.5 | 38.9 | 0/600 |
| 100x | sql-por-salto | 1 | 0.277 | 0.355 | 0.444 | 6.3 | 5.3 | 0/600 |
| 100x | sql-por-salto | 2 | 0.630 | 0.972 | 1.306 | 34.5 | 38.9 | 0/600 |
| 100x | sql-recursivo | 1 | 40.172 | 40.374 | 41.426 | 0.0 | 0.0 | 600/600 |
| 100x | sql-recursivo | 2 | 40.141 | 40.269 | 40.358 | 0.0 | 0.0 | 600/600 |
| 10x | memoria | 1 | 0.056 | 0.092 | 0.151 | 6.4 | 5.4 | 0/600 |
| 10x | memoria | 2 | 0.286 | 0.535 | 0.622 | 35.9 | 40.4 | 0/600 |
| 10x | sql-por-no | 1 | 0.091 | 0.112 | 0.135 | 6.4 | 5.4 | 0/600 |
| 10x | sql-por-no | 2 | 0.557 | 1.046 | 1.204 | 35.9 | 40.4 | 0/600 |
| 10x | sql-por-salto | 1 | 0.175 | 0.214 | 0.257 | 6.4 | 5.4 | 0/600 |
| 10x | sql-por-salto | 2 | 0.612 | 1.010 | 1.200 | 35.9 | 40.4 | 0/600 |
| 10x | sql-recursivo | 1 | 40.267 | 40.499 | 41.564 | 1.1 | 0.0 | 492/600 |
| 10x | sql-recursivo | 2 | 39.073 | 40.410 | 40.463 | 21.7 | 0.0 | 249/600 |
| 1x | memoria | 1 | 0.039 | 0.070 | 0.086 | 6.5 | 5.5 | 0/600 |
| 1x | memoria | 2 | 0.168 | 0.326 | 0.408 | 33.9 | 40.1 | 0/600 |
| 1x | sql-por-no | 1 | 0.085 | 0.108 | 0.120 | 6.5 | 5.5 | 0/600 |
| 1x | sql-por-no | 2 | 0.525 | 0.952 | 1.175 | 33.9 | 40.1 | 0/600 |
| 1x | sql-por-salto | 1 | 0.173 | 0.217 | 0.273 | 6.5 | 5.5 | 0/600 |
| 1x | sql-por-salto | 2 | 0.541 | 0.871 | 1.027 | 33.9 | 40.1 | 0/600 |
| 1x | sql-recursivo | 1 | 2.253 | 2.745 | 3.449 | 6.5 | 0.0 | 0/600 |
| 1x | sql-recursivo | 2 | 2.316 | 2.515 | 2.682 | 33.9 | 0.0 | 0/600 |
| hub-10029 | memoria | 1 | 0.089 | 0.119 | 15.428 | 6.2 | 234.0 | 0/150 |
| hub-10029 | memoria | 2 | 20.012 | 30.676 | 33.738 | 49.7 | 10205.6 | 0/150 |
| hub-10029 | sql-por-no | 1 | 0.160 | 0.244 | 3.843 | 8.3 | 34.3 | 0/150 |
| hub-10029 | sql-por-no | 2 | 7.462 | 12.627 | 16.186 | 67.6 | 304.2 | 0/150 |
| hub-10029 | sql-por-salto | 1 | 0.462 | 0.568 | 32.545 | 5.6 | 31.7 | 0/150 |
| hub-10029 | sql-por-salto | 2 | 35.199 | 40.708 | 41.051 | 15.8 | 151.3 | 26/150 |

## SLO-12 — memória pronta para o S2, sem reranker (meta: p50 ≤ 120 ms, p95 ≤ 250 ms)

Caminho completo da §6.8: densa (simulada) + léxica FTS5 + 2 saltos de grafo, fundidos por RRF.

| escala | execução | n | p50 (ms) | p95 (ms) | truncados |
|---|---:|---:|---:|---:|---:|
| 1x | 1 | 100 | 1.35 | 1.85 | 0 |
| 1x | 2 | 100 | 1.33 | 1.65 | 0 |
| 1x | 3 | 100 | 1.37 | 1.94 | 0 |
| 10x | 1 | 100 | 8.44 | 12.02 | 0 |
| 10x | 2 | 100 | 6.59 | 10.91 | 0 |
| 10x | 3 | 100 | 8.42 | 11.90 | 0 |
| 100x | 1 | 100 | 44.57 | 62.32 | 0 |
| 100x | 2 | 100 | 35.46 | 49.26 | 0 |
| 100x | 3 | 100 | 38.27 | 55.54 | 0 |

## Veredito (aceite (e) do cartão)

- **SLO-11 é alcançável**: com a travessia de produção (`sql-por-no`), o pior p95 medido em todos os casos — escalas 1×/10×/100× e o grafo com hub de grau 10 000 — foi **0.271 ms** com 1 salto (meta 40 ms) e **15.501 ms** com 2 saltos. Fora do caso do hub, 2 saltos ficam em 1.936 ms p95 na escala 100× (12 200 episódios, ~97 600 arestas).
- **SLO-12 é alcançável**: pior p95 do caminho completo = **62.32 ms** (meta 250 ms), ainda sem reranker, na escala 100×, com 0 consulta truncada.
- **Limite de saltos: 2 saltos cabem**, em todas as escalas e também com hub. O custo de 1 → 2 saltos cresce poucas vezes, não exponencialmente, porque o teto de fan-out por nó corta a expansão.
- **O que aperta é o hub, não o tamanho do grafo:** com grau 10 000, 2 saltos vão de 1.936 ms para **15.501 ms** p95. É o número que torna a penalidade de hub da §6.7 requisito, e não enfeite.
- **Teto dentro da varredura vence teto depois dela** (aceite (d)): no hub, a mesma travessia com `ROW_NUMBER() ... WHERE pos <= teto` custou 41.075 ms p95 e a propagação em memória 41.311 ms (lendo ~10 000 arestas), contra 15.501 ms de `sql-por-no`, que para de ler no `LIMIT` de cada nó. Por isso `ativar_por_no` é a implementação de produção.
- **A travessia recursiva em SQL não serve**: `WITH RECURSIVE` sem teto de fan-out ficou 100–200× mais lenta e estourou o orçamento em 1941/3600 consultas nas escalas maiores. Fica no repositório como medição, não como caminho.

## O que estes números **não** dizem

- nada sobre qualidade (recall, nDCG): é a medição da §8.2, com corpus anotado, em F3;
- nada sobre o corpus real do dono depois do exportador de C1 (cartão F0-08) — aqui o grafo é sintético, com grau médio declarado;
- nada sobre Windows: o harness roda nos dois sistemas (só stdlib + SQLite), mas foi **executado apenas em Linux**;
- nada sobre reranker: SLO-8 é outra medição, com modelo de licença comercial (ADR-0011).
