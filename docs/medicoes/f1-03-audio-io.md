# F1-03 — piso de software do `audio-io`: números medidos

**Gerado por** `tools/harness_audio_io.py` (não editar à mão). **Data:** 2026-10-15.

> **piso de software, sem dispositivo.** Nenhum dispositivo de áudio foi aberto: a fonte é um WAV e o sumidouro é memória.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 10000 quadros de 20 ms por execução (200 s de áudio), 3 execuções
- fonte `arquivo` (WAV PCM16 mono 16 kHz) com 20 ms de fala e 20 ms de silêncio alternados, o que força **um evento por quadro**: é pior caso declarado, não uso típico
- o relógio da fonte é o **falso** (tempo virtual: a espera de 20 ms não entra na conta) e o cronômetro é `time.perf_counter_ns` (tempo real do nosso código)
- `captura→AudioActivity` mede energia + detector de limiar + envelope da §3.1 + validação na borda do contrato. O detector **não** é o VAD (o `silero-vad` é o cartão F1-05): o número do VAD está em `f0-04-captura.md`

## Resultado por caminho (mediana das execuções)

| caminho | n | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) |
|---|---:|---:|---:|---:|---:|
| `captura→AudioActivity` | 10000 | 0.2610 | 0.2826 | 0.4049 | 0.6433 |
| `quadro→decisão (sem evento)` | 10000 | 0.0155 | 0.0158 | 0.0191 | 0.4900 |
| `Cancel→fila vazia` | 1000 | 0.5413 | 0.5660 | 0.5996 | 1.1367 |
| `erro de played_ms (ms)` | 1000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

## O que não foi medido

- **jitter de captura, xruns, período e latência do driver** — exigem dispositivo real; nada disso foi aberto por este harness (F1-16, na máquina do dono)
- **latência do caminho de saída e cancelamento perceptível ao ouvido** — a fila do driver não é a nossa fila: esvaziar a nossa em 0,0x ms não garante que o alto-falante parou (F1-10 piso, F1-16 aceite)
- **SLO-1 de verdade** — este é o piso do nosso código sobre arquivo; o SLO-1 é do microfone ao evento, com AEC (F1-04) e VAD (F1-05) no caminho
- **Windows** — o harness é portável (só biblioteca padrão), mas rodou só em Linux
