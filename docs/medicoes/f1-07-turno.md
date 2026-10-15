# F1-07 — curva falso corte × atraso: semântico vs silêncio fixo

**Gerado por** `tools/curva_turno.py` (não editar à mão). **Data:** 2026-10-15.

> **ESTE CARTÃO NÃO FECHA O ACEITE (d) DA F1.** A curva é sobre corpus **sintético**: serve para ordenar candidatos e pegar regressão. O número publicado de SLO-4 e SLO-9 sai do corpus **real** (F1-15), medido na máquina do dono (F1-16). Apresentar esta curva como aceite da fase é motivo de recusa na revisão.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- texto do detector semântico: transcrição real de `openai/whisper-small` do áudio até o início da pausa (cache em `f1-07-texto-no-corte.csv`), **não** o texto do rótulo — dar ASR perfeito ao semântico inflaria o resultado dele
- A/B **pareado**: os dois detectores veem os mesmos itens, e a decisão é simulada de 20 em 20 ms dentro da pausa gravada
- limiar escolhido no split `calibracao` pelo critério declarado: candidato é quem decide em ≥ 50% dos itens de fim de turno (senão "nunca ceder" ganharia por vácuo); entre eles, menor atraso p50 com falso corte ≤ 3%; se nenhum alcança, menor falso corte. Número publicado no split `retido`
- IC de 95% por *bootstrap* de 1000 reamostragens **de itens**

## Curva no split `calibracao`

| detector | limiar | falso corte | atraso p50 | atraso p95 | decidiu | não decidiu |
|---|---:|---:|---:|---:|---:|---:|
| `silencio_fixo` | 100ms | 100.0% | 100 ms | 100 ms | 175/175 | 0 |
| `silencio_fixo` | 200ms | 100.0% | 200 ms | 200 ms | 175/175 | 0 |
| `silencio_fixo` | 300ms | 91.4% | 300 ms | 300 ms | 175/175 | 0 |
| `silencio_fixo` | 400ms | 78.3% | 400 ms | 400 ms | 149/175 | 26 |
| `silencio_fixo` | 500ms | 71.4% | 500 ms | 500 ms | 114/175 | 61 |
| `silencio_fixo` | 600ms | 62.9% | 600 ms | 600 ms | 86/175 | 89 |
| `silencio_fixo` | 700ms | 52.6% | 700 ms | 700 ms | 60/175 | 115 |
| `silencio_fixo` | 800ms | 40.6% | 800 ms | 800 ms | 25/175 | 150 |
| `silencio_fixo` | 900ms | 32.6% | 900 ms | 900 ms | 1/175 | 174 |
| `silencio_fixo` | 1000ms | 21.1% | — | — | 0/175 | 175 |
| `silencio_fixo` | 1200ms | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.2 | 100.0% | 0 ms | 0 ms | 175/175 | 0 |
| `semantico` | 0.3 | 60.0% | 0 ms | 0 ms | 111/175 | 64 |
| `semantico` | 0.4 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.5 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.6 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.7 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.8 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.9 | 0.0% | — | — | 0/175 | 175 |
| `semantico` | 0.95 | 0.0% | — | — | 0/175 | 175 |

## Ponto de operação escolhido e número no `retido`

| detector | limiar | falso corte (IC 95%) | atraso p50 (IC 95%) | atraso p95 | não decidiu |
|---|---:|---|---|---:|---:|
| `silencio_fixo` | 500ms | 0.680 [0.573; 0.787] | 500.000 [500.000; 500.000] | 500 ms | 29 |
| `semantico` | 0.3 | 0.587 [0.480; 0.693] | 0.000 [0.000; 0.000] | 0 ms | 30 |

## Regra de empate (escrita antes de medir) e veredito

> O detector semântico só entra no v1 se, **no mesmo atraso**, reduzir o falso corte, **ou**, no **mesmo falso corte**, reduzir o atraso. Empate dentro do intervalo de confiança → fica o `silencio_fixo`, que é mais simples e mais explicável.

**Veredito:** fica o `silencio_fixo` — INCONCLUSIVO: nenhum ponto de operação é utilizável neste corpus (silencio_fixo, semantico com falso corte acima do alvo de 3%), então não há candidatos a ordenar. Fica o `silencio_fixo` por ser o padrão conservador, e quem decide é o corpus real (F1-15/F1-16).

## SLO-4 e SLO-9

- **SLO-4** (pausa → decisão), alvo da SPEC §7: p50 ≤ 120 ms, p95 ≤ 250 ms.
  - `silencio_fixo`: p50 500 ms, p95 500 ms → **não atinge** — **sem valor: o ponto não é utilizável** (falso corte 68.0%)
  - `semantico`: p50 0 ms, p95 0 ms → atinge — **sem valor: o ponto não é utilizável** (falso corte 58.7%)
- **SLO-9** (3% de falso corte, marcado **[SUPOSIÇÃO]** na SPEC §7) com `silencio_fixo`: 0.680 [0.573; 0.787] → o alvo **não se sustenta nem no sintético**.
- **SLO-9** (3% de falso corte, marcado **[SUPOSIÇÃO]** na SPEC §7) com `semantico`: 0.587 [0.480; 0.693] → o alvo **não se sustenta nem no sintético**.

- custo de computação da decisão: 3.2 µs p50 e 3.3 µs p95 por chamada (é o nosso código; o atraso acima é tempo de **áudio**, que é o que o SLO-4 mede)

## Âncoras externas (são âncoras, não metas nossas)

- **Semantic VAD (2023)**: −53,3% de latência média em conjunto **interno** deles.
- **Voice-Light**: recall de EOT aprendido de 12,53% contra 95,60% do Silero.

Outro conjunto, outro idioma, outra definição de corte. Servem para situar a ordem de grandeza — comparar com os nossos números seria comparar coisas diferentes.

## O que não foi medido

- **o aceite (d) da F1** — não fecha aqui: a curva é sintética e serve para ordenar candidatos; o número publicado sai do corpus real (F1-15) na máquina do dono (F1-16)
- **pausa humana** — a pausa aqui é a que **nós** sorteamos (300-900 ms no fim de turno, 200-1200 ms na hesitação); hesitação, respiração e retomada reais não estão no gerador
- **prosódia** — o detector semântico usa texto e pausa. Prosódia de TTS é mais limpa que a humana e favoreceria o semântico justo no eixo comparado — por isso não foi usada
- **adaptação por falante** — fora do escopo do cartão
- **Windows** — a medição rodou só em Linux
