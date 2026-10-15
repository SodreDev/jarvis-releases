# F1-04 — AEC/NR/AGC: ERLE por condição e o A/B do detector

**Gerado por** `tools/harness_aec.py` (não editar à mão). **Data:** 2026-10-15.

> **Eco sintético, linear: limite inferior de dificuldade.** Sem sala, sem distorção de alto-falante, sem duplo-falar real. Nenhum dispositivo foi aberto.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 8 s de áudio por condição (400 quadros de 20 ms), 3 execuções, nove condições
- a referência é **o nosso próprio playback** (fala sintética do F1-01); o microfone é essa referência atrasada e atenuada
- as colunas de detector contam quadros com fala **depois** dos primeiros 3 s (o filtro adaptativo precisa aprender), com o `DetectorDeEnergia` em -45 dBFS — que **não** é o VAD (F1-05)
- cadeia completa: AEC → NR → AGC, a mesma que o `audio-io` usa

## ERLE e o A/B do detector (mediana das execuções)

| atraso | eco | ERLE total | ERLE convergido | converge em | quadros com fala SEM AEC | COM AEC |
|---:|---:|---:|---:|---:|---:|---:|
| 60 ms | -20 dB | 25.8 dB | 38.8 dB | 200 ms | 178/250 | 0/250 |
| 60 ms | -12 dB | 23.8 dB | 34.9 dB | 200 ms | 250/250 | 0/250 |
| 60 ms | -6 dB | 23.5 dB | 33.9 dB | 200 ms | 250/250 | 0/250 |
| 120 ms | -20 dB | 26.0 dB | 38.9 dB | 240 ms | 178/250 | 0/250 |
| 120 ms | -12 dB | 23.0 dB | 34.9 dB | 240 ms | 250/250 | 0/250 |
| 120 ms | -6 dB | 23.7 dB | 34.1 dB | 240 ms | 250/250 | 0/250 |
| 240 ms | -20 dB | 27.5 dB | 38.9 dB | 340 ms | 178/250 | 0/250 |
| 240 ms | -12 dB | 24.7 dB | 35.5 dB | 340 ms | 250/250 | 0/250 |
| 240 ms | -6 dB | 23.9 dB | 33.6 dB | 340 ms | 250/250 | 0/250 |

Energia média do que o detector vê (mediana das execuções):

| atraso | eco | sem AEC | com AEC |
|---:|---:|---:|---:|
| 60 ms | -20 dB | -41.4 dBFS | -79.9 dBFS |
| 60 ms | -12 dB | -33.4 dBFS | -68.2 dBFS |
| 60 ms | -6 dB | -27.4 dBFS | -61.9 dBFS |
| 120 ms | -20 dB | -41.5 dBFS | -80.0 dBFS |
| 120 ms | -12 dB | -33.5 dBFS | -68.2 dBFS |
| 120 ms | -6 dB | -27.5 dBFS | -61.2 dBFS |
| 240 ms | -20 dB | -41.5 dBFS | -79.9 dBFS |
| 240 ms | -12 dB | -33.5 dBFS | -68.7 dBFS |
| 240 ms | -6 dB | -27.5 dBFS | -60.6 dBFS |

## Duplo-falar sintético (dono falando em cima do eco)

| quadros | ERLE sobre o microfone | preservação da voz do dono |
|---:|---:|---:|
| 400 | -0.3 dB | 1.1 dB |

## Deriva de relógio (aceite (d))

| deriva | ERLE | saída finita (sem NaN/inf) |
|---:|---:|:--|
| -100 ppm | 21.8 dB | sim |
| +100 ppm | 22.7 dB | sim |

## O que não foi medido

- **eco real de alto-falante aberto, no volume de uso** — sala, volume e caminho acústico são do dono; eco sintético é linear e por isso mais fácil (F1-16, na máquina dele)
- **duplo-falar real** — os dois falando junto, com voz humana: o duplo-falar aqui é fala sintética somada, e o congelamento do passo é proteção simples, não o detector do WebRTC
- **diferença entre headset e alto-falante, e cauda longa da sala** — exigem o ambiente do dono
- **distorção não linear do alto-falante** — a cadeia é linear: alto-falante barato em volume alto distorce, e isso nenhum filtro linear cancela
- **Windows** — numpy tem roda para os dois sistemas, mas o harness rodou só em Linux
