# ADR-0072 — Laço canônico do agente e chamada nativa de ferramenta

- Estado: aceita (2026-11-16)
- Contexto: [docs/estudos/laco-canonico.md](../estudos/laco-canonico.md); dono, 2026-11-16 (memória
  391a8b23): o Jarvis é um agente-CLI com voz; ADR-0070, ADR-0071.

## Decisão

1. **Um laço só.** O modelo é chamado em um lugar (`jarvis.s2.laco.rodada_do_agente`), pelo turno
   do Jarvis e pelo subagente (o do pedido e o do `tarefa.iniciar`). O resultado de cada ferramenta
   volta ao modelo como mensagem, junto da chamada que o gerou (`Mensagem.chamada`). O código só
   valida segurança e permissão (devolvendo o veredito ao modelo), executa, mede e limita
   (devolvendo notificação) e fala o que o modelo mandou falar.
2. **Chamada nativa para quem tem function calling.** O motor compatível com OpenAI
   (`provedores/compativel.py`) manda, quando o serviço tem `tools` (OpenAI, Groq, OpenRouter, ou
   o servidor cuja listagem diz que tem): o catálogo como `tools` (o esquema do manifesto, sem as
   chaves `x-`; o nome `browser.click` vai como `browser__click`), a conversa em mensagens de
   verdade (`user`/`assistant`, e cada resultado no par `assistant.tool_calls` → `tool` com o
   mesmo id) e lê `delta.tool_calls` do stream como `PedidoDeTool`. O raciocínio do provedor
   (`delta.reasoning`) segue como `Raciocinio`. O protocolo de texto (ADR-0028) fica para o motor
   sem function calling (o `claude -p`, servidores locais que não declaram `tools`).

## Por quê

Na validação da ADR-0071 o DeepSeek falhou 6 de 21 por causa do protocolo de texto (resposta
vazia, `<</pensar>>` solto): o provedor tem chamada nativa e não era usada. Um agente-CLI normal
chama ferramenta pela API; o texto era um desvio do provisório.

## Consequências

- Argumentos que não fecham em JSON viram a proposta malformada, recusada com motivo; o modelo
  corrige na rodada seguinte, como no protocolo de texto.
- O pedido passa a mandar a conversa inteira em mensagens (não um texto achatado): o cache de
  prompt do provedor reaproveita o começo igual.
