# `consultas/` — C2, perguntas anotadas (F3)

Mede recuperação de memória (§8.1 e §8.2): recall, nDCG e **abstinência** — a resposta certa
pode ser "não encontrei evidência".

```jsonc
{"id": "c-0001", "pergunta": "quem pediu o relatório de junho?",
 "relevantes": ["mu-000123", "mu-000456"],   // memory_unit que respondem
 "negativos": ["mu-000789"],                  // parecidos e errados, de propósito
 "sem_resposta": false,                        // true = o certo é abster-se
 "tipo": "multi_salto",                        // direta | relacional | temporal | multi_salto
 "instante": "2026-10-15T12:00:00Z",          // "agora" da pergunta, para validade temporal
 "split": "retido"}
```

Sem os `negativos` e sem os casos `sem_resposta: true`, a medição mede só o caso fácil.
