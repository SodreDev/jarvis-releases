# Palavra de ativação — falso positivo e falso negativo por limiar

**Gerado por** `tools/harness_palavra.py` (não editar à mão). **Data:** 2026-10-16. **Dados:** `palavra-de-ativacao.csv`.

> **Só texto.** O detector recebe a transcrição; aqui ele recebe frases escritas. Nenhum áudio foi tocado, nenhum microfone aberto, nenhum ASR rodado. Quanto o ASR local erra o nome na voz do dono **não foi medido**.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43
- palavra: `jarvis`; janelas de uma e duas palavras (`jarvis.voz.palavra`)
- negativos do corpus: 340 frases distintas de `corpus/turnos/rotulos.jsonl` (`texto` ∪ `texto_antes`); nenhuma tem a palavra
- vizinhos: 18 nomes/palavras × 4 moldes = 72 frases (lista no código, escolhida à mão)
- positivos: 12 grafias × (sozinha + antes e depois de 20 pedidos do corpus) = 492 frases (**construídos à mão**: o corpus não tem a palavra)
- `comando errado`: chamou, mas o pedido extraído não é o do molde
- tempo: um `achar` por frase negativa, `perf_counter_ns`

## Limiar sugerido

| fonemizador | limiar sugerido | FP corpus | FP vizinhos | FN | tempo p50 | tempo p95 |
|---|---:|---:|---:|---:|---:|---:|
| `simples` | 0.75 | 0/340 | 0/72 | 0/492 (0.0%) | 215 µs | 275 µs |
| `epitran` | 0.75 | 0/340 | 0/72 | 0/492 (0.0%) | 611 µs | 788 µs |

Regra: o meio do platô de limiares com **zero** disparo nos dois conjuntos negativos e o menor falso negativo. A curva anda em degraus porque `jarvis` vira seis símbolos e cada edição custa 1/6: entre 0,67 e 0,83 todo limiar é o mesmo corte — **no máximo uma edição** —, e o meio do platô é o que fica mais longe das duas bordas.

## Varredura (de 0,05 em 0,05; a de 0,01 está no CSV)

| fonemizador | limiar | FP corpus | FP vizinhos | FN | comando errado |
|---|---:|---:|---:|---:|---:|
| `simples` | 0.60 | 0 | 32 | 0 (0.0%) | 0 |
| `simples` | 0.65 | 0 | 32 | 0 (0.0%) | 0 |
| `simples` | 0.70 | 0 | 0 | 0 (0.0%) | 0 |
| `simples` | 0.75 | 0 | 0 | 0 (0.0%) | 0 |
| `simples` | 0.80 | 0 | 0 | 0 (0.0%) | 0 |
| `simples` | 0.85 | 0 | 0 | 246 (50.0%) | 0 |
| `simples` | 0.90 | 0 | 0 | 246 (50.0%) | 0 |
| `simples` | 0.95 | 0 | 0 | 246 (50.0%) | 0 |
| `epitran` | 0.60 | 0 | 16 | 0 (0.0%) | 0 |
| `epitran` | 0.65 | 0 | 16 | 0 (0.0%) | 0 |
| `epitran` | 0.70 | 0 | 0 | 0 (0.0%) | 0 |
| `epitran` | 0.75 | 0 | 0 | 0 (0.0%) | 0 |
| `epitran` | 0.80 | 0 | 0 | 0 (0.0%) | 0 |
| `epitran` | 0.85 | 0 | 0 | 369 (75.0%) | 0 |
| `epitran` | 0.90 | 0 | 0 | 410 (83.3%) | 0 |
| `epitran` | 0.95 | 0 | 0 | 410 (83.3%) | 0 |

## Parecença de cada grafia e de cada vizinho, sozinhos

| palavra | conjunto | `simples` | `epitran` |
|---|---|---:|---:|
| jarvis | positivo | 1.000 | 1.000 |
| járvis | positivo | 1.000 | 0.833 |
| djarvis | positivo | 1.000 | 0.857 |
| jarves | positivo | 1.000 | 0.833 |
| jervis | positivo | 0.833 | 0.833 |
| jarviz | positivo | 0.833 | 0.833 |
| jarvas | positivo | 0.833 | 0.833 |
| javis | positivo | 0.833 | 0.833 |
| jarvi | positivo | 0.833 | 0.833 |
| jarbis | positivo | 0.833 | 0.833 |
| jar vis | positivo | 1.000 | 1.000 |
| jár vis | positivo | 1.000 | 0.833 |
| jarbas | vizinho | 0.667 | 0.667 |
| marvin | vizinho | 0.667 | 0.667 |
| charles | vizinho | 0.667 | 0.500 |
| carlos | vizinho | 0.500 | 0.500 |
| travis | vizinho | 0.500 | 0.500 |
| davis | vizinho | 0.667 | 0.667 |
| jardim | vizinho | 0.667 | 0.667 |
| jarra | vizinho | 0.333 | 0.333 |
| chaves | vizinho | 0.667 | 0.500 |
| harvey | vizinho | 0.500 | 0.500 |
| garcia | vizinho | 0.500 | 0.500 |
| service | vizinho | 0.571 | 0.429 |
| jovens | vizinho | 0.333 | 0.333 |
| já vi | vizinho | 0.667 | 0.500 |
| já vou | vizinho | 0.500 | 0.167 |
| já disse | vizinho | 0.500 | 0.286 |
| james | vizinho | 0.667 | 0.500 |
| jair | vizinho | 0.500 | 0.167 |

## Os negativos do corpus mais perto do alvo

- `simples`: 0.500 em “tarde” (marca a reunião de quinta no fim da tarde); 0.500 em “tarde” (marca a renovação do contrato no fim da tarde); 0.500 em “tarde” (marca a entrega do relatório no fim da tarde); 0.500 em “tarde” (marca a consulta do dentista no fim da tarde); 0.500 em “tarde” (lembra o jogo do fim de semana no fim da tarde)
- `epitran`: nenhum chega a 0,50

## O que esta medição não cobre

- **áudio real**: nenhuma voz do dono, nenhum ruído da casa, nenhum ASR de verdade transcrevendo o nome — a taxa de acerto em uso é desconhecida;
- **as grafias positivas e os vizinhos são listas escritas à mão**: o número vale para estas listas, não para o português inteiro;
- **o corpus é pequeno e de um domínio só** (pedidos de casa e escritório): conversa livre, TV e música ao fundo não estão aqui;
- **outra palavra escolhida pelo dono** muda o alvo e, com ele, o degrau da curva: o limiar sugerido é para `jarvis`.
