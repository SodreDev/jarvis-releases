# ADR-0042 — Fechar a janela × encerrar o app: a fala decide, o código acha o alvo, e o sinal vai só ao PID certo

**Data:** 2026-10-21 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que é janela e o que é app, quando perguntar), arquiteto (a resolução do alvo, as proteções, os sinais)
**Pedido:** dono, 2026-10-21 — "FECHAR JANELA × ENCERRAR APP, com entendimento NATURAL de linguagem: "fecha o discord" → fecha só a JANELA ativa/do app (como o X da janela); "fecha a janela" → idem (a janela ativa ou a nomeada); "fecha o discord todo / inteiro / de vez / mata o discord / encerra o discord" → ENCERRA o aplicativo (processo): SIGTERM por PID e SIGKILL só após prazo curto se não sair, apenas dos processos que pertencem ao app resolvido (use o resolvedor fonético/catálogo de apps e o foco de janelas já existentes, evidência por PID/classe/executável; ambiguidade → pergunta ao dono, nunca palpite). Proteja: nunca PID 1, o próprio Jarvis, o gerenciador de sessão/compositor/shell do desktop, root/outros usuários, processos fora da lista do app resolvido; sem usar pkill/killall. Tiers: fechar janela = livre/moderado; encerrar app = moderado, com "sim" se o app pode ter trabalho não salvo (editor, jogo, documento) ou se houver mais de um candidato; ao resolver coisa de sistema ou o próprio navegador do dono em uso, peça confirmação." Substitui a `window.close_app` (2026-10-18). Emenda a ADR-0035 (dois casos novos no roteador), a ADR-0030 (o critério de pronto pelo motivo) e usa a porta de janelas e a evidência da ADR-0037 e o `Pedido.exige_o_sim` da ADR-0041.

## Contexto

1. Só havia `window.close_app`: **perigosa** (perguntava sempre), pelo `wmctrl` (no Wayland do KDE só vê janelas X11) e com o nome casado por pedaço de texto. Não havia como encerrar um app — e a regra do projeto proíbe `pkill`/`killall`/`pgrep -f`: matar por nome derruba o que não devia (o dono já perdeu a sessão assim).
2. O dono fala dos dois jeitos: "fecha o Discord" é o X da janela (o Discord vai para a bandeja, e está certo); "fecha o Discord todo", "mata o Discord" é sair do app.
3. A porta de janelas da ADR-0037 já lista janela, classe, PID e a da frente (`kdotool` no KDE, `wmctrl` no X11). O `kdotool` tem `windowclose {uuid}` ("Close a window", no `--help` dele; o `windowkill` não existe — o KWin não o expõe aos scripts).
4. Um app é vários processos (Electron: o principal, os de render, o crashpad; Steam: o cliente, o `steamwebhelper`, o `reaper` e o jogo); o executável pode ser genérico (`flatpak`, `electron`, `python3`).

## Decisão

**Duas ferramentas — `window.close` (a janela, livre) e `apps.quit` (o app, moderada) —, a fala do dono decide qual vale no turno, e o alvo é resolvido pelo código com evidência; o sinal vai por PID, só a processos do app, conferidos e fora da lista protegida, e o "sim" vem do alvo.**

1. **A fala decide** (`jarvis.politica.fechamento`): "fecha …" é **janela**; com "todo", "inteiro", "de vez", "completamente", "por completo", "o processo", ou com "mata", "encerra", "finaliza", "força o fechamento", é o **app**. Aba e guia são do navegador. O roteador (ADR-0035) ganha `fecha_janela` (tira `apps.quit` do turno) e `encerra_app` (tira `window.close`), antes de `cita_app`; "encerra o sistema" continua sendo encerrar o Jarvis (ADR-0041). O critério de pronto (ADR-0030) passa a sair também do motivo: "a janela fechada e conferida", "o app encerrado e conferido".
2. **`window.close`** (tier **livre**, como o X; `jarvis.executor.fechar`): sem nome, a janela em primeiro plano ("fecha a janela", "fecha esse aí"); com o nome, a janela daquele app — várias abertas e nenhuma na frente é pergunta ("qual?"); com `janela_id`, aquela. O pedido é o do gerenciador de janelas (`kdotool windowclose`, `wmctrl -i -c`) e a resposta confere se a janela saiu da lista — se não saiu, diz que o app pode estar perguntando se salva. Nunca a janela do próprio Jarvis nem a casca do desktop. Sem porta de janelas (o Wayland sem `kdotool`), diz o que instalar.
3. **`apps.quit`** (tier **moderado**, aviso «Encerrei o {app}.»):
   - **quem é o app:** pelo nome, o resolvedor fonético contra os apps instalados (`.desktop` do menu; binário solto do PATH não conta) e, se der dúvida, o que estiver aberto entre os parecidos — senão, pergunta; sem o app no catálogo, as janelas cuja classe ou título têm o nome (classes diferentes = pergunta); pela janela (`janela_id`, ou a da frente para "encerra esse aí");
   - **os processos dele:** os do executável do app (do `.desktop`, ou o do processo da janela; o genérico não conta) e os das janelas dele, **só do dono**, mais os descendentes; o SIGTERM vai às **raízes** (as instâncias), e o que não sair em 3 s leva SIGKILL;
   - **cada sinal** vai a um PID que ainda é o mesmo processo — mesmo início (`starttime` do `/proc/<pid>/stat`), mesmo dono, não zumbi —, e o resultado confere que todos saíram.
4. **Nunca recebe sinal** (`protecao`): PID 1; processo de outro usuário ou do root (os quatro UIDs têm de ser o do dono); o próprio Jarvis e os processos dele (os descendentes na sessão dele: o `claude -p`, o trabalhador de voz — o app que o Jarvis abriu tem sessão própria e pode ser encerrado); quem abriu o Jarvis (o terminal em que ele roda); a sessão do desktop (o compositor, o painel, o `krunner`, o gerenciador de sessão, os portais, o áudio, o D-Bus, o `systemd`…). Raiz protegida recusa o pedido inteiro, com o porquê; descendente protegido fica de fora. Mais de 400 processos é alvo errado: recusa.
5. **O "sim" vem do alvo** (`Pedido.exige_o_sim`, ADR-0041): ao encerrar, o navegador do dono ("as abas abertas fecham junto"), um jogo aberto (o `reaper SteamLaunch` do Steam, a janela `steam_app_<id>`: "pode perder o progresso"), programa do sistema (categoria `System`/`Settings` do `.desktop`), app que pode ter trabalho não salvo (categorias de editor, escritório, gráficos, desenvolvimento, jogo — o lançador de jogos não conta pela categoria —, ou um editor conhecido), e mais de uma instância; ao fechar a janela, o navegador e o programa do sistema. A pergunta falada diz o porquê; o "sim" falado segue a regra de sempre (ADR-0038); sem o portão (Jev), na tarefa, só o clique responde.
6. **Alvo resolvido duas vezes:** antes do PDP (o que não está aberto, o ambíguo e o protegido voltam negados ao modelo, com a pergunta quando é dúvida, `alvo_ausente`/`alvo_ambiguo`/`alvo_protegido` na trilha) e no corpo, na hora de agir — entre a pergunta e o "sim" a janela pode ter mudado.
7. **Persona v13**, parágrafo FECHAR É JANELA, ENCERRAR É O APP. A `window.close_app` e o `desktop.fechar` saem.

## Alternativas descartadas

- **`pkill`/`killall` por nome:** proibido pelo dono, e é o caminho para matar o que não devia (outro usuário, outro app com o nome parecido, o próprio Jarvis).
- **Só fechar a janela:** o Steam e o Discord ficam na bandeja; o dono pediu o app inteiro quando diz "todo".
- **SIGKILL direto:** o app não salva nada nem fecha os filhos; o SIGTERM primeiro é o que o "sair" do próprio app faz.
- **Deixar o modelo escolher entre as duas sem a regra do código:** "fecha o Discord" viraria encerrar o app às vezes; a tabela por fala é testável e a recusa diz o caminho.
- **Perguntar sempre ao encerrar:** o dono pediu o sim só no caso que pode perder algo.

## Consequências

- As frases do dono: "fecha o discord" fecha a janela; "fecha o discord todo" encerra os processos dele; "fecha a janela" e "fecha esse aí" fecham a da frente; "encerra o steam inteiro" encerra o Steam e o jogo, perguntando antes se há jogo aberto.
- **Risco aceito:** a tabela de fala é por palavras ("desliga o Spotify" não é nenhum dos dois); o app que se esconde atrás de um executável genérico só é achado pelas janelas; o Flatpak e o PID que o KWin informa dentro da caixa de areia não foram vistos de verdade.
- **[SUPOSIÇÃO]** o `kdotool windowclose` pede o fechamento educado (o `closeWindow` do KWin, como o X) e não mata o processo; confirma ou derruba: o teste do dono (fechar o Kate com um arquivo não salvo deve abrir a pergunta "salvar?").
- **Não provado:** o KWin de verdade, o Steam e o Discord de verdade, o Wayland do dono (sem `kdotool` instalado lá, o `window.close` diz o que falta e o `apps.quit` encerra pelo nome, sem "o da frente"). Os processos de verdade dos testes são descartáveis, criados pelo próprio teste com executável de nome único e sessão nova.
- Testes: `tests/unit/executor/test_fechar_e_encerrar.py` (a tabela de fala, a janela pelo nome e a da frente, várias janelas, a janela do Jarvis, a que não some, a ambiguidade; o app pelos PIDs, o teimoso que leva SIGKILL só depois do prazo, o Steam com e sem jogo, editor, navegador e duas instâncias, as proteções, o "encerra esse aí", o PID reaproveitado, sem porta de janelas; pelo executor com o PDP; e dois processos descartáveis de verdade, um que sai com o SIGTERM e um que só sai com o SIGKILL), `tests/unit/politica/test_tiers.py`, `tests/unit/executor/test_nativas_sistema.py`.

## Como invalidar esta decisão

- O teste do dono mostrar a janela fechada matando o app (a suposição do `windowclose` cair): o `window.close` passa a usar outro caminho do KWin.
- Um app de verdade não ser achado pelos PIDs (o Flatpak, um jogo do Proton) ou um processo de fora do app entrar na lista: a resolução muda antes de qualquer sinal novo.
- O dono pedir para "fecha o X" encerrar o app, ou para perguntar sempre.

## Emenda de 2026-10-25 — o sim só no que é arriscado (ADR-0046)

A ordem explícita do dono ("fecha o Brave", "fecha essa janela") fecha a janela sem o sim, também a
do navegador; encerrar o app pede o sim só com trabalho não salvo detectado, jogo aberto, app fora da
lista liberada ou alvo que o pedido não citou. «O navegador» sem nome é o que está em foco, senão o
único aberto. A tabela inteira está na ADR-0046.
