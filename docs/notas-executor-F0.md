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
