# F3-01 — índice da memória: ChromaDB × LanceDB (SPEC §8.1)

**Gerado por** `tools/harness_indice.py` (não editar à mão). **Data:** 2026-10-16. **Commit:** `fd6e40e`.

> **Corpus sintético.** O C2 da SPEC é anotado pelo dono sobre a vida dele; este é o substituto gerado com semente (`tools/corpus_c2.py`), com gabarito por construção. Ele compara os dois índices **no mesmo** corpus — não diz quanto o Jarvis acerta na vida do dono. A decisão abaixo é provisória até o C2 real.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM; Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- corpus `688097187be8340a`: 3184 unidades no índice (842 memórias, o resto turnos), 175 consultas (C2a–C2d); limiar de abstinência calibrado em 123 consultas e métricas de qualidade nas 52 retidas
- embedding: `intfloat/multilingual-e5-small` (ONNX, CPU, 2 fios), calculado **uma vez** e entregue aos dois — 13.9 s para as passagens; por consulta p50 6.9 ms, p95 8.6 ms (fora dos números de busca abaixo)
- 3 execuções por candidato, cada uma num processo novo; busca = 3 passadas pelas consultas com `k=20` e filtro `tipo=memoria, status=active`; percentil por execução, publicada a mediana das 3
- versões: chromadb 1.5.9, lancedb 0.40.0

## Resultado (mediana das 3 execuções)

| candidato | recall@20 | nDCG@10 C2a | abstinência correta (C2d) | abstinência indevida | busca p50 | busca p95 | busca fria | indexar por 1k unidades | CPU por 1k | RSS de pico | disco |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `chroma` | 0.714 | 0.650 | 0.70 | 0.50 | 4.18 ms | 5.34 ms | 4.28 ms | 354 ms | 478 ms | 167 MiB | 9.3 MiB |
| `lance` | 0.714 | 0.650 | 0.70 | 0.50 | 5.61 ms | 6.75 ms | 7.51 ms | 349 ms | 357 ms | 381 MiB | 5.0 MiB |

Sobreposição média do top-20 entre os dois (1ª execução): 0.991. Por subconjunto (retidas, mediana): `chroma` C2a recall@20 0.778, C2b recall@20 0.733, C2c recall@20 0.556; `lance` C2a recall@20 0.778, C2b recall@20 0.733, C2c recall@20 0.556.

## Critérios de veto

| candidato | filtro antes do ranking | `delete` tira da busca | vetor no disco depois do `delete` | vetor no disco depois da manutenção | manutenção tentada | onde ficou | listas iguais nas 3 execuções |
|---|:-:|:-:|:-:|:-:|---|---|:-:|
| `chroma` | sim | sim | sim | **sim** | chroma vacuum (CLI documentado) e reabrir o cliente | `0a809b70-2584-46ce-8229-676cea9d6e1f/data_level0.bin; chroma.sqlite3` | não |
| `lance` | sim | sim | sim | **não** | IndiceLance.expurgar (reescrever + optimize), API pública | `-` | sim |

Como a exclusão é verificada: o harness apaga as unidades de uma memória (a memória e o turno de mesmo texto) e procura os **bytes do vetor** — os 16 primeiros floats, crus ou renormalizados, com tolerância 1e-6, em qualquer alinhamento — em todos os arquivos da pasta do índice. No LanceDB, um segundo vetor é apagado depois de a tabela já estar compactada num fragmento só: é o caso em que o `optimize` sozinho não reescreve o fragmento (menos de 10% de linhas apagadas). `expurgar` custou 20.1 ms com 3184 unidades.

Windows: o `uv.lock` tem rodas `win_amd64` das duas bibliotecas; **não executado** — não há máquina Windows aqui. Os dois são embutidos (sem serviço), em Linux verificado.

## Decisão pela regra da §8.1 (fechada antes de medir)

- **regra 1 (veto): chroma guarda o vetor apagado no disco** → vencedor: **lance**
- recall@20 LanceDB − Chroma: +0.0 pontos; p95 Chroma ÷ LanceDB: 0.79

## O que não foi medido

- **C1 e C2 reais** (memórias exportadas do Orchestrator e consultas anotadas pelo dono): o corpus aqui é sintético
- **C3, latência sob indexação concorrente**
- **híbrido nativo**: os dois candidatos ficam só com a lista densa, porque a léxica (FTS5) e a fusão (RRF) já estão no livro-razão SQLite (`jarvis.memoryd.recuperacao`), para qualquer índice — o FTS do LanceDB não foi usado nem medido
- **reranker** e outros embeddings (e5-base, bge-m3, Qwen3-Embedding): a §8.1 lista; aqui só o e5-small, o que o Orchestrator do dono já usa
- **Windows**, ver acima
