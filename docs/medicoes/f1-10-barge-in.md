# F1-10 — barge-in ponta a ponta: SLO-2 e a decomposição por salto

**Gerado por** `tools/harness_barge_in.py` (não editar à mão). **Data:** 2026-10-15.

> **Piso de software, sem dispositivo.** A fila do **driver** não está na conta, e é nela que o áudio velho sobrevive. O SLO-2 de verdade é o aceite (a) da F1 e sai no F1-16, na máquina do dono.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 200 interrupções por execução, 3 execuções, fonte `arquivo` (itens do corpus sintético)
- conta-se do **início real da fala** (`inicio_fala_ms` do rótulo), não de quando o VAD percebeu: o SLO-2 é do ponto de vista de quem fala
- o número do veredito é o **conservador**: tempo de áudio + custo de CPU dos saltos
- alvo da SPEC §7: p50 ≤ 80 ms, **p95 ≤ 150 ms**

## SLO-2 por VAD

| VAD | n | SLO-2 p50 | SLO-2 p95 | máximo | só áudio p95 | atraso do VAD p50 | custo de código p95 | piso p50 ≤ 80? | piso p95 ≤ 150? (gatilho) |
|---|---:|---:|---:|---:|---:|---:|---:|:--|:--|
| `energia` | 600 | 51.7 ms | 71.7 ms | 79.7 ms | 71.0 ms | 51.0 ms | 831 µs | piso cabe | piso cabe |
| `silero` | 600 | 81.6 ms | 105.7 ms | 123.7 ms | 105.0 ms | 81.0 ms | 957 µs | **piso excede** | piso cabe |

**Quem gasta o SLO-2 é o VAD, não o nosso caminho de cancelamento.** O custo de código dos cinco saltos depois da detecção fica na casa de 1 a 4 ms; o resto é o tempo que o VAD leva para ter certeza de que é fala. É aí que está a troca: o limiar de energia detecta mais rápido (menor p50) e o `silero` não produz falso positivo por quadro (F1-05, precisão 1,000 contra 0,999). Escolher entre os dois é escolher entre calar mais rápido e calar por engano — e isso se decide com voz real (F1-16).

## Decomposição por salto (aceite (c))

Tempo de **áudio** (o que o dono sente), mediana entre interrupções:

| VAD | salto | mediana |
|---|---|---:|
| `energia` | `fala_comecou→vad_detectou` | 51.0 ms |
| `energia` | `vad_detectou→epoch_incrementado` | 0.0 ms |
| `energia` | `epoch_incrementado→cancel_publicado` | 0.0 ms |
| `energia` | `cancel_publicado→fila_vazia` | 0.0 ms |
| `energia` | `fila_vazia→sintese_interrompida` | 0.0 ms |
| `energia` | `sintese_interrompida→s2_cancelado` | 0.0 ms |
| `silero` | `fala_comecou→vad_detectou` | 80.5 ms |
| `silero` | `vad_detectou→epoch_incrementado` | 0.0 ms |
| `silero` | `epoch_incrementado→cancel_publicado` | 0.0 ms |
| `silero` | `cancel_publicado→fila_vazia` | 0.0 ms |
| `silero` | `fila_vazia→sintese_interrompida` | 0.0 ms |
| `silero` | `sintese_interrompida→s2_cancelado` | 0.0 ms |

Custo de **CPU** por salto (o que é nosso para otimizar), mediana:

| VAD | salto | mediana |
|---|---|---:|
| `energia` | `vad_detectou` | 0.0 µs |
| `energia` | `epoch_incrementado` | 28.2 µs |
| `energia` | `cancel_publicado` | 0.0 µs |
| `energia` | `fila_vazia` | 652.1 µs |
| `energia` | `sintese_interrompida` | 0.3 µs |
| `energia` | `s2_cancelado` | 0.1 µs |
| `silero` | `vad_detectou` | 0.0 µs |
| `silero` | `epoch_incrementado` | 28.2 µs |
| `silero` | `cancel_publicado` | 0.0 µs |
| `silero` | `fila_vazia` | 641.3 µs |
| `silero` | `sintese_interrompida` | 0.4 µs |
| `silero` | `s2_cancelado` | 0.1 µs |

## Nenhum salto espera o ASR (aceite (b))

| situação | SLO-2 p50 | SLO-2 p95 |
|---|---:|---:|
| ASR normal (energia) | 35.7 ms | — |
| ASR atrasado em 2 s (energia) | 35.7 ms | — |

O transcritor lento avança o relógio em 2 s **dentro** da percepção. O SLO-2 não muda porque o `Cancel` é o primeiro envelope que a percepção devolve — a ordem da regra 1 da §3.3 é o que garante isso, e não a velocidade de ninguém.

## O que não foi medido

- **SLO-2 com microfone e alto-falante reais** — é o aceite (a) da F1 e sai no F1-16: a fila do driver ignora o nosso Cancel e continua entregando o que já aceitou
- **cancelar tool de efeito já executada** — não existe no v1 por especulação (§3.3 regra 3), então não há o que medir
- **voz de verdade no playback** — o motor de TTS aqui é o paramétrico: o que se mede é o caminho de cancelamento, não a voz (F1-09 mede a voz)
- **Windows** — a medição rodou só em Linux
