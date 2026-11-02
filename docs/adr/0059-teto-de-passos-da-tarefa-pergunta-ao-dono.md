# ADR-0059 — A tarefa tem 50 passos por bloco e, no teto, pergunta ao dono se continua

**Data:** 2026-11-01 · **Estado:** aceita (implementada e testada sem microfone; o uso real é do dono) · **Decide:** dono (o teto, as respostas possíveis, o que acontece sem resposta), arquiteto (onde a pergunta mora, o prazo do bloco)
**Pedido:** dono, 2026-11-01 — os subagentes da tarefa delegada têm no máximo ~11-12 passos, e depurar já consome isso: 50 passos e, ao chegar neles sem terminar, perguntar se continua por mais 50 ou até terminar; sem resposta ou com um «não», encerrar com o resumo do que foi feito. Emenda a ADR-0038 (o teto da tarefa) e a ADR-0054 (`max_turnos`).

## Contexto

Três coisas seguravam a tarefa, e só a primeira estava no pedido:

1. **`laco_max_passos = 12`**, que a tarefa herda do turno, menos os passos que o turno já deu.
2. **O prazo do turno (`laco_prazo_s`, 90 s) valia para a tarefa inteira.** Cinquenta passos, cada um com uma rodada do motor, não cabem em 90 s: só subir o teto de passos não mudaria nada, porque a tarefa morreria antes por tempo.
3. **O arquivo do dono grava o padrão.** O `escrever` põe todas as chaves no `jarvis-voz.toml`, então `laco_max_passos = 12` estava lá sem ter sido escolhido, e mudar o padrão no código não chegaria a ele.

## Decisão

1. **Bloco de 50 passos** (`laco_max_passos`, de 1 a 200) e **tempo próprio do bloco** (`tarefa_prazo_s`, padrão 900 s, de 30 a 7200). O `laco_prazo_s` volta a ser só do turno. O motor `agente` usa o mesmo bloco (antes, 6 passos).
2. **No teto, de passos ou de tempo, a tarefa pergunta** (`GestorDeTarefas._no_teto`). Ela pergunta com o próximo passo já proposto: a tarefa que acabaria ali não pergunta nada. O prazo de uma ação de um passo e o do foco de um app continuam sendo o fim deles.
3. **A pergunta é a pendência de sempre** (ADR-0048): uma por vez, por id, dita pela fila de avisos e mostrada na faixa, com a conversa livre. Ela não roda nada: `tarefa.continuar` não está no catálogo, e o «sim» só acorda a tarefa. Dura 120 s (o padrão de 30 s é o de uma ação na hora; tarefa longa roda com o dono longe). Se outra pergunta estiver aberta, esta espera a vez dentro desse prazo.
4. **As respostas:**

   | o dono | a tarefa |
   |---|---|
   | «sim», «continua», «mais 50», o clique em sim | mais um bloco de passos e de tempo; depois pergunta de novo |
   | «até terminar», «vai até o fim» | segue sem perguntar mais, sem teto de passos nem de tempo |
   | «não», o clique em não, outro assunto, 120 s sem resposta | acaba com o resumo |

   A leitura é do código (`jarvis.s2.portao.ler_continuacao`): fala com negação nunca escolhe nada, e «mais 10» não vira «mais 50».
5. **O resumo** vem de uma rodada do motor sem ferramentas (`MotorDoObjetivo.resumir_no_teto`), com o filtro de etapas internas de sempre. Se o motor cair ou pedir outra ferramenta, o código conta os passos. O estado é `falhou`: o objetivo ficou sem cumprir, e a resposta diz «Parei sem terminar».
6. **O eco.** A pergunta diz as opções e o dono as repete, mas a ADR-0048 descarta como eco o que só repete a pergunta. Por isso «até terminar» e «mais 50» só valem depois de a pergunta tocar inteira (`espera.ouvida`); enquanto ela toca, são eco. A frase acaba na razão, e não nas opções, para o fim da fala não voltar pelo microfone como resposta. E a razão não diz «não» (a primeira versão dizia «ainda não acabei», e o «não» do dono virava eco); com a pergunta já ouvida, «sim» e «não» também valem antes do filtro de eco, porque a descrição da tarefa pode trazer essas palavras. O «sim» segue cobrando os sinais fortes da ADR-0043, e «até terminar» também é um «sim».
7. **O arquivo antigo**: `laco_max_passos = 12` sem a chave `tarefa_prazo_s` é o padrão gravado, e lê como 50. Regravado, o 12 passa a ser escolha do dono e fica.
8. **`delegar.claude_code`**: `max_turnos` padrão 50 e prazo padrão 600 s (o teto do manifesto; com 300 s, os 50 turnos não caberiam).

## Alternativas descartadas

- **Só subir o número**: o prazo de 90 s mataria a tarefa antes, e tirar o teto deixaria o gasto sem nenhuma pergunta ao dono.
- **Perguntar só no teto de passos**: um passo pode levar minutos (uma delegação leva até 600 s), e a tarefa morreria por tempo sem resumo.
- **Terceiro botão «até terminar» na faixa**: a faixa é a mesma de todas as confirmações, com sim e não. Fica dito ou digitado, e o texto da faixa explica.

## Consequências

- `tests/unit/tarefas/test_gestor.py`, `tests/unit/s2/test_teto_da_tarefa.py` e `tests/unit/voz/test_resposta_ao_teto.py`, sem áudio.
- **«Até terminar» não tem teto nenhum, por pedido do dono.** Um modelo em laço de passos que dão certo gasta até o dono mandar parar: o que segura é o «parar» do card, `tarefa.cancelar`, o fim da sessão e o orçamento de falhas da tarefa. Cada bloco a mais também consome o limite da conta do dono.
- Falar de outro assunto com a pergunta aberta encerra a tarefa com o resumo, como em toda pendência (ADR-0048).

## O que não foi provado

A pergunta tocando na voz real e o «até terminar» dito por cima do eco real da caixa de som; 900 s como tempo de bloco no uso real. `--max-turns` do Claude Code delegado não vira pergunta: o processo roda sem sessão salva e não dá para retomar. Ao esgotar os turnos, volta como um passo que falhou (`error_max_turns`) e o motor da tarefa decide, dentro de `delegacoes_por_objetivo`.

## Como invalidar esta decisão

Se a trilha mostrar `permissao` de `tarefa.continuar` com resposta «sim» sem o dono ter dito (o eco das opções), a opção «até terminar» sai da fala e fica só na tela. Se os blocos de 900 s acabarem antes dos 50 passos com frequência, o tempo do bloco sobe.
