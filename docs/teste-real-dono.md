# Teste real do dono: os cinco casos (Jarvis agente, ADR-0070)

**Ligado a:** [ADR-0070](adr/0070-o-jarvis-e-agente-o-codigo-entrega-eventos.md), [auditoria](estudos/auditoria-automacao.md) e [redes-sociais-teste-real.md](redes-sociais-teste-real.md) (como preparar o navegador e as redes). A prova sem a sua máquina está em `tests/e2e/` — motor, extensão e Claude Code falsos. Este roteiro é o que só a sua máquina prova.

## Antes

1. Instale o pacote de `dist-teste/` (no Nobara, o `.rpm`), reinstale o host do navegador e clique em **Recarregar** na extensão do Jarvis (passos 0.1–0.4 de [redes-sociais-teste-real.md](redes-sociais-teste-real.md)).
2. Abra o Jarvis. Se ele não abrir, o motivo está em `~/.local/state/jarvis/abertura.log` (mande o fim desse arquivo).
3. O que olhar em todos os casos: a tela do Jarvis (as linhas `Jarvis:` são o que ele falou), o card de tarefas e a trilha `~/.local/state/jarvis/voz/diagnostico/turnos.jsonl` (só códigos, nenhum texto seu).

**A regra que vale para os cinco:** toda fala é do Jarvis, com as palavras dele, e **uma por estímulo**. Se você ouvir duas respostas ao mesmo pedido, ou uma frase que soa pronta («Pronto.», «Não consegui.», «Parei o que você tinha pedido.»), anote a hora e mande a trilha.

## (a) «Jarvis, clica na conversa do Bruno» (WhatsApp Web aberto)

- **Deve:** ele não responde nada logo (o pedido foi ao subagente); na trilha, `browser.inspecionar` **antes** do primeiro `browser.click`; a conversa certa abre; só então ele diz que abriu.
- **Erro de passo:** se um aviso cobrir a lista, a trilha mostra `browser.click` com erro, **outra** `browser.inspecionar` e outro `browser.click` — ele relê e tenta de novo, não desiste no primeiro erro.
- **Não deve:** clicar pelo texto chutado sem ler; dizer «abri» antes de a leitura confirmar.

## (b) «Jarvis, manda pro Bruno no zap que vou atrasar uns dez minutos»

- **Deve:** a mensagem enviada é **escrita por ele** (algo como «Oi, Bruno! Vou me atrasar uns dez minutinhos, já chego.»), não a sua fala copiada; antes de digitar, a conversa aberta é a do Bruno (o cabeçalho); depois de enviar, ele lê a conversa e só então diz que mandou.
- **Se você ditar entre aspas** («manda pro Bruno "chego às 8"»), vai exatamente o que você ditou.
- **Não deve:** digitar em outra conversa; dizer «mandei» sem a mensagem aparecer no chat.

## (c) Alerta de rede social (agente monitor, ADR-0073)

1. Com o WhatsApp **monitorado** ([redes-sociais-teste-real.md](redes-sociais-teste-real.md) §1) e o Jarvis **calado** (sem falar nada), peça a alguém para (i) te mandar uma mensagem direta, (ii) te ligar pelo WhatsApp sem você atender e (iii) mandar uma mensagem comum num grupo.
2. Repita (ii) **enquanto o Jarvis estiver falando** (peça algo longo antes, «me conta a história do Brasil»).
- **Deve:** a mensagem direta e a ligação perdida ele avisa, com as palavras dele, **uma vez cada**, poucos segundos depois (ocioso, fala na hora); com ele falando, o aviso da ligação vem **depois** que a fala dele termina, sem cortar. O grupo ele pode deixar só no card. Na trilha, para cada evento, uma linha `monitor.decisao` (`encaminhar` ou `descartar`, com `urgencia` e `motivo`) e, para o encaminhado, `entrega` com `falada`/`jarvis_falou` ou `silenciosa`/`jarvis_calou`.
- **Não deve:** a frase antiga «WhatsApp: 2 mensagens novas — Ana (1)»; o mesmo alerta dito duas vezes; `[fora_da_forma]` no motivo da `entrega` de um aviso `rede-…`.
- **Se ele não falar:** mande as linhas `monitor.decisao` e `entrega` daquele horário — elas dizem se o monitor descartou, se o Jarvis calou ou se o motor caiu.

## (d) Limites: tentativas, passos, prazo e o Claude Code

- Peça algo que não tem como dar certo, sem risco (ex.: «clica no botão Exportar do WhatsApp Web», que não existe).
- **Deve:** depois das tentativas, ele **decide** — explica o que tentou e o erro real, ou pergunta se segue. Na trilha, `tarefa.limite` com `decisao=` (`continuar`, `perguntar` ou `encerrar`).
- **Prazo do turno:** se ele demorar mais de 90 s pensando, ele mesmo diz algo (segue em segundo plano, pergunta ou explica) — nunca silêncio com «(sem resposta: o laço de ferramentas passou de 90 s)» na tela.
- **Claude Code (se a delegação estiver ligada):** numa tarefa longa, quando ele esgotar os turnos, o Jarvis conta o que o Claude chegou a fazer e decide; nada de «o Claude Code terminou com erro».

## (e) Delegação e conversa livre

1. «Jarvis, abre o YouTube e procura o último vídeo do canal X» — e, **enquanto ele trabalha**, pergunte «que horas são?».
- **Deve:** a hora vem na hora (a conversa não espera o subagente); o resultado do vídeo vem **depois**, quando o subagente terminar, uma vez.
- **Com a delegação ao Claude Code ligada:** na tela aparece «Delegando ao Claude Code…» com um **objetivo escrito pelo Jarvis**, não a sua frase copiada; a resposta só chega depois do retorno do Claude.

## (f) Os parâmetros são do Jarvis (ADR-0071)

- **«Jarvis, o contato da minha mãe é literalmente mãe, salve para não esquecer depois»** (fale corrido, sem pausa): ele **não** abre nada; diz que guardou só depois de gravar. Na janela de memórias aparece o trecho «o contato da minha mãe é literalmente mãe». Na trilha do turno, `caracteres_do_plano` > 0 e `ferramentas` = 1 (`memoria.lembrar`).
- **Logo depois: «Jarvis, manda pra minha mãe que eu te amo»**: a tarefa abre a conversa **Mãe** (a memória de voz chega ao subagente) e manda uma mensagem redigida por ele, não a sua frase.
- **«Jarvis, manda pro João que eu tô saindo»** (sem João na lista): ele não manda para ninguém e pergunta qual é.
- **Antes, se você der o OK de gastar crédito:** `uv run --frozen python -m tools.avaliar_parametros --motor real --saida docs/medicoes/parametros-do-modelo.md`. São 40 falas contra uma página falsa (nada seu é tocado). Rode também com `--sem-raciocinio-escondido`, para medir o 1º token sem o raciocínio escondido.

## O que mandar se algo der errado

O horário, o que você disse, o que ouviu, e os arquivos `turnos.jsonl` (só códigos) e `abertura.log` (sem segredos: as chaves saem redigidas).
