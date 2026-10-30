# Tom de voz: acerto e custo medidos (ADR-0058)

Gerado por `tools/harness_tom.py` · commit da medição: 9231d77 + árvore de trabalho (tom não commitado) · hardware: AMD Ryzen 5 5600G with Radeon Graphics · Python 3.12.14 · numpy 2.5.4. Tudo é áudio sintético: nenhum número aqui vale para a voz do dono antes de ela ser medida.

### Banco sintético (20 sementes; `sintetico`: sim)

| cena | rótulo esperado | com a base pronta | sem base (1º turno) |
|---|---|---|---|
| afirmacao | entonacao=afirmacao, volume=normal | 20/20 | 20/20 |
| pergunta | entonacao=pergunta | 20/20 | 20/20 |
| pergunta_oxitona | entonacao=pergunta | 20/20 | 20/20 |
| grito | volume=grito | 20/20 | 0/20 |
| voz_baixa | volume=baixo | 20/20 | 0/20 |
| sussurro | volume=sussurro | 20/20 | 20/20 |
| risada | evento=risada | 20/20 | 20/20 |
| tosse | evento=tosse | 20/20 | 20/20 |
| suspiro | evento=suspiro | 19/20 | 19/20 |
| rapido | ritmo=rapido | 20/20 | 20/20 |
| lento | ritmo=lento | 20/20 | 20/20 |

Turnos neutros (a voz «de sempre») rotulados fora do neutro: 0/60.

### Custo da análise (`medir`, numpy, uma linha)

| fala | n | p50 ms | p95 ms |
|---|---|---|---|
| 1 s | 35 | 2.6 | 2.8 |
| 2 s | 35 | 7.0 | 7.8 |
| 4 s | 35 | 10.9 | 11.6 |
| 6 s | 35 | 14.4 | 15.5 |

### Voz piper local, a mesma frase com `?` e com `.` (`sintetico`: sim)

O texto que o rótulo recebe é o da frase **sem** pontuação (o ASR que não pôs o `?`).

| dita com | n | rotulada certo | pico final − resto (st), p50 | p10 | p90 |
|---|---|---|---|---|---|
| pergunta | 12 | 4/12 | 0.7 | -3.7 | 7.8 |
| afirmação | 12 | 12/12 | -1.4 | -3.3 | 0.3 |

### Em paralelo ao ASR (whisper small int8, CPU, 4 threads; n=24)

| medida | p50 ms | p95 ms |
|---|---|---|
| ASR sozinho | 1169 | 1217 |
| ASR com o tom na linha ao lado | 1186 | 1223 |
| análise do tom | 5.9 | 10.6 |
| espera do laço depois do ASR | 0.01 | 0.01 |
