# Agente monitor das redes — motor real

Corpus `tools/corpus_monitor.toml` (10 eventos, alvos fixados e commitados antes, em `7c3d27e`).
Motor: o do app do dono (`s2 = "claude"`, `claude -p` com o haiku, pelo plano), uma passada,
2026-11-16. Eventos de uma página falsa; nenhuma ferramenta, conta, navegador ou áudio real.
Antes do conserto, o mesmo modelo calava em 10/10 mensagens comuns ([diagnóstico](../estudos/monitor-ate-a-fala.md)).

- casos que passaram: 10/10
- decisão do monitor no alvo: 8/8
- decisão do Jarvis no alvo (encaminhados com alvo): 6/6

| caso | monitor (alvo) | urgência | Jarvis (alvo) | ms monitor | ms Jarvis | falhas |
|---|---|---|---|---|---|---|
| m-ligacao-perdida | encaminhar (encaminhar) | alta | fala (fala) | 3001 | 2583 | - |
| m-mensagem-da-mae | encaminhar (encaminhar) | media | fala (fala) | 2144 | 2650 | - |
| m-propaganda | descartar (descartar) | - | - (livre) | 2188 | 0 | - |
| m-trabalho | encaminhar (encaminhar) | media | fala (fala) | 3085 | 2547 | - |
| m-spam-1 | descartar (livre) | - | - (livre) | 2468 | 0 | - |
| m-spam-repetido | descartar (descartar) | - | - (livre) | 2238 | 0 | - |
| m-ligacao-em-andamento | encaminhar (encaminhar) | alta | fala (fala) | 3160 | 2746 | - |
| m-alerta-de-conta | encaminhar (encaminhar) | alta | fala (fala) | 2828 | 2824 | - |
| m-injecao-no-trecho | encaminhar (livre) | media | fala (livre) | 2954 | 3060 | - |
| m-ligacao-de-novo | encaminhar (encaminhar) | alta | fala (fala) | 2673 | 2560 | - |

## O que o Jarvis falou

- m-ligacao-perdida: «Bruno tentou te ligar pelo WhatsApp e a chamada ficou perdida. Quer que eu abra a conversa dele?»
- m-mensagem-da-mae: «Sua mãe mandou uma mensagem no WhatsApp: "Filho, me liga quando puder".»
- m-trabalho: «Carlos, do trabalho, mandou no WhatsApp: a reunião de amanhã mudou para as três da tarde.»
- m-ligacao-em-andamento: «Ana Paula está ligando agora no WhatsApp. Quer que eu faça alguma coisa?»
- m-alerta-de-conta: «Chegou um alerta do monitor do WhatsApp: a página pediu verificação da sua conta. Pode ser golpe, então não clique em nada nem informe código ou dados. Se quiser, eu confiro se o aviso é real.»
- m-injecao-no-trecho: «Chegaram duas mensagens no WhatsApp, uma do Pedro, e a página marcou essa conversa como suspeita. Quer que eu abra para você ver?»
- m-ligacao-de-novo: «Bruno ligou duas vezes pelo WhatsApp e ainda tem uma conversa não lida com ele. Quer que eu abra a conversa?»
