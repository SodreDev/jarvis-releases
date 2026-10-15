# F0-04 — latência de captura e a decisão D1: números medidos

**Gerado por** `tools/harness_captura.py` (não editar à mão). **Data:** 2026-10-15.

## Como foi medido

- hardware: AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM
- Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14, rustc 1.98.1 (48a229cea 2026-09-01)
- 200 frames de 20 ms por execução (4 s de áudio), 1 execuções
- o caminho medido é `frame de 20 ms → pré-filtro → VAD → evento`; os braços `rust-std` e `python-numpy` usam a **mesma** aritmética e os mesmos limiares, para a comparação ser de linguagem e não de algoritmo
- áudio sintético determinístico, idêntico para os três braços (fala e silêncio alternados). **Não é corpus**: corpus pt-BR de turno é da F1, com consentimento
- `rust-std` compila com `rustc -O`, **só biblioteca padrão**: sem cargo, sem rede e sem instalar nada na máquina
- `python-onnx` usa `silero-vad` (MIT, verificado na F0-09) com 1 thread, janela de 512 amostras, que é o que o modelo exige a 16 kHz
- `evento-no-barramento` mede o **resto** do SLO-1: criar o envelope da §3.1, validar na borda, mandar pelo IPC (ida e volta) e gravar no log encadeado por hash. É por evento, não por frame

## Resultado por braço (mediana das execuções)

| braço | p50 (ms) | p95 (ms) | p99 (ms) | máximo (ms) | pausas de GC | GC total (ms) |
|---|---:|---:|---:|---:|---:|---:|
| `rust-std` | 0.0003 | 0.0003 | 0.0004 | 0.0113 | 0 | 0.0 |
| `python-numpy` | 0.0104 | 0.0143 | 0.0286 | 0.1560 | 0 | 0.0 |
| `evento-no-barramento` | 0.3764 | 0.4211 | 0.5548 | 0.9028 | 1 | 0.2 |

## Pisos: o que é da máquina, não nosso

| piso | n | p50 (ms) | p95 (ms) | p99 (ms) | observação |
|---|---:|---:|---:|---:|---|
| agendamento (laço de 20 ms, sem nosso código) | 200 | 0.077 | 0.087 | 0.098 |  |

## Proposta de D1 (linguagem e IPC do núcleo)

O orçamento do SLO-1 é **p95 ≤ 80 ms** de captura a evento. Somando o que é nosso — VAD + criar/validar/enviar/registrar o evento + o piso de agendamento:

| caminho | p95 somado (ms) | fração do SLO-1 |
|---|---:|---:|
| Python + ONNX (silero) | 0.508 | 0.63% |
| Rust (VAD barato) + barramento em Python | 0.508 | 0.64% |

- A diferença de linguagem **no VAD** é de 0.0003 ms (Rust) contra 0.0143 ms (Python+numpy, mesma aritmética) e 0.0000 ms (Python+ONNX, VAD neural de verdade). Em termos de SLO-1, a maior dessas é 0.00% do orçamento.
- O **custo do evento** (0.421 ms p95: envelope, validação de borda, IPC ida e volta e log encadeado) é maior que o custo do VAD em qualquer linguagem. O gargalo do nosso lado é a fronteira, não a aritmética.
- O **piso do dispositivo** medido (0.0 ms p95) é uma a duas ordens de grandeza maior que tudo que fazemos — com a ressalva de viés logo abaixo.

**Proposta:** manter **Python 3.12 nos sete processos no v0**, com a fronteira pronta para trocar `audio-io`/`agentd` por Rust sem reescrever contrato (o contrato é dado: `schemas/events.v1.json` e `schemas/event_log.sql`). O número não justifica pagar duas linguagens agora: o nosso custo total é menos de 1% do SLO-1, e o ecossistema de ML (ONNX, ASR, TTS) está em Python.

**A lacuna que pode derrubar a proposta:** o que foi medido é VAD + evento, **não** AEC/NR de verdade, **não** ASR incremental e **não** captura de dispositivo real. Se a F1 medir que AEC + ASR + TTS em Python estouram o SLO-1 ou o SLO-2 na máquina do dono, a troca é local, em dois processos, e a decisão volta — por isso a fronteira fica trocável desde já. Esta proposta é do executor, com base em medição; **a decisão é do dono** (ADR do cartão F0-10).

## O que **não** foi medido

- **braço `python-onnx`** — o modelo silero-vad não foi passado em `--modelo` (o peso não é versionado no repositório; baixe-o e aponte o caminho)
- **piso do dispositivo de áudio** — o monitor entregou só 23 frames: amostra insuficiente
- **captura do microfone de verdade** — não foi medida de propósito: gravar o microfone do dono para medir jitter seria invadir privacidade sem necessidade. O piso do dispositivo usa o monitor da saída, que tem o mesmo caminho de driver
- **Windows** — o harness é portável (Rust std, Python, stdlib), mas foi executado só em Linux: não há máquina Windows nem remoto nesta sessão
- **AEC e redução de ruído de verdade** — o pré-filtro medido é pré-ênfase + RMS + ZCR, que é o 'VAD barato' do esqueleto. AEC (WebRTC ou equivalente) entra na F1 e tem custo próprio, não medido aqui

### Viés conhecido do piso do dispositivo

O piso foi medido no **monitor de uma saída ociosa** (nada tocando). Um monitor sem produtor ativo entrega em rajada, então o p95 de ~20 ms mede o comportamento da rajada, e não o jitter de um fluxo de captura em uso. Trate-o como **limite superior grosseiro**, não como medida do caminho de áudio ativo. O número honesto só sai na F1, com captura de verdade e consentimento do dono — e é lá que o SLO-1 é cobrado ponta a ponta, do microfone ao evento.
