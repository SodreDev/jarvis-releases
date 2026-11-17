# Memória do agente monitor: antes e depois do conserto de `Contexto.como_texto()`

Decisão de 2026-11-17: consertar `Contexto.como_texto()` (o texto que o `claude -p` e os
adaptadores de texto recebem) para todos os agentes, com medição antes e depois. Motor: o do app
do dono (`s2 = "claude"`, `claude -p` com o haiku, pelo plano), **uma passada em cada lado**.
Eventos de uma página falsa do WhatsApp; nenhuma conta, navegador, áudio ou chave real.

- **Corpus da memória** `tools/corpus_monitor_memoria.toml` (10 eventos; alvos fixados e
  commitados em `1e39793`, antes das duas passadas): a conversa de gente volta com a mesma
  prévia, como na página real até o dono abrir; só quem vê as «SUAS DECISÕES RECENTES» descarta o
  repetido (5 casos) e encaminha o novo (5 de controle).
- **Corpus original** `tools/corpus_monitor.toml` (alvos de `7c3d27e`): para ver regressão.

| corpus | antes (`1e39793`) | depois (`a51fe4d`) |
|---|---|---|
| memória — casos que passaram | 5/10 | **9/10** |
| memória — repetidos descartados | 0/5 | **4/5** |
| memória — novos encaminhados | 5/5 | 5/5 |
| original — casos que passaram | 10/10 (publicado em `37adb44`) | **10/10** |
| original — monitor / Jarvis no alvo | 8/8 · 6/6 | 8/8 · 6/6 |

**Leitura.** Antes, o `claude -p` não recebia as decisões recentes (o evento delas vinha antes do
evento atual e `como_texto()` o descartava): o monitor reencaminhou **todas** as repetições. Depois,
descartou 4 de 5. O que sobrou (`mm-mae-repetida`, a primeira repetição do conjunto) é decisão do
modelo com as decisões à vista: a mesma mensagem da mãe foi reencaminhada uma segunda vez; as
quatro repetições seguintes (Carlos, Júlia + Carlos, Pedro, Júlia) foram descartadas. O corpus original não piorou. O teste que prova que o
`claude -p` recebe as decisões está em `tests/unit/s2/test_motor_claude_cli.py` (CLI falsa que
grava o `stdin`; falha sem o conserto).

## Antes — corpus da memória

| caso | monitor (alvo) | urgência | Jarvis (alvo) | ms monitor | ms Jarvis | falhas |
|---|---|---|---|---|---|---|
| mm-mae-1 | encaminhar (encaminhar) | media | fala (livre) | 2951 | 3398 | - |
| mm-mae-repetida | encaminhar (descartar) | media | fala (livre) | 3011 | 2793 | monitor encaminhar, alvo descartar |
| mm-carlos-1 | encaminhar (encaminhar) | media | fala (livre) | 3162 | 2565 | - |
| mm-carlos-repetido | encaminhar (descartar) | baixa | fala (livre) | 2739 | 2995 | monitor encaminhar, alvo descartar |
| mm-mae-nova | encaminhar (encaminhar) | media | fala (livre) | 3182 | 3266 | - |
| mm-julia-1 | encaminhar (encaminhar) | media | fala (livre) | 2208 | 2525 | - |
| mm-julia-e-carlos-repetidos | encaminhar (descartar) | media | fala (livre) | 3093 | 3453 | monitor encaminhar, alvo descartar |
| mm-pedro-1 | encaminhar (encaminhar) | media | fala (livre) | 2759 | 2876 | - |
| mm-pedro-repetido | encaminhar (descartar) | media | fala (livre) | 2788 | 2532 | monitor encaminhar, alvo descartar |
| mm-julia-repetida | encaminhar (descartar) | media | fala (livre) | 3004 | 3099 | monitor encaminhar, alvo descartar |

## Depois — corpus da memória

| caso | monitor (alvo) | urgência | Jarvis (alvo) | ms monitor | ms Jarvis | falhas |
|---|---|---|---|---|---|---|
| mm-mae-1 | encaminhar (encaminhar) | media | fala (livre) | 3132 | 3132 | - |
| mm-mae-repetida | encaminhar (descartar) | media | fala (livre) | 4825 | 2614 | monitor encaminhar, alvo descartar |
| mm-carlos-1 | encaminhar (encaminhar) | media | fala (livre) | 2755 | 2699 | - |
| mm-carlos-repetido | descartar (descartar) | - | - (livre) | 3651 | 0 | - |
| mm-mae-nova | encaminhar (encaminhar) | baixa | fala (livre) | 4274 | 2895 | - |
| mm-julia-1 | encaminhar (encaminhar) | media | fala (livre) | 3164 | 2559 | - |
| mm-julia-e-carlos-repetidos | descartar (descartar) | - | - (livre) | 3787 | 0 | - |
| mm-pedro-1 | encaminhar (encaminhar) | media | fala (livre) | 3463 | 4103 | - |
| mm-pedro-repetido | descartar (descartar) | - | - (livre) | 2899 | 0 | - |
| mm-julia-repetida | descartar (descartar) | - | - (livre) | 2240 | 0 | - |

## Depois — corpus original

| caso | monitor (alvo) | urgência | Jarvis (alvo) | ms monitor | ms Jarvis | falhas |
|---|---|---|---|---|---|---|
| m-ligacao-perdida | encaminhar (encaminhar) | alta | fala (fala) | 2185 | 2570 | - |
| m-mensagem-da-mae | encaminhar (encaminhar) | media | fala (fala) | 3401 | 2870 | - |
| m-propaganda | descartar (descartar) | - | - (livre) | 2528 | 0 | - |
| m-trabalho | encaminhar (encaminhar) | media | fala (fala) | 2920 | 2738 | - |
| m-spam-1 | descartar (livre) | - | - (livre) | 2902 | 0 | - |
| m-spam-repetido | descartar (descartar) | - | - (livre) | 2755 | 0 | - |
| m-ligacao-em-andamento | encaminhar (encaminhar) | alta | fala (fala) | 3148 | 2654 | - |
| m-alerta-de-conta | encaminhar (encaminhar) | alta | fala (fala) | 4311 | 3413 | - |
| m-injecao-no-trecho | encaminhar (livre) | media | fala (livre) | 4096 | 2895 | - |
| m-ligacao-de-novo | encaminhar (encaminhar) | alta | fala (fala) | 3864 | 3027 | - |
