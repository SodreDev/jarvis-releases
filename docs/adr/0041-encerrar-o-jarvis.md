# ADR-0041 — Encerrar o Jarvis a pedido: a tool `jarvis.encerrar`, limpo, e o sim só com algo no ar

**Data:** 2026-10-21 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o tier e quando perguntar), arquiteto (o caminho do fim)
**Pedido:** dono, 2026-10-21 — "TOOL PARA ENCERRAR O JARVIS: quando o dono pedir ("encerra o sistema", "pode fechar o Jarvis", "desligar o Jarvis" etc.), o modelo chama uma tool própria que encerra o Jarvis LIMPO (cancela tarefas, solta mouse/teclado virtual, fecha janela e extensão-host, salva conversa). Não é desligar o PC. Tier moderado (pede o "sim" só se houver tarefa em andamento/pendência)." Emenda a ADR-0028 (uma tool nova do laço), a ADR-0035 (um caso novo na tabela do roteador) e a ADR-0003 (o PDP ganha o "sim" pedido pelo alvo que o executor resolveu).

## Contexto

1. Para fechar o Jarvis o dono tinha de ir à janela; dito por voz, o modelo não tinha ferramenta e, no máximo, tentaria `window.close_app` na própria janela — que mata a conversa no meio de um turno, sem soltar nada.
2. Fechar a janela não soltava o mouse e o teclado virtuais (o `Interruptor` da ADR-0027) nem as abas que o Jarvis controla (a faixa «Jarvis no controle» ficaria até o prazo), e a conversa (`ConversaPersistente`) não era fechada: a indexação em curso podia ser cortada.
3. O host do navegador é do navegador (decisão do dono de 2026-10-19): o Jarvis é cliente da ponte; "fechar o host" é o Jarvis soltar as abas e desconectar, não matar o processo que o navegador lançou.
4. A tier do controle por voz (ADR-0028, emenda de 2026-10-18) é estática por manifesto; "pedir o sim só se houver tarefa" depende de **agora**.

## Decisão

**Uma tool `jarvis.encerrar`, moderada, que só pede o fim: o laço termina o turno (a despedida toca), sai pelo caminho de sempre e solta o resto; a janela fecha; e o sim vem do código, quando há tarefa em andamento ou pergunta esperando o dono.**

1. **O manifesto** (`catalogo/jarvis.encerrar.yaml`): sem argumentos, tier **moderado** (`confirmation: never`), aviso falado «Encerrando o Jarvis. Até mais.», efeito passageiro. A descrição diz o que ela não faz: não desliga nem reinicia o computador, não fecha outro programa. Só existe para o modelo quando há um laço que possa ser encerrado (`ExecutorDeFerramentas.encerramento`).
2. **O sim pelo alvo** (`Pedido.exige_o_sim`, novo, do código — o modelo não alcança, como `contaminado`): o executor pergunta ao aplicativo o que está no ar (`Encerramento.pendente`): uma tarefa do dono rodando ("a tarefa «…» ainda está rodando e vai ser cancelada") ou uma pergunta esperando a resposta dele. Com isso o PDP **confirma**; só o "sim" do dono solta. Acompanhar o foco de um app (ADR-0037) não conta: parar isso não perde nada. A pergunta falada diz o porquê (`Confirmacao.razao_falada` → `pergunta_falada`), e vale a regra de sempre do "sim" falado (ADR-0038).
3. **Não vira tarefa**: `jarvis.` entra em `FORA_DA_ALLOWLIST` — roda no turno em que o dono pediu (uma tarefa em segundo plano não desliga o assistente) e tarefa nenhuma a chama.
4. **O corpo só pede** (`Encerramento.pedir`): marca o fim e devolve quantas tarefas serão canceladas. O laço (`rodar_audio`, `rodar_texto`) acaba o turno — a despedida toca — e sai no topo da volta seguinte; no `finally` de sempre (tarefas e pendências canceladas, microfone e alto-falante fechados, o motor de voz solto) entra `_encerrar_limpo`: as abas soltas (`parar_navegador`, o PARAR), o mouse e o teclado virtuais soltos (`Interruptor.parar`), a indexação da conversa adiantada, `Aplicativo.encerrado`. A janela (`SessaoDeVoz.ao_encerrar` → `Ponte.encerramentoPedido` → `QGuiApplication.quit`) fecha, e o `main` fecha a conversa (`ConversaPersistente.fechar`, que espera a indexação). A conversa já estava no livro turno a turno.
5. **O roteador** (ADR-0035): "encerra o sistema", "pode fechar o Jarvis", "desliga o Jarvis", "se desliga" → método `sistema`, motivo `encerra_o_jarvis`, com `window.close_app` e a entrada virtual de fora no turno. O Jarvis (ou "o sistema", como o dono o chama) tem de ser o objeto do verbo: "desliga o computador", "termina o que você estava fazendo" e "fecha o Discord, Jarvis" não são encerrar.
6. **Persona v13:** "Encerrar você mesmo: jarvis.encerrar, e só uma despedida curta — não é desligar o computador, que você não faz."

## Alternativas descartadas

- **Fechar a própria janela com `window.close_app`:** mata a conversa no meio do turno, não solta nada, e a ferramenta pergunta sempre (é perigosa).
- **Encerrar dentro do corpo da tool:** o turno morreria antes de a despedida tocar, e o laço sairia por exceção, pulando o fim de sempre.
- **Perguntar sempre:** o dono pediu o sim só com algo no ar; encerrar sem nada rodando se desfaz abrindo o Jarvis de novo.
- **Tier perigoso com a exceção no PDP:** o tier é o que o validador confere contra o manifesto; o "sim" que depende do agora é do alvo, e mora no pedido.
- **Uma tool de desligar o computador junto:** o dono foi explícito — não é desligar o PC.

## Consequências

- O caso do dono: "pode fechar o Jarvis" → «Encerrando o Jarvis. Até mais.» e a janela fecha; com uma tarefa rodando, ele pergunta antes, dizendo qual.
- `Pedido.exige_o_sim` serve também ao fechar e encerrar apps (ADR-0042).
- **Risco aceito:** o roteador é por palavras; "encerra o sistema" quer dizer o Jarvis (é como o dono o chama), e "desliga o sistema operacional" não. Um pedido de encerrar dito de outro jeito cai em `conversa` e o modelo escolhe — a descrição da tool diz que não é desligar o PC.
- **Não provado:** o Qt de verdade fechando pela ponte (o teste da sessão usa o `ao_encerrar` e o modo texto); o `claude -p` real chamando a tool; a extensão de verdade soltando as abas no fim (testada no PARAR, ADR-0027).
- Testes: `tests/unit/voz/test_encerrar_o_jarvis.py` (o roteador; a tool sem nada no ar e com tarefa rodando; o foco que não pede o sim; tarefa que não encerra; o laço que despede e sai limpo; a janela avisada; parar a conversa não é encerrar; a porta que sobrevive à troca de acesso) e `tests/unit/politica/test_tiers.py` (o tier e o `exige_o_sim`).

## Como invalidar esta decisão

O dono pedir para o Jarvis também desligar o computador, ou perguntar sempre antes de encerrar; ou a trilha mostrar `encerra_o_jarvis` em pedidos que não eram de encerrar.
