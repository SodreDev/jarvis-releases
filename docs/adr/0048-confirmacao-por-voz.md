# ADR-0048 — A confirmação se responde pela voz: «Jarvis, sim» por cima da pergunta confirma uma vez, e o eco dela não responde

**Data:** 2026-10-25 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que vale como resposta, o que só o clique responde), arquiteto (quem lê a resposta, o que a vigia faz com ela)
**Pedido:** dono, 2026-10-25 — "eu disse «Jarvis, sim» e ele perguntou de novo, três vezes". Emenda a ADR-0027 (a confirmação sem o portão), a ADR-0038 (a pergunta de tarefa cortada), a ADR-0040 (a vigia corta pela resposta) e a ADR-0043 (o «sim» por cima cobra os sinais fortes). Commit `a84a004`.

## Contexto

A trilha do dono (24/10, só metadados): ele roda `escuta = "palavra"` e `enderecamento = ""` — **sem o portão Jev** (ADR-0029). Sem o portão nada interpretava a fala, e toda confirmação era só clique (`_confirmar` bloqueante, `Espera.so_clique`). O dono respondeu «Jarvis, sim» por cima da pergunta; a vigia cortou pela palavra de ativação (ADR-0040); a pergunta cortada contava como não ouvida, e não ouvida é «não» (ADR-0038); a tarefa propôs `apps.quit` de novo — três vezes em 11 s. E, sem a palavra, o «sim» dito depois da pergunta era descartado no modo palavra; o eco da própria pergunta («…Posso?») podia virar "outro assunto" e cancelá-la.

## Decisão

1. **A pergunta de confirmação vira pendência também sem o portão** (`FluxoDeAcao(portao=None)`, `Cerebro.pendencia_sem_portao`, que o app liga): o turno acaba em «Posso {ação}? {Razão}.» (`Confirmacao.pergunta_falada` — sem «sim» na frase: ela passa pelo alto-falante e volta pelo microfone), e a resposta vale falada — com ou sem a palavra de ativação, por cima da pergunta ou depois dela — ou no clique. Sem o Jev, a fala é lida só pelo literal curto do código (`jarvis.s2.portao.resposta_literal`); com ele, como antes.
2. **A leitura da resposta** (`jarvis.voz.resposta.ler_resposta`): tira a palavra de ativação do começo; tira o começo que é eco da pergunta (duas palavras ou mais seguidas que estão nela); o que sobra é `sim`, `nao` (o literal, que pode vir seguido só de palavras da própria pergunta: «pode apagar» a «Posso apagar de vez?» — e nenhuma outra ação), `eco` (só palavras da pergunta: ignora, não cancela; `MotivoDoRuido.ECO_DA_PERGUNTA` na trilha) ou `outra` (outro pedido: o fluxo de sempre). Não autoriza nada sozinha: o «sim» ainda passa pelo cérebro, contra a pendência válida.
3. **A vigia corta limpo pela resposta** (`Motivo.RESPOSTA_A_PERGUNTA`, nos dois modos): com a pergunta no ar, «sim»/«não» por cima cortam, a pendência é marcada **ouvida** (`marcar_ouvida_a_aberta`) e não cai como «não»; o trecho vira o turno da resposta. O eco da pergunta não corta. Na confirmação que só o clique responde (o que está sob o clique, ADR-0027), o «sim» falado **não corta** (`Motivo.SO_NA_TELA`) — cortar derrubaria a pergunta — e a tela diz para tocar em sim ou não.
4. **O «sim» cobra os sinais fortes do ASR** (ADR-0043), agora também o de «Jarvis, sim»: o pior caso é o ruído confirmando ação perigosa.
5. **Uma vez**: o clique e o «sim» depois do turno levam a proveniência do turno do pedido (a memória confirmada é apagada — antes o PDP a negava fora do turno) e a frase do feito é a resposta; a tarefa cuja pergunta foi respondida não repropõe (ADR-0046).

## Alternativas descartadas

- **Exigir o Jev para confirmar por voz**: o dono roda sem ele; a confirmação ficaria só no clique, e é exatamente o que ele não quer.
- **Não cortar com pergunta no ar** (deixar a pergunta terminar): o dono que já sabe a resposta espera o Jarvis acabar de falar — e o «sim» dito por cima se perdia do mesmo jeito.
- **Aceitar «sim» com qualquer sinal**: um «sim» inventado pelo ASR na respiração confirmaria `apps.quit`; a ADR-0043 mediu que o texto inventado tem sinais fracos.

## Consequências

- `tests/unit/voz/test_confirmacao_por_voz.py`: áudio sintético, sim/pode/não/cancela, por cima e depois, palavra e contínua, e o eco da pergunta — uma chamada ao motor em todos.
- Três testes da GUI mudaram: o turno agora acaba em «Posso …?» e o clique resolve pela pendência.

## O que não foi provado

A voz do dono respondendo por cima da caixa de som dele (o eco real da pergunta); os sinais da Groq num «sim» curto por cima do eco (limiares da ADR-0043 medidos no whisper local); literais além dos de `resposta_literal` («pode encerrar», «melhor não») — ficaram como `outra`, que não confirma.

## Como invalidar esta decisão

Se a trilha mostrar `permissao` com resposta «sim» sem o dono ter dito (o eco ou o ruído confirmando), a leitura volta a exigir a palavra de ativação no «sim» por cima; se mostrar `resposta_a_pergunta` seguida do mesmo `ferramenta.inicio` de novo, o "uma vez" quebrou.

## Emenda de 2026-10-29 — o «sim» dito do jeito natural, e a pergunta de tarefa respondida por voz (ADR-0057)

A resposta deixa de depender do literal curto quando o Jev está desligado: `resposta_literal` lê a fala
natural sem rede («sim, pode seguir», «vai em frente», «melhor não»), a mesma no laço de voz (onde o
«sim» ainda cobra os sinais fortes da ADR-0043) e no cérebro; o ambíguo («não, pode seguir») não
autoriza. A pergunta por ação de uma tarefa (o que está sob o clique) deixa de ser só do clique: é
dita em voz e respondida por voz ou pelo clique. Detalhes, a tabela e os testes na ADR-0057.
