# F1-06 — ASR incremental: WER de pt-BR, SLO-3 e o custo da janela crescente

**Gerado por** `tools/harness_asr.py` (não editar à mão). **Data:** 2026-10-15.

> **Ressalva obrigatória: o corpus é TTS sintético, material fácil.** Sem sotaque, sem ruído de casa, sem nome próprio difícil, prosódia limpa. O WER daqui é piso otimista; WER na voz do dono é F1-15/F1-16.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- 24 itens do split `calibracao` (metade fim de turno, metade hesitação)
- estratégia incremental: janela crescente a cada 200 ms + acordo de prefixo; **utilizável** = `stability >= 0.6`, limiar escrito antes de medir
- normalização de WER/CER: minúsculas, sem pontuação, **acento preservado** (`jarvis.corpus.metricas`)
- `oráculo` não é ASR: devolve o texto do rótulo e serve para separar o custo do **encanamento** do custo do **modelo**

## Resultado por implementação

| motor | modelo | licença | n | WER médio | WER p50 | CER médio | SLO-3 p50 | SLO-3 p95 | sem parcial utilizável |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| `incremental+faster-whisper@small` | `openai/whisper-small` | Apache-2.0 | 24 | 0.089 | 0.000 | 0.027 | 1007 ms | 1362 ms | 0 |
| `incremental+oráculo-do-rótulo@1` | `(nenhum)` | não se aplica (texto do próprio corpus) | 24 | 0.000 | 0.000 | 0.000 | 345 ms | 457 ms | 0 |

## Custo de CPU da janela crescente

| motor | passos p50 | RTF de parede p50 | RTF de parede p95 | RTF de CPU p50 |
|---|---:|---:|---:|---:|
| `incremental+faster-whisper@small` | 14 | 6.02× | 8.17× | 25.48× |
| `incremental+oráculo-do-rótulo@1` | 15 | 0.00× | 0.00× | 0.00× |

RTF (*real-time factor*) é tempo gasto por segundo de áudio. O de **parede** é o que responde "dá para rodar ao vivo?": acima de 1,0, **não dá** nesta máquina com este modelo. O de **CPU** soma as threads e mostra quanto da máquina o ASR consome. A janela crescente re-transcreve o turno inteiro a cada passo, então o custo cresce com o quadrado da duração — o caminho para o v1 é modelo *streaming* (um transducer como o `parakeet-tdt` decodifica por quadro, sem refazer o passado) ou GPU.

## O que não foi medido

- **WER na voz do dono** — com o microfone e o ruído dele, sotaque, nome próprio e termo do domínio: é F1-15 (corpus real) e F1-16 (aceite)
- **SLO-3 ao vivo** — aqui é tempo de áudio sobre arquivo; ao vivo entram captura, AEC, VAD e a fila do driver
- **nvidia/parakeet-tdt-0.6b-v3** — registrado e verificado na origem (CC-BY-4.0, 25 idiomas com pt), mas NÃO executado: o runtime é o NeMo, pesado e orientado a GPU. A comparação com o whisper em pt-BR real é do F1-16
- **whisper-large-v3** — 3 GB: o que rodou foi o `small`, mesma família e mesma licença (Apache-2.0)
- **Windows** — a medição rodou só em Linux
