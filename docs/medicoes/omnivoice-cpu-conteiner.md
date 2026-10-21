# OmniVoice real na CPU, num contêiner (ADR-0039)

**Data:** 2026-10-21 · **Commit medido:** `b0606ba` · **Dados:** `omnivoice-cpu-conteiner.csv`

**Onde:** contêiner podman `python:3.12-slim-bookworm` com `--cpus 8 --memory 12g`, **sem GPU**,
numa máquina com AMD Ryzen 5 5600G (6 núcleos, 12 threads) e 31 GB de RAM. Nada foi instalado nem
baixado fora do contêiner. O trabalhador usou de 2,8 a 3,7 núcleos (observado pelo `podman stats`).

**Versões:** `torch 2.8.0+cpu`, `torchaudio 2.8.0+cpu`, `omnivoice 0.2.1`, `transformers 5.20.2`,
`numpy 2.5.4`, Python 3.12.15 — instaladas pelo `tools/instalar_omnivoice.py` de verdade
(`--aceito-uso-pessoal --dispositivo cpu`), com os 11 arquivos de peso da revisão `c5fdb5ccb189`
baixados e conferidos pelos sha256 do registro.

**Referência de voz:** um sinal sintético de 6 s (`jarvis.audio_io.sintese.fala_simulada`), não a
voz de ninguém. Por isso esta medição diz **tempo**, e não diz nada de qualidade da clonagem nem do
português.

## Resultado

| rodada | lote | palavras | prazo do motor | síntese | áudio gerado | fator de tempo real |
|---|---|---|---|---|---|---|
| 1 | 1 | 17 | 120 s | passou do prazo | — | — |
| 2 | 1 | 17 | 1500 s | 114,3 s | 7,76 s | 14,7× |
| 2 | 2 | 16 | 1500 s | 180,1 s | 9,40 s | 19,2× |

`n` = 2 lotes medidos (rodada 2) e 1 que estourou o prazo (rodada 1). A rodada 2 ia medir 3 lotes e
foi **interrompida** no terceiro, a pedido do dono (a máquina era dele naquela hora). Na rodada 1,
a máquina fazia outro trabalho leve ao mesmo tempo; na rodada 2, não.

**O que isto quer dizer:** na CPU, um lote de 16 a 17 palavras leva de 114 a 180 s — de 15 a 19
vezes o tempo da própria fala — e passa, ou quase passa, do prazo de 120 s que o motor dá a cada
lote. Na conversa, o Jarvis cai no motor padrão (`tts-piper-epitran`) no primeiro lote que estourar.
**Na CPU, o OmniVoice serve para conferir a instalação, não para conversar.** O primeiro "Olá." (a
carga dos pesos, a voz de referência e um lote curto) saiu dentro dos prazos nas duas rodadas.

## O que NÃO foi medido

- **GPU** (a RTX 4060 do dono): nem carga, nem latência, nem memória de vídeo;
- qualidade da voz clonada e do português — a referência era sintética;
- o primeiro áudio de ponta a ponta no aplicativo, com o alto-falante;
- mais de 2 lotes, outras CPUs, Windows e macOS.
