# F2-01 — primeira fala com o cérebro em stream: SLO-5 por trecho

**Gerado por** `tools/harness_primeira_fala.py` (não editar à mão). **Data:** 2026-10-16. **Commit:** `0484858`.

> **Piso de software, sem dispositivo.** O 1º áudio é o primeiro pedaço na fila de playback e o primeiro tick dela; a fila do driver não está na conta. O SLO-5 de verdade é medido na máquina do dono com o dispositivo (F1-16).

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14
- caminho: `Cerebro.responder` (s2) numa linha de execução → `ResponseChunk` → `falar_stream_para` (TTS) → `FilaDePlayback.tick`, tudo em memória, sem barramento entre processos
- tempos contados do **turno aceito**; "desde o fim da fala" soma os 500 ms de decisão de turno do `silencio_fixo` publicados no F1-07 (tempo de áudio, não remedido)
- `roteirizado`: resposta do corpus de turnos, sem atraso de motor — o que sobra é o nosso lado; `claude-cli`: as 8 perguntas curtas da medição do S2 provisório, com rede
- alvo da SPEC §7 para o SLO-5: p50 ≤ 600 ms, p95 ≤ 900 ms

## Resultado

| motor | TTS | n | montagem p50 | 1ª fronteira p50 | 1ª fronteira p95 | 1º áudio p50 | 1º áudio p95 | 1º áudio máx | desde o fim da fala p50 | piso cabe no SLO-5? |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--|
| `roteirizado (teste)` | `parametrico@1` | 40 | 0.03 ms | 0.1 ms | 0.1 ms | 17.3 ms | 24.5 ms | 29.4 ms | 517.3 ms | piso cabe |
| `claude-cli:haiku (provisório)` | `parametrico@1` | 10 | 0.03 ms | 1491.2 ms | 1886.4 ms | 1508.6 ms | 1905.3 ms | 1905.3 ms | 2008.6 ms | **piso excede** |
| `roteirizado (teste)` | `piper-onnx@1.0.0+pt_BR-faber-medium` | 40 | 0.03 ms | 0.1 ms | 0.1 ms | 110.7 ms | 131.7 ms | 142.8 ms | 610.7 ms | piso cabe |
| `claude-cli:haiku (provisório)` | `piper-onnx@1.0.0+pt_BR-faber-medium` | 10 | 0.03 ms | 1403.0 ms | 1655.7 ms | 1537.6 ms | 1745.9 ms | 1745.9 ms | 2037.6 ms | **piso excede** |

## O que não foi medido

- **fila do dispositivo** — o primeiro áudio audível depende do driver; aqui é o primeiro tick sobre sumidouro de memória (F1-16, máquina do dono)
- **barramento entre processos** — o `ResponseChunk` vai de linha para linha de execução, não por IPC: o custo por evento medido na F0-04 (0,384 ms p95) fica de fora, uma vez por pedaço
- **motor local e motor de API** — D18 manda medir os dois; ainda não há adaptador — este harness já os aceita pela interface `MotorDeConversa`
- **decisão de turno no corpus real** — o atraso somado é o do `silencio_fixo` no corpus sintético (F1-07); o número do v1 sai do F1-15/F1-16
- **percentis altos do motor com rede** — 10 turnos por configuração não sustentam p95 de verdade; servem para a ordem de grandeza
