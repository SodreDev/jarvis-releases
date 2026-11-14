# STT em pt-BR: modelo, beam, dica e placa (ADR-0067)

Medido em 2026-11-14 sobre o commit 38c3997 com `tools/harness_stt.py` (dados por trecho em
`stt-pt-br.csv`). Hardware: Ryzen 5 5600G (4 threads, `nice -n 19`, int8) e RTX 4060 8 GB (float16,
com a cuBLAS 12 do pacote `nvidia-cublas-cu12` numa pasta à parte — a máquina não a tem instalada).

**Material:** 16 frases (as do dono — «mãe», «abre o contato da minha mãe», «WhatsApp» —, apps,
IAs, sim/não) × 3 variações (ritmo 1,0/0,85/1,2; altura 1,0/0,93/1,07; fundo −62/−50/−45 dB) na voz
piper `pt_BR-faber-medium` com fonemas do espeak-ng (só em `tools/`), cada uma com 400 ms antes e
1,3 s depois, como o laço manda ao ASR. Mais os 8 ruídos forçados do `harness_ruido` (sala, clique,
teclado, respiração, tosse, ventilador, chiado). `language="pt"` em todas.

**Ressalva:** voz sintética é material fácil e tem defeitos próprios — o piper diz «Mãe.» sozinho
de um jeito que **todo** modelo ouve «Não.», e «Sim.» sai «Tchau.». O número ordena configurações;
não é o WER na voz do dono (para isso: `tools/diagnostico_stt.py`).

Colunas: WER médio; termo-chave = o nome esperado saiu escrito (sem caixa e sem acento); «mãe» e
«WhatsApp» = as frases do dono com cada termo; fala descartada = fala que o filtro de ruído da
ADR-0043 jogou fora; ruído que vira texto = ruído forçado que o ASR transcreveu e o filtro deixou
passar; ASR p50 = mediana do tempo de uma transcrição.

## CPU (int8)

| configuração | WER médio | termo-chave | «mãe» | «WhatsApp» | fala descartada | ruído que vira texto | ASR p50 (ms) |
|---|---|---|---|---|---|---|---|
| small, beam 1, dica atual (o de hoje) | 0,381 | 35/48 | 9/12 | 8/9 | 4 | 0/8 | 1899 |
| small, beam 1, sem dica | 1,101 | 28/48 | 10/12 | 6/9 | 3 | 0/8 | 1668 |
| small, beam 5, dica atual | 0,375 | 35/48 | 9/12 | 8/9 | 3 | 0/8 | 2248 |
| small, beam 5, dica em frase | 0,396 | 34/48 | 10/12 | 8/9 | 2 | 0/8 | 2527 |
| large-v3-turbo, beam 1, dica atual | 0,222 | 37/48 | 9/12 | 9/9 | 1 | 5/8 | 9184 |

A rodada de CPU do turbo parou depois da primeira configuração: 9 s por trecho já decide que ele
não roda ao vivo na CPU (o CSV não tem as linhas dela; o resumo acima é o que a rodada imprimiu).

## Placa de vídeo (float16)

| configuração | WER médio | termo-chave | «mãe» | «WhatsApp» | fala descartada | ruído que vira texto | ASR p50 (ms) |
|---|---|---|---|---|---|---|---|
| small, beam 1, dica atual | 0,339 | 36/48 | 10/12 | 8/9 | 0 | 0/8 | 140 |
| small, beam 5, dica atual | 0,367 | 36/48 | 10/12 | 8/9 | 0 | 0/8 | 136 |
| medium, beam 5, dica atual | 0,326 | 36/48 | 9/12 | 9/9 | 2 | 0/8 | 246 |
| **large-v3-turbo, beam 1, dica atual** | **0,194** | **38/48** | 9/12 | **9/9** | 1 | 3/8 | 265 |
| large-v3-turbo, beam 5, dica atual | 0,243 | 37/48 | 9/12 | 8/9 | 0 | 4/8 | 460 |
| large-v3, beam 5, dica em frase | 0,309 | 37/48 | 9/12 | 9/9 | 3 | 1/8 | 438 |

## O que a medição decide

1. **O modelo é o teto, não a configuração.** No small, beam 5 e dica em frase não mudam nada que
   valha o tempo; o turbo corta o WER quase pela metade (0,381 → 0,194) e escreve «WhatsApp» em
   todas as variações.
2. **Na CPU o turbo não cabe** (9 s por trecho). Na placa ele leva 265 ms — menos que o small na
   CPU (1,9 s). Por isso o `auto`: turbo na placa, small na CPU.
3. **Beam 1** ganha do beam 5 no turbo (0,194 × 0,243) e custa a metade.
4. **A dica fica** (lista curta da ADR-0043): sem ela o WER passa de 1 (o small inventa frase
   inteira) e o «Jarvis» some; a dica em frase tira o «Jarvis» do começo (3/3 → 0/3).
5. **Risco novo:** o turbo inventa «E aí» no silêncio e no chiado **com confiança alta**, e o
   filtro da ADR-0043 (calibrado no small) só descarta «e aí» sem sinais fortes — 3 dos 8 ruídos
   forçados passaram. Na prática o portão do trecho e o silero vêm antes (não abriram para nenhum
   destes ruídos), mas os limiares do filtro precisam ser revistos no turbo pela trilha `ruido`.

Rodar de novo: `nice -n 19 uv run --frozen python -m tools.harness_stt` (CPU) ou com
`--dispositivo cuda` (placa; precisa da cuBLAS 12 no caminho do Python).
