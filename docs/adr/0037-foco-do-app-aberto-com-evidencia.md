# ADR-0037 — Ao abrir um app, o foco vai para a janela dele, só com evidência

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono, Lote C) · **Decide:** dono (o prazo, a conta do Steam, a dúvida), arquiteto (a evidência e a porta de janelas)
**Pedido:** dono, 2026-10-20 — "FOCO DE JANELAS DO PC: ao abrir um app, o Jarvis verifica se o foco virou o app; se não, coloca o app em foco. Com tratamento de apps LENTOS (ex.: jogo via Steam: Steam abre, pode pedir escolha de conta — quem escolhe é o dono —, o jogo demora, a janela do jogo aparece sozinha depois). Desenho pedido: acompanhar com ping/intervalo escolhido pelo Jarvis (revive a tarefa, sem bloquear a conversa), a cada ciclo listar as janelas existentes distinguindo as em PRIMEIRO plano e as em SEGUNDO plano, para ver se a janela do jogo abriu; se abriu, focar. TRATAMENTO DE AMBIGUIDADE: janela com nome genérico que pode ou não ser o app NÃO é focada por palpite — só foca com evidência (PID/classe/app_id/executável ligados ao processo lançado, título bate com o catálogo, janela nova surgida depois do lançamento); na dúvida, pergunta ao dono ou espera. Prazo máximo configurável e mensagem honesta se não achou." Emenda a ADR-0022 (a tarefa ganha prazo e aviso escolhidos pelo código) e usa o critério de ambiente da ADR-0027 (entrada virtual: `kdotool` no Wayland do KDE).

## Contexto

`apps.launch` devolvia o PID e acabava: se o gerenciador de janelas não desse o foco ao app (o KWin segura o foco contra janela que aparece sozinha), o dono ficava na janela antiga; app lento (o Steam, o jogo) abria a janela minutos depois, sem ninguém olhando. `window.focus_app` e `window.list` só usavam o `wmctrl`, que no Wayland vê apenas as janelas X11/XWayland. E "a janela mais nova" não é evidência: pode ser uma notificação, o Steam, ou outro app com o mesmo nome no título.

## Decisão

1. **A porta de janelas** (`jarvis.executor.janelas.Janelas`): `listar` (cada janela com id, título, classe, PID e se está em primeiro plano) e `ativar`. No KDE, `kdotool`: **uma chamada por ciclo**, encadeada (`search --class .` põe todas na pilha; `getwindowid`, `getwindowname`, `getwindowclassname` e `getwindowpid` com `%@` imprimem um bloco cada; `getactivewindow` no fim), e, se um título com quebra de linha desalinhar os blocos, uma chamada por janela. No X11, `wmctrl -lxp` e `xprop -root _NET_ACTIVE_WINDOW`. O ambiente escolhe como na entrada virtual (`jarvis.entrada.foco`): no Wayland só o `kdotool` (KDE) vê as janelas dos outros; sem ele, não há porta — e tudo fica como antes. Os ids são conferidos (`0x…` do X11, `{uuid}` do KWin) antes de chegar ao programa.
2. **Acompanhar, sem prender a conversa.** `apps.launch` guarda as janelas de antes, lança o app e devolve na hora, com `foco: acompanhando` e o id da tarefa; uma **tarefa** (ADR-0022) com o `MotorDeFoco` acorda em intervalos que crescem (1, 2, 3, 5 e 8 segundos, depois a cada 10), lista as janelas e, quando a do app aparece com evidência, **propõe** `window.focus_app` com o id — quem executa é o executor, pelo PDP, como qualquer chamada. O motor e o prazo são do código; o modelo não os escolhe. Só o que a conversa abriu é acompanhado (tarefa não cria tarefa); sem porta ou sem gestor de tarefas, nada muda.
3. **A evidência, em pontos** (forte = 3 ou mais; o empate entre fortes é dúvida):

   | Sinal | Pontos | Por quê |
   |---|---|---|
   | PID: a janela é do processo lançado ou de um descendente dele | 3 | ligado ao que foi lançado |
   | Jogo do Steam: classe `steam_app_<id>` ou o processo descende do `reaper` do Steam com `AppId=<id>` | 3 | o id que veio no `steam://rungameid/<id>` |
   | Classe da janela (`WM_CLASS`, `app_id`) = `StartupWMClass`, id do `.desktop` ou executável | 2 | o app se diz ele |
   | Executável do processo da janela = o lançado (a instância que já rodava) | 2 | o mesmo programa |
   | Janela nova (não existia antes do lançamento) | 1 | sozinha não diz qual app é |
   | Título com um nome do catálogo (palavra inteira) | 1 | sozinho é palpite |

   Executável e classe genéricos (`python3`, `flatpak`, `java`, `wine`…) não contam; a casca do desktop (`plasmashell`, `krunner`…) nunca é o app. **Nova e com o nome no título não bastam** (2 pontos): essa janela não vai para a frente, e entra na mensagem do prazo como "vi, mas sem ligação com o que eu abri".
4. **Num jogo do Steam, o PID não vale:** tudo o que o Steam abre descende dele. As janelas do cliente (`steam`: loja, biblioteca, atualização) não são o jogo, e a de **entrar na conta é do dono** — o Jarvis não a foca nem clica nela, espera, e o prazo diz que o Steam ficou esperando a conta. Abrir o próprio Steam é outra coisa: aí a janela dele é o alvo.
5. **Carência e reaproveitamento:** nos primeiros 5 s só janela nova conta; depois, a que o app já tinha vale pela classe ou pelo executável com mais um sinal — é o app de instância única que recebeu o pedido e não abriu janela nova.
6. **Dúvida:** empate que dura 3 ciclos vira **pergunta ao dono** (o aviso leva as janelas candidatas) e nada vai para a frente; empate que some sozinho (a janela de abertura que fecha) não pergunta.
7. **Depois do foco:** o motor confere que a janela ficou na frente (até 1 s) e espera 3 s; se ela sumiu (a janela de abertura que dá lugar à do app), procura a seguinte. Com o foco confirmado, a tarefa acaba: não se briga com o dono se ele for para outra janela.
8. **Prazo e franqueza:** `prazo_do_foco_s` na configuração (padrão 300 s, de 10 a 1800; o jogo demora); a tarefa ganha esse prazo mais 60 s, para quem diz "não apareceu" ser o motor, com o que viu: a janela não apareceu; o Steam ficou esperando a conta; vi «tal», sem ligação; ou não consegui ver as janelas.
9. **O aviso do fim é do código** (`FimDaTarefa.aviso`, emenda à ADR-0022): o app que abriu em menos de 10 s termina **sem aviso falado** (o dono acabou de ouvir "abri"; o card mostra); o que demorou diz "abriu e está em foco"; dúvida e falha sempre chegam ao dono.
10. **`window.focus_app` ganha `janela_id`** (opcional, conferido na lista de agora) e **`window.list`** diz o id e qual está em primeiro plano — pela porta, quando há; sem ela, o `wmctrl` de antes. A persona (v12) diz para não chamar `window.focus_app` logo depois de `apps.launch`, e a nota do roteiro de método (ADR-0035) diz que o foco vai sozinho.

## Alternativas descartadas

- **Focar a janela mais nova:** é palpite — a notificação, o Steam, outro app com o mesmo nome.
- **Esperar dentro do `apps.launch`:** prende a conversa, e o jogo leva minutos.
- **Ler o ambiente do processo (`SteamAppId`):** traria para a memória as variáveis do processo, que podem ter chave de API do dono; a linha de comando do `reaper` basta.
- **Script do KWin direto pelo D-Bus, sem o `kdotool`:** mais código e mais uma peça para manter; o `kdotool` já é a dependência da entrada virtual.
- **`wmctrl` pelo XWayland no Wayland sem `kdotool`:** só veria as janelas X11, e a janela ativa do XWayland pode estar velha (o motivo de `jarvis.entrada.foco` não usá-lo ali).

## Consequências

- O caso do dono: o Steam pede a conta, o jogo abre minutos depois, e só a janela do jogo vai para a frente, com o aviso falado.
- **Risco aceito:** a tarefa ocupa uma das duas vagas de tarefa (ADR-0022) enquanto espera, até o prazo; com o teto cheio, o app abre e o resultado diz que o foco não vai ser acompanhado.
- **Na máquina do dono** (KDE no Wayland), o acompanhamento só liga com o `kdotool` instalado — o mesmo que a entrada virtual pede; sem ele, `apps.launch` e as `window.*` ficam como antes.
- **[SUPOSIÇÃO]** o Steam lança o jogo sob `reaper SteamLaunch AppId=<id> -- …` e o jogo do Proton tem a classe `steam_app_<id>`. Confirma: `ps -o args` de um jogo aberto pelo Steam na máquina do dono. Se derrubar, o jogo nativo sem essas marcas não é achado e o prazo diz que a janela não apareceu — nunca foca outra por engano.
- **[SUPOSIÇÃO]** o `kdotool` imprime, em cada ação com `%@`, uma linha por janela na ordem do `search`, e a consulta final imprime a janela ativa (lido no código-fonte dele, `templates.rs`). Confirma: rodar a chamada no KDE do dono. Se derrubar, os blocos não fecham e vale o caminho de uma chamada por janela, que o teste cobre.
- **Não provado:** o KWin de verdade (o contêiner tem openbox), o Steam de verdade e o Wayland.
- Testes: `tests/unit/executor/test_janelas.py` (as listas do `kdotool` e do `wmctrl`, o ambiente, a tabela de evidência, o Steam, a carência), `tests/unit/tarefas/test_foco.py` (o motor no tempo: rápido, Steam lento, dúvida, palpite, prazo, a janela de abertura, o parar), `tests/unit/executor/test_foco_do_app.py` (ponta a ponta no executor, com PDP e auditoria) e o roteiro em contêiner `tools/harness_janelas.py` (X de verdade com openbox sem foco em janela nova, `wmctrl`/`xprop`, apps `xterm` e um Steam falso).

## Emenda de 2026-10-21 — as janelas por monitor, numa leitura do KWin, e o `window.focused`

**Relato do dono (dois monitores):** o Jarvis não identificou o Brave em foco no monitor principal.
Causa medida num KWin 6.7.5 **virtual** com duas saídas (o mesmo KWin da máquina, numa sessão
isolada: `tools/harness_foco.py`, 13 conferências): a porta só conhecia «a janela ativa» — a do
teclado. Com o Jarvis (ou qualquer janela) ativo no segundo monitor, o Brave na frente do principal
era «segundo plano», sem monitor nem pilha. E sem janela ativa (tudo minimizado, «mostrar a área de
trabalho») o `getactivewindow` da busca encadeada estoura em `null` e a lista inteira voltava vazia.

1. **A leitura é uma consulta do KWin** (`kdotool kwinscript --inline`, `CONSULTA_DO_KWIN`, só lê):
   os monitores na ordem do KDE (`workspace.screenOrder`: o principal primeiro), o monitor ativo, e
   cada janela com o monitor dela, a pilha (`stackingOrder`), a área de trabalho e se está
   minimizada. A **da frente de cada monitor** é a de cima na pilha entre as de app que o dono pode
   ver ali. A resposta é conferida campo a campo; com um `kdotool` sem `kwinscript` (< 0.3), a busca
   encadeada de antes, agora com a ativa numa chamada à parte (falhar não leva a lista junto).
   Medido no KWin virtual: ~5 ms por leitura (a de antes, ~6 ms).
2. **`window.focused`** (livre, só leitura): a ativa com o monitor dela e a da frente de cada
   monitor, dizendo qual é o principal. `window.list` ganha o monitor, a da frente e a minimizada.
   O caminho rápido (ADR-0045) responde «o que está em foco?» por ela, sem o motor.
3. **O `kdotool` 0.3 recusa rodar sem `KDE_SESSION_VERSION=6`** («Unsupported KDE version», no código
   dele): numa sessão KDE o executor completa a variável só para ele (`comandos.ambiente_do_programa`)
   — o Jarvis aberto por um serviço ou um lançador pode não tê-la herdado.
4. **O diagnóstico de 1 comando** que o dono roda e cola: `tools/diagnostico_foco.py` (a sessão, o
   `kdotool`, a leitura nova e a de antes com os tempos, o que o `window.focused` responderia, e o
   que a extensão acha que está em foco; só lê; títulos cortados ou omitidos com `--sem-titulos`).

**Não provado:** o KWin da sessão do dono (o painel e a área de trabalho do Plasma de verdade, os
monitores físicos, o Brave de verdade) — é para isso o diagnóstico. Testes:
`tests/unit/executor/test_janelas.py` (a resposta gravada do KWin, sem ativa, fora do formato, a
lista por monitor, sem `kwinscript`, a variável do kdotool), `tests/unit/politica/test_tiers.py`.
