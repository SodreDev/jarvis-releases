# ADR-0062 — A tarefa que repete passos sem avançar é avisada e, se insistir, para

**Data:** 2026-11-12 · **Estado:** aceita (implementada e testada com motores falsos; o laço real é do uso do dono) · **Decide:** arquiteto (o que é laço, onde a guarda mora); dono (a tarefa para sozinha quando insiste no laço, sem perguntar)
**Pedido:** backlog do núcleo, item B3 (`docs/estudos/openjarvis-nucleo.md` §8), autorizado pelo dono em 2026-11-12. Emenda a ADR-0059.

## Contexto

- A tarefa que planeja passos (a de um pedido, ADR-0038, e a do motor `agente`) só parava no teto de 50 passos e de 900 s (ADR-0059). Com «até terminar», nem isso: o que segurava era o «parar» do dono.
- A `recuperacao` (`src/jarvis/s2/recuperacao.py`) já recusa repetir a ação idêntica que **falhou**. A ação que **dá certo** e não muda nada (reler a mesma página, ir e voltar entre duas abas) passava.
- O `LoopGuard` do OpenJarvis (`OJ/agents/loop_guard.py:60-232`, commit 13706f2) compara só o nome da ferramenta na oscilação. Aqui isso daria falso positivo: rolar e ler, rolar e ler é o jeito certo de ler uma página longa.

## Decisão

1. **Um passo é a ação e o que ela devolveu**: ferramenta, argumentos, status, dados e motivo, num hash curto (`jarvis.tarefas.laco.marca_do_passo`). Só a marca fica na memória da guarda.
2. **É laço** (`GuardaDeLaco`):
   - a mesma marca 3 vezes seguidas (A A A);
   - um ciclo de período 2 ou 3 repetido inteiro (A B A B, A B C A B C);
   - 6 passos seguidos sem nada novo, cada um com uma marca que a tarefa já tinha visto (o ciclo mais longo). Um passo novo zera a conta.
3. **Primeira vez, aviso.** A nota vai ao motor no próximo passo (`Tarefa.nota_de_laco`, lida e apagada pelo motor): «mude de caminho, ou termine dizendo o que ficou feito». A linha vai à tela, nunca à voz.
4. **Depois do aviso, parada.** Se o laço volta, a tarefa acaba pelo mesmo caminho do «não» no teto (ADR-0059 §5): uma rodada sem ferramentas resume o que foi feito, o estado é `falhou`, e a frase começa com «Parei sem terminar: eu estava repetindo os mesmos passos sem avançar.». Não há pergunta ao dono: o «sim» só daria mais do mesmo.
5. **A guarda vive a tarefa inteira.** «Mais 50» e «até terminar» não a zeram. No «até terminar», ela é o único freio automático.
6. **Trilha:** o evento `tarefa.laco` leva `tool_id` (a última ferramenta do laço), `categoria` (`identica`, `ciclo`, `sem_novidade`), `decisao` (`aviso`, `parada`), `periodo` e `passo`. Nunca argumento nem resultado.
7. **Onde vale:** só na tarefa que planeja passos (`de_objetivo` ou motor `agente`). O passo recusado por estar fora da allowlist também conta.

## Alternativas descartadas

- **Comparar só o nome da ferramenta, como o OpenJarvis:** pararia a leitura de página longa.
- **Perguntar ao dono no laço, como no teto:** o laço não é falta de passos, e o «sim» repetiria o laço. O dono ainda pode pedir de novo de outro jeito.
- **Parar já na primeira detecção:** o modelo às vezes relê por um motivo (esperar a página carregar). O aviso dá uma chance de mudar de caminho.
- **Guarda também no laço do turno:** o turno tem prazo de 90 s (ADR-0059 §1), o que já limita o laço. Fica para quando a trilha mostrar o caso.

## Consequências

- Resultados com relógio ou id novo a cada chamada nunca repetem a marca: esse laço continua só sob o teto. É o preço de não ter falso positivo.
- Os testes do teto que usavam uma ação repetida (`system.clock.now`) criam o gestor sem a guarda (`guarda_de_laco=None`): eles testam o teto, não o laço.
- Testes: `tests/unit/tarefas/test_laco.py` e os do gestor e da tarefa do pedido, só com motores falsos.
- Código: ideia do `LoopGuard` do OpenJarvis (Apache-2.0), sem trecho copiado.

## Como invalidar esta decisão

Se a trilha mostrar `tarefa.laco` com `decisao=parada` numa tarefa que o dono diz que estava avançando, a regra que disparou (`categoria`) sobe o limiar ou sai. Se tarefas em «até terminar» rodarem mais de 200 passos sem nenhum `tarefa.laco`, olhar se o laço escapou pela marca (resultado com relógio).
