# Handoff — portão contextual das ferramentas (Jarvis → Jev → PDP → pendência → tarefa)

## Decisão do dono (2026-10-19)

1. O pedido chega ao Jarvis normalmente; ele **não** chama o Jev direto.
2. Dentro do Jarvis, antes de executar uma ferramenta, o Jev classifica *fazer / pedir permissão /
   não fazer* com o pedido, as mensagens relevantes e a situação.
3. O Jev é classificador, nunca autoridade: o PDP/manifesto continua podendo recusar ou exigir
   confirmação mesmo quando o Jev permite.
4. Intenção explícita já dita autoriza a ação simples **naquele** escopo, sem nova confirmação —
   estreita (ação, argumentos, turno, prazo), sem valer para ação seguinte ou diferente.
5. Com confirmação pendente, "sim" falado só resolve a pendência exata e ainda válida; expiração,
   cancelamento e negação continuam seguros.
6. Autorizado, o Jarvis despacha a execução numa tarefa e continua responsivo; o término chega sem
   cortar fala em andamento.

## O fluxo

```text
motor propõe PedidoDeTool
  → ExecutorDeFerramentas.avaliar      método do turno (ADR-0035): fora dele → negado com o
                                        caminho certo (só no turno; a tarefa não segue o método)
                                        catálogo, contrato, PDP: allow | confirm | deny
      deny ─────────────────────────→ negado (o Jev nem é consultado)
  → PortaoDeAcao.classificar (Jev)     pedido do dono + últimas falas + situação + objetivo
                                        (critério de pronto, fase, passos; na nuvem sem o texto
                                        do pedido de novo — ADR-0030, emenda C2)
      nao_fazer ────────────────────→ negado; grant solto; auditoria "portão contextual: …"
      pedir_permissao + allow + AutorizacoesExplicitas.consumir → vira fazer
      fazer + allow ────────────────→ ExecutorDeFerramentas.concluir (roda no turno)
      resto (confirm do PDP, ou pedir_permissao) → RegistroDePendencias.abrir
          o Jarvis diz "Preciso do seu sim para … Posso?" e o turno ACABA
próximo turno do dono (voz ou texto) → FluxoDeAcao.ler_a_resposta
      "sim" → tomar(id) → GestorDeTarefas.iniciar(motor direto, sim de uso único)
              → o turno é só "Certo, estou fazendo: …" (o motor não é chamado)
      "não" → cancela; "Tudo bem, não vou fazer isso"
      outra coisa → cancela; o motor responde, sabendo que a pergunta caiu
clique na faixa → Aplicativo.responder_confirmacao → Cerebro.resolver_pendencia (mesmo tomar)
tarefa termina → ao_concluir → FilaDeAvisos (ADR-0025): fala na fronteira, nunca por cima
```

## Onde mora cada peça

- `jarvis/s2/portao.py` — `PortaoDeAcao` (as perguntas fechadas ao Jev e os limiares),
  `AutorizacoesExplicitas`, `cobre_literalmente`, `resposta_literal`.
- `jarvis/s2/pendencias.py` — `RegistroDePendencias`: uma por vez, amarrada ao id, com prazo.
- `jarvis/s2/fluxo_de_acao.py` — a ordem acima; `_despachar` e `_sim_de_uso_unico`.
- `jarvis/s2/cerebro.py` — `Cerebro.portao` liga o fluxo; `None` = o caminho antigo, idêntico.
- `jarvis/executor/ferramentas.py` — `executar` = `avaliar` + `concluir` (mesmo comportamento);
  `pergunta_de`, `descartar`; `Confirmacao.argumentos`.
- `jarvis/politica/pdp.py` — `Pdp.liberar` solta o grant de um allow que não vai rodar.
- `jarvis/tarefas/gestor.py` — `iniciar(..., motor=, confirmar=)`: escolhidos pelo código, nunca
  pelo modelo.
- `jarvis/voz/app.py` — `_ligar_o_portao` (o classificador do "é comigo?"), faixa da janela,
  vencimento por `threading.Timer`, clique.

## Limites (de propósito)

- **A autorização explícita nunca troca o `confirm` do PDP.** Perigoso, irreversível e turno
  contaminado continuam pedindo o sim. Ela só evita a pergunta que o **Jev** pediria. Exige: Jev
  `pedido_explicito ≥ 0,80` **e** cada valor dos argumentos literalmente na fala do turno (URL conta
  pelo nome do site); vale uma vez por (ferramenta, argumentos), só no turno, por até 60 s.
- **"Sim" literal** ("sim", "pode", "confirmo"…) resolve sem rede; o resto vai ao Jev com a
  pergunta pendente e as falas recentes, e precisa de p ≥ 0,85. Qualquer fala que não seja "sim"
  cancela a pendência: um "sim" atrasado não acha mais nada. Se o dono corta a fala antes de
  ouvir a pergunta inteira, ela também cai (`Cerebro.ouvido`): "sim" por cima não vale.
- **Só uma pendência por vez**; uma nova pergunta no mesmo turno é negada ("já há uma pergunta").
- **O que é delegado:** a execução que precisou de autorização (pendência resolvida). O que o
  PDP e o Jev liberam direto roda no turno, como antes, porque o motor precisa do resultado (ex.:
  o laço "vídeo mais recente" confere a página). Comando longo continua indo por `tarefa.iniciar`.
  `tarefa.*` e `acao.desfazer` confirmados rodam na hora (não cabem em tarefa: profundidade 1).
- **Na tarefa, o PDP decide de novo**; o Jev não (já classificou na conversa). O sim dado responde
  só à pergunta da mesma ferramenta com os mesmos argumentos, uma vez; um segundo "sim" por ação
  (navegador, mouse/teclado) cai na janela, como antes.
- **O "sim" por ação das `browser.*`/`input.*` durante o turno** continua bloqueando na janela
  (caminho de antes): fica para uma próxima fatia.
- **Privacidade:** ao Jev vão o pedido, as últimas 6 falas de dono/Jarvis (300 caracteres cada) e
  os argumentos (strings até 200); resultado de ferramenta (texto de terceiros) não vai.
- **Sem o classificador** (o "é comigo?" não escolhido, sem chave, nuvem desligada): portão
  desligado e comportamento idêntico ao anterior. Classificador que falha no meio: "pedir
  permissão" (na dúvida, pergunta).

## Testes

`tests/unit/s2/test_portao_de_acao.py` — 33 casos, sem rede: limiares de allow/confirm/deny, Jev fora
do ar, estado enviado sem resultado de ferramenta, deny do PDP sem consultar o Jev, `confirm` do PDP
vencendo "fazer", autorização explícita (uma vez, só argumento literal, só o turno, prazo),
"sim" literal e contextual, vencido rejeitado, "não"/outro assunto cancelam, clique só no id
certo e uma vez, sim de uso único e execução delegada com a conversa respondendo enquanto a
tarefa roda.

## Não verificado

Jev real com estas perguntas (limiares sem corpus); latência por ferramenta (~0,5 s com o Jev de
nuvem, medido no endereçamento); a janela de verdade com o "sim" falado.
