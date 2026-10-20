# ADR-0035 — Roteador de método: o caminho mais direto para aquele pedido

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono, Lote C) · **Decide:** dono (os casos), arquiteto (a tabela e onde ela age)
**Pedido:** dono, 2026-10-20 — "ESCOLHA DO MÉTODO DE EXECUÇÃO: ao executar um pedido, o Jarvis escolhe o método mais eficiente para AQUELE contexto, com base nas ferramentas que tem e no que foi pedido (ex.: pedido sobre navegador/site vai direto à extensão, sem passar por app/atalho/terminal; pedido de app local vai pelo resolvedor/foco; shell vai a subagente). Roteador explícito, testável, com tabela de casos e log de qual método foi escolhido e por quê (só metadados)." Complementa a ADR-0028 (laço) e a ADR-0030 (objetivo do turno).

## Contexto

O modelo escolhia o caminho sozinho e às vezes o mais longo: abrir o navegador como app e digitar a URL com o teclado virtual, quando a extensão abre a página direto; ou digitar um comando num terminal pelo teclado, quando o Jarvis não tem shell e o trabalho é de uma tarefa (ADR-0028, "sem canivete suíço").

## Decisão

1. **O roteador é do código** (`jarvis.politica.metodo.escolher_metodo`): lê a fala do dono e o que está ligado nesta sessão (`ContextoDoMetodo`: controle do navegador, mouse e teclado virtuais, apps autorizados) e devolve a `Escolha` — método, motivo (código curto e estável) e as ferramentas que ficam **de fora** do turno.
2. **A tabela de casos** (o teste `tests/unit/politica/test_metodo.py` é a tabela):

   | O pedido | Método | Motivo | De fora no turno |
   |---|---|---|---|
   | cita site, domínio ou "pesquisa na web", com a extensão ligada | `navegador` | `cita_site` | abrir o navegador como app, mouse e teclado virtuais |
   | idem, sem a extensão | `web` | `cita_site_sem_extensao` | mouse e teclado virtuais |
   | WhatsApp ou Instagram, com extensão e entrada virtual | `entrada_virtual` | `site_sem_automacao` | nada (ADR-0027: ali vale o teclado e o mouse) |
   | "abre o navegador" (sem site) | `app` | `abre_o_navegador` | mouse e teclado virtuais |
   | cita um app autorizado | `app` | `cita_app` | mouse e teclado virtuais |
   | terminal, comando, script, arquivos do sistema | `subagente` | `pede_terminal` | abrir app (inclusive terminal), mouse e teclado virtuais |
   | volume, brilho, música, hora, bateria, lembrete | `sistema` | `pede_sistema` | mouse e teclado virtuais |
   | "anota", "o que eu disse" | `memoria` | `pede_memoria` | nada |
   | o dono pede teclado ou mouse pelo nome ("aperta ctrl+L") | `entrada_virtual` | `pede_teclado_ou_mouse` | nada |
   | cai em mais de um método | `conversa` | `pedido_misto` | **nada** |
   | nenhum dos casos | `conversa` | `sem_metodo_especifico` | nada |

3. **Onde age.** `ExecutorDeFerramentas.novo_turno` escolhe o método com a fala do dono; a chamada **do turno** a uma ferramenta de fora volta negada com o caminho certo ("este pedido vai pelo método navegador (cita_site): apps.launch fica de fora neste turno — use a extensão…"). A tarefa em segundo plano, que traz a contaminação dela, não segue o método do pedido de agora. O cérebro põe a nota no prompt do turno ("Método deste pedido: …").
4. **Trilha:** o evento `metodo` com método, motivo e quantas ferramentas ficaram de fora — nunca a fala.

## Alternativas descartadas

- **Deixar o modelo escolher com uma instrução na persona:** era o que havia; a tabela torna a escolha testável e a recusa diz o caminho.
- **Um classificador (Jev) para o método:** o pedido é do dono e as regras são poucas e estáveis; o classificador é para decisões de contexto (ADR-0029), não para uma tabela.
- **Restringir também o pedido misto:** bloquearia metade de um pedido legítimo ("abre o Spotify e pesquisa no Google").

## Consequências

- O caso do dono: "abre o canal do Primo Rico no YouTube" não abre o navegador como app nem digita a URL; vai pela extensão.
- **Risco aceito:** a tabela é por palavras; um pedido descrito de um jeito que ela não reconhece cai em `conversa` e não restringe nada (o comportamento de antes).
- Testes: `tests/unit/politica/test_metodo.py` (a tabela, o que cada método deixa de fora, a recusa só no turno, a nota no prompt, a trilha só com metadados).
