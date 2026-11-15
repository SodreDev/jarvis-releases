# Auditoria: onde o código fala ou decide pelo Jarvis

**Data:** 2026-11-15 · **HEAD auditado:** `2252c51` · **Pedido:** dono — «do jeito que você está criando, o Jarvis fica cada vez mais automação; se não mudar o rumo teremos de refazer do zero».

**A regra (memória `bbab63e2`):** o código só transforma acontecimentos em **notificações/eventos** entregues ao Jarvis (o LLM). Quem decide e quem fala é o Jarvis. Nenhuma frase de resposta, falha ou alerta, nem decisão de ramo, escrita no código e entregue ao dono.

Cada item diz **onde** (`arquivo:linha`, caminhos sob `src/jarvis/` salvo indicação), **o que faz hoje**, e **a troca**: que evento o Jarvis recebe no lugar. Gravidade: **A** (o dono ouve frase do código ou o código decide o rumo), **M** (decide por regra o que o modelo deveria decidir, ou frase menos frequente), **B** (tela/card, ou só telemetria).

Fica de fora, por ser **invariante de segurança** (fica no código, não é «falar pelo Jarvis»): lista de negação do PDP, `deny`/«barrar» do guarda, o «não fazer» do portão, o comando do modo de permissão lido só da fala do dono (`politica/permissao.py:110`), a leitura do sim/não de uma pendência (`s2/portao.py:361`, `:407`; `voz/resposta.py:74`), o barge-in (`voz/interrupcao.py:114`), as travas do envio **autônomo** da ADR-0060 (`social/envio.py` `Guardiao`, `social/ausente.py`), as regras fixas e o argv do `delegar.claude_code`, e o relato verdadeiro como **filtro** (cortar o «abri/enviei» que nada confirmou — o que muda é quem fala depois do corte).

---

## O caminho comum: todo fim de tarefa e todo aviso é falado sem o LLM

Antes dos itens, o defeito que os une. Tudo o que o código escreve vira voz por um só cano:

`GestorDeTarefas._terminar` (`tarefas/gestor.py:661`) → `ao_concluir` → `voz/app.py:1101 _tarefa_concluida` / `:1138 _resposta_da_tarefa` → fila de avisos → `voz/app.py:1277 decidir_entrega(liberados)` **sem `julgar`** (cai em `s2/avisos.py:39 falar_sempre`) → `Cerebro.avisar` (`s2/cerebro.py:1567`, «sem chamar o motor») → `s2/avisos.py:58 frase_do_aviso` («Aviso de {origem}: {resumo}.»).

O gancho para o modelo decidir já existe e está **sem uso**: `AvisoLiberado` + `Julgar` (`s2/avisos.py:28-36`). A decisão do dono de 2026-10-16 (memória `c2bb11f8`) já pedia isto: o Jarvis **recebe** a notificação e decide se fala, quando e como.

**Troca (base de tudo):** o fim de tarefa, o teto, o laço e o evento de rede chegam ao `Cerebro` como **evento do sistema** (dados, não frase); uma rodada do motor, com a persona e o contexto do momento, decide falar/mostrar/calar e escreve o texto. A frase do código só existe se o motor cair — e aí vai à **tela**, não à voz.

---

## (a) Respostas e falhas fixas ao estourar passos, tentativas, tempo e guarda de laço

| # | Onde | Hoje | Gatilho | G | Troca |
|---|---|---|---|---|---|
| a1 | `tarefas/gestor.py:676-703` `_pergunta_do_teto` | A pergunta inteira é do código: «já dei N passos em «…» e ainda falta», «continuar por mais 50 passos ou até terminar»; falada por `cerebro.py:1157 _pergunta_do_teto` | teto de 50 passos / 900 s (ADR-0059) | A | **Notificação do teto ao motor** (pedido, cada passo com ferramenta/status/erro real, o que deu certo, gasto em passos e segundos). O motor **decide**: seguir N passos, mudar de estratégia, perguntar algo ao dono (com as palavras dele) ou encerrar explicando |
| a2 | `tarefas/gestor.py:623-644` `_parar_no_teto`, `:629` | Prefixa «Parei sem terminar.» ao resumo do motor | «não»/120 s no teto | A | Sem prefixo: o motor recebe o evento «o dono disse não / não respondeu» e escreve o fim |
| a3 | `tarefas/gestor.py:710-717` `_resumo_do_codigo` | «Parei sem terminar, depois de N passos; K deram certo.» — o código conta os passos | motor caiu no resumo | A | Vai à tela/card; a voz fica com o motor (ou com nada) |
| a4 | `tarefas/gestor.py:56`, `:558-577` `ABERTURA_DO_LACO` + `_no_laco` | Na segunda detecção, a tarefa **acaba** com «Parei sem terminar: eu estava repetindo…» | guarda de laço, parada (ADR-0062) | A | A parada vira **notificação de laço** ao motor (a categoria, o período, os passos repetidos), que decide mudar de caminho, perguntar ou encerrar. Só um laço que insiste depois da decisão do motor de seguir corta a tarefa — e mesmo aí o fim é escrito pelo motor |
| a5 | `s2/tarefa_do_pedido.py:183-184`, `:103-109` `FRASES_SEM_SAIDA` | «A extensão do Jarvis… clique em Recarregar…», «Parei, como você mandou.», «Não deu para seguir.» | falha sem saída (`recuperacao.SEM_SAIDA`) | A | Evento «sem saída: <código>, <motivo real>» numa rodada final sem ferramentas; o motor explica ao dono |
| a6 | `s2/tarefa_do_pedido.py:185-186`, `:238-239`, `:256` → `_desistir` `:305-312` → `explicacao_para_ouvir` `:504-521` | «Não consegui. Tentei X (motivo); Y — e nenhum caminho deu certo.» / «Não consegui: não achei um jeito…» (`SEM_JEITO`, `:90`) | orçamento da recuperação (`recuperacao.py:39-42`: 4 seguidas, 8 por tarefa) e `RODADAS_POR_PASSO` (`:97`) | A | Orçamento esgotado = **notificação** ao motor com as tentativas; ele decide (como no teto). Mesmo cano do a1 |
| a7 | `s2/tarefa_do_pedido.py:211-214` → `_sem_motor` `:314-329` | «Pronto: «título» está aberto.» / «Pronto, está feito.» ou `ErroDeTarefa` «o motor da conversa falhou N vez(es)…» | motor caiu > 2 vezes | A | Sem motor não há quem fale: tela/card com o estado; o Jarvis do turno recebe o evento quando voltar |
| a8 | `s2/tarefa_do_pedido.py:447-459` `_fim` | Nada deu certo: **joga fora o texto do motor** e diz «Não consegui: {motivo}.» / a lista de tentativas / «Não fiz, porque você não confirmou.» (`:89`) | nenhum passo ok | A | O motor recebe o motivo real e escreve; o relato verdadeiro continua cortando o «abri» sem prova |
| a9 | `s2/tarefa_do_pedido.py:460-466` e `s2/cerebro.py:755`, `:867-872` → `s2/verdade.py:187-188` | Acrescenta «Não consegui confirmar que ficou feito.» / «A mensagem ainda não foi enviada…» | 2 cobranças sem confirmação (ADR-0066 §2) | A | Depois da última cobrança, o motor recebe «o que você afirmou não foi confirmado: <frases cortadas>» numa rodada sem ferramentas e diz a verdade com as palavras dele |
| a10 | `s2/tarefa_do_pedido.py:467-469` | «Terminei o que você pediu.» (texto vazio) e «Não consegui conferir se ficou certo.» (`SEM_CONFERIR`, `:88`) | resposta vazia; falta conferir | M | Texto vazio = rodada de cobrança; falta conferir = nota ao motor (já existe `NOTA_DE_CONFERIR`) |
| a11 | `s2/tarefa_do_pedido.py:540-547` `_recusado` | «Não fiz, porque você não confirmou.» | prazo da confirmação | M | Evento «o dono não confirmou» ao motor |
| a12 | `tarefas/gestor.py:498-503` | `ErroDeTarefa("passou de N s: o prazo é nosso")` → falado por `voz/app.py:1124`/`:1192` | prazo da tarefa de um passo | A | Evento de prazo com o estado; o Jarvis do turno decide |
| a13 | `tarefas/gestor.py:368-371` | «já há N tarefas rodando (o teto é 2)…» → `cerebro.py:1147-1148` «Agora não dá para começar isso: {erro}.» | teto de tarefas simultâneas | A | Pelo `tarefa.iniciar` já volta ao motor (ok); pelo `_delegar` do cérebro, vira resultado ao motor, não frase |
| a14 | `tarefas/gestor.py:476-479`, `:231` (`MotorDireto`), `tarefas/foco.py:112-161`, `tarefas/motores.py:98` | Exceção crua vira `motivo` falado: «esperei N s e a janela de X não apareceu», «o motor da tarefa falhou: …» | erro de ferramenta/motor | A | O motivo é dado do evento de fim; quem fala é o motor |
| a15 | `voz/app.py:1124`, `:1156`, `:1160`, `:1162`, `:1192` | «a tarefa «X» falhou: …», «Terminei o que você pediu.», «deu um erro aqui dentro», «Não consegui terminar o que você pediu: …», «Não deu para X: …» | qualquer fim de tarefa | A | O cano comum (acima): evento ao `Cerebro`, rodada do motor |
| a16 | `s2/fluxo_de_acao.py:441`, `:446`, `:450`, `:458`, `:460`, `:65`, `:517` | «Não deu para fazer {x}: {motivo}.», «Tudo bem, paro por aqui.», «Certo.», `frase_do_feito` — via `_so_dizer`, sem LLM | resposta a pendência; erro depois do «sim» | M | O resultado da pendência volta ao motor como evento |
| a17 | `s2/cerebro.py:122`, quebras em `:642-651`, `:711-717`, `:805-814`, `:852-857`; `:860-864` | Prazo de 90 s / teto de passos do **turno**: o turno acaba **sem rodada final**; o dono ouve silêncio e a tela mostra «(sem resposta: o laço de ferramentas passou de 90 s)» (`voz/app.py:2359-2365`) | teto do turno | M | Antes do `break`, uma rodada sem ferramentas com a nota do limite (o que foi feito, o que falta); o motor decide continuar em tarefa ou explicar |
| a18 | `s2/cerebro.py:389` | «Não deu para fazer o que você confirmou: {motivo}» na fila de voz | erro depois do clique em sim | M | Evento ao motor |
| a19 | `delegacao/claude_code.py` (`--max-turns`) | Ao esgotar turnos, volta `error_max_turns` como passo que falhou; o subagente **não** devolve o estado parcial | teto do subagente | M | O pedido ao subagente manda devolver o estado no último turno; o resultado (mesmo parcial) chega ao motor como evento |

## (b) Alertas de redes sociais montados em frase fixa (ADR-0060)

O caminho de hoje: `extensao/social.js` (`lerEstado` `:300-362`, `informar` `:386-416`) → `extensao/background.js:1266` → ponte → `social/monitor.py:556 _tique` → `EstadoDoMonitor.receber` (`:294`) **escreve a frase** → `gui/ponte.py:637` `redeNotificou(rede, texto)` → `voz/app.py:761 aviso_de_rede` → fila → `Cerebro.avisar` → voz. Em nenhum ponto o LLM decide.

| # | Onde | Hoje | G | Troca |
|---|---|---|---|---|
| b1 | `social/monitor.py:398-408` `_texto` | «WhatsApp: 2 mensagens novas — Ana (1), Bruno (1) e mais N» falado palavra por palavra | A | **Evento de rede estruturado**: `rede`, `tipo`, `remetentes[{nome, nao_lidas, suspeito}]`, `novas`, `trecho`, `urgencia_observada`, `momento` |
| b2 | `social/monitor.py:321-326`, `:146-153` `ALERTAS_DITOS` | «{Rede}: sinal de alerta — a página pediu captcha. O Jarvis parou o envio desta rede por 24 h; confira a aba você mesmo.» | A | Evento `tipo=alerta_de_conta` com o código; a pausa de 24 h **fica** (é trava do envio autônomo) e vai como fato no evento |
| b3 | `s2/avisos.py:58-74` `frase_do_aviso` | «Aviso de WhatsApp: WhatsApp: 2 mensagens novas — Ana (1).» (a rede sai duas vezes) | A | O texto falado vem da rodada do motor |
| b4 | `voz/app.py:1277` (`decidir_entrega` sem `julgar`) e `s2/cerebro.py:1567-1617` `avisar` | Todo aviso liberado é falado, sem chamar o motor | A | `avisar` chama o motor com os eventos e o **contexto** (presente/ausente, hora, não perturbe, última vez que falou desta rede); ele responde falar/card/calar e o texto |
| b5 | `s2/cerebro.py:542-548` | Com mensagem do dono junto, o código fala os avisos **antes** e o motor só recebe «você já disse…, não repita» | A | Os eventos entram como nota **antes** da geração: «eventos pendentes: …; decida se e como mencionar» |
| b6 | `gui/ponte.py:647-656` | «WhatsApp: respondi a {nome} (você está ausente)» / «… não respondi a {nome} — {motivo}» | A | Evento `tipo=resultado_envio` com `enviado` e `codigo` da recusa |
| b7 | `social/envio.py:261-281` `FRASES`; `social/ausente.py:30`, `:128-133`; `social/enviar.py:103`, `:122` | Motivos de recusa em prosa («é madrugada: sem envio nesse horário», «o contato não está na sua lista permitida»…) chegam à voz pelo b6 | M | O `Guardiao` e as travas **ficam** (só valem para o envio autônomo); vai ao Jarvis o `codigo`, não a frase |
| b8 | `social/monitor.py:349-355` | Só notifica quando a contagem **sobe**; `notificar=false` (`social/config.py:56`) **corta o evento** antes do Jarvis | M | O ajuste do dono vira **contexto** do evento («o dono pediu para não ser avisado desta rede»); o Jarvis respeita, mas sabe |
| b9 | `agentd/fila_de_avisos.py:110-111`, `:149`, `:165` | «não perturbe» e «privacidade» decidem no código só card / nada | M | Privacidade (microfone desligado) **fica** como trava; «não perturbe», «ausente» e «madrugada» passam a contexto do evento |
| b10 | `extensao/social.js:3-4`, `:190-245` | Não há classificação mensagem × ligação × notificação do sistema, nem trecho; só `{nome, naoLidas}` e alerta de conta | A | **Agente monitor**: ao detectar mudança, lê a página (CDP/árvore), classifica, junta o trecho e entrega o evento (b1) |
| b11 | `social/monitor.py:389-395` `NOME_SUSPEITO` | Troca o nome por «uma conversa com nome suspeito» na frase | B | A checagem (ADR-0065) fica; vai como `suspeito=true` no evento |
| b12 | `social/monitor.py:121-164` (`ESTADOS`, `LOGIN_POR_REDE`) | Frases do cartão da aba | B | Só tela: fica |

## (c) Templates, `if/elif` de intenção e regex que escolhem a ação em vez do LLM

| # | Onde | Hoje | G | Troca |
|---|---|---|---|---|
| c1 | `politica/atalho.py:267` `achar`, chamado em `s2/cerebro.py:581`; executa em `:589`; `pular_o_motor` | **Caminho rápido**: regex na fala do dono escolhe ferramenta e argumentos e roda **antes do LLM**; com `atalho.completo`, o motor nem vê o turno. Ligado por padrão (`voz/config.py:871`) | A | O atalho vira **sugestão** ao motor (dica de ferramenta e argumentos no prompt), nunca execução; pendência |
| c2 | `politica/atalho.py:503` `frase`, `:464` `frase_da_ferramenta`; falado em `s2/cerebro.py:620`, `:844` | «Abrindo o X.», «Fechei a janela…» — a resposta principal do caminho rápido e da ação de um passo | A | A rodada do motor com o resultado escreve |
| c3 | `politica/metodo.py:164` `escolher_metodo`, usado em `executor/ferramentas.py:488` | Palavras-chave escolhem o método e **tiram ferramentas** do modelo (`Escolha.evitar`) | A | Nota de método como contexto; as ferramentas ficam; pendência |
| c4 | `s2/roteiro_do_navegador.py:134` `pedido_de_envio`, `:193` `_roteiro_do_envio`, `:285` `_roteiro_geral`; injetado em `s2/tarefa_do_pedido.py:355` | Regex tira rede, contato e mensagem da fala e o código escreve **um roteiro de 5-6 passos** («execute sem perguntar»). E `roteiro` (`:180`) põe o roteiro geral em **toda** tarefa que tem `browser.*` no catálogo | A | Sai o roteiro de passos fixos. A garantia de ler antes de agir passa ao **subagente do navegador** (ferramenta + prompt); o contato resolvido das memórias vai como contexto, não como passo |
| c5 | `s2/cerebro.py:772`, `s2/tarefa_do_pedido.py:273` → `roteiro_do_navegador.py:253` `copia_da_mensagem` | Veta o `browser.type` cujo texto é a fala do dono copiada e manda `NOTA_DE_REDIGIR` | M | Vira nota no pedido ao subagente (redigir no tom do dono); sem veto por regex; pendência |
| c6 | `s2/leitura_da_pagina.py:70` `leitura_antes` (em `cerebro.py:784`, `tarefa_do_pedido.py:279`) | **Troca** a ação proposta pelo LLM por `browser.inspecionar` | M | A ordem ler → agir → reler vira contrato **da ferramenta do subagente** (item B2) |
| c7 | `s2/verdade.py:59` `_PEDE` | Corta toda pergunta do motor («quer que eu…», «posso…») e força outra rodada | M | Corta só a pergunta de permissão sobre o que o dono já pediu (ADR-0066); a pergunta legítima (falta um dado) passa; pendência |
| c8 | `s2/cerebro.py:154` `ACOES_DE_UM_PASSO`, `:1073` `_cumpriu_no_turno`, `politica/atalho.py:436` `fala_simples` | O código **encerra o turno** depois de uma ação simples sem nova rodada do motor | M | Uma rodada com o resultado; o motor decide se acabou; pendência |
| c9 | `s2/receitas.py:254` `PALAVRAS`, `:274`, `:288` | Palavras-chave escolhem o bloco de receita (sequência de ferramentas) no prompt | B | Só prompt; fica como pendência leve |
| c10 | `s2/portao.py:257-266` | Classificador falhou → «na dúvida, pergunto» | B | Política de segurança; fica |
| c11 | `voz/endpoint.py:1455` `comando_de_estilo`; `s2/cerebro.py:477` | Comando de estilo lido por regex, resposta fixa (`:1488`) | B | É ajuste do dono como o modo de permissão; a frase pode vir do motor; pendência |
| c12 | `s2/cerebro.py:135` `FRASE_AO_DELEGAR` | «Certo, já cuido disso.» quando o motor não falou nada ao delegar | M | O motor fala antes de delegar (persona); sem frase do código |

## (d) Onde o Jarvis executa ele mesmo em vez de delegar

| # | Onde | Hoje | G | Troca |
|---|---|---|---|---|
| d1 | `s2/cerebro.py:815` `_chamar`; `:1023` `_vai_para_tarefa`; `:142` `PASSOS_NO_TURNO = 2` | As **duas primeiras** ferramentas rodam **dentro do turno** do Jarvis (clique, digitação, apps, `web.*`, `script.rodar`, `files.*`); só a terceira, ou depois de 12 s, vai para tarefa. No navegador, depois do 1º passo (`:1040`) | A | **Toda execução vai para tarefa/subagente desde o 1º passo.** O turno só conversa, delega e lê; o subagente devolve progresso e resultado como eventos (item B2) |
| d2 | `s2/cerebro.py:589` | O caminho rápido executa no turno (c1) | A | Idem d1 |
| d3 | `executor/ferramentas.py:1450` `_delegar`; `catalogo/delegar.claude_code.yaml:85` | No modo automático, `delegar.claude_code` proposto no turno roda **síncrono** (até 600 s): bloqueia a voz, e o prazo de 90 s do turno mata o subprocesso | A | Vai para tarefa como as demais execuções (d1) |
| d4 | `s2/cerebro.py:909` `_abrir_o_navegador`, `:950` | O código abre o navegador e espera a extensão (12 s) dentro do turno | M | Vira passo do subagente; pendência |
| d5 | `s2/fluxo_de_acao.py:487-500` | Depois do «sim» falado, a ferramenta rápida roda no turno | B | Pendência |
| d6 | Progresso parcial | Nenhum retorno parcial da tarefa chega ao LLM do Jarvis: só a linha da tela (`_mostrar`), o card e o fim (já em frase) | A | A tarefa emite **eventos de progresso** (passo, resultado curto) que o `Cerebro` recebe; no fim, o evento de fim (cano comum) |
| d7 | `delegacao/claude_code.py:77` `REGRAS` | «Leia a página antes de cada ação» é só texto; o subagente Claude Code devolve um `result` final único (`--output-format json`), sem parciais | M | A regra vira contrato da ferramenta do subagente do navegador; parciais ficam como pendência (precisa de `stream-json`) |

---

## Estado (2026-11-15, depois das rodadas 1 e 2)

**Rodada 1** (ADR-0070): `a0bc7a7` caminho comum, `530fc62` limites, `2d55f21` execução delegada, `7ff9a17` redes por agente monitor, `73a1c58` caminho rápido como dica e roteiro como orientação, `8afc8a2` a ADR. **Rodada 2:** `c16d79a` grupo A, `649061f` grupo B, `a9d499f` grupo C. **Rodada final:** `560fc85` (a17, a19, sai o `passos_no_turno`, varredura de frases) e `1a4e51c` (suíte de ponta a ponta e consertos) — o fim do caminho `passos_no_turno`, a varredura de frases e a suíte de ponta a ponta `tests/e2e/` (que achou e consertou dois buracos: a releitura depois do erro e o envio pelo botão «Enviar»).

| Item | Estado | Onde foi resolvido |
|---|---|---|
| Caminho comum (todo aviso falado sem o motor) | **resolvido** | `a0bc7a7`: `Cerebro.avisar` roda o motor com os eventos |
| a1–a6 (teto, laço, orçamento, sem saída) | **resolvido** | `530fc62`: notificação ao motor, que decide |
| a7 (motor que cai no fim da tarefa) | **resolvido** | `530fc62`: o fim vai ao Jarvis como evento |
| a8–a11 (nada feito, sem confirmação, vazio, falta conferir, prazo da pergunta) | **resolvido** | `530fc62`: `_explicar` com o fato |
| a12–a15 (prazo, teto de tarefas, exceção crua, fallback do app) | **resolvido** | `a0bc7a7`/`2d55f21`: viram dado do evento e a recusa volta ao motor |
| a16 (respostas fixas à pendência) | **resolvido** | `c16d79a`: `LeituraDaResposta.evento` e `_responder_ao_evento` |
| a17 (prazo do turno sem rodada final) | **resolvido** | Rodada final: o teto do turno (prazo ou passos) vira notificação (`NOTA_DO_LIMITE_DO_TURNO`) numa rodada do motor (`Cerebro._rodada_do_limite`); ele responde, pergunta ou propõe o passo, que vai ao subagente |
| a18 (status do clique) | **resolvido** | `c16d79a`: vai à fila como dado |
| a19 (subagente sem devolver o estado no último turno) | **resolvido** | Rodada final: `error_max_turns` vira `Codigo.LIMITE_DE_TURNOS`, com `o_que_fez` (os últimos parciais do stream) e `limite.decida` nos dados; as regras do subagente pedem o estado no fim |
| b1–b8, b10, b11 (redes) | **resolvido** | `7ff9a17`: agente monitor e evento estruturado |
| b9 («não perturbe» filtra) | **resolvido** | `a9d499f`: vira contexto do aviso; só a privacidade segura a voz |
| b12 (frases do cartão) | **fica** | Só tela |
| c1, c2, d2 (caminho rápido executa e fala) | **resolvido** | `73a1c58`: virou dica; `c16d79a`: sem frase da ação |
| c3 (método tira ferramentas) | **resolvido** | `649061f`: dica, sem recusa |
| c4 (roteiro de passos fixos) | **resolvido** | `73a1c58`: orientação e fatos |
| c5 (veto regex da mensagem copiada) | **resolvido** | `649061f` |
| c6 (o código troca a ação por leitura) | **fica, como guarda** | Ler antes de agir é garantia de ferramenta (ADR-0069), pedida pelo dono |
| c7 (`_PEDE` corta perguntas) | **resolvido** | `c16d79a`: perguntar é decisão do Jarvis |
| c8 (o código encerra o turno) | **resolvido** | `c16d79a` |
| c9 (receitas por palavra-chave) | **resolvido** | `649061f`: vêm como dica |
| c10 (classificador falhou → pergunta) | **fica** | Política de segurança |
| c11 (frase do comando de estilo e do modo) | **resolvido** | `c16d79a`: a troca é do código, a fala é do Jarvis |
| c12 («Certo, já cuido disso.») | **resolvido** | `2d55f21` |
| d1, d3 (execução no turno, delegação síncrona) | **resolvido** | `2d55f21` |
| d4 (navegador fechado aberto pelo código) | **resolvido** | `a9d499f`: o motor recebe o fato e decide; o código só espera a extensão depois do `browser.launch` dele |
| d5 (ferramenta rápida depois do «sim» no turno) | **resolvido** | `649061f`: vai ao subagente |
| d6 (progresso parcial) | **resolvido** | `2d55f21`: `ao_progresso` e nota SUBAGENTES EM ANDAMENTO |
| d7 (parciais do Claude Code) | **resolvido** | `a9d499f`: `stream-json`, cada passo vira parcial |
| D (agente monitor ler a página por CDP) | **não feito, de propósito** | Anexar o depurador à aba da rede, a cada notificação, é o risco de detecção e banimento que a ADR-0060 restringe ao envio (CDP só durante o envio, sem ligar domínio nenhum). O agente usa a leitura do content script (prévia e ícones de cada linha). Volta se o dono aceitar esse risco explicitamente. |

**Rodada final (o que faltava):** a17 e a19 resolvidos (acima); o caminho no turno com `passos_no_turno > 0` saiu do código (só existia nos testes: com o subagente ligado, toda execução vai a ele desde o primeiro passo; sem ele, o laço inteiro roda no turno, como no harness); a varredura de frases tirou o código morto `Recuperacao.explicacao` («Não consegui…») e `frase_do_estilo` («Certo, estilo…»), e o fim cancelado pelo dono no card virou fato («(cancelada pelo dono: …)») em vez de «Parei o que você tinha pedido.». A suíte `tests/e2e/` prova os cinco casos do dono com fakes e achou dois buracos, consertados: (1) depois de um passo que falhou na página, a guarda de repetição recusava a nova tentativa **antes** da releitura obrigatória — o subagente desistia sem reler (`MotorDoObjetivo.proximo` agora relê primeiro); (2) enviar pelo botão «Enviar» não contava como envio, e o filtro da verdade não deixava o Jarvis dizer que mandou mesmo com a mensagem no chat (`browser.click` agora marca `enviado` quando o clique é o de enviar). **Fica, com motivo:** b12 (frases do cartão, só tela), c6 (ler antes de agir é guarda pedida pelo dono), c10 (política de segurança) e D (CDP na aba da rede). Nada disto foi testado no navegador, nas contas, no microfone nem no áudio reais do dono: o roteiro está em [teste-real-dono.md](../teste-real-dono.md).

## O que a Fase B tratou (registro original)


1. **Limites → notificação ao Jarvis** (a1–a6, a17 parcial, a19): teto de passos/tempo, laço e orçamento da recuperação deixam de gerar fala ou pergunta do código. O gestor monta a **notificação** (pedido, passos com ferramenta/status/erro real, o que deu certo, gasto) e o motor **decide** numa rodada própria: `continuar` (N passos e a estratégia nova), `perguntar` (a pergunta escrita por ele vai ao dono; a resposta volta a ele como novo evento) ou `encerrar` (a resposta dele). O subagente pensa no último passo: a rodada final nunca é bloqueada sem devolver o estado.
2. **Execução sempre delegada** (d1, d3, d6, c4, c6, d7): a primeira ferramenta de execução já vai para a tarefa; o turno do Jarvis só conversa e lê; o progresso volta como evento. O subagente do navegador é **obrigado pela ferramenta** a ler a página (árvore/DOM via CDP) antes do primeiro clique e a reler depois para conferir; sai o roteiro de passos fixos.
3. **Redes sociais por agente monitor** (b1–b8, b10–b11, e o cano comum b3/b4/b5 para eventos de rede): o monitor entrega um **evento estruturado**; o Jarvis decide se fala, quando e o quê; ausente, madrugada e não perturbe viram contexto. As travas da ADR-0060 ficam só no envio autônomo.

## Pendências levantadas na auditoria (ver «Estado» acima para o que já saiu)

- c1/c2/d2 — caminho rápido por regex que executa e fala sem o motor.
- c3 — `escolher_metodo` tirando ferramentas por palavra-chave.
- c5 — veto por regex da mensagem copiada.
- c7 — o filtro `_PEDE` que corta toda pergunta do motor.
- c8 — o código encerrando o turno depois da ação simples.
- c9, c11, c12 — receitas por palavra-chave, frase do comando de estilo, «Certo, já cuido disso.».
- a7, a10, a11, a12, a13, a14, a16, a18 — os fins de tarefa e de pendência que ainda têm frase própria do código fora do cano comum (os que passam pelo cano comum ganham a rodada do motor no item 3).
- d4, d5 — abrir o navegador e a ferramenta rápida depois do «sim», ainda no turno.
- d7 — parciais do subagente Claude Code (`--output-format stream-json`).
- b9 — «não perturbe» da fila de avisos como contexto e não como filtro (a privacidade fica).
- `recuperacao.py:283-289` `Recuperacao.explicacao` não tem chamador (código morto).
