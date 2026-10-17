# F3-02 — recuperação: vetor × híbrido × grafo+vetor (SPEC §8.2)

**Gerado por** `tools/harness_recuperacao.py` (não editar à mão). **Data:** 2026-10-16. **Commit:** `9d615ef`.

> **Corpus sintético** (`tools/corpus_c2.py`, hash `688097187be8340a`), com gabarito por construção. Ele compara os braços no mesmo corpus; não mede o Jarvis na vida do dono. A decisão abaixo é provisória até o C2 real.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM; Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- livro em arquivo, com cofre, montado pela API do produto em 27.4 s (inclui o embedding de todas as unidades): episode 2342, assertion 842, memory_unit 3184, entity 375, entity_edge 690, entity_mention 1974
- índice LanceDB (ADR-0005 item 5), embedding `intfloat/multilingual-e5-small` local; `k` = 40 por lista, top-20 para recall, top-8 para o que iria ao prompt; filtro `status=active` e validade no instante da pergunta
- 175 consultas: parâmetros escolhidos em 123 (calibração) e números das 52 retidas (regra 7)
- braço C: sementes por apelido exato na pergunta (1a) e pelas entidades dos 8 melhores acertos densos (1b); orçamento do grafo 40 ms; testados 1 e 2 saltos, energia por máximo e por soma
- latência: consulta inteira **com** o embedding da pergunta, 3 execuções sobre todas as consultas; percentil por execução, publicada a mediana

## Qualidade nas consultas retidas

| configuração | recall@20 C2a | recall@20 C2b | recall@20 C2c | recall@20 C2b+C2c | nDCG@10 C2b+C2c | abstinência correta | abstinência indevida | sustentada | vencido nas evidências | sem caminho | limiar |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `A` | 0.778 | 0.733 | 0.556 | 0.667 | 0.410 | 0.70 | 0.50 | 0.33 | 0 | 0 | 0.8545 |
| `B` | 0.889 | 0.800 | 0.556 | 0.708 | 0.498 | 0.70 | 0.50 | 0.38 | 0 | 0 | 0.8545 |
| `C-1s-max` | 0.889 | 0.933 | 0.556 | 0.792 | 0.433 | 0.60 | 0.02 | 0.57 | 0 | 0 | 0.8546 |
| `C-1s-soma` | 0.889 | 0.933 | 0.556 | 0.792 | 0.425 | 0.60 | 0.02 | 0.57 | 0 | 0 | 0.8546 |
| `C-2s-max` | 0.889 | 0.933 | 0.556 | 0.792 | 0.440 | 0.60 | 0.02 | 0.60 | 0 | 0 | 0.8546 |
| `C-2s-soma` | 0.889 | 0.933 | 0.556 | 0.792 | 0.431 | 0.60 | 0.02 | 0.60 | 0 | 0 | 0.8546 |

"Sustentada" aqui é um substituto mecânico do anotado da SPEC: a consulta não absteve e **todo** o gabarito está nas 8 evidências que iriam ao prompt. "Vencido nas evidências" conta consultas em que uma memória substituída apareceu (gate 4); "sem caminho", evidências sem o porquê (gate 6).

## Latência (mediana das 3 execuções)

| configuração | consulta p50 | consulta p95 | consulta máx | cabe no SLO-12? |
|---|---:|---:|---:|:--|
| `A` | 16.2 ms | 21.1 ms | 26.0 ms | sim |
| `B` | 17.6 ms | 23.4 ms | 30.6 ms | sim |
| `C-1s-max` | 22.7 ms | 29.5 ms | 34.5 ms | sim |
| `C-1s-soma` | 22.9 ms | 30.3 ms | 38.1 ms | sim |
| `C-2s-max` | 24.9 ms | 33.8 ms | 114.6 ms | sim |
| `C-2s-soma` | 24.5 ms | 31.7 ms | 36.7 ms | sim |

## Decisão pela regra da §8.2 (fechada antes de medir)

- C comparado: `C-2s-soma` (o melhor na **calibração** em recall@20 de C2b+C2c)
- recall@20 C2b+C2c: B 0.708 → C 0.792 (+8.3 pontos); nDCG@10: 0.498 → 0.431; abstinência correta: 0.70 → 0.60 (sobre 10 negativas retidas: cada uma vale 10 pontos); abstinência indevida: 0.50 → 0.02
- **inconclusivo: C ganha 8.3 pontos, mas a abstinência correta cai 10 pontos (> 2), então a regra 2 não se cumpre, e a regra 3 só cobre ganho de 2 a 5 — fica o mais simples, B, e o grafo fora do caminho da voz** → no caminho da voz: **`B`**, gravado em `src/jarvis/memoryd/parametros.toml`
- regra 5 (precisão de aresta ≥ 80% em 100 arestas revisadas): **não medida** — aqui as arestas vêm do gabarito do gerador, não de um extrator; no produto, aresta só nasce ativa pela mão do dono (ADR-0026). Sem esse número, C não vira padrão mesmo que a regra 2 dissesse que sim

## O que não foi medido

- **C2 real** anotado pelo dono; **datas relativas** ("terça passada") resolvidas para o instante — o corpus não cobre
- **reranker e MMR** (braço B completo da §8.2): sem reranker comercial baixado
- **precisão de aresta** (regra 5), ver acima
- custo de extração do grafo: as arestas do corpus vêm prontas
