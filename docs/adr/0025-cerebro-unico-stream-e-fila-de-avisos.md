# ADR-0025 — Cérebro único: conversa contínua, stream S2→TTS interrompível e fila de notificações

**Data:** 2026-10-16 · **Estado:** aceita para implementar a fatia mínima — pelo diretor, em
2026-10-16, em nome do dono; **o dono pode revisar** · **Decide:** dono (os requisitos marcados
**DECISÃO DO DONO**, já dados; aceitar esta ADR), planejador (o contrato, os tetos e a ordem)
**Pedido:** respostas do dono de 2026-10-16 (memórias `34d72b96` e `c2bb11f8`), dadas sobre as
ADRs 0022–0024. Emenda a SPEC §2, §3.2, §3.3 e §3.4 e substitui a regra 7 da ADR-0022. Mede o
que existe hoje em `docs/medicoes/s2-provisorio-primeira-fala.md`.

## Contexto

### O que o dono decidiu (não é proposta)

- **DECISÃO DO DONO — um cérebro, conversa contínua.** Não é processamento individual por
  pedido: é uma conversa que continua, interrompível, com resposta rápida, e "pensar" só quando
  necessário. Natural e instantâneo.
- **DECISÃO DO DONO — resposta em streaming.** O Jarvis começa a falar enquanto ainda gera. Se o
  dono interromper, ele para de falar **e de gerar**.
- **DECISÃO DO DONO — aviso de tarefa ou evento.** O Jarvis recebe a notificação e **decide
  sozinho** se avisa e como, sem depender de o dono falar primeiro. Nunca corta fala em
  andamento: o aviso fica em fila até o TTS parar ou o dono mandar mensagem; aí vai junto com a
  mensagem — o Jarvis informa e depois continua respondendo. Também pode mostrar um card na
  tela.

O resto desta ADR é o desenho que cumpre isso. Cada escolha de desenho está justificada; nenhuma
delas é do dono, salvo as perguntas do fim.

### O que já existe (lido no código em 2026-10-16, `bdc1ac6`)

- **TTS em streaming cancelável** (`src/jarvis/agentd/tts.py`): `SintetizadorEmStreaming.pedacos`
  recebe o **texto inteiro** e o fatia com `fatiar()` (primeiro pedaço de 3 palavras ou até a
  primeira pontuação; os outros de 8), consultando `cancelado()` antes de sintetizar e antes de
  entregar cada pedaço. `Fala.texto_ate(amostras_tocadas)` devolve o texto que de fato tocou (P4).
  Falta: aceitar texto que **ainda está chegando**.
- **Epoch e cancelamento** (ADR-0002, `src/jarvis/barramento/epoch.py`): `speech_started` sobe o
  epoch e emite `Cancel`; o motor de voz recebe o cancelamento como pergunta
  (`Cancelado = Callable[[], bool]`, emenda da ADR-0017).
- **S2 provisório** (ADR-0018, `src/jarvis/voz/s2_provisorio.py`): `responder(texto) -> str`, um
  processo `claude --print --output-format text` por pedido; cancela matando o processo. Não há
  stream nem histórico: cada pergunta chega sozinha.
- **Vocabulário fechado do Workspace** (ADR-0019, emenda; `src/jarvis/gui/acoes.py` e
  `componentes.py`): oito ações (`createWidget`, …) e um catálogo de componentes que já tem
  `notificacoes` e `tarefas`. Card de aviso cabe nisso sem ação nova.

### O que foi medido hoje (`docs/medicoes/s2-provisorio-primeira-fala.md`)

Observação de `n` pequeno, rede doméstica, Ryzen 5 5600G, Claude Code `2.1.302`, repositório em
`bdc1ac6`. Mediana do tempo até a **1ª fronteira** de fala (o que o `fatiar()` precisa para
sintetizar o primeiro pedaço), contada da escrita da pergunta:

| série | n | 1ª fronteira (mediana) | mín–máx |
|---|---:|---:|---:|
| avulso (um processo por pergunta), `haiku` | 10 | 1388 ms | 1181–2279 ms |
| contínuo (um processo, `--input-format stream-json`), `haiku` | 10 | 992 ms | 860–1822 ms |
| contínuo, `sonnet`, `--effort low` | 6 | 1050 ms | 797–2091 ms |
| avulso, modelo padrão da conta | 6 | 2021 ms | 1224–2919 ms |
| contínuo, modelo padrão da conta | 6 | 2330 ms | 1082–3727 ms |

E três fatos de cancelamento, `n = 1`: no modo contínuo, `control_request` com `subtype:
interrupt` encerra o turno em **8 ms**, o processo **continua vivo**, e a conversa da CLI
**guarda o texto gerado até o corte** — que é mais do que tocou no alto-falante.

### O que isso diz sobre o SLO-5

SLO-5 (§7): fim de turno aceito → primeiro áudio em até 600 ms na mediana e 900 ms no p95. Depois
do turno aceito vêm: montar o contexto, o motor chegar à 1ª fronteira, o TTS sintetizar o 1º
pedaço (piper: 116 ms de mediana e 145 ms de p95, piso medido na F1-09, `docs/medicoes/f1-09-tts.md`)
e a fila do dispositivo (não medida).

- **O `claude -p` não cabe no SLO-5 em nenhuma configuração medida.** A melhor mediana (992 ms +
  116 ms ≈ 1,1 s) já passa do p95 de 900 ms.
- **Orçamento do motor definitivo**, por subtração: 900 − 145 (TTS) − 100 (montagem) − 50
  (dispositivo) ≈ **600 ms de p95 até a 1ª fronteira**, e ≈ 330 ms de mediana (600 − 116 − 100 −
  50). **[SUPOSIÇÃO: os 100 ms de montagem e os 50 ms de dispositivo são reserva, não medida;
  confirma ou derruba o harness da fatia mínima, que mede os quatro trechos separados.]**
- Contínuo é ~400 ms mais rápido que avulso no `haiku` (sem abrir processo por pergunta), e o
  esforço de raciocínio pesa mais que o tamanho do modelo: `sonnet` com `--effort low` ficou perto
  do `haiku`; o modelo padrão com o esforço padrão ficou em mais de 2 s.

## Três desenhos comparados

**A — um processo por pedido (o de hoje).** Cada turno abre o motor, manda a pergunta, espera.

**B — a sessão do motor é a conversa.** Um processo de motor vivo, com a conversa guardada nele
(o modo contínuo da CLI, uma sessão com estado no servidor, um contexto de KV mantido no motor
local).

**C — a conversa é nossa, o motor é sem estado.** O `s2` mantém a conversa (estado de trabalho da
§3.4 + histórico no `memoryd`, ADR-0026) e manda ao motor, em cada pedido, o contexto montado por
nós: prefixo estável (instrução de sistema, tools do núcleo) que o motor pode guardar em cache,
mais o trecho variável (conversa com o texto **tocado**, evidências, avisos pendentes, o turno).

| Critério | A | B | C |
|---|---|---|---|
| Conversa contínua | não | sim | sim |
| P4: só entra no histórico o que tocou | não se aplica (sem histórico) | **viola**: a sessão do motor guarda o gerado (medido na CLI) e não dá para reescrever a última resposta | cumpre: nós mandamos o texto tocado |
| Trocar o motor no meio da conversa (local↔nuvem) | sim | perde a conversa | sim |
| Cancelar sem perder a conversa | sim | só se o motor tiver interrupção que preserva a sessão | sim: matar o pedido não toca a conversa |
| Custo do primeiro token | o maior (abre processo) | o menor | perto do B quando o motor tem cache de prefixo |
| Replay (P10) | trivial | depende do motor | trivial: o contexto de cada pedido é nosso e vai para o log |

## Decisão

**Desenho C: um `s2` vivo por sessão, dono da conversa; motores de conversa sem estado atrás de
uma interface de streaming cancelável; o texto sai em pedaços com epoch para o TTS; e os avisos
esperam o piso livre numa fila do `agentd`.**

### Regras do cérebro

1. **Um cérebro.** O `s2` é um processo longo, com **uma** conversa por sessão, acordado por
   evento (§2, sem laço cego): `FinalTranscript` ou texto digitado, `ToolResult`,
   `NotificationRelease`. Tarefa delegada (ADR-0022) não é outro cérebro conversando com o dono:
   é trabalho de fundo que volta como aviso.
2. **A conversa é nossa.** O que o motor recebe é montado pelo `s2` a cada pedido e registrado
   (por hash, com o conteúdo no `memoryd`) para o replay. O motor não guarda estado de que a
   conversa dependa; cache de prefixo dele é otimização descartável.
3. **Só o tocado volta ao contexto (P4).** A resposta interrompida entra na conversa como
   `Fala.texto_ate(amostras_tocadas)`, marcada "interrompida pelo dono". O texto gerado e não
   tocado vai para a auditoria e não volta para o modelo. "Continua" segue a regra 5 da §3.3.
4. **Rápido por padrão, pensar quando precisa.** Todo turno começa no modo `rapido` (menor
   esforço de raciocínio que o motor oferece). O motor pode devolver o sinal `pensar` em vez de
   texto; o `s2` então solta uma **ponte** (regra 8) e refaz o mesmo turno no modo `pensar`, com
   teto de tokens e de tempo vindo de configuração. O texto de raciocínio **nunca** vai para o TTS
   nem para a UI (P10). O barge-in cancela o `pensar` como cancela o resto. Quem decide pensar é o
   modelo; quem limita é o código. **[SUPOSIÇÃO: o sinal `pensar` vindo do próprio motor acerta o
   bastante para não precisar de classificador antes; confirma ou derruba o corpus da F2, contando
   turnos que pediram `pensar` sem precisar e turnos errados que não pediram.]**
5. **Contexto com orçamento fixo.** Instrução de sistema e tools do núcleo no prefixo estável;
   depois resumo da conversa, os últimos turnos estáveis (§3.4 `fala_ouvida`), as evidências da
   memória no degrau 0–1 (§6.8) e os avisos liberados. A memória **não atrasa** a voz: o que não
   chegou até o prazo de montagem fica de fora e o modelo pode pedir com as tools da ADR-0026.

### Contrato do stream S2 → TTS

6. **Interface do motor de conversa** (mesmo padrão dos motores de voz da ADR-0017):
   `gerar(contexto, modo, cancelado) -> Iterator[Delta]`, com `Delta` = `Texto(str)` |
   `PedidoDeTool(tool_id, args)` | `Pensar(motivo)` | `Fim(motivo, uso)`. O motor declara `onde`
   (local/nuvem) e entra no mesmo portão de registro e de egress dos motores de voz. O motor não
   conhece epoch: recebe a pergunta `cancelado()`.
7. **Evento novo `ResponseChunk`** (`s2`, P1): `response_id`, `turn_id`, `epoch`, `seq`, `text`,
   `boundary: frase|virgula|limite|fim`, `last: bool`, `end_reason?:
   concluido|erro|prazo`, `notif_ids?: []`. O `s2` **junta os deltas até a fronteira** e
   publica um evento por pedaço de fala, não por token: são de 3 a 10 eventos por resposta, e não
   centenas — o mesmo motivo de orçamento que tirou o PCM do barramento (ADR-0015). A regra de
   fronteira é a do `fatiar()` (1º pedaço com 3 palavras ou até a 1ª pontuação; os seguintes até 8
   palavras ou pontuação), movida para uma função **incremental** usada pelos dois lados, para não
   haver duas regras de corte.
8. **Ponte**: se a 1ª fronteira não chegou até o prazo da ponte (configurável; proposta 700 ms
   **[SUPOSIÇÃO: confirma ou derruba o teste de ouvido do dono no `jarvis-voz`]**), o `s2` publica
   **uma** ponte curta de uma lista fechada ("hum", "deixa eu ver"), sem conteúdo. No máximo uma
   por turno; entra no histórico como qualquer fala tocada. É a "ponte curta" que a §7 já prevê no
   SLO-5, e não é resposta inventada (P9).
9. **Cancelamento com epoch.** `Cancel(epoch)` faz, nesta ordem: (a) o `audio-io` esvazia a fila
   (já existe); (b) o `s2` para de publicar `ResponseChunk` daquele epoch — o que já saiu é
   descartado pela regra 6 da §3.3; (c) o `s2` cancela o pedido ao motor **em até 50 ms** (uma
   consulta de `cancelado()`, o mesmo intervalo do provisório); (d) o `s2` grava na conversa só o
   tocado (regra 3). **[Ajuste da implementação, 2026-10-16:]** não há `ResponseChunk` com
   `end_reason: cancelado` — publicá-lo seria publicar no epoch morto, o que o item (b) proíbe; o
   fim por cancelamento fica na conversa e na `Resposta` do `s2` (auditoria local). `boundary`
   ganhou `fim`: o último pedaço pode sair vazio, quando a resposta acabou numa pontuação.
10. **O TTS consome pedaços.** O `SintetizadorEmStreaming` passa a aceitar um iterador de
    `ResponseChunk` do epoch corrente, além do texto inteiro; o resto (cancelamento antes e depois
    de sintetizar, `Fala.texto_ate`) não muda.

### O que cada motor precisa suportar

| Requisito | `claude -p` (provisório) | API HTTP (Anthropic e semelhantes) | Local (servidor llama.cpp, Ollama) |
|---|---|---|---|
| (a) texto incremental | sim: `--output-format stream-json --include-partial-messages` (medido) | sim: SSE com `text_delta` e `thinking_delta` (documentação de streaming) | sim: SSE ou NDJSON |
| (b) parar a geração | `interrupt` em 8 ms (`n = 1`) ou matar o processo; se o servidor para de cobrar: **não verificado** | fechar a conexão; a página de streaming consultada não diz o que o servidor faz com a geração abandonada: **não verificado** | fechar a conexão; a documentação consultada não garante parada em toda versão: **não verificado** |
| (c) sem estado (desenho C) | avulso sim; contínuo **não** (a CLI guarda o gerado) | sim: a conversa vai em cada pedido | sim: o prompt vai em cada pedido |
| (d) cache de prefixo | não controlável pela CLI | sim; mudar a definição de tools invalida o cache inteiro, mudar o raciocínio invalida as mensagens (documentação de *prompt caching*) | sim: `cache_prompt` reaproveita o KV (README do servidor llama.cpp) |
| (e) tool estruturada | **não** (ADR-0018: sem ferramenta) | sim (`tool_use`) | depende do modelo; gramática restrita no llama.cpp |
| (f) raciocínio controlável (`rapido`/`pensar`) | `--effort` | `effort` / orçamento de raciocínio | depende do modelo |
| (g) 1ª fronteira dentro de ~600 ms de p95 | **não** (melhor mediana 992 ms) | não medido | não medido |

Requisito que vale para todos e vira teste: **depois do cancelamento, 0 `ResponseChunk` do epoch
morto e o motor sem gerar** — medido contando deltas recebidos e, onde o motor informar, tokens de
saída cobrados depois do corte.

### Fila de notificações

11. **Evento novo `Notification`** (P3), publicado por quem tem algo a avisar — `tarefas`
    (ADR-0022, nas transições `Succeeded`, `Failed`, `AwaitingApproval`), `executor`, cliente MCP
    (ADR-0023): `notif_id`, `origem`, `task_id?`, `tipo: concluida|falhou|precisa_decisao|evento`,
    `resumo_ref`, `trust` herdado da origem (resultado de tarefa é `third_party`). Nunca emite
    `Cancel`.
12. **A fila mora no `agentd`**, porque só ele sabe se o piso está livre: fala do dono
    (`AudioActivity`), TTS tocando (`PlaybackProgress`), decisão do S1. O `agentd` publica
    **`NotificationRelease`** (P3) com `notif_ids` e `motivo`: `piso_livre` (playback terminou e
    nenhuma fala do dono por um intervalo configurável) ou `mensagem_do_dono` (chegou
    `FinalTranscript` ou texto digitado; leva o `turn_id`).
13. **O `s2` decide** (DECISÃO DO DONO): falar, mostrar card, os dois, ou calar. Com
    `mensagem_do_dono`, a resposta começa pelo aviso, curto, e segue respondendo a mensagem
    (DECISÃO DO DONO). Card é `createWidget` do componente `notificacoes` ou `tarefas`, que já estão
    no catálogo — não há ação nova. O card pode aparecer **antes** do piso livre, porque não corta
    fala; a voz espera o `NotificationRelease`.
14. **O que o código impõe por cima do julgamento:** `precisa_decisao` sempre gera card (a
    confirmação é na UI, §5.3); "não perturbe" = só card, nunca voz; botão de privacidade = nada em
    voz; teto de avisos falados por intervalo **[SUPOSIÇÃO: 1 a cada 2 min; confirma ou derruba o
    uso, contando avisos que o dono interrompeu]**; aviso que o modelo calou continua na lista de
    notificações da UI — nada some sem rastro.
15. **Entregue é o que tocou (P4).** O `ResponseChunk` que fala do aviso carrega `notif_ids`. Se o
    dono cortar antes de o aviso tocar, ele volta para a fila. Conteúdo de aviso vindo de tarefa é
    evidência, não instrução (ADR-0022 regra 6).

**Emendas que esta ADR pede quando aceita:** SPEC §2 (o `s2` é um processo de conversa contínua e
publica pedaços de fala), §3.2 (`ResponseChunk`, `Notification`, `NotificationRelease`), §3.3
regra 2 (o que "`s2` cancela geração" exige) e §3.4 (`modo`, `avisos_pendentes`). ADR-0022: regra
7 substituída pelas regras 11–15. ADR-0018: a interface `responder(texto) -> str` é substituída
pela da regra 6 quando a fatia mínima entrar; a ADR-0018 continua valendo até lá para o
`jarvis-voz`.

## Ajustes da implementação (2026-10-16, fatia 4: fila de avisos)

`jarvis.agentd.fila_de_avisos` (a fila), `jarvis.s2.avisos` (a decisão de entrega e a frase),
`Cerebro.responder(avisos=…)` e `Cerebro.avisar` (a fala), `fala_em_stream.avisos_tocados` (o
que tocou). O que mudou em relação ao texto das regras 11–15:

1. **`Notification` leva `resumo` em texto** (até 280), e não só `resumo_ref`: o card e a voz
   precisam de algo legível, e buscar o texto em outro lugar a cada aviso seria uma segunda
   leitura no caminho da fala. A origem `tarefas` entra no contrato quando o processo da
   ADR-0022 existir (a lista de fontes da §3.1 ainda não o tem).
2. **O teto de 2 min (D22) vale para o aviso espontâneo**, não para o que vai junto com a
   mensagem do dono: ali quem abriu a conversa foi ele, e segurar o aviso esconderia o que ele
   decidiu que quer saber. Espontâneo, sai **um por vez**: com um aviso liberado e ainda não
   tocado, cortado ou decidido, a fila não libera outro (defeito que o teste pegou).
3. **A frase do aviso é montada pelo código**, a partir do `resumo`, e sai antes da resposta em
   pedaços marcados com `notif_ids`; o motor recebe, no contexto, que o aviso já foi dito e
   responde à mensagem. Sem isso não há como saber se o aviso **tocou** (regra 15). Resumo de
   terceiros é dito como de terceiros ("Aviso de mcp · arquivos: …"). O julgamento do modelo
   entra por `julgar` (falar, só card, calar); `precisa_decisao` nunca é calado.
4. **Card:** `FilaDeAvisos.dados_do_card()` devolve `{"avisos": [...]}` no contrato que o
   componente `notificacoes` já valida (`tipo`, `origem`, `resumo`, `instante`, `entrega`,
   `confianca`); o teste passa os dados pelo próprio `validar_dados` da janela. **Não ligado na
   janela:** quem troca os dados de demonstração pelos da fila é a `ponte`, que é da CLI da
   janela. E o vocabulário fechado não tem ação para **atualizar os dados** de um widget já
   criado: `createWidget` de novo cria outro. É preciso uma ação nova (emenda da ADR-0019) ou
   uma regra de "mesmo componente substitui" no `Workspace`.

Testado sem rede e sem microfone: fila (`tests/unit/agentd/test_fila_de_avisos.py`), `s2`
(`tests/unit/s2/test_avisos.py`) e uma hora simulada com 50 avisos e barge-in
(`tests/integration/test_fila_de_avisos_ponta_a_ponta.py`, aceites (d), (e) e (f)): nenhuma
liberação com o dono falando, com TTS tocando ou com menos de 1,5 s de silêncio; espontâneos com
2 min de distância; a mensagem do dono leva todos os pendentes; aviso cortado volta, e nenhum se
perde. **Não ligado:** os processos `agentd` e `s2` reais pelo barramento (a fila e o cérebro
rodam em biblioteca), e o "não perturbe" não tem interruptor na UI.

## Ajustes da implementação (2026-10-17, fatia 5: a janela)

- **O `Aplicativo` (o laço do `jarvis-voz` e da janela) responde pelo `Cerebro`.** O motor gera
  numa linha de execução; o laço, que é o dono do epoch e da fila, sintetiza e toca cada
  `ResponseChunk` assim que chega, olhando o teclado entre os quadros. A interface
  `responder(texto) -> str` da ADR-0018 sai do laço, como esta ADR previa; a ADR-0018 continua
  valendo para o motor `claude -p`, que segue provisório.
- **Motor padrão é o eco** (`s2 = "eco"`, sem rede); o `claude -p` só roda com `s2 = "claude"`
  escolhido pelo dono, e a tela diz `[nuvem]` ao lado do nome (D18).
- **A janela mostra a resposta crescendo** (porta `ao_pedaco` do laço) e troca a linha parcial
  pela final; o estado do núcleo (pensando → falando → repouso) vem do laço, e `falando` só
  começa no primeiro pedaço de áudio pronto. O "interromper" da janela mata o epoch: o cérebro
  fecha o motor e a fila descarta o que não tocou (teste: cancelamento durante o "pensando",
  com motor de 6 s, volta em menos de 1 s).
- **A fila de avisos mora no laço**, que no app faz o papel do `agentd`: a janela não importa
  `agentd` nem barramento (teste de fronteira da ADR-0019). O card `notificacoes` mostra a fila
  pelo `updateWidget` com `dados_reais`, sem o selo de demonstração; o roteiro não escreve mais
  avisos inventados nele. Falha da conversa e do motor entram como aviso `falhou`, só no card.
- **Não feito:** a fila do laço ainda não libera avisos para a voz (`NotificationRelease` →
  `Cerebro.avisar`) — no app, os avisos ficam no card; e não há produtor real de avisos além das
  falhas, porque ainda não há tarefa (ADR-0022) nem cliente MCP (ADR-0023).

## Decisões do diretor (2026-10-16)

Decisões do diretor de 2026-10-16 (o dono delegou "siga a partir daí"); o dono pode revisar qualquer uma delas.

- **D16 — esta ADR:** aceita para implementar a fatia mínima.
- **D18 — motor do cérebro:** medir um motor local **e** um de API de nuvem no harness da
  fatia mínima e escolher pelo número: o local, se couber em ~600 ms de p95 até a 1ª fronteira.
  O `claude -p` fica só como provisório e de teste.
- **D22 — limiares:** os propostos — ponte aos 700 ms sem 1ª fronteira (regra 8); no máximo 1
  aviso falado a cada 2 min (regra 14); piso livre depois de 1,5 s sem fala após o fim do
  playback (regra 12). Ficam em configuração, não no código.

## Alternativas descartadas

- **B, a sessão do motor como conversa** — viola o P4 (medido: a CLI guarda o gerado, não o
  tocado) e prende a conversa a um motor, o que contradiz o motor configurável que o dono pediu.
  Volta se algum motor permitir reescrever a última resposta da sessão e isso for mais rápido que
  o cache de prefixo do C.
- **Publicar cada token no barramento** — dezenas a centenas de eventos por resposta com envelope,
  validação e log encadeado; a ADR-0015 mediu 0,384 ms por evento. O TTS não usa token solto: ele
  precisa de fronteira.
- **Dois cérebros (um rápido que responde e um lento que pensa)** — é o "processamento individual
  por pedido" que o dono recusou, e cria duas conversas para reconciliar. O modo `pensar` no mesmo
  cérebro e na mesma conversa dá o mesmo ganho de latência sem a reconciliação.
- **Aviso interrompendo a fala com prioridade alta** — o dono decidiu que não.
- **Fila no `s2`** — o `s2` não vê o áudio; teria de assinar `AudioActivity` e `PlaybackProgress`
  para saber do piso, duplicando o que o `agentd` já decide.

## Consequências

- Fica mais fácil: trocar de motor sem perder a conversa; replay de cada pedido; medir cada trecho
  da latência separado.
- Fica mais caro: o contexto vai inteiro em cada pedido (mitigado por cache de prefixo onde
  existe); três tipos de evento novos; o `fatiar()` vira incremental.
- **O S2 provisório não serve para julgar o SLO-5**: o dono vai ouvir mais de 1 s até a primeira
  palavra com a CLI. Isso é do motor, não da voz, e o relatório do `jarvis-voz` já separa os
  tempos.
- Passa a ser obrigatório testar: nenhum pedaço de epoch morto toca; o motor para de gerar; o
  histórico só tem o tocado; nenhum aviso por cima da fala do dono.

## Riscos

| Risco | Controle |
|---|---|
| Nenhum motor cabe nos ~600 ms até a 1ª fronteira | regra 8 (ponte) e regra 4 (rápido por padrão); o harness da fatia mede cada motor antes da escolha |
| O motor continua gerando e cobrando depois do cancelamento | teste de aceite (c), por motor; motor que não para de gerar não entra no registro como motor de conversa |
| Ponte vira tique verbal | uma por turno, lista fechada, teste de ouvido do dono |
| Contexto cresce até estourar o orçamento | regra 5 (orçamento fixo); resumo da conversa feito fora do caminho da voz |
| Aviso nunca sai porque o dono fala sem parar | `mensagem_do_dono` também libera; card aparece na hora |
| O modelo cala aviso que importava | regra 14: `precisa_decisao` sempre gera card; lista na UI |

## Fatia mínima (implementar primeiro)

1. A interface da regra 6 com dois motores: **stub determinístico** (texto roteirizado entregue em
   deltas com atraso configurável, para testar sem rede) e o `claude -p` em
   `--output-format stream-json`, avulso, recebendo o contexto montado por nós em `stdin`.
2. `fatiar` incremental, `ResponseChunk`, e o `SintetizadorEmStreaming` consumindo pedaços.
3. Cancelamento da regra 9 e a conversa do `s2` com o tocado (regra 3), ainda em memória; a
   gravação em disco é a fatia M1 da ADR-0026.
4. Fila de notificações com um produtor de teste (sem a ADR-0022): `Notification`,
   `NotificationRelease`, o card `notificacoes`.
5. Harness que publica em `docs/medicoes/` os quatro trechos do SLO-5 por motor (montagem, 1ª
   fronteira, TTS, dispositivo quando houver), com `n`, hardware e commit.

## Teste de aceite

- **(a)** Interromper em 20 pontos de uma resposta em stream (motor stub): 0 pedaços de epoch
  morto tocados, 0 `ResponseChunk` de epoch morto aceitos, e a conversa contém só o tocado em
  20/20.
- **(b)** O mesmo com o `claude -p` em stream: 20/20, e o tempo do `Cancel` ao fim do pedido
  publicado.
- **(c)** Por motor candidato: deltas recebidos depois do cancelamento, e tokens de saída cobrados
  depois do corte quando o motor informar. Publicado; o motor que não para fica fora.
- **(d)** 50 notificações em instantes aleatórios com fala do dono simulada: 0 avisos sobrepostos à
  fala; o aviso sai até 2 s depois do piso livre ou na resposta à mensagem seguinte.
- **(e)** Aviso cortado pelo dono antes de tocar volta para a fila em 100% dos casos.
- **(f)** `precisa_decisao` com "não perturbe": card em 100%, voz em 0%.
- **(g)** Turno com sinal `pensar`: a ponte toca uma vez, o texto de raciocínio não aparece no TTS,
  na UI nem no histórico.
- **(h)** Trocar o motor entre dois turnos: o terceiro turno responde a uma referência do primeiro
  ("e o outro?") — a conversa sobreviveu à troca.

## Como invalidar esta decisão

- Um motor com sessão própria (desenho B) que permita reescrever a última resposta e entregue a 1ª
  fronteira mais rápido que o C com cache: o B volta a ser medido.
- O harness mostra que montar o contexto por pedido custa mais que o orçamento de 100 ms mesmo com
  cache: a regra 2 é revista para um contexto incremental.
- O dono, ouvindo, prefere aviso imediato para algum tipo: a regra 12 ganha exceção por tipo, por
  decisão dele.

## Fontes (acesso em 2026-10-16)

- Medição desta ADR: `docs/medicoes/s2-provisorio-primeira-fala.md`; piso do TTS:
  `docs/medicoes/f1-09-tts.md`.
- Claude Code `claude --help` (versão 2.1.302): `--output-format stream-json`,
  `--include-partial-messages`, `--input-format stream-json`, `--effort`, `--tools`.
- Streaming da API: <https://platform.claude.com/docs/en/build-with-claude/streaming> — eventos
  `content_block_delta` com `text_delta`/`thinking_delta`, `ping`, `error` no meio do stream.
- *Prompt caching*: <https://platform.claude.com/docs/en/build-with-claude/prompt-caching> —
  ordem `tools`, `system`, `messages`; "Modifying tool definitions (names, descriptions,
  parameters) invalidates the entire cache"; mínimo de 512 tokens nos modelos 5.x; vida de 5 min.
- Servidor llama.cpp: <https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md>
  — `cache_prompt` ("Re-use KV cache from a previous request if possible"), padrão `true`.
