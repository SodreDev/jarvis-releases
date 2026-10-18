# F1-17 — pronúncia aproximada de aplicativos

Data: 2026-10-18. Resultado reproduzível com:

```bash
uv run --frozen python tools/medir_pronuncia_apps.py
```

## Cenário e resultado

O corpus é [f1-17-pronuncia-apps.csv](f1-17-pronuncia-apps.csv): 21 transcrições sintéticas
pt-BR para sete apps autorizados fictícios, incluindo `discórdi`, `espótifai`, `vi esse côdi`,
`cróme`, `brêive`, `obisídian` e `tim speak`, mais variações e três falas que devem ser negadas.
O resolvedor usa nomes/metadados do catálogo, normalização fonética local e limiar 0,74; não há
alias inicial nem rede.

| Métrica | Resultado |
|---|---:|
| itens | 21 |
| itens com app esperado | 18 |
| top-1 | 18/18 (100%) |
| top-3 | 18/18 (100%) |
| falso-aceite | 0/21 (0%) |

Falso-aceite é qualquer abertura automática para app diferente do esperado — inclusive nas três
frases sem app. Empates são classificados como ambíguos e não contam como abertura.

## Limite honesto e próxima rodada

Esta é uma regressão de **texto transcrito**, não uma medição fim a fim do Whisper: ela é
determinística, não usa microfone, TTS, rede nem modelo. Antes de mudar limiar ou declarar
qualidade de ASR, gerar dois áudios por nome (voz pt-BR e voz inglesa, TTS local licenciado),
transcrever com o Whisper local configurado e guardar o texto devolvido como novos itens do CSV.
Medir o mesmo top-1/top-3/falso-aceite em um split retido, com o catálogo real do dono e pares
conflitantes (por exemplo Discord/Discord Canary). O teste de regressão é
`tests/unit/apps/test_resolvedor.py`.
