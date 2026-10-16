# F1-09 — TTS em streaming: primeiro pedaço, piso do SLO-5 e licença da voz

**Gerado por** `tools/harness_tts.py` (não editar à mão). **Data:** 2026-10-15.

> **Piso de software, sem dispositivo.** A fila do driver não está na conta, e é justamente ela que atrasa o primeiro áudio de verdade. SLO-5 real e qualidade da voz são julgamento do dono (F1-16).

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 40 textos do corpus de turnos, um turno por item
- primeiro pedaço = 3 palavras (ou até a primeira pontuação); demais, 8
- alvo da SPEC §7 para o SLO-5: p50 ≤ 600 ms, p95 ≤ 900 ms
- o fonemizador do piper é o `espeak-ng` (GPL-3.0), **injetado** pela ferramenta de medição: no produto ele não pode entrar (ver notas do executor)

## Resultado por candidato

| motor | voz | licença | n | 1º pedaço p50 | 1º pedaço p95 | piso SLO-5 p50 | piso SLO-5 p95 | piso cabe no SLO-5? | RTF p50 |
|---|---|---|---:|---:|---:|---:|---:|:--|---:|
| `parametrico@1` | `parametrico` | Apache-2.0 | 40 | 17.3 ms | 24.9 ms | 17.3 ms | 24.9 ms | piso cabe | 0.026× |
| `piper-onnx@1.0.0+pt_BR-faber-medium` | `pt_BR-faber-medium` | MIT | 40 | 116.3 ms | 145.2 ms | 116.3 ms | 145.3 ms | piso cabe | 0.113× |

## O que não foi medido

- **SLO-5 de verdade** — a fila do dispositivo entra na conta e não está aqui: o primeiro áudio audível depende do driver (F1-16, máquina do dono)
- **qualidade e naturalidade da voz pt-BR** — é julgamento do dono, não teste: ele escolhe a voz no F1-16
- **fonemização permissiva para pt-BR** — as quatro vozes pt-BR do piper usam espeak-ng (GPL-3.0), verificado voz por voz. No produto isso não entra; a decisão (G2P próprio, modelo que aceite grafema, ou outra família de voz) é do dono
- **Kokoro-82M** — registrado (Apache-2.0) e **não** executado: também depende de fonemizador externo para pt-BR, então não resolve a pendência de licença
- **Windows** — a medição rodou só em Linux
