# F1-05 — VAD: acerto de início de fala e piso de SLO-1

**Gerado por** `tools/harness_vad.py` (não editar à mão). **Data:** 2026-10-15.

> **Corpus sintético e piso de software.** Nenhum microfone foi aberto. VAD em ruído real da casa do dono e SLO-1 com captura de verdade são o F1-16.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 100 itens do corpus sintético, 3 execuções do piso
- verdade de referência: `inicio_fala_ms` e `inicio_pausa_ms` do rótulo, que o gerador gravou (não é estimativa nossa sobre o áudio)
- acerto de início: detectar entre -100 ms e +500 ms do início verdadeiro; antes disso é falso positivo
- a matriz por quadro cobre só a região **até o início da pausa**: depois dela o VAD segura fala por projeto (histerese e hangover), e isso aparece como caracterização
- `hangover` é a **transição** para silêncio depois do início da pausa; quando o arquivo acaba antes de o VAD desligar, o item entra na coluna "não desligou" em vez de virar 0 ms
- o piso roda a cadeia real (AEC → NR → AGC → VAD → envelope validado), com relógio falso na fonte e `perf_counter_ns` no cronômetro

## Acerto de início de fala (aceite (a))

| VAD | itens | no prazo | cedo | não detectou | recall | precisão | atraso p50 | atraso p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `energia@1` | 100 | 100 | 0 | 0 | 1.000 | 1.000 | 31 ms | 51 ms |
| `silero-vad@v5` | 100 | 100 | 0 | 0 | 1.000 | 1.000 | 61 ms | 80 ms |

Matriz de confusão por quadro (até o início da pausa) e hangover:

| VAD | VP | FP | FN | VN | recall | precisão | hangover p50 | não desligou no arquivo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `energia@1` | 7251 | 4 | 112 | 1048 | 0.985 | 0.999 | 260 ms | 1/100 |
| `silero-vad@v5` | 7112 | 0 | 251 | 1052 | 0.966 | 1.000 | 575 ms | 51/100 |

## Piso de SLO-1 (aceites (c) e (d))

| caminho | n | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) |
|---|---:|---:|---:|---:|---:|
| `cadeia AEC+energia@1 (com evento)` | 172 | 0.5327 | 0.6208 | 0.6944 | 1.0479 |
| `cadeia AEC+energia@1 (sem evento)` | 11389 | 0.1796 | 0.2181 | 0.2442 | 0.3457 |
| `cadeia AEC+silero-vad@v5 (com evento)` | 154 | 0.7737 | 0.8169 | 0.8523 | 2.2446 |
| `cadeia AEC+silero-vad@v5 (sem evento)` | 11407 | 0.3061 | 0.3821 | 0.7848 | 32.9949 |

**Veredito do gatilho da ADR-0014:** pior p95 medido = 0.8169 ms contra o orçamento de 80 ms do SLO-1 — dentro do orçamento, D1 não reabre.

## O que não foi medido

- **SLO-1 com microfone** — é o aceite (a) da F1 e sai no F1-16, na máquina do dono: jitter, período do driver e ruído de entrada são do hardware
- **VAD em ruído real da casa do dono** — o corpus tem ruído rosa sintético em ~30% dos itens; sala, televisão e conversa ao fundo são outra coisa
- **fim de turno** — o VAD não decide turno (§2): isso é o cartão F1-07, e o hangover desta tabela é política de fala, não de turno
- **Windows** — o código roda nos dois sistemas, mas a medição foi feita só em Linux
