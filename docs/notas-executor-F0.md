# Notas de implementação da F0 (executor)

Decisões de implementação, divergências e limites verificados durante os cartões da F0. O que
muda contrato está marcado como **emenda proposta** — a SPEC só muda por ADR.

**Autor:** executor · **Início:** 2026-10-15

---

## F0-01 — repositório, licença, linter, CI

- **Licença: Apache-2.0** (`LICENSE`, copyright `SodreDev`). ADR-0011 exige licença que permita
  uso comercial; Apache-2.0 é permissiva, tem concessão de patente explícita e é a mesma família
  dos modelos preferidos (`bge-reranker-v2-m3`, `Qwen3-*` em Apache-2.0; `bge-m3` e
  `multilingual-e5-base` em MIT), o que evita atrito de compatibilidade.
- **Linguagem: Python 3.12 provisório.** A decisão D1 (SPEC §2) é do cartão F0-04 e se fecha por
  medição. Para que ela continue aberta de verdade, o contrato do barramento não mora em código
  Python: `schemas/events.v1.json` (envelope e os 11 tipos da §3.2) e `schemas/event_log.sql`
  (log encadeado por hash) são a fonte de verdade, e o Python é só uma implementação que valida
  contra eles. Reimplementar `audio-io`/`agentd` em Rust lê os mesmos arquivos.
- **O linter é parte da política, não estilo:** as regras `S` (bandit) do ruff barram
  `shell=True`, `os.system` e `eval`/`exec`, que é a proibição de canivete suíço da §4 em forma
  executável. Há teste que prova a recusa (`tests/unit/test_portoes_de_qualidade.py`).
- **Um comando por sistema:** `uv run --frozen python tools/verificar.py` roda a mesma sequência
  do CI em Linux e Windows (P11).
- **Não verificado aqui:** o job `windows-latest` do CI. Esta máquina é Linux e o repositório não
  tem remoto (o dono não autorizou push), então o workflow foi escrito e revisado, mas **nunca
  executado** — nem no Windows nem no GitHub. O aceite (a) do cartão ("CI verde nos dois SOs")
  continua **pendente de execução real**. O que foi executado aqui é a sequência equivalente em
  Linux, local.

---

## F0-02 — barramento tipado, prioridades, coalescing e log encadeado

### O contrato mora em dados

`schemas/events.v1.json` (envelope da §3.1, os onze payloads da §3.2, prioridade e origem
canônicas) e `schemas/event_log.sql` (log encadeado) são a fonte de verdade. `jarvis.barramento`
é a implementação de referência em Python e **valida contra esses arquivos**; o teste
`test_os_onze_tipos_do_contrato_batem_com_o_enum` falha se o código divergir do contrato. É
assim que a decisão D1 (cartão F0-04) continua aberta sem custo: outra linguagem lê os mesmos
arquivos.

### O que a borda recusa (não ignora)

Tipo fora dos onze; `schema_version` diferente de `1`; campo extra no envelope ou no payload
(`additionalProperties: false` em todos); `event_id`/`session_id` que não sejam uuid v7;
`ts_wall` sem fuso; prioridade diferente da que a §3.2 fixa para o tipo; tipo emitido por
processo que não é a origem canônica; `ToolCallRequested` de efeito sem `idempotency_key`;
`payload.epoch` diferente do envelope; `DesktopObservation` ou evento de `mcp:*` que não seja
`third_party`.

### Emendas propostas à SPEC §3 (implementadas; a SPEC só muda por ADR)

1. **`policy` entra na lista de `source` da §3.1.** A §3.2 diz que `PolicyDecision` vem de
   `policy`, mas a lista de `source` do envelope não traz o processo. Sem ele o contrato se
   contradiz.
2. **`ToolResult.payload.read_only` (obrigatório).** A regra 3 da §3.3 ("tool de leitura stale
   pode terminar") é indecidível sem saber se a tool era de leitura. O `executor` copia o campo
   do manifesto (§4), nunca do modelo. Sem isso, a regra 3 seria letra morta ou dependeria de o
   `s2` adivinhar.
3. **`ToolResult.payload.status` fechado** em `ok|error|timeout|cancelled|denied` — a §3.2 só
   dizia "status".
4. **`mcp:<id>` como `source` vale apenas para `DesktopObservation` e `ToolResult`.** A §2 diz
   que o cliente MCP é adaptador do `executor`; nenhum servidor MCP emite `Cancel`,
   `PolicyDecision` ou transcrição. O `trust` desses eventos é sempre `third_party`, inclusive
   quando entram pela fronteira interna.
5. **"Eventos de auditoria" da regra 6 = `PolicyDecision` + `ToolResult`.** A §3.3 cita a
   exceção sem nomeá-la. A §5.5 exige decisão registrada antes do efeito e resultado anexado
   depois: descartar esses dois por epoch velho abriria buraco no registro exatamente no caso
   cancelado. Eles chegam com veredito `SO_AUDITORIA` — vão ao log, não alimentam raciocínio.
6. **`evidencia` da §3.4 fechada como `{ref, resumo}`.** O rascunho usava a chave variável
   `"memory_id|call_id"`, que não é tipo fechado; `ref` carrega `memory_id` ou `call_id`.

### Decisões de implementação

- **Coalescing só em hipótese.** `PartialTranscript`, `TurnPrediction`, `StateRevision` e
  `AudioActivity` de silêncio se sobrescrevem por chave (tipo + sessão + epoch, e `task_id` na
  revisão de estado). `FinalTranscript`, `ToolResult`, `PolicyDecision` e `PlaybackProgress`
  **nunca** são coalescidos: perder um muda o histórico (P4) ou a auditoria. `speech_started`
  também não — é o gatilho do barge-in.
- **A banda P0 não tem teto.** Fila cheia recusa P1–P4 com exceção explícita (`FilaCheia`), mas
  `Cancel` e `speech_started` sempre entram; interromper vence tudo (P3).
- **Descarte é devolvido, não engolido.** `descartar_epoch` retorna o que saiu da fila, para ir
  ao log: descarte silencioso não é auditável.
- **`played_ms` é a única fonte do histórico** (`LivroDeFala`): trecho enfileirado sem
  `PlaybackProgress` é apagado no cancelamento e nunca aparece em `texto_tocado()`.
- **Append-only no banco, não na boa vontade da aplicação:** gatilhos `BEFORE UPDATE`/`DELETE`
  com `RAISE(ABORT)`. Quem tem o arquivo pode derrubar o gatilho — e a cadeia de sha256 acusa,
  que é justamente o aceite (e).
- **`uuid7` é nosso** porque `uuid.uuid7()` só existe depois do 3.12. A ordem forte do log vem
  do `seq` do banco, não do uuid.
- **Não verificado aqui:** o CI em `windows-latest` (sem máquina Windows e sem remoto). O
  barramento não usa nada específico de sistema — `pathlib`, `sqlite3` e `hashlib` da stdlib —
  mas "roda nos dois SOs" segue **não comprovado por execução**.

---

## F0-09 — porta de licença no CI

### O que a porta faz

`tools/license_gate.py` inventaria duas coisas e falha se achar cláusula não comercial:

1. **dependências instaladas**, lidas dos metadados reais do ambiente
   (`importlib.metadata`: `License-Expression`, classificadores `License ::` e, por último, o
   campo livre `License`) — não de uma lista escrita à mão que envelhece;
2. **modelos** (embedding, reranker, VAD, ASR, TTS) do registro `licenses/modelos.toml`, com
   licença, fonte, revisão do repositório do modelo e data de acesso.

Categorias: `permissiva`, `atribuicao` (uso comercial com atribuição obrigatória, como CC-BY),
`copyleft_forte` (GPL/AGPL/SSPL), `nao_comercial` e `desconhecida`.

**Bloqueia** (sai 1): qualquer item `nao_comercial`, e item `desconhecida` que esteja em uso.
**Avisa** (sai 0): `copyleft_forte` — permite uso comercial, mas obriga abrir o derivado; vira
bloqueio com `--estrito-copyleft`. **Também avisa** em `atribuicao`, porque a obrigação é
visível no produto e alguém tem de colocá-la lá.
**Não bloqueia**: modelo marcado `estado = "barrado"` — é um NC registrado justamente para
ficar fora, e o registro serve para ninguém tentar de novo.

### Verificação dos model cards (aceite b)

Os treze modelos do registro foram conferidos **na origem** em 2026-10-15, com
`--online`, que lê a API do model card do Hugging Face (ou a API de licença do GitHub) e
compara com o registrado. Resultado dos seis nomeados no cartão:

| modelo | licença oficial |
|---|---|
| `BAAI/bge-reranker-v2-m3` | apache-2.0 |
| `Qwen/Qwen3-Reranker-0.6B` | apache-2.0 |
| `mixedbread-ai/mxbai-rerank-large-v2` | apache-2.0 |
| `intfloat/multilingual-e5-base` | mit |
| `BAAI/bge-m3` | mit |
| `Qwen/Qwen3-Embedding-0.6B` | apache-2.0 |

**A dúvida da ADR-0011 está resolvida:** o agregador que dizia MIT para o
`bge-reranker-v2-m3` estava errado — o model card oficial diz `apache-2.0`. O MIT que a ADR
viu provavelmente era do `bge-m3` (embedding), que é MIT mesmo. Nenhum dos seis é NC, então a
ordem de preferência da ADR-0011 continua válida sem emenda.

**Dois NC verificados e barrados:** `jinaai/jina-reranker-v2-base-multilingual` (cc-by-nc-4.0,
já previsto) e — achado novo — `coqui/XTTS-v2`, que o Hugging Face mostra como `other` e cujo
nome de licença é a *Coqui Public Model License* (uso não comercial). Como TTS é escolha da
F1, fica registrado agora para não entrar por engano. O classificador reconhece CPML,
PolyForm Noncommercial, CC-BY-NC e "research only".

**Uma atribuição obrigatória:** `nvidia/parakeet-tdt-0.6b-v2` é CC-BY-4.0 — comercial sim, mas
a atribuição tem de aparecer no produto. A porta avisa em todo commit para isso não sumir.

A tabela comitada é `docs/licencas.md`, **gerada** por `--escrever-tabela` e **verificada** por
`--verificar-tabela` no CI: se alguém editar o registro e esquecer a tabela, o CI cai.

### Não verificado

- O CI em `windows-latest` (sem máquina Windows e sem remoto): a etapa está no workflow e roda
  offline, mas nunca foi executada. O script só usa stdlib (`importlib.metadata`, `tomllib`,
  `pathlib`), sem chamada de sistema nem caminho fixo.
- `--online` não roda no CI de propósito: porta de qualidade que depende de rede falha por
  motivo errado. A verificação na origem é manual e datada.
- Vozes individuais do `rhasspy/piper-voices` podem ter licença própria (algumas CC-BY-SA);
  a voz escolhida tem de ser verificada em F1.

---

## F0-03 — os sete processos como esqueleto e o evento que atravessa tudo

### IPC: três decisões de segurança

1. **Endereço por sistema, nunca porta de rede.** `AF_UNIX` no Linux (socket dentro da pasta
   de execução, com modo 0600 e a pasta 0700) e named pipe `AF_PIPE` no Windows. Um barramento
   de desktop não precisa ser alcançável pela rede, então não é.
2. **JSON, nunca pickle.** `multiprocessing.connection` serializa com pickle no `send`/`recv`,
   o que transformaria um processo comprometido em execução de código no vizinho. Só se usa
   `send_bytes`/`recv_bytes` com JSON, com teto de 4 MiB por quadro — payload grande vai por
   `payload_ref`, como a §3.2 já previa. A autenticação do handshake (HMAC com `authkey`) é a
   do `multiprocessing`; a chave é gerada por sessão, gravada com permissão restrita e nunca
   passa pelo `argv`.
3. **Limite de `sun_path`.** O caminho do socket cai para a pasta temporária do sistema, com
   nome derivado por hash, quando a pasta de execução é comprida (acontece em teste). É limite
   do sistema operacional, não escolha de projeto.

### O corretor (dentro do `agentd`)

Ordem fixa para cada quadro: **valida na borda → grava no log → classifica pelo epoch →
entrega a quem assinou**. Três consequências:

- `trust` é atribuído pela fronteira do processo que publicou (`audio-io` → `user_voice`,
  `ui` → `user_ui`, `executor` → `tool_result`, resto → `system`), e o quadro não pode se
  promover;
- um processo **não publica no lugar de outro**: `source` diferente do nome registrado é
  recusado e o nome de quem tentou vai para a lista de recusados (um `s2` comprometido não
  fabrica um `PolicyDecision: allow`);
- o roteamento vive em `schemas/roteamento.v1.json` (dado, como o resto do contrato):
  `policy` não recebe transcrição, `memoryd` não recebe pedido de tool.

**Reposição por cursor:** cada processo grava o último `seq` visto em `cursor-<nome>`; ao
reconectar, pede do cursor e o corretor reenvia do log o que ele perdeu. Isso é o que faz
"matar e reabrir" não perder evento.

**Idempotência do efeito é do executor, não do cursor.** O executor registra cada `call_id`
executado em `executor-efeitos.jsonl` antes de responder; mesmo perdendo o cursor e recebendo
a mesma `PolicyDecision` de novo, o efeito não acontece duas vezes. O teste apaga o cursor de
propósito para provar isso no pior caso.

**Thread só para aceitar conexão.** Conexão de SQLite não atravessa thread, então a thread de
aceitação faz apenas o handshake e enfileira; a admissão e a reposição acontecem na thread
principal, que é a dona do log.

### Ver funcionando

```
uv run --frozen python tools/rodar_esqueleto.py
```

Sobe os sete, injeta um `AudioActivity(speech=True)` sintético e imprime o log:

```
seq  tipo                 origem    epoch  trust
  1  AudioActivity        audio-io      0  user_voice
  2  Cancel               agentd        1  system
  3  FinalTranscript      agentd        1  user_voice
  4  ToolCallRequested    s2            1  system
  5  PolicyDecision       policy        1  system
  6  ToolResult           executor      1  tool_result
  7  StateRevision        s2            1  system
```

O epoch sobe uma vez (o `speech_started` da regra 1, antes de qualquer transcrição) e depois é
preservado de ponta a ponta, com o mesmo `call_id` atravessando s2 → policy → executor → s2.

### Não verificado

- O caminho `AF_PIPE` do Windows: escrito e revisado, **nunca executado** (máquina Linux, sem
  remoto). É o único trecho de `ipc.py` específico de sistema.
- Reinício do `agentd`: o cartão pede "qualquer processo", e o corretor reabre o log sem perder
  registro (a cadeia de hash continua de onde parou), mas o teste automatizado cobre o
  reinício de um processo **cliente**. Reiniciar o dono do barramento com os clientes vivos
  exige reconexão automática do cliente, que é trabalho de F1 — anotado como limite conhecido.

---

## F0-06 — política: raízes, canonicalização, TOCTOU e auditoria

### O truque que deixa o item (f) ser provado em Linux

As armadilhas do Windows (`a.txt:oculto`, `PROGRA~1`, `CON`/`NUL`/`COM1`, UNC, `\\?\`,
`C:foo`, ponto ou espaço final, case-folding) são **lexicais**: dependem da forma do caminho,
não da API do sistema. Por isso `canonicalizacao.py` recebe o sistema como parâmetro e a suíte
roda as duas gramáticas em qualquer máquina. O que de fato precisa de Windows — handle com
`FILE_FLAG_OPEN_REPARSE_POINT`, `GetFinalPathNameByHandleW`, nome 8.3 real criado pelo
sistema de arquivos — está escrito e **não executado**.

### Dois caminhos de abertura, mesma garantia

`openat2` com `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_MAGICLINKS | RESOLVE_NO_XDEV`
é o caminho preferido. Quando ele não existe (kernel < 5.6) ou é bloqueado por seccomp, a
travessia é componente a componente com `O_NOFOLLOW` e `dir_fd`, conferindo `st_dev` a cada
passo. **A suíte de TOCTOU roda nos dois caminhos** (`pytest` parametrizado), porque garantia
que só vale no caminho rápido não é garantia.

### O que a suíte prova, e como

- **(a) corrida de link simbólico:** uma thread alterna um componente entre pasta real e link
  para fora, enquanto o abridor tenta 400 vezes. O critério de escape é **identidade**
  (`device:inode` do descritor aberto), não conteúdo: o trocador recria o arquivo de dentro o
  tempo todo e um arquivo recém-criado pode estar vazio — medir conteúdo dava falso positivo.
  O teste também exige que o trocador tenha conseguido trocar ao menos uma vez, senão ele não
  provou nada. Resultado: 0 escapes nos dois caminhos de abertura.
- **(b) hardlink para fora:** arquivo regular com `st_nlink > 1` é recusado. Caminho dentro da
  raiz não prova conteúdo dentro da raiz. **Decisão conservadora anotada:** isso recusa
  também hardlink legítimo dentro da própria raiz; para as capacidades do v1 (§5.6) isso não
  atrapalha, e quando atrapalhar a saída é permitir por manifesto, não afrouxar no geral.
- **(c) `..` e unicode:** `..` que sobe acima da raiz é **recusa**, não corte silencioso; NFC
  e NFD do mesmo nome produzem o mesmo canônico, então negação escrita em uma forma não é
  burlada pela outra.
- **(d) ponto de montagem trocado:** o descritor da raiz continua válido quando o caminho
  passa a ser outro objeto, então `ainda_e_a_mesma()` compara `stat` do caminho com `fstat` do
  descritor. O teste troca a raiz por outra pasta de mesmo nome — mesma string, outro inode,
  que é exatamente o efeito de um mount trocado. **Montar de verdade exige privilégio e não é
  feito em teste** (a regra é nunca pedir root); o mecanismo exercitado é o mesmo.
- **(e) raiz apagada no meio:** depois de apagar, a próxima abertura é recusada com motivo, em
  vez de estourar exceção crua do sistema.
- **(g)** reduzir modo vale na hora, incrementa `policy_epoch`, cancela as chamadas em voo e
  mata os grants; ampliar fica **pendente** e só vale com `confirmar_ampliacao(dono_presente=True)`.
- **(h)** varredura do catálogo: nenhuma capacidade mexe em nível, elevação ou `allowed_tools`
  — com um manifesto plantado (`config.set_access_level`) para provar que a varredura acusa.
- **(i)** com elevação desligada, `system.install_package` **não aparece na allowlist**: o
  planejador não pode nem propor. `total` não implica elevação (teste próprio).

### Decisões de implementação

- **Lista de negação por caminho e por nome.** Caminhos conhecidos (`~/.ssh`, `.gnupg`,
  chaveiros, perfis de Chrome/Firefox, `.password-store`, carteiras, `/etc/shadow`,
  credenciais do Windows) e nomes que são segredo onde estiverem (`.env`, `id_rsa`,
  `credentials`). Negação é `deny`, nunca `confirm` — e vence no `total` (teste).
- **Raiz mais específica ganha.** Um caminho dentro de duas raízes (pasta do Jarvis dentro do
  lar, no modo `total`) é julgado pela raiz mais profunda, para a permissão por raiz valer.
- **Auditoria em duas tabelas, duas cadeias** (`schemas/audit_log.sql`): a decisão é imutável
  e o resultado chega depois em `audit_result`. Assim "decisão registrada **antes** do efeito"
  deixa de ser promessa: não existe caminho no banco que deixe o resultado reescrever a
  decisão. Gatilhos abortam `UPDATE`/`DELETE` nas duas; adulterar derrubando o gatilho quebra
  a cadeia de sha256 (teste).
- **Catálogo mínimo em `catalogo/`** com três manifestos (`system.read.status`,
  `files.move_to_trash` da §4, `system.install_package` com `requires_elevation: true`). O
  validador completo, o codegen e o lint de catálogo são o cartão F0-07; aqui só se lê o que
  decide acesso, e já se recusa manifesto sem campo de política e id de canivete suíço.

### Não verificado

- Todo o caminho Windows da abertura (handle, `GetFinalPathNameByHandleW`, identidade por
  volume + file id) e o nome 8.3 criado pelo sistema de arquivos: **escritos, nunca
  executados**. A parte lexical do item (f) está provada; a parte de API, não.
- Troca real de ponto de montagem e perda de privilégio em `openat2` sob seccomp.
- Elevação de verdade (polkit/UAC): o cartão não pede, e o interruptor aqui é só estado de
  política com teste de que nada o muda sem o dono.

---

## F0-05 — harness da memória em grafo

### O `n` não é inventado

O grafo sintético é dimensionado pelo corpus real: **122 episódios**, que é quantas memórias
o Orchestrator guarda para este projeto em 2026-10-15 (contagem feita com `list_memories`).
As razões do gerador — 3 entidades e 8 arestas por episódio, grau médio ~5 — são
**[SUPOSIÇÃO]** declarada; o exportador do cartão F0-08 substitui isso pela contagem real de
C1. As escalas 10× e 100× existem porque o corpus do dono vai crescer, e é a forma do grafo
(grau, hub) que a travessia sente, não o tamanho absoluto.

O gerador tem semente fixa: a medição de amanhã mede o mesmo grafo.

### Quatro implementações, de propósito

| implementação | o que é |
|---|---|
| `ativar_por_no` | **produção**: uma consulta por nó da fronteira, com `ORDER BY ... LIMIT` dentro da varredura |
| `ativar_por_salto` | uma consulta por salto, com `ROW_NUMBER() ... WHERE pos <= teto` |
| `ativar_recursivo_sql` | `WITH RECURSIVE`, uma consulta só |
| `ativar_em_memoria` | arestas da fronteira trazidas por consulta simples, propagação em Python |

**O achado que mudou a escolha:** `ROW_NUMBER()` obriga o SQLite a ranquear **todas** as
arestas do nó antes de cortar no teto. Num hub de grau 10 000, a travessia por salto custou
~31 ms e ainda perdia nós úteis (o `LIMIT` global cortava as arestas do hub); a mesma
travessia com o teto **dentro** da varredura (uma consulta por nó, `ORDER BY ... LIMIT`, que
para de ler no teto e usa o índice) custou ~4,8 ms com 1 salto e ~15 ms com 2, achando 35 e
167 nós. Mais consultas, menos trabalho. `ativar_por_no` passou a ser a de produção; as outras
ficam no repositório porque são a comparação do aceite (d) — e porque um teste confere que as
quatro concordam no **conjunto de nós**, sem o que comparar custo não significaria nada.

A `WITH RECURSIVE` não serve: 100–200× mais lenta e estourando o orçamento nas escalas
maiores. Fica como medição, não como caminho.

### "Nunca espera" vale dentro do SQL

O orçamento em milissegundos é verificado entre saltos **e** dentro da consulta, via
`sqlite3.Connection.set_progress_handler`: estourado o prazo, a consulta é interrompida, o
resultado volta com `graph_truncated: true` e o motivo, e as sementes continuam utilizáveis.
Com `orcamento_ms=0` as quatro implementações devolvem parcial em menos de 200 ms — teste do
aceite (b).

### Números e veredito

Em `docs/medicoes/f0-05-grafo.md` (gerado por `tools/harness_memoria.py`, com hardware, `n`,
três execuções, mediana e p95) e `docs/medicoes/f0-05-grafo.csv`. Resumo do que decide:

- **SLO-11 (p95 ≤ 40 ms) é alcançável**: 1 salto ficou em **0,16 ms** p95 na escala 100× e
  **0,24 ms** no grafo com hub; 2 saltos, em **1,54 ms** na escala 100× (12 200 episódios,
  ~97 600 arestas) e **12,6 ms** no hub;
- **SLO-12 (memória pronta, p95 ≤ 250 ms, sem reranker) é alcançável**: pior p95 de **62 ms**
  na escala 100×, com 0 consulta truncada — folga de ~4×;
- **2 saltos cabem** em todas as escalas medidas e também com hub;
- o caso que aperta não é o tamanho do grafo, é o **hub**: com grau 10 029, 2 saltos vão de
  1,5 ms para 12,6 ms p95. Continua dentro do SLO-11, e é o número que justifica a penalidade
  de hub da §6.7 ser requisito, não enfeite;
- **p95 do hub varia entre execuções** (medi 9,4 ms e 12,6 ms em execuções diferentes, com a
  máquina em uso): o relatório publica as três execuções, e é por isso que ele traz p99 também.

### Não verificado

- **Qualidade de recuperação** (recall, nDCG, abstinência): não é deste cartão. A lista densa
  da fusão é **simulada** (sobreposição de termos, determinística) — serve para a fusão ter
  três listas de verdade e o custo do RRF ser medido com o número real de candidatos, e está
  marcado assim no relatório. Qualidade é a medição da §8.1/§8.2, com corpus anotado, em F3.
- **Corpus real**: o grafo é sintético; o `n` base é real, o resto é razão declarada.
- **Windows**: o harness só usa stdlib e SQLite, então roda nos dois sistemas, mas foi
  **executado apenas em Linux**.
- **Reranker**: SLO-8 é outra medição, com modelo de licença comercial (ADR-0011).
- `entity_mention` fica vazia no grafo sintético (a extração de entidade é trabalho de
  consolidação, §6.7), então a ligação nó → `memory_unit` cai no nome canônico via FTS5. Com
  o corpus de C1 isso passa a usar as menções de verdade.

---

## F0-04 — latência de captura e a decisão D1

### O que a máquina já tinha, e o que não foi instalado

`rustc`/`cargo` 1.98.1 já estavam instalados (do dono). Mesmo assim o braço Rust é
**`std`-only e compila com `rustc -O`**, sem cargo, sem rede e sem baixar crate — a regra era
não instalar nada, e um teste varre a fonte para garantir que nenhuma linha `use` sai de
`std::`. Para o braço Python+ONNX, `numpy` e `onnxruntime` entraram num grupo **`medicao`**
que não é instalado pelo CI nem faz parte do produto; o peso do `silero-vad` (MIT, verificado
na F0-09) **não é versionado** no repositório — passa-se o caminho em `--modelo`.

### Quatro medidas, não duas

O SLO-1 é `captura → AEC/VAD → **evento**`, então medir só o VAD deixaria de fora a parte que
a nossa arquitetura cobra:

| braço | p95 (mediana de 3 execuções) |
|---|---:|
| `rust-std` (VAD barato, `std` puro) | **0,0003 ms** |
| `python-numpy` (mesma aritmética, mesmos limiares) | **0,0105 ms** |
| `python-onnx` (silero-vad, 1 thread) | **0,110 ms** |
| `evento-no-barramento` (envelope + validação + IPC ida e volta + log com hash) | **0,384 ms** |

Com `n` = 10 000 frames de 20 ms por execução (200 s de áudio), 3 execuções, áudio sintético
determinístico idêntico nos braços, no Ryzen 5 5600G. Números completos em
`docs/medicoes/f0-04-captura.{csv,md}`.

**O gargalo do nosso lado é a fronteira, não a aritmética:** publicar o evento custa 3,5× o
VAD neural e mais de 1000× o VAD em Rust. Trocar a linguagem do VAD muda 0,1 ms num orçamento
de 80 ms; o que vale otimizar, se algum dia precisar, é o caminho do evento.

### Equivalência antes de comparar

Um teste roda o binário Rust e o braço Python sobre o mesmo áudio e exige **a mesma contagem
de eventos**. Sem isso, a comparação de linguagens seria comparação de algoritmos diferentes.

### Pisos, e o viés do piso de dispositivo

- **Piso de agendamento** (laço de 20 ms sem processamento): p95 **0,080 ms**. É o chão de
  qualquer implementação em Python nesta máquina.
- **Piso do dispositivo**: p95 **20 ms**, medido no **monitor de uma saída ociosa**. Há um
  viés grande e declarado no relatório: monitor sem produtor ativo entrega em rajada, então
  esse número é limite superior grosseiro, não jitter de captura em uso.
- **Microfone não foi gravado, de propósito.** Gravar o microfone do dono para medir jitter
  seria invadir privacidade sem necessidade; o monitor tem o mesmo caminho de driver. O número
  honesto do caminho de áudio sai na F1, com captura de verdade e consentimento.

### Proposta de D1 (a decisão é do dono)

**Python 3.12 nos sete processos no v0**, com a fronteira pronta para trocar `audio-io` e
`agentd` por Rust sem reescrever contrato. Motivo em número: todo o nosso caminho em Python
soma **0,575 ms p95**, ou **0,72% do SLO-1**; em Rust seria 0,466 ms — a diferença é 0,14% do
orçamento, e o ecossistema de ASR/TTS/ONNX está em Python.

**A lacuna que pode derrubar a proposta, dita antes de alguém perguntar:** não foram medidos
AEC/NR de verdade, ASR incremental, TTS streaming nem captura de dispositivo real. Se a F1
medir estouro do SLO-1 ou do SLO-2 com esses componentes, a troca é local (dois processos) e a
decisão volta — é exatamente para isso que o contrato está em `schemas/` e não em código.

---

## F0-07 — ferramental de manifesto de capacidade

### O contrato do manifesto também é dado

`schemas/manifesto.v1.json` guarda o esquema da §4 com **todos** os enums fechados, e mais
três listas que o ferramental lê em vez de ter hard-coded: `x-ids-proibidos` (padrões de
canivete suíço), `x-tools-proibidas-de-promover` (ADR-0010 item 8) e `x-tetos-de-catalogo`.

### O que o validador cobra além do schema

Coerência entre campos, que é onde manifesto errado passa despercebido:

- efeito (`side_effect != none`) exige `idempotency: required` (§3.3 r3) e `confirmation`
  diferente de `never`;
- `risk_class: leitura` com efeito é contradição;
- `requires_elevation: true` exige `confirmation: per_action`;
- `data_egress: network:*` exige classe de risco de egress — não se manda dado para fora como
  "leitura";
- efeito reversível tem de apontar `undo` (leitura não precisa: não muda nada);
- `access_level_min: jarvis` não pode pedir raiz fora da pasta do Jarvis;
- `platforms` tem de cobrir Linux **e** Windows (P11), e `tests` tem de incluir `contract`,
  `postcondition` e `denial`;
- `id` com 2 a 4 níveis (a §4 pede `domínio.objeto.verbo`);
- nome do arquivo tem de ser `<id>.yaml`, e id repetido no catálogo é erro.

### Lint de catálogo (§4 e ADR-0010)

Recusa id de canivete suíço, descrição que promete shell ou "qualquer comando", descrição que
não passa no teste do estagiário (precisa dizer quando usar **e** o que a tool não faz),
namespace acima do teto, capacidade que mexe em nível de acesso ou elevação (P12, segunda
barreira além do teste do PDP), e nas promoções de MCP: tool da lista proibida
(`shell_exec`, `ssh_exec`, `cli_send`…), política vinda da anotação do servidor, `trust_input`
diferente de `untrusted` e egress de rede classificado como leitura.

### Codegen: o stub vem do contrato

`tools/manifesto.py codegen` gera `src/jarvis/capacidades/<id>.py` com as constantes de
política, as dataclasses de entrada e saída, `validar_entrada` (recusa argumento fora do
contrato e argumento obrigatório ausente) e `executar` que levanta `NotImplementedError` —
porque implementar é das fases seguintes, mas o contrato já é verificável agora.

**Detalhe que custou uma iteração:** o código gerado tem de sair **exatamente** como o
formatador do projeto o escreveria, senão `conferir` (que compara byte a byte) acusa stub
velho em todo commit. Por isso o codegen monta tupla de um elemento como `("x",)` e cuida das
linhas em branco entre blocos.

### No CI

`tools/verificar.py` e o workflow passaram a rodar `validar`, `lint` e `conferir`. Mudar um
manifesto e esquecer de regenerar o stub derruba o CI — era o ponto do cartão.

### Não verificado

- O codegen gera stub **Python**. Se a decisão D1 (cartão F0-04) trocar a linguagem de algum
  processo, o gerador ganha um alvo novo; o manifesto não muda, que é o motivo de ele ser dado.
- `tests` do manifesto declara quais suítes a capacidade exige, mas **nada ainda confere que
  essas suítes existem** — isso só faz sentido quando houver capacidade implementada (F2/F4).
