# ADR-0015 — canal de áudio entre `audio-io` e `agentd`: números medidos

**Gerado por** `tools/harness_canal.py` (não editar à mão). **Data:** 2026-10-15.

> **Dois processos de verdade.** O produtor roda em outro processo e envia quadros de 20 ms no ritmo real; o consumidor mede. A latência usa o `CLOCK_MONOTONIC` do sistema, que os dois processos compartilham no Linux.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- `n` = 1500 quadros de 20 ms por execução (30 s de áudio), 3 execuções
- capacidade do anel e folga do socket: 64 quadros (1.28 s)
- formato do quadro no canal: cabeçalho: <IIQI (epoch u32, seq u32, ts_mono_ns u64, amostras u32) = 20 bytes; amostras: PCM16 little endian, 640 bytes por quadro de 20 ms a 16000 Hz; anel: selo u64 antes e depois de cada posição, contador u64 no deslocamento 0.
- `tortos` conta quadro cujo padrão determinístico não bateu: é a prova de que o selo do anel não deixa passar escrita pela metade

## Com ritmo real (o caso de uso)

| canal | n | latência p50 | p95 | p99 | máximo | jitter p95 | descartados | tortos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `anel` | 1500 | 22.3 µs | 47.1 µs | 58.8 µs | 542.4 µs | 205.9 µs | 0 | 0 |
| `conexao` | 1500 | 31.6 µs | 59.3 µs | 68.1 µs | 281.6 µs | 298.3 µs | 0 | 0 |
| `socket` | 1500 | 27.9 µs | 50.2 µs | 65.0 µs | 397.2 µs | 284.2 µs | 0 | 0 |

## Sem ritmo (teto de vazão, não é o caso de uso)

| canal | quadros/s | latência p95 | descartados |
|---|---:|---:|---:|
| `anel` | 141248 | 6.2 µs | 0 |
| `conexao` | 123993 | 90.3 µs | 0 |
| `socket` | 119205 | 8.3 µs | 0 |

## O que não foi medido

- **Windows** — `AF_UNIX` em datagrama não existe no Python para Windows, e `shared_memory` existe mas com semântica de nome diferente. A implementação escolhida precisa de um caminho Windows antes de o P11 valer (está na ADR-0015 como consequência)
- **concorrência real de produtor e consumidor sob carga** — a máquina estava ociosa; com os sete processos rodando e o ASR consumindo CPU, o jitter tende a piorar — e é por isso que o canal descarta em vez de bloquear
- **mais de um consumidor** — o anel é um produtor e um consumidor por projeto. Dois consumidores exigem outro desenho (ou um anel por consumidor)
