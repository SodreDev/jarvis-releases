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
