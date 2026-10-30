Índice: LanceDB + multilingual-e5-small; 3612 itens indexados (842 fatos, 1500 turnos de conversa à toa); montar levou 15.1 s.

| caminho | n | p50 (ms) | p95 (ms) | máx (ms) | instantâneo (p95 < 150 ms)? |
|---|---:|---:|---:|---:|---|
| abrir o modelo + 1ª inferência (a 1ª consulta da sessão) | 1 | 763.6 | — | — | — |
| 1ª inferência com o modelo aquecido ao abrir o livro (agora) | 1 | 5.1 | — | — | — |
| memória do turno (`consultar`, todo turno) | 300 | 15.2 | 17.6 | 76.0 | sim |
| `memoria.buscar_historico` | 300 | 15.4 | 17.1 | 19.9 | sim |
| memória do turno com o indexador gravando | 300 | 46.9 | 78.8 | 119.2 | sim |

Durante a medição concorrente o indexador gravou 428 turnos.
