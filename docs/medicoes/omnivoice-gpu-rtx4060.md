# OmniVoice real na GPU, RTX 4060 (ADR-0039)

**Data:** 2026-10-21 · **Commit medido:** `9c4d97a` · **Dados:** `omnivoice-gpu-rtx4060.csv`

**Onde:** a máquina do dono, fora de contêiner — NVIDIA GeForce RTX 4060 (8 GB), driver 595.104,
AMD Ryzen 5 5600G, 31 GB de RAM, Linux (Nobara, Fedora 44). O processo de medição rodou com
`nice -n 19`; o jogo não estava aberto.

**Instalação:** `tools/instalar_omnivoice.py --aceito-uso-pessoal` de verdade, detecção automática:
driver ≥ 570 → `torch 2.8.0+cu128`, `torchaudio 2.8.0+cu128`, `omnivoice 0.2.1`,
`transformers 5.20.2`, `numpy 2.5.4`; os 11 arquivos de peso da revisão `c5fdb5ccb189`
(3,27 GB) conferidos pelos sha256 do registro; `--verificar` viu a GPU. O `uv pip install` levou
~45 s (40 pacotes baixados), e a pasta do motor ficou com 11 GB (venv com as bibliotecas CUDA +
pesos).

**Como:** pelo motor do Jarvis (`motor_omnivoice` → `MotorComReserva` → `MotorTtsOmniVoice` →
trabalhador), em fp16 na GPU, saída em PCM16 16 kHz gravada em arquivo — nada foi tocado no
alto-falante. **Referência de voz:** o mesmo sinal sintético de 6 s da medição na CPU
(`jarvis.audio_io.sintese.fala_simulada`), não a voz de ninguém. O lote 0 é "Olá." logo depois de
abrir o motor, e mede a carga dos pesos + a voz de referência + a síntese.

## Resultado

| rodada | lote | palavras | síntese | áudio gerado | fator de tempo real |
|---|---|---|---|---|---|
| 1 | 0 | 1 | 10,04 s (carga 8,64 s) | 1,48 s | — |
| 1 | 1 | 10 | 1,70 s | 6,00 s | 0,28 |
| 1 | 2 | 18 | 2,31 s | 10,12 s | 0,23 |
| 1 | 3 | 11 | 2,00 s | 7,69 s | 0,26 |
| 2 | 0 | 1 | 10,36 s (carga 8,83 s) | 1,48 s | — |
| 2 | 1 | 10 | 1,70 s | 6,36 s | 0,27 |
| 2 | 2 | 18 | 2,30 s | 10,68 s | 0,22 |
| 2 | 3 | 11 | 1,92 s | 5,37 s | 0,36 |

`n` = 6 lotes de 10 a 18 palavras (2 rodadas) e 2 cargas. Memória de vídeo: ~760 MiB antes, ~4,9 GB
com o modelo carregado (≈ 4,1 GB do OmniVoice), de volta a ~870 MiB depois de fechar.

**O que isto quer dizer:** na RTX 4060, um lote de 10 a 18 palavras sai em 1,7 a 2,3 s — de 0,22 a
0,36 do tempo da própria fala, ou seja, de 3 a 4,5 vezes mais rápido que o tempo real (na CPU era
de 15 a 19 vezes **mais lento**). A carga leva ~9 s, que o aplicativo esconde ao aquecer o motor
na abertura. Como o lote só toca inteiro, a primeira fala de uma resposta espera a síntese do
primeiro lote (~1,7 s para 10 palavras), e os seguintes ficam prontos antes de o anterior
terminar de tocar. **Na GPU, dá para conversar.**

## O que NÃO foi medido

- qualidade da voz clonada e do português — a referência era sintética; quem julga é o dono, com
  a voz dele cadastrada;
- o primeiro áudio de ponta a ponta no aplicativo, com o alto-falante;
- a GPU disputada: com um jogo aberto, os ~4,1 GB do modelo podem não caber nos 8 GB — aí a carga
  ou a síntese falham e o Jarvis cai no motor padrão (o caminho de reserva tem teste, mas não foi
  provocado nesta máquina);
- mais rodadas, frases longas, outras GPUs.
