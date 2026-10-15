# `turnos/` — pausa real em pt-BR (F1)

Mede **SLO-4** (pausa → decisão de turno) e **SLO-9** (falso corte). Meta da F1: ≥ 500 pausas
reais, consentidas.

- áudio em `turnos/audio/<id>.wav` — PCM 16 bits, mono, 16 kHz;
- rótulo em `turnos/rotulos.jsonl`, uma linha por pausa.

```jsonc
{"id": "t-0001", "arquivo": "audio/t-0001.wav", "sha256": "…",
 "termo": "TERMO-0001", "falante": "dono",
 "pausa_ms": 420, "fim_de_turno": true,        // o dono realmente parou?
 "texto": "liga o rádio",                       // transcrição humana
 "contexto": "pedido curto, sala silenciosa",
 "split": "calibracao"}
```

`fim_de_turno: false` é o caso que importa mais: pausa no meio da frase, que o assistente
**não** pode interromper. Grave os dois, na mesma proporção em que acontecem.
