# ADR-0070 — O Jarvis é agente: o código transforma acontecimentos em eventos, e quem decide e fala é ele

**Data:** 2026-11-15 · **Estado:** aceita (implementada e testada só com fakes: motores roteirizados, páginas falsas, extensão falsa; o uso real é do dono) · **Decide:** dono (o princípio: o Jarvis é agente, não automação), arquiteto (onde cada evento nasce e por onde chega ao Jarvis)
**Pedido:** dono, 2026-11-15 (memória `bbab63e2`): «do jeito que você está criando, o Jarvis fica cada vez mais automação; se não mudar o rumo teremos de refazer do zero». Emenda: ADR-0025 (fila de avisos), ADR-0045 (caminho rápido), ADR-0046 (o que roda no turno), ADR-0059 (teto da tarefa), ADR-0060 (redes sociais), ADR-0062 (guarda de laço), ADR-0066 (relato verdadeiro), ADR-0069 (formular, ler a página). Auditoria: [docs/estudos/auditoria-automacao.md](../estudos/auditoria-automacao.md).

## Contexto

As correções anteriores trocavam um comportamento por outro **roteirizado**: frase fixa no teto («já dei N passos… posso continuar?», «Parei sem terminar…», «Não consegui. Tentei…»), alerta de rede montado no código («WhatsApp: 2 mensagens novas — Ana (1)»), regex que executava e falava antes do modelo (o caminho rápido), roteiro de passos numerados para o navegador, e as primeiras ferramentas rodando dentro do turno do Jarvis. A auditoria achou a raiz comum: **todo fim de tarefa e todo aviso ia à voz por `Cerebro.avisar` «sem chamar o motor»**, com a frase escrita pelo código.

## Decisão

**O princípio:** o código só transforma acontecimentos em **notificações/eventos** entregues ao Jarvis (o modelo). Quem decide e quem fala é o Jarvis. Nenhuma frase de resposta, falha ou alerta, nem decisão de ramo, escrita no código e entregue ao dono. Ficam no código só os **invariantes de segurança**: lista de negação, PDP, o «não fazer» do portão, a leitura do sim/não de uma pendência, o barge-in, o modo de permissão lido da fala do dono e as travas do envio **autônomo** da ADR-0060.

### 0. O caminho comum: todo aviso é um turno do Jarvis (`a0bc7a7`)

- `s2/avisos.nota_dos_eventos`: os avisos viram **EVENTOS DO SISTEMA** (tipo, de onde, de terceiros, conteúdo, contexto) numa nota para o motor; `frase_do_aviso` saiu.
- `Cerebro.avisar` (piso livre) roda uma rodada do motor, sem ferramentas, com os eventos: ele fala com as palavras dele ou responde `[silencio]` (o card guarda). Motor que cai = nada na voz.
- Com a mensagem do dono, os eventos entram como nota **antes** da geração, e o Jarvis decide se e como mencioná-los.
- `Contexto` ganha o papel `evento`: o turno aberto pelo sistema não se passa por fala do dono.
- O fim de tarefa vai ao Jarvis como dado (a resposta da tarefa, ou o estado e o motivo real). O eco de uma pergunta inclui o que o Jarvis disse, sem as palavras de resposta.

### 1. Limites viram notificação, e o motor decide (`530fc62`)

- Teto de passos, teto de tempo, parada da guarda de laço, orçamento de falhas e rodadas sem passo viram `NotificacaoDoLimite` (`tarefas/limite.py`): o pedido, cada passo com ferramenta, status e erro real, o que deu certo, o gasto e o próximo passo proposto.
- O motor decide numa rodada sem ferramentas (ele **pensa no último passo**): `continuar` N passos com uma estratégia, `perguntar` ao dono com o texto dele, ou `encerrar` com o texto dele.
- Continuar sozinho: no máximo `CONTINUACOES_SEM_O_DONO` (2) vezes seguidas; depois, só perguntar ou encerrar. O «sim» do dono zera. O «não» ou o silêncio volta ao motor, que escreve o fim.
- No `MotorDoObjetivo`, sem saída, nada feito, afirmação sem confirmação, resposta vazia e falta de conferência viram evento numa rodada do motor (`_explicar`), sem frase do código.

### 2. Execução sempre delegada (`2d55f21`)

- `PASSOS_NO_TURNO = 0`: toda ação no computador (clicar, digitar, abrir, enviar, pesquisar, rodar comando, `delegar.claude_code`) vai ao subagente desde o primeiro passo. No turno ficam só as consultas do próprio Jarvis (`FICAM_NO_TURNO`, `memoria.*`).
- O código não diz nada ao delegar; a recusa do teto de tarefas volta ao motor como resultado.
- O progresso volta como evento: `GestorDeTarefas.ao_progresso` → `Cerebro.andamento`, nota **SUBAGENTES EM ANDAMENTO** em todo turno; a cada 45 s, um evento na fila, e o Jarvis decide se conta.
- O subagente lê a página antes do primeiro clique, escolhe o alvo pelo que está nela, relê para conferir e depura no erro: está na nota da tarefa e é garantido pela guarda de leitura (ADR-0069 §2), não por um roteiro.

### 3. Redes sociais por agente monitor (`7ff9a17`)

- A extensão manda, de cada conversa não lida, o trecho que a lista mostra e os rótulos dos ícones — evidência crua (ponte versão 6).
- O monitor entrega `Notificacao.evento` estruturado; o nome ou trecho que tenta dar ordens vai marcado como `suspeito`, sem o texto (ADR-0065).
- `social/agente.AgenteMonitor` classifica cada conversa (mensagem, ligação, notificação do sistema, outra) e a urgência observada, numa rodada de modelo; sem modelo, segue `nao_classificado`.
- Ausente, madrugada, não perturbe e «não avisa» viram **contexto** do evento (`contexto_do_dono`), não filtro. As travas do envio autônomo (lista, ausente, tetos, madrugada, pausa de 24 h) ficam como estão.

### 4. Caminho rápido vira dica; roteiro vira orientação

- A regra do caminho rápido (`politica/atalho.achar`) continua reconhecendo o comando simples, mas não executa nem fala: vira **DICA DO CÓDIGO** no prompt (ferramenta e argumentos que ela acharia), e o motor decide.
- O roteiro de passos numerados do navegador virou **orientação** (`ORIENTACAO`: ler antes de agir, escolher pelo que está na página, reler, depurar) e, num envio, os **fatos** que o código resolveu (rede, contato das memórias, o que o dono quer dizer, se ditou literal) e as travas (conferir o contato no cabeçalho antes de digitar, conferir o envio depois).

## Alternativas descartadas

- **Manter a frase do código como reserva quando o motor cai:** é o código falando pelo Jarvis de novo. Sem motor, o evento fica no card e na tela.
- **Um classificador por regex para mensagem × ligação:** é o mesmo erro do caminho rápido. A extensão coleta a evidência; o agente decide.
- **Cobrar o motor a cada passo da tarefa com uma rodada de voz:** custo de uma chamada ao modelo por passo. O progresso vai como nota a todo turno e, como evento, a cada 45 s.

## Consequências

- Cada aviso e cada fim de tarefa custa uma rodada do motor a mais (o turno de eventos); o pedido de um passo («abre o Discord») passa pelo subagente e chega ao dono como evento: mais latência que o caminho rápido de antes, em troca de o Jarvis decidir.
- O teto de continuações sozinho (2) e o teto de tarefas ao mesmo tempo seguram o custo sem escrever frase.
- Os testes do caminho no turno fixam `passos_no_turno=2` de propósito: o caminho existe no código, mas a produção não o usa mais para execução.

## Pendências (cabem na regra; não feitas aqui)

Da auditoria, com o motivo de cada uma estar fora: abrir o navegador fechado ainda é feito pelo código no turno e na tarefa (d4); a ferramenta rápida depois do «sim» falado roda no turno (d5); `escolher_metodo` ainda tira ferramentas por palavra-chave (c3); o veto da mensagem copiada (c5) e o filtro `_PEDE` que corta toda pergunta do motor (c7) seguem como estão; a frase da ação de um passo e o fim do turno pelo código (c2/c8) só valem no caminho no turno; receitas por palavra-chave (c9), a frase do comando de estilo (c11) e as respostas a pendência do `fluxo_de_acao` («Tudo bem, paro por aqui.», a16) seguem do código; os parciais do Claude Code delegado (`stream-json`, d7); «não perturbe» ainda filtra na fila (b9); o agente monitor não lê a página por CDP — usa a leitura do content script.

## Como testar

`tests/unit/s2/test_avisos.py`, `test_andamento.py`, `test_teto_da_tarefa.py`, `test_caminho_rapido.py`, `test_roteiro_do_navegador.py`; `tests/unit/tarefas/test_limite.py`, `test_gestor.py`; `tests/unit/social/test_agente.py`, `test_monitor.py`, `social.test.mjs` (página falsa com ligação perdida); `tests/unit/voz/test_app.py` (evento de rede na fila com o contexto). Tudo com fakes: nenhum teste abre navegador, conta, microfone ou áudio reais.

## Como invalidar esta decisão

Se a trilha mostrar o Jarvis calando (`jarvis_calou`) a resposta de um pedido que o dono esperava ouvir, a nota dos eventos muda (o modelo é instruído a falar o resultado de um pedido do dono); se mostrar `tarefa.limite` com `decisao=continuar` repetido em tarefas que o dono diz que não avançavam, o teto de continuações sozinho cai para 1.

## Emendas

- **2026-11-15 — rodada 2** (pedido do dono: «sua lista de pendentes é exatamente o tipo de automação que o dono não quer»). Grupo A (`c16d79a`): sem frase do código depois da ação de um passo e sem o código encerrar o turno; a resposta à pendência, a troca de estilo e a de modo viram evento e o Jarvis responde (`Cerebro._responder_ao_evento`); a pergunta da pendência é escrita por ele (`Cerebro._perguntar_ao_dono`); o filtro `_PEDE` não corta mais a pergunta dele. Grupo B (`649061f`): o método e as receitas viram dica (nenhuma ferramenta recusada nem tirada do motor), saiu o veto por regex da mensagem copiada, e o «sim» falado manda a ação ao subagente. Grupo C (`a9d499f`): o código não abre mais o navegador fechado (o motor recebe o fato e decide), os parciais do Claude Code delegado vêm em `stream-json` e vão ao Jarvis como eventos, e «não perturbe» vira contexto do aviso (só a privacidade segura a voz).
- **Não feito, de propósito: o agente monitor ler a página das redes por CDP.** Anexar o depurador à aba da rede a cada notificação é o risco de detecção e banimento que a ADR-0060 restringe ao envio (CDP só durante o envio, sem ligar domínio nenhum). O agente segue com a leitura do content script (a prévia e os ícones de cada linha). Volta se o dono aceitar esse risco explicitamente.
- **Ainda pendente:** o corte por prazo do turno acaba sem rodada final do motor; o `--max-turns` esgotado do Claude Code volta como falha (os parciais já enviados ficam com o Jarvis); e o caminho no turno com `passos_no_turno > 0` existe no código e nos testes, mas a produção não o usa para execução.

