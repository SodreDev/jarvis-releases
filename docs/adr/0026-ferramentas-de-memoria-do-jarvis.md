# ADR-0026 — Ferramentas de memória do Jarvis: histórico e memória por capacidade tipada, com proveniência e confirmação

**Data:** 2026-10-16 · **Estado:** aceita para implementar a fatia mínima — pelo diretor, em
2026-10-16, em nome do dono; **o dono pode revisar** · **Decide:** dono (aceitar; retenção do histórico;
memória para motor de nuvem), planejador (o conjunto de tools, as classes de risco e a ordem)
**Pedido:** resposta do dono de 2026-10-16 (memória `34d72b96`): **DECISÃO DO DONO** — o Jarvis
tem histórico de conversas e contexto e, como a MCP do Orchestrator, lê mensagens passadas do
chat, grava, altera e cria grafos e memórias, e lembra delas. Detalha a SPEC §6 (que já decide o
livro-razão, o grafo, o esquecimento e os gates) do lado de **quem chama**: o cérebro da ADR-0025.

**Por que é uma ADR separada da 0025:** a 0025 decide como o cérebro conversa (latência, stream,
cancelamento, avisos); esta decide o que ele pode ler e escrever da vida do dono. Os riscos são
outros (P6, P7, P8, egress de dado pessoal), os gates são outros (§6.6) e a ordem de entrada é
outra (esta depende da cifra do livro-razão; aquela não). Fundir as duas faria o aceite de uma
esperar o da outra.

## Contexto

- **O livro-razão já existe** (`schemas/memoria.sql`, F0-05): `episode` com `trust`,
  `pii_class`, `retention_until` e `raw_cipher_ref`; `assertion` com `status`
  (`proposed|active|superseded|retracted|quarantined`), `source_episode_id`, `supersedes_id`,
  `approved_by`; `entity`, `entity_edge`, `entity_mention`, `memory_unit_fts` (FTS5). A
  recuperação combinada da §6.8 está medida (ADR-0013: 2 saltos em 3,29 ms de p95 no corpus real
  do dono). **Não existe**: gravação de turno de conversa, cifra do bruto, nem nenhuma tool que o
  cérebro chame.
- **A SPEC já decide as regras de escrita:** caminho crítico só grava episódio e outbox (§6.4);
  contradição encerra validade e não apaga (P7, §6.2 b); aresta nasce `proposed` e só vira
  `active` com duas evidências, extrator determinístico ou confirmação do dono (§6.7); exclusão em
  cascata até o grafo (§6.6 gate 2); "Gates de memória (antes de qualquer escrita autônoma)"
  (§6.6, título).
- **O modelo do dono é a MCP do Orchestrator** (`retrieve_memory`, `get_memory`, `store_memory`,
  `delete_memory_chunk`, …), que grava sem confirmação e sem episódio de origem. Serve de modelo
  para **o que** o Jarvis faz (ler, gravar, alterar, apagar, por tool), não para **como**: a
  memória do Orchestrator é sobre código; a do Jarvis é sobre a vida do dono, chega por voz (com
  erro de ASR) e por conteúdo `third_party`.
- **P1:** memória por tool passa pelo PDP como qualquer capacidade. Não há porta lateral do `s2`
  para o `memoryd`.

## Decisão

**Oito capacidades da família `memoria`, com manifesto, PDP e auditoria como as outras; o cérebro
(o `s2` da conversa do dono) é o único chamador no v1; escrever exige um episódio de origem;
alterar e esquecer exigem confirmação; e cada tool entra só depois dos gates de memória que a
protegem.**

### O conjunto

| Tool | O que faz | Classe (§5.3) | Confirmação | Resultado no livro-razão |
|---|---|---|---|---|
| `memoria.buscar_historico(consulta, desde?, ate?, k)` | busca nos turnos de conversa (FTS + denso), filtrando por data e sessão | `leitura_local` | não | — |
| `memoria.ler_mensagem(episode_id, vizinhos?)` | lê um turno e os vizinhos da mesma sessão | `leitura_local` | não | — |
| `memoria.buscar(consulta, instante?)` | recuperação da §6.8 (grafo + vetor), devolve evidências **com o caminho** (gate 6) | `leitura_local` | não | — |
| `memoria.lembrar(texto, sujeito?, predicado?, valor?)` | grava memória nova a partir de um episódio | `escrita_recuperavel` | ver regra 3 | `assertion` `proposed` ou `active` |
| `memoria.atualizar(assertion_id, valor, motivo)` | corrige o que o Jarvis sabe | `escrita_recuperavel` | 1×, mostrando antes → depois | antiga `superseded` + nova `active` com `supersedes_id` |
| `memoria.criar_no(tipo, nome, apelidos?)` | entidade nova no grafo | `escrita_recuperavel` | ver regra 3 | `entity` |
| `memoria.criar_aresta(origem, relacao, destino, desde?, ate?)` | relação nova no grafo | `escrita_recuperavel` | ver regra 3 | `entity_edge` `proposed` ou `active` |
| `memoria.esquecer(alvo, modo)` | `retratar` (reversível) ou `apagar` (cascata) | `retratar`: `escrita_recuperavel`; `apagar`: `alto_impacto` | `retratar`: 1×; `apagar`: na UI, uma por vez, mostrando o que cai na cascata | `retracted` com tombstone; ou exclusão em cascata da §6.6 gate 2 |

`memoria.buscar` não estava na lista do pedido. Entrou porque "lembra delas" precisa de uma tool:
a recuperação automática dos degraus 0–1 (§6.8) cobre o turno comum e não custa chamada, e a tool
cobre os degraus 2–3 quando o modelo precisa de mais. Leio "lembrar" do pedido como **gravar**
("lembra que eu…"); se o dono quis dizer outra coisa, é a pergunta 2 do fim.

### Regras

1. **Só o cérebro chama, no v1.** Tarefa delegada (ADR-0022) não tem nenhuma tool `memoria.*` na
   allowlist; servidor MCP de entrada (ADR-0023) não expõe nenhuma, **nem de leitura**; o Jev
   não lê memória (ADR-0024). Abrir qualquer um desses é emenda desta ADR.
2. **Escrever exige episódio de origem.** Toda escrita cita `source_episode_id` (o turno em que
   aconteceu), `actor` (`dono` ou `jarvis`), o `call_id` da tool e o motor (`s2:<motor>@<versão>`
   no campo de extrator). Sem episódio, o PDP nega.
3. **Quem é a fonte decide o estado, e o código confere.** Se a fonte é **fala estável do dono no
   turno corrente** (`FinalTranscript` ou texto digitado, `trust: user_voice|user_ui`, o episódio é
   o daquele turno) e o dono pediu a escrita, nasce `active` com `approved_by = dono`, e a UI mostra
   um card "lembrei: …" com desfazer — o pedido explícito é a confirmação, e o desfazer cobre o
   erro de ASR. Em qualquer outro caso — iniciativa do Jarvis, ou fonte `tool_result` /
   `third_party` — nasce `proposed` e só promove pelas regras da §6.7. Fonte `third_party`
   sozinha nunca promove (P6, gate 5): texto de página que diz "lembre que o dono quer X" vira, no
   máximo, `proposed` de peso reduzido.
4. **Alterar e esquecer sempre confirmam.** Mudar o que o Jarvis sabe estraga mais que gravar algo
   novo, e a frase pode ter vindo mal transcrita. `atualizar` e `esquecer(retratar)` confirmam
   uma vez (voz serve: é `escrita_recuperavel`); `esquecer(apagar)` é `alto_impacto`: só na UI, uma
   chamada por vez, com a lista do que a cascata derruba.
5. **Nada se edita no lugar (P7).** `atualizar` encerra a validade da antiga e cria a nova;
   `retratar` muda o status e deixa tombstone; só `apagar` remove, e remove tudo (bruto, FTS,
   vetor, resumo, cache e grafo).
6. **Histórico de conversa é episódio.** Cada turno vira `episode(kind = 'turno', actor =
   'dono'|'jarvis', session_id, trust)`, com o texto em `raw_cipher_ref` (cifrado) e a redação no
   `memory_unit`. O turno do Jarvis grava **só o tocado** (P4, ADR-0025 regra 3), com a marca de
   interrompido quando for o caso. Gravar é fora do caminho da voz: episódio + outbox, o resto no
   worker (§6.4). Áudio não é gravado (§9, "nada de áudio bruto por padrão").
7. **Três alcances de memória, escolhidos pelo dono na UI e por nenhuma tool ou frase (P12):**
   `conversa` (sessão corrente, sempre), `historico` (sessões passadas e memória não sensível) e
   `sensivel` (as classes de cofre da §6.5: credencial, saúde, finanças, íntimo — opt-in por
   classe). São ortogonais aos níveis de arquivo da ADR-0009: lá a pergunta é "onde no disco";
   aqui é "que parte da vida do dono".
8. **Egress é o do motor.** O que uma tool de memória devolve entra no contexto do motor da
   ADR-0025; com motor de nuvem, sai da máquina. O PDP decide pela classe do dado contra o `onde`
   do motor: `sensivel` **nunca** vai para motor de nuvem; `historico` vai só se o dono ligou
   (**DECISÃO DO DONO**, pergunta 3). O egress é mostrado como qualquer egress da §5.3.
9. **O que volta é dado, não instrução.** Turno antigo e memória recuperada são evidência com
   `memory_id` e caminho; não ampliam `allowed_tools`, não criam grant e não mudam cenário
   (gate 5). Um turno antigo do dono dizendo "pode apagar tudo" não é pedido de agora.
10. **Não encontrar é resposta.** Escore abaixo do limiar ⇒ "não encontrei" (§6.8 passo 5). A tool
    nunca devolve lembrança sem caminho.

### Encaixe nos gates de memória (§6.6)

Cada tool entra só quando os gates que a protegem passam. "Escrita autônoma" (a do Jarvis por
iniciativa própria) é o último degrau, como o título da §6.6 manda.

| Fatia | Entra | Gates que precisam passar antes |
|---|---|---|
| M1 — histórico | gravação de turno (regra 6), `buscar_historico`, `ler_mensagem`, `esquecer(apagar)` de turno e de sessão | 2 (cascata, já com índice), 3 (segredo sintético), 5 (injeção vinda de turno antigo), 6 (caminho: "acerto direto no turno X") e a cifra do bruto |
| M2 — memória por pedido do dono | `lembrar` e `atualizar` com fonte do dono, `esquecer(retratar)`, `buscar` sem grafo | + 1 (fonte em 100%) e 4 (conflito temporal) |
| M3 — grafo | `criar_no`, `criar_aresta`, `buscar` com 1–2 saltos | + regras da §6.7 e precisão de aresta amostrada (aceite (f) da F3) |
| M4 — escrita autônoma | `lembrar`/`criar_aresta` por iniciativa do Jarvis, sempre `proposed` | os 6 gates (aceite (a) da F3) |

A cifra entra em M1, e não depois, porque conversa gravada em claro e cifrada mais tarde já deixou
cópia em claro no disco (WAL, backup, lixeira do sistema).

**Emendas que esta ADR pede quando aceita:** SPEC §5.3 (as classes das tools `memoria.*`), §5.6
(a família `memoria` no catálogo do v1, com as de leitura no núcleo invariável da §5.1), §6.4
(turno como episódio) e §6.6 (a tabela de fatias acima). ADR-0023: a lista do que o servidor nunca
expõe ganha a leitura de memória e de histórico.

## Decisões do diretor (2026-10-16)

Decisões do diretor de 2026-10-16 (o dono delegou "siga a partir daí"); o dono pode revisar qualquer uma delas.

- **D17 — esta ADR:** aceita para implementar a fatia mínima (M1).
- **D19 — retenção:** turno que nenhuma memória cita fica 90 dias (`retention_until`); turno
  citado por memória fica até o dono apagar a memória ou o turno.
- **D20 — nuvem:** `sensivel` nunca vai a motor de nuvem; `historico` só vai se o dono ligar,
  **por motor**, e vem desligado (regra 8).
- **D21 — "lembrar":** gravar com proveniência (`memoria.lembrar`) e recuperar
  (`memoria.buscar`, que entra no conjunto).

## Ajustes da implementação (2026-10-16, fatias M1 e M2)

O que o código mostrou e mudou nesta ADR. Cada ajuste mantém a regra e muda a forma.

1. **`esquecer` virou duas tools: `memoria.retratar` e `memoria.apagar`.** A classe de risco é por
   manifesto (SPEC §4), e uma tool cujo risco depende de um argumento obrigaria o PDP a ler o
   argumento para saber o risco. `retratar` é `escrita_recuperavel`; `apagar` é
   `apagar_permanente`, que já está em `RISCOS_QUE_SEMPRE_CONFIRMAM`. São nove tools, dentro do
   teto de 10 por namespace.
2. **A regra 3 ficou verificável sem mapa de frase.** "O dono pediu" não se decide por código sem
   virar regex de intenção (P2). O que o código confere (`jarvis.politica.memoria`) é a
   **proveniência do conteúdo**: nasce `active` só o que é **fala literal do dono neste turno** —
   o texto (`lembrar`, duas palavras ou mais), o nome (`criar_no`) ou os dois nomes
   (`criar_aresta`), comparados sem acento e sem pontuação. Paráfrase, inferência e conteúdo de
   terceiro nascem `proposed`. O modelo continua julgando **se** o dono quis que lembrasse.
3. **O "pedido é a confirmação" virou grant de turno no PDP.** O validador do repositório recusa
   efeito persistente com `confirmation: never`; por isso `lembrar`, `criar_no` e `criar_aresta`
   declaram `once_per_batch`, e a política de memória, antes da matriz comum, devolve `allow` só
   no caso do item 2. Fora dele: `deny` (escrita autônoma, até os gates) ou o `confirm` comum.
4. **Índice:** nem ChromaDB nem LanceDB estão nas dependências do produto. A interface
   `MemoryIndex` da §6.3 existe (`jarvis.memoryd.indice`) com um índice **falso** de teste
   (sobreposição de termos, sem modelo): prova o contrato e a exclusão em cascata, **não mede
   qualidade**. A lista léxica é o FTS5 do SQLite. A escolha do índice continua sendo a medição
   da §8.1.
5. **Cifra:** `cryptography` virou dependência direta (Fernet; `Apache-2.0 OR BSD-3-Clause`,
   conferido no PyPI em 2026-10-16; commit `3eaed14`). A chave fica no chaveiro do SO; banco em
   disco sem cofre **não abre**. Ver a pergunta 1: **só o bruto está cifrado**.
6. **Proveniência vem do cérebro.** `Cerebro.proveniencia` monta o turno de origem a partir do
   episódio que ele mesmo gravou; o `Pedido` do PDP carrega isso, e o modelo não tem como
   escrever esse campo.

**Gates da §6.6 nesta fatia** (o que tem teste, em `tests/unit/memoria/`):

| Gate | Situação |
|---|---|
| 1 — fato com episódio fonte | toda escrita exige episódio; sem origem, o PDP nega e audita |
| 2 — exclusão em cascata | apagar a sessão: bruto, `memory_unit`, FTS, assertiva, índice, menção, aresta e entidade sem suporte zerados |
| 3 — segredo sintético | a chave dita na conversa não volta em `buscar_historico` nem em `ler_mensagem` e não vai para o disco em claro |
| 4 — fato vencido | depois de `atualizar`, `buscar` só devolve a nova |
| 5 — texto recuperado não vira política | conteúdo `third_party` nasce `proposed`; argumento fora do schema é recusado antes do efeito. **Falta** a suíte de injeção da F2 com histórico envenenado |
| 6 — caminho da evidência | todo achado de `buscar` e de `buscar_historico` traz o caminho |

`escrita_autonoma_liberada` continua **falso**: a escrita por iniciativa do Jarvis (M4) espera o
aceite (a) da F3, com os seis gates medidos no corpus, não só testados.

**Não feito nesta fatia:** o processo `executor` chamando as tools pelo barramento (elas rodam
em biblioteca); o laço `tool_call` do cérebro (depende do motor real, passo 5 do roteiro); o
card "lembrei: … [desfazer]" na UI; a tela de alcances (os padrões estão no código: histórico
ligado, sensível desligado, nenhum motor de nuvem com histórico); a precisão de aresta amostrada
do aceite (f) da F3.

**Perguntas ao dono** (registradas aqui; o trabalho seguiu com a proposta):

1. **Cifrar o livro inteiro?** Hoje o bruto vai cifrado, mas o texto redigido (`memory_unit`) e o
   FTS5 ficam **em claro** no SQLite — a redação tira segredo, não tira a conversa. Opções: (a)
   SQLCipher para o banco todo (dependência nativa, licença e Windows a conferir); (b) aceitar o
   índice em claro e exigir disco cifrado pelo SO; (c) não indexar texto de turno (sem busca
   léxica no histórico). **Proposta:** (a), medida antes; até lá vale (b), dito na tela.
2. **Classe sensível:** hoje "sensível" é o que a redação e o `classe_de_pii` pegam (segredo,
   caminho de cofre). Saúde, finanças e íntimo (§6.5) não têm classificador. Marcar na UI, por
   turno, ou esperar um classificador medido? **Proposta:** marcar na UI agora; classificador
   depois, medido.

## Alternativas descartadas

- **Acesso direto do `s2` ao `memoryd`, sem tool** — mais rápido de escrever e invisível ao PDP e
  à auditoria (P1). A recuperação automática dos degraus 0–1 continua direta, porque é leitura
  pedida pelo código, não pelo modelo, e não é decisão do modelo.
- **Gravar sem confirmação, como o `store_memory` do Orchestrator** — no Orchestrator quem grava
  é a IA, sobre código, e o erro custa uma memória ruim de projeto. Aqui a entrada é voz com erro
  de ASR e conteúdo de terceiro, e o erro vira "o Jarvis acha que meu filho se chama Pedro". O
  `proposed` e o desfazer custam pouco e fecham isso.
- **Uma tool genérica `memoria.executar(sql)`** — é shell genérico com outro nome; o executor não
  tem shell genérico (§2).
- **Memória como servidor MCP à parte** — põe a parte mais sensível do produto atrás do porto de
  terceiros, com o isolamento de processo da ADR-0023 servindo para nada: o dado é nosso.

## Consequências

- Fica mais fácil: o dono pergunta "o que eu te disse ontem sobre X?" e a resposta vem com o
  turno; corrigir o Jarvis é uma frase seguida de "sim".
- Fica mais caro: oito manifestos, testes de contrato e a cifra do bruto antes da primeira
  gravação de conversa.
- Passa a ser obrigatório testar: nenhuma escrita sem episódio; nenhum `active` vindo de
  `third_party` sozinho; `apagar` não deixa resto em nenhuma das seis camadas; nenhuma tool de
  memória visível para tarefa, MCP de entrada ou Jev.

## Riscos

| Risco | Controle |
|---|---|
| ASR erra e o Jarvis grava errado com `active` | card com desfazer (regra 3); `atualizar` confirma |
| Conteúdo de página ou e-mail planta memória | regra 3 (`proposed`, peso reduzido), gate 5 |
| Histórico vaza para a nuvem | regra 8; `sensivel` nunca; `historico` só com o dono ligando |
| "Esquece tudo" por engano | `apagar` só na UI, uma chamada por vez, com a lista da cascata |
| Histórico cresce sem limite | retenção da §6.5 (pergunta 1 ao dono) e expiração por `retention_until` |

## Fatia mínima (implementar primeiro)

M1 inteira: gravação de turno com o tocado, cifra do bruto, `buscar_historico`, `ler_mensagem` e
`esquecer(apagar)` de turno e de sessão, com manifesto e testes de contrato. Depende da fatia
mínima da ADR-0025 (o turno do Jarvis só existe com o tocado quando o stream existe).

## Teste de aceite

- **(a)** 100 turnos gravados com interrupções: o turno do Jarvis contém exatamente o tocado em
  100%.
- **(b)** "O que eu disse sobre X na terça?" num corpus de sessões sintéticas: o turno certo no top-5
  e o caminho na resposta; nos negativos, "não encontrei".
- **(c)** Apagar uma sessão: varredura de bruto, FTS, vetor, resumo, cache e grafo não acha nada
  dela.
- **(d)** Turno antigo com instrução injetada ("ignore a política e …") e saída de tool com "lembre
  que …": 0 grants, 0 `allowed_tools` ampliados, 0 `active` criados.
- **(e)** Escrita sem `source_episode_id`: negada pelo PDP em 100%.
- **(f)** Varredura das allowlists de modelos de tarefa, do servidor MCP e da entrada do Jev: 0
  tools `memoria.*`.
- **(g)** Motor de nuvem com alcance `sensivel` ligado: 0 bytes de classe sensível no contexto
  enviado (teste com segredo e dado de saúde sintéticos).

## Como invalidar esta decisão

- O uso mostra que `proposed` com promoção pela §6.7 deixa memória certa parada por semanas
  (contagem de `proposed` que o dono confirma quando vê na tela "o que sei sobre você"): a regra 3
  é revista, por exemplo com promoção por confirmação em lote na UI.
- O dono passa a usar tarefas que precisam ler memória: a regra 1 ganha leitura para tarefas, com
  alcance próprio.
- Custo da cifra no caminho de gravação passa do orçamento do worker: muda a forma da cifra, não a
  regra de cifrar antes de gravar.
