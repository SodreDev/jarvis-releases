# ADR-0046 — Uma resposta por pedido, e o sim só no que é arriscado: a tabela de permissões de abrir, fechar e encerrar

**Data:** 2026-10-25 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que pede o sim, quantas vezes o Jarvis fala), arquiteto (onde a regra mora, o que vira tarefa)
**Pedido:** dono, 2026-10-25, depois de testar a versão da ADR-0045 — "o Jarvis responde duas vezes: diz que vai fazer, faz, e fala de novo que fez"; "«fecha meu Brave» pede permissão, «fecha o navegador» não sabe qual, e encerrar qualquer editor pergunta mesmo sem nada a perder"; "pedi «abre um vídeo no YouTube» com o navegador fechado e ele mandou eu abrir". Emenda a ADR-0038 (o que vira tarefa), a ADR-0042 (quem pede o sim para fechar e encerrar) e a ADR-0036 emendada (o navegador fechado). Commits `b0a2774` (A), `233d486` (B), `fd6639d` (B3), `8ee2cd4`.

## Contexto

A trilha do dono (24/10, só metadados):

1. **Todo pedido com ferramenta virava tarefa** (ADR-0038): «Certo, já cuido disso.» no turno, o passo, e no fim a conclusão da tarefa falava de novo — duas ou três frases para "abre o Discord". Depois de uma ferramenta, a frase do motor que só repetia o já dito também ia à voz.
2. **A pergunta de uma tarefa cortada virava «não»** e a tarefa propunha a mesma ação de novo: três `apps.quit` com `confirmacao_do_pdp` → «não» em 11 s (a causa da voz é da ADR-0048; a reproposta é desta).
3. **O sim estava em tudo o que fecha**: a ordem explícita do dono ("fecha o Brave") perguntava como se o modelo tivesse decidido sozinho; "o navegador", sem nome, era ambíguo mesmo com um só aberto; app instalado fora da lista liberada era negado sem pergunta.
4. **Navegador fechado**: só o caminho rápido sabia cair no `sites.open`; a proposta do motor e a tarefa ouviam o erro da extensão e devolviam ao dono.

## Decisão

1. **A primeira ferramenta roda no turno.** Vira tarefa só o trabalho longo: mais de `passos_no_turno` (2) ferramentas, ou o laço acima de `segundos_no_turno` (12 s). O objetivo que precisa conferir (navegador, entrada virtual) passa à tarefa logo depois do primeiro passo, que cobra a leitura antes de deixar dizer «abri».
2. **A ação de um passo diz o resultado uma vez**, na frase do código (a do caminho rápido), e o pedido acaba ali, sem outra rodada do motor. Depois de uma ferramenta, a frase do motor que só repete o já dito vai à tela, não à voz (`jarvis.s2.entrega`; a trilha conta em `frases_caladas`).
3. **O fim de uma tarefa é entregue uma vez por id** e só fala o que traz algo novo (o já dito do turno e os avisos dela contam); cancelada ou recusada pelo dono, acaba calada. Evento `entrega` na trilha (falada ou silenciosa, e o porquê — nunca o texto).
4. **A tarefa cujo pedido o dono não confirmou acaba ali**: nunca repropõe a mesma ação; só fala do prazo vencido. O «sim» falado a uma ação rápida roda no turno (o dono ouve o resultado numa frase); a demorada e a do clique seguem para a tarefa. Acompanhar o foco de um app não ocupa o teto de tarefas.
5. **A tabela do sim** (código, não modelo — `jarvis.executor.fechar`, `jarvis.politica.abertura`):

   | ação | vai sem o sim | pede o sim | negado |
   |---|---|---|---|
   | fechar a janela (`window.close`) | ordem explícita: o pedido cita o app, «navegador», «essa janela» — também o navegador | alvo que o pedido não citou (o modelo decidiu, um texto lido sugeriu) | — |
   | encerrar o app (`apps.quit`) | a pedido: navegador, várias instâncias, programa do sistema, editor sem nada a perder | trabalho não salvo **detectado** (marca no título: `*`, `●`, `[modificado]`; LibreOffice com documento aberto), jogo aberto, app fora da lista liberada, alvo não citado | PID 1, compositor e sessão do desktop, o próprio Jarvis e o terminal dele, processo de outro usuário |
   | abrir app (`apps.launch`) | da lista liberada | instalado e fora da lista (o lançamento confirmado o acha no catálogo do sistema) | não instalado (com a sugestão) |

   As frases do motivo não trazem «sim», «pode» nem «não» (o eco delas não pode responder, ADR-0048).
6. **«O navegador» sem nome** é o que está em foco; senão o único aberto; senão o único na frente de um monitor; dois igualmente plausíveis é pergunta. «Meu Brave» é o Brave (posse e artigo saem).
7. **Navegador fechado, o Jarvis o abre e segue** — no turno, no caminho rápido e na tarefa: a navegação com endereço vai pelo `sites.open` (abre o navegador do dono já na página); o passo sem endereço abre o navegador (`browser.launch`), espera a extensão conectar (até 12 s, pela ponte) e tenta de novo, uma vez. Tudo pelo PDP, Jev e pergunta de sempre; só a abertura do navegador vai sem o filtro do método do pedido (ADR-0035), que tiraria o `browser.launch` num pedido de site — ali quem decide é o código. Sem navegador configurado, o erro volta ao motor.

## Alternativas descartadas

- **Pedir ao modelo para "não repetir"** (persona): o modelo não sabe o que a frase do código já disse nem o que a tarefa vai entregar; o filtro tem de ser de quem sabe — o código.
- **Sim em todo `apps.quit`** (como antes): ensina o dono a dizer sim sem ler. O sim fica para o que tem algo a perder, e a trava para o que nunca se encerra.
- **Detectar trabalho não salvo perguntando ao app** (D-Bus, AT-SPI): cada app fala de um jeito, e a marca no título cobre os editores do dono; o que não marca (LibreOffice) é tratado como arriscado com documento aberto.

## Consequências

- "Abre o Discord" é uma frase; "fecha o Brave" fecha sem perguntar; "fecha o VS Code" com `●` no título pergunta.
- A ADR-0038 continua valendo para o trabalho longo; o limite que a separa do turno é número de passos e tempo, ambos no `Cerebro`.
- Os testes: `tests/unit/s2/test_tarefa_do_pedido.py`, `tests/unit/s2/test_entrega.py`, `tests/unit/executor/test_fechar_e_encerrar.py`, `tests/unit/gui/test_janela_abrir_apps.py`.

## O que não foi provado

O dono ouvindo "uma resposta só" em todos os tipos de pedido; a marca de não salvo em cada editor que ele usa (só os de título padrão foram testados); o tempo da extensão para conectar num navegador frio na máquina dele (12 s é o teto, não a medida).

## Como invalidar esta decisão

Se a trilha mostrar `entrega` silenciosa onde o dono esperava ouvir (perdeu um resultado), ou um `apps.quit` sem sim que perdeu trabalho, a tabela volta a perguntar naquele caso — a linha da tabela muda, não a regra inteira.
