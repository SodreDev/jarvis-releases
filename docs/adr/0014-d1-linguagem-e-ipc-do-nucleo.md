# ADR-0014 — D1: linguagem e IPC do núcleo, decidida por medição

**Data:** 2026-10-15 · **Estado:** proposta (a decisão é do dono) · **Decide:** dono
**Mede:** executor, cartão F0-04 · **Commit da medição:** `85e23a4`
**Fecha:** a decisão aberta D1 da SPEC §2 e a pendência Q1 do dono.

## Contexto

A §2 deixou D1 aberta com um critério explícito: medir o p95 de captura→evento (SLO-1) num
esqueleto Rust e num Python+ONNX **na máquina do dono**, e decidir pelo número.

Medição do cartão F0-04, em `docs/medicoes/f0-04-captura.{csv,md}`:

- **hardware:** AMD Ryzen 5 5600G (12 fios), 31 GiB de RAM, Linux 7.2.9 (Nobara 44);
- **ferramentas:** rustc 1.98.1, Python 3.12.14, onnxruntime 1.31.0, silero-vad (MIT);
- **`n` = 10 000 frames de 20 ms por execução** (200 s de áudio), **3 execuções**, áudio
  sintético determinístico idêntico nos braços; um teste exige que Rust e Python contem **o
  mesmo número de eventos** sobre o mesmo áudio, senão a comparação não valeria.

| caminho | p50 | p95 | p99 | máximo |
|---|---:|---:|---:|---:|
| `rust-std` (VAD barato, só `std`) | 0,0003 ms | **0,0003 ms** | 0,0003 ms | 0,0146 ms |
| `python-numpy` (mesma aritmética) | 0,0100 ms | **0,0105 ms** | 0,0155 ms | 0,1894 ms |
| `python-onnx` (silero-vad, 1 thread) | 0,0979 ms | **0,1101 ms** | 0,1204 ms | 0,4670 ms |
| `evento-no-barramento` (envelope + validação + IPC + log com hash) | 0,3639 ms | **0,3840 ms** | 0,4753 ms | 1,3394 ms |
| piso de agendamento (laço de 20 ms, sem nosso código) | 0,070 ms | **0,080 ms** | 0,086 ms | — |
| piso do dispositivo (monitor de saída ociosa) | 1,33 ms | **20,0 ms** | 20,0 ms | — |

Somando o que é nosso (VAD + evento + piso de agendamento): **0,575 ms p95 em Python** e
0,466 ms em Rust, contra um orçamento de **80 ms p95** (SLO-1) — 0,72% e 0,58%.

Três leituras diretas desses números:

1. a diferença de linguagem **no VAD** vale 0,11 ms, ou **0,14% do SLO-1**;
2. o **custo do evento** (0,384 ms) é maior que o do VAD em qualquer linguagem: o gargalo do
   nosso lado é a fronteira de processo, não a aritmética;
3. o piso do dispositivo é uma a duas ordens de grandeza acima de tudo que fazemos — com
   **viés declarado**: monitor de saída ociosa entrega em rajada, então 20 ms p95 é limite
   superior grosseiro, não jitter de captura em uso.

## Decisão

**Python 3.12 nos sete processos no v0**, com IPC local autenticado (`AF_UNIX` no Linux,
`AF_PIPE` no Windows, JSON e nunca pickle) e a fronteira pronta para trocar `audio-io` e
`agentd` por Rust sem reescrever contrato — porque o contrato é dado (`schemas/events.v1.json`,
`schemas/event_log.sql`), não código.

## Alternativas descartadas

- **Rust em `audio-io` + `agentd` desde já:** ganharia 0,11 ms num orçamento de 80 ms e
  custaria duas linguagens, dois ferramentais de build e duas implementações do contrato, com
  o ecossistema de ASR/TTS/ONNX ficando do outro lado da fronteira. Volta a ser a escolha se a
  lacuna abaixo se confirmar.
- **Rust em tudo:** `s2` e `memoryd` vivem de ecossistema de ML; perderíamos ONNX Runtime,
  reranker e bibliotecas de áudio por um ganho que não aparece no SLO.
- **IPC por TCP em loopback:** simplificaria o Windows e abriria o barramento para qualquer
  processo da máquina. Socket de domínio e named pipe com `authkey` custam o mesmo e não
  escutam na rede.
- **Decidir por preferência de linguagem:** era o que a §2 proibia.

## Consequências

- Mais fácil: um ferramental, um CI, um formato; F1 começa com ASR/TTS em Python sem ponte.
- Mais caro: se a F1 estourar o orçamento, a troca é um projeto, não um `sed` — mitigado por o
  contrato estar em dados e o barramento ter implementação de referência testada.
- Passa a ser obrigatório medir em F1, **com AEC e ASR reais**, o SLO-1 e o SLO-2 ponta a
  ponta; e manter o braço Rust do harness funcionando como linha de base (ele compila com
  `rustc`, sem dependência, então custa quase nada).

## A lacuna que pode derrubar esta decisão (dita antes de alguém perguntar)

O que foi medido é **VAD + evento**. **Não** foram medidos AEC/redução de ruído de verdade,
ASR incremental, TTS streaming nem captura de dispositivo real (o microfone do dono não foi
gravado, por privacidade). Se a F1 medir que esses componentes em Python estouram SLO-1 ou
SLO-2 na máquina do dono, D1 volta para a mesa e a troca é local, em dois processos.

## Como invalidar esta decisão

Medição de F1 com AEC + ASR + TTS mostrando p95 de captura→evento acima de 80 ms ou de
barge-in acima de 150 ms em Python, na máquina do dono.
