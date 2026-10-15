# J.A.R.V.I.S — Especificação v0.1

**Data:** 2026-10-15 · **Autor:** arquiteto (Opus 5) · **Estado:** proposta para aprovação do dono
**Mudou da v0 para a v0.1** (respostas do dono de 2026-10-15): memória semântica **com grafo** (§6.7, §6.8, ADR-0008); **modelo de acesso em 4 níveis + interruptor de elevação** (§5.5, ADR-0009); **catálogo do v1** com abrir apps e **porto para clientes MCP** (§5.6, ADR-0010); **"instantâneo" virou SLO medido** (SLO-11 a SLO-13) com experimento de decisão fechada (§8.2); **licença comercial é requisito** (ADR-0011); **F0 destrinchada em cartões delegáveis** (§9 e `docs/F0-tarefas.md`). Pendências Q2, Q3, Q4 e Q5 fechadas pelo dono; Q1 segue para a medição da F0.
**Base factual:** relatórios de pesquisa de 2026-10-15 em `GranaFacil-backup/pesquisa/` (01 tempo-real, 02 assistentes, 03 memória, 04 tools), que citam fontes primárias com data de acesso. Este documento **não** inventa números: tudo que é medição de terceiro vem marcado com a fonte; tudo que é estimativa nossa vem marcado como **[SUPOSIÇÃO]** e tem um teste que a confirma ou derruba.

**Escopo v0:** assistente pessoal desktop, voz bidirecional, Linux (Wayland e X11) e Windows desde F0. Reescrita do zero; o código antigo é só referência histórica em `/home/sodre/GranaFacil-backup`.

---

## 1. Princípios (não negociáveis)

| # | Princípio | Consequência verificável |
|---|---|---|
| P1 | **O modelo propõe, o código autoriza.** Nenhuma chamada de ferramenta executa sem passar por um Policy Decision Point determinístico, fora do LLM. | Teste: injetar `tool_call` fora de escopo → negado e auditado, em 100% dos casos. |
| P2 | **Nenhuma frase dispara ação.** Não existe regex, keyword ou intent fixo ligado a efeito. Palavras só viram ação via catálogo tipado + política. | Teste: `grep` na base não acha mapa frase→comando; corpus de paráfrases novas é resolvido pelo catálogo. |
| P3 | **Interromper vence tudo.** Fala do usuário, "pare" e botão de privacidade são P0 e preemptam qualquer trabalho. | SLO-2 (§7) e suíte de cancelamento (§9, F1). |
| P4 | **Só entra no histórico o que de fato tocou.** Áudio na fila que não foi reproduzido nunca é tratado como ouvido. | Teste de truncamento (§9, F1). Problema documentado na API Realtime (relatório 01, S3). |
| P5 | **Hipótese ≠ compromisso.** Trabalho especulativo é permitido só para leitura idempotente; efeito exige intenção estável e, quando material, confirmação. | Métrica: efeitos externos iniciados por especulação = **0**. |
| P6 | **Tudo que vem de fora é dado, não instrução.** Transcrição, tela, web, e-mail, retorno de tool e servidor MCP são `trust: untrusted`; não ampliam `allowed_tools`, não viram política nem memória durável sozinhos. | Suíte de prompt injection (§9, F2/F4). |
| P7 | **Episódio imutável; projeção revisável.** Fato, resumo e entidade são derivados de um episódio com proveniência; contradição encerra validade, não apaga. | Gate de memória: 100% dos fatos citados têm `source_episode_id`. |
| P8 | **Esquecer é função de produto.** Ver, editar e apagar memória, com deleção em cascata verificável (raw, FTS, vetor, resumo, cache). | Teste de exclusão (§6.6). |
| P9 | **Degradar, não improvisar.** Sem rede, sem permissão ou com ferramenta quebrada: calar, pedir confirmação ou cair em push-to-talk. Nunca inventar resultado. | Teste de falha (§9, F1/F3). |
| P10 | **Observabilidade antes de autonomia.** Estado, decisão, epoch, política e latência persistidos e reproduzíveis. Não exigimos nem exibimos CoT privado. | Replay de sessão (§9, F2). |
| P11 | **Portável desde o primeiro commit.** Nenhum caminho crítico depende de X11, de systemd ou de um provedor de nuvem. | CI roda F0..F5 em Linux e Windows. |
| P12 | **O alcance é escolha do dono, aplicada por código.** Nível de acesso e elevação vêm de configuração mudada só pela UI pelo dono; nenhuma capacidade os altera, nenhuma frase os altera. | Teste: varredura do catálogo não acha tool que mude nível/elevação; mudar por voz ou por MCP falha (§5.5). |
| P13 | **Mais alcance nunca é menos rigor.** Subir de nível amplia **onde** se pode agir, jamais reduz confirmação, auditoria ou lista de negação. | Teste: a matriz da §5.3 produz o mesmo veredito no nível `total` e no `jarvis` para a mesma ação. |

**Metáfora proibida no projeto:** "consciência". O requisito é um processo persistente com estado de trabalho revisável e auditável (relatório 01, resumo executivo). Usar o termo em docs internos é bug de comunicação.

---

## 2. Processos e fronteiras

Sete processos/áreas, cada um reiniciável e testável sozinho. A fronteira é o barramento de eventos (§3), não uma biblioteca compartilhada.

```text
 ┌──────────────┐  PCM 20 ms, AEC/NR/AGC, botão de privacidade
 │ audio-io     │  (processo do usuário, perto do dispositivo)
 │ captura+play │◄──── chunks de TTS com epoch + PlaybackProgress
 └──────┬───────┘
        │ frames + PlaybackProgress
        ▼
 ┌──────────────────────────────────────────────┐
 │ agentd  (percepção + barramento + S1)        │
 │  VAD → ASR incremental → detector de turno   │
 │  S1: ouvir | backchannel | ceder | falar |   │
 │      cancelar   (20–100 ms)                  │
 │  dono do epoch, do event log e da fila P0..P4│
 └───┬───────────────┬───────────────┬──────────┘
     │ StateRevision │ ToolResult    │ eventos
     ▼               ▲               ▼
 ┌─────────┐   ┌───────────┐   ┌───────────┐
 │ s2      │──►│ policy    │──►│ executor  │──► capacidades
 │ reasoner│   │ PDP det.  │   │ isolado   │    (API > a11y > visual)
 │ plano + │   │ ACL,risco,│   │ credencial│
 │ tools   │◄──│ confirmar │◄──│ pós-cond. │
 └────┬────┘   └─────┬─────┘   └───────────┘
      │ consulta     │ grants/confirmações
      ▼              ▼
 ┌──────────────┐  ┌──────────────┐
 │ memoryd      │  │ ui (desktop) │ confirmações, "o que sei sobre você",
 │ SQLite ledger│  │ indicador mic│ transcrição editável, PTT, kill switch
 │ + índice     │  └──────────────┘
 │ (trocável)   │
 └──────────────┘
```

| Processo | Responsabilidade | Proibições |
|---|---|---|
| `audio-io` | AEC, redução de ruído, AGC, VAD barato, captura em frames de 20 ms, playback cancelável, reporta `PlaybackProgress` real. | Não decide turno, não fala com LLM. |
| `agentd` | ASR incremental, detector semântico de fim de turno, S1, emissão/validação de `epoch`, event log, prioridades P0–P4, coalescing. | Não executa capacidade, não escreve memória durável. |
| `s2` (reasoner) | Atualiza estado de trabalho, planeja, escolhe capacidade na shortlist autorizada, redige resposta. Acordado por evento, **nunca em loop cego**. | Não autoriza, não bloqueia mídia, não publica fala de epoch morto. |
| `policy` (PDP) | `permitir | confirmar | negar` a partir de `tool_id` + argumentos normalizados + identidade + cenário + classe de dado + destino. Emite grants com TTL. | Não consulta o LLM. Não aceita `allowed_tools` vindo de conteúdo. |
| `executor` | Valida schema, injeta credencial de menor privilégio, roda em sandbox, verifica pós-condição, devolve observação rotulada `untrusted`. | Não infere intenção, não eleva privilégio, não tem shell genérico. |
| `memoryd` | Ledger SQLite, outbox de indexação, índice de recuperação atrás de interface trocável, consolidação em segundo plano. | Não indexa no caminho crítico da voz, não promove procedimento a `approved`. |
| `ui` | Confirmação de alto risco, indicador de microfone, PTT, editor/visualizador de memória, log de ações, kill switch. | Confirmação de risco alto **não** pode ser só por voz. |

**Jev (classificador leve)** não é processo: é uma biblioteca chamada por `agentd`/`s2` (§5.2). Ele filtra, nunca autoriza.

**Cliente MCP** também não é processo novo: é **adaptador do `executor`**, um filho isolado por servidor (§5.6). Tool de servidor MCP não vira capacidade sem promoção para manifesto nosso, e a saída é sempre `trust: third_party`. Nenhum atalho entra no barramento por fora do PDP.

**D1 — linguagem/IPC: decidida (ADR-0014, aceita em 2026-10-15).** O critério era medir o p95 de captura→evento nos dois candidatos na máquina do dono, e o cartão F0-04 mediu: VAD em Rust `std` 0,0003 ms p95, em Python+ONNX 0,110 ms, e o evento no barramento (envelope, validação de borda, IPC e log encadeado) 0,384 ms — total nosso de 0,575 ms p95 em Python, **0,72% do orçamento de 80 ms do SLO-1**. A decisão é **Python 3.12 nos sete processos no v0**, com a fronteira pronta para trocar `audio-io`/`agentd` por Rust sem reescrever contrato, porque o contrato vive em `schemas/`. Lacuna explícita, aceita junto com a decisão: AEC real, ASR incremental, TTS streaming e captura de dispositivo real **não** foram medidos — e o **gatilho de reabertura** está escrito na ADR-0014: se a medição da F1 com esses componentes passar de 80 ms p95 em captura→evento (SLO-1) ou de 150 ms p95 no barge-in (SLO-2), D1 reabre sem precisar de nova autorização.

---

## 3. Contrato de evento e de epoch

### 3.1 Envelope comum

Todo evento no barramento, sem exceção:

```jsonc
{
  "schema_version": "1",
  "event_id": "uuid-v7",          // ordenável por tempo
  "session_id": "uuid-v7",
  "epoch": 42,                     // u64 monotônico por sessão
  "ts_mono_ns": 123456789,         // relógio monotônico da máquina de origem
  "ts_wall": "2026-10-15T12:00:00.123Z",
  "source": "audio-io|agentd|s2|executor|memoryd|ui|mcp:<id>",
  "trust": "system|user_voice|user_ui|tool_result|third_party",
  "priority": "P0|P1|P2|P3|P4",
  "type": "...",
  "payload": { }
}
```

`trust` é atribuído pelo processo que **recebe** do mundo, nunca declarado pelo emissor remoto. `third_party` inclui web, e-mail, documento, tela e servidor MCP.

### 3.2 Tipos de evento (v0 fechado)

| Tipo | Origem | Prioridade | Payload essencial |
|---|---|---|---|
| `AudioActivity` | audio-io | P1 (P0 se `speech_started`) | `speech: bool`, `device_id`, `energy_db`, `aec_ok` |
| `PartialTranscript` | agentd | P1 | `text`, `stability: 0..1`, `t_start_ms`, `t_end_ms`, `lang` |
| `FinalTranscript` | agentd | P1 | `text`, `confidence`, `t_start_ms`, `t_end_ms` |
| `TurnPrediction` | agentd | P1 | `p_eot: 0..1`, `detector`, `decision: hold|yield|unknown` |
| `DesktopObservation` | executor/ui | P3 | `kind`, `app_id`, `payload`, sempre `trust: third_party` |
| `ToolCallRequested` | s2 | P2 | `call_id`, `tool_id`, `args`, `dry_run: bool`, `idempotency_key?` |
| `PolicyDecision` | policy | P2 | `call_id`, `verdict: allow|confirm|deny`, `reason`, `grant_id?` |
| `ToolResult` | executor | P2 | `call_id`, `status`, `payload_ref`, `postcondition: verified|unverified|failed` |
| `PlaybackProgress` | audio-io | P1 | `chunk_id`, `played_ms`, `epoch` |
| `StateRevision` | s2 | P2 | estado de trabalho (§3.4) |
| `Cancel` | agentd | **P0** | `epoch_invalidado`, `reason: barge_in|stop_word|privacy|aec_fail|timeout` |

Prioridade decide **qual computação preempta qual**, nunca qual comando executar (relatório 01, §agenda de eventos).

### 3.3 Regras de epoch (obrigatórias, derivadas do relatório 01)

1. `speech_started` local → `epoch := epoch + 1` e emissão imediata de `Cancel(epoch_anterior)`. Não esperar ASR, não esperar S2.
2. `audio-io` esvazia a fila de playback no mesmo tick; `s2` cancela geração; chamadas em voo são marcadas `stale`.
3. Tool **de leitura** `stale` pode terminar; o resultado só entra se `s2` reavaliar que ainda serve no epoch novo. Tool **de efeito** nunca é iniciada por especulação e carrega `idempotency_key` + expiração.
4. O histórico registra apenas `played_ms` real (P4). Texto/áudio enfileirado e não tocado não existe para o modelo.
5. "Continua" não ressuscita o plano antigo: o modelo decide a retomada a partir do trecho realmente tocado.
6. Qualquer evento cujo `epoch` < epoch atual é descartado por padrão, exceto `ToolResult` de leitura (regra 3) e eventos de auditoria.

### 3.4 Estado de trabalho (o que S2 lê, em vez da transcrição inteira)

```jsonc
{ "task_id": "...", "epoch": 42, "objetivo": "...", "evidencia": [{"memory_id|call_id": "...", "resumo": "..."}],
  "incertezas": ["..."], "tarefas": [{"id":"...","estado":"Draft|Planned|AwaitingApproval|Running|Observing|Succeeded|Failed|Cancelled"}],
  "fala_ouvida": "últimos N turnos estáveis", "audio_tocado_ms": 1234, "cenario": {"nome":"trabalho","p":0.81,"ttl_s":300} }
```

Coalescing obrigatório: 10 parciais em 200 ms substituem a hipótese, não disparam 10 raciocínios.

---

## 4. Contrato de capacidade (manifesto de tool)

Manifesto **versionado em repositório**, fora do contexto do modelo. Campos de política **não** vêm do LLM nem de servidor remoto (anotações MCP são dica, não enforcement — relatório 04).

```yaml
id: files.move_to_trash                  # domínio.objeto.verbo
title: Mover arquivo para a lixeira
description: >
  Move um arquivo dentro de uma raiz autorizada para a lixeira do sistema.
  Use quando o usuário pedir para remover/limpar um arquivo. Não apaga de
  forma permanente, não sai da raiz autorizada, não lê o conteúdo.
input_schema:   {type: object, additionalProperties: false, required: [path], properties: {path: {type: string}}}
output_schema:  {type: object, required: [trash_id, restored_path_hint]}
preconditions:  ["path dentro de workspace_root", "arquivo existe"]
postcondition:  "arquivo ausente no caminho original E presente na lixeira"   # verificada pelo executor
capability:     files.write.trash        # chave de ACL
risk_class:     escrita_recuperavel      # §5.3
side_effect:    persistent
reversible:     true
undo:           files.restore_from_trash
idempotent:     false
idempotency:    required                 # executor exige chave
data_egress:    none                     # none | local | network:<destino>
pii_touch:      path_only
confirmation:   once_per_batch           # never | once_per_batch | per_action | handoff
access_level_min: jarvis                 # §5.5: menor modo de acesso em que esta tool existe
roots:          [workspace_root]         # quais raízes do modo valem para esta tool
requires_elevation: false                # §5.5: true só existe com o interruptor de elevação ligado
timeout_ms:     3000
cancellable:    true
platforms:      [linux-wayland, linux-x11, windows]
executor:       local-files
trust_input:    untrusted
tests:          [contract, postcondition, linux-wayland, windows, denial]
version:        1
```

**Regras de catálogo** (relatório 04; guias da OpenAI de <20 funções no prompt e <10 por namespace adiado):

- Núcleo sempre visível: 4–8 tools de leitura/controle de conversa (`status`, `ask_user`, `search_catalog`, `read_notification`, `cancel`).
- Por turno, o planejador vê **no máximo 5–12** capacidades, já filtradas pela política. `allowed_tools` do turno é uma allowlist real, não sugestão.
- Proibido: `run_command`, `do_anything`, qualquer tool "canivete suíço" ou shell irrestrito. Rejeitado em revisão de código.
- Toda tool de escrita oferece `dry_run`/`plan` com recibo antes/depois.
- Descrição passa no "teste do estagiário": um humano chamaria a função certa só com a descrição.
- **Abrir app é capacidade tipada, não linha de comando:** `apps.launch` recebe `app_id` de um registro versionado, nunca `argv` livre, nunca shell (§5.6).
- **Tool de servidor MCP só existe depois de promovida** a manifesto nosso, com `risk_class`, `confirmation`, `data_egress` e `access_level_min` decididos por nós; anotação do servidor entra como comentário (§5.6).

---

## 5. Seleção, cenário e política

### 5.1 Pipeline por turno

```text
estado observável + fala estável
  ├─ Jev: P(cenário), P(intenção), risco estimado  (local, <30 ms [SUPOSIÇÃO: medir em F2])
  ├─ overlay: núcleo invariável + 1 cenário (até 2 em transição)
  └─ recuperação híbrida no manifesto: BM25 ∪ embeddings → top 30 → reranker → top 5–12
           └─ PDP filtra por ACL/SO/app/usuário/egress  → allowed_tools do turno
                  └─ LLM planejador → tool_call tipada → validação de schema
                         └─ PDP decide de novo com argumentos → executor isolado
                                └─ pós-condição → observação `untrusted` → auditoria
```

Evidência de que recuperar em vez de despejar o catálogo ajuda: RAG-MCP reporta −50% de tokens e seleção de 13,62% → 43,13% (arXiv 2505.03275, relatório 04). É um paper, não garantia para desktop: vira hipótese medida em F2.

### 5.2 O que o Jev pode e não pode

| Pode | Não pode |
|---|---|
| Estimar cenário (`trabalho | jogo | casa | mídia | desconhecido`) com probabilidade calibrada e TTL | Conceder autorização, em nenhuma hipótese |
| Filtrar/ordenar a shortlist de tools | Distinguir duas operações de escrita parecidas |
| Decidir "isto exige memória?" e "isto exige S2?" | Escolher entre conta pessoal e profissional |
| Marcar risco estimado para subir o rigor | Compor fluxo de múltiplas tools |

Confiança baixa, mudança de cenário ou qualquer escrita/efeito externo **ampliam** a recuperação e/ou vão para confirmação. Cenário é hipótese com TTL, não verdade: "estou em casa com o notebook do trabalho" compõe, não força categoria.

### 5.3 Política de confirmação

| Classe de risco | Exemplos | Decisão |
|---|---|---|
| `leitura_local` | listar janelas, status do player, buscar arquivo em raiz autorizada | permitir, registrar, limitar volume |
| `transitorio_reversivel` | focar janela, volume, pausa, luz por sessão | permitir se cenário e escopo batem; oferecer desfazer |
| `escrita_recuperavel` | lixeira, rascunho, reordenar fila | confirmar 1× por lote explícito ou grant estreito |
| `egress_representacao` | enviar e-mail/mensagem, postar, upload, compartilhar tela/arquivo | confirmar **no momento do envio**, mostrando destino, resumo e anexos |
| `alto_impacto` | apagar permanente, pagar, instalar, executar baixado, mudar permissão/VPN/sistema | confirmação específica por ação, **uma chamada por vez** |
| `credencial_barreira` | trocar senha, OTP, CAPTCHA, aviso de HTTPS/paywall | entregar o controle ao usuário; nunca contornar |

- Confirmação de `alto_impacto`, `egress_representacao` e `credencial_barreira` **exige UI** (ou segundo fator). Voz sozinha não confirma em ambiente ruidoso.
- "Sempre permitir X" cria um **grant** `{tool_id, destino, classe_de_dado, ttl, escopo}` visível e revogável na UI. Nunca uma permissão global implícita.
- Conteúdo `third_party` não cria grant, não muda cenário, não pede segredo e não converte confirmação em permissão. Sessão que abriu web/e-mail/documento fica marcada como contaminada e sobe o rigor.

### 5.4 Camadas de atuação no desktop

Ordem obrigatória: **API/integração oficial > protocolo bem definido (D-Bus, MPRIS, xdg) > árvore de acessibilidade (UIA no Windows, AT-SPI no Linux) > navegador com DOM isolado > tela+coordenadas**. Visual é fuga, limitado a 1–3 ações por vez, com foco verificado e parada se a tela divergir.

Wayland: entrada e captura só via portal `org.freedesktop.portal.RemoteDesktop`/`ScreenCast` (consentimento do compositor, sessão explícita, revogável). X11: XTEST funciona e por isso é mais perigoso — sessão dedicada, desligado quando ocioso, nunca elevar privilégio para contornar. Windows: UIA + PowerShell contido.

---

### 5.5 Modelo de acesso: quatro níveis e um interruptor de elevação

Decisão do dono (ADR-0009). O alcance do Jarvis no disco é **configuração dele**, não inferência do modelo (P12).

| Modo | Nome do dono | O que materializa | Amplitude |
|---|---|---|---|
| `jarvis` | nível 2 — só a pasta do Jarvis | `~/.local/share/jarvis` (dados, corpus, cofre) e mais nada | menor |
| `padrao` | nível 1 — só pastas padrão | Documentos, Downloads, Imagens, Música, Vídeos, Área de Trabalho + a pasta do Jarvis | ↑ |
| `concedido` | nível 3 — pastas específicas concedidas | `padrao` + raízes que o dono adicionou uma a uma na UI, com permissão por raiz | ↑ |
| `total` | nível 4 — PC inteiro | a árvore do usuário e do sistema, **menos a lista de negação** | maior |

A numeração do dono é preservada como nome, mas a ordem real de amplitude é `jarvis ⊂ padrao ⊂ concedido ⊂ total` — a UI lista nessa ordem, porque "nível 2" é mais estreito que "nível 1".

**Lista de negação vence até no `total`:** `~/.ssh`, `~/.gnupg`, chaveiros, perfis de navegador, gerenciador de senha, `.env`, caches de token, `/etc/shadow`; no Windows, credenciais do DPAPI, hives do registro e LSASS; carteiras de cripto. "PC inteiro" não é "credenciais". Ler cofre de segredo é **negado**, não confirmável — a exceção é item único liberado pelo dono na UI, com TTL.

**Enforcement em dois lugares independentes:**

1. **PDP** decide sobre argumentos normalizados: modo atual, raiz resolvida, `access_level_min` e `requires_elevation` do manifesto, classe de risco, cenário, destino de egress. Emite grant com TTL e escopo.
2. **Executor** confere de novo no momento da chamada de sistema, e **opera sobre descritor, não sobre string**: a raiz é aberta uma vez no grant e tudo acontece relativo a ela (`openat2` com `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS` no Linux; handle com `FILE_FLAG_OPEN_REPARSE_POINT` + `GetFinalPathNameByHandle` no Windows), conferindo identidade do arquivo (device+inode / file id) contra o autorizado. Caminho fora da raiz deixa de ser expressável.

**Canonicalização obrigatória** antes de qualquer comparação: normalização unicode, `..` resolvido, link simbólico resolvido até o fim; no Windows também recusa ADS (`a.txt:oculto`), nome 8.3, dispositivo reservado (`CON`, `NUL`, `COM1`…), UNC e `\\?\`, caminho relativo a unidade (`C:foo`), ponto/espaço final, e compara com case-folding completo.

**TOCTOU é a falha a evitar:** checar a string e depois abrir permite trocar um link simbólico no meio. Por isso a decisão vale sobre o descritor aberto, e a suíte de corrida da F0-06 é critério de aceite — não revisão de código.

**Elevação é ortogonal e desligada por padrão.** `total` **não** implica elevação. Desligada, toda capacidade `requires_elevation: true` é filtrada **antes de o modelo ver o catálogo** (não é negada depois: o planejador não pode nem propor). Ligada: por ação, confirmada na UI, TTL curto, uma chamada por vez, `argv` exato auditado; o segredo é digitado pelo dono no prompt do SO (polkit/UAC) e o Jarvis nunca captura, guarda ou reusa, nunca instala regra `NOPASSWD`, nunca mantém sessão root e nunca roda como serviço privilegiado.

**Como o nível muda em tempo de execução:** só pela UI, com o dono presente (autenticação do SO ou senha do app). Não existe capacidade que mude nível ou elevação — verificado por teste que varre o catálogo. Voz sozinha não muda; conteúdo `third_party` e servidor MCP não mudam. A mudança incrementa `policy_epoch`, invalida grants de amplitude maior e vale a partir da próxima fronteira de turno; **reduzir vale na hora** e cancela chamadas em voo; **ampliar** exige confirmação explícita e é anunciado por voz.

**O que continua exigindo confirmação mesmo no `total`** (P13): apagar permanente, sobrescrever sem desfazer, operação recursiva ou lote acima do teto, renomear em massa; qualquer egress ou representação do dono (enviar, postar, subir, compartilhar); instalar ou executar baixado; mudar sistema, permissão, VPN ou firewall; a própria elevação; e tocar fora do diretório do dono. Credencial e barreira (OTP, CAPTCHA, aviso de HTTPS) continuam entregues ao dono (§5.3), nunca contornadas.

**Auditoria:** decisão registrada **antes** do efeito, resultado anexado depois, cada registro com o sha256 do anterior (cadeia à prova de edição silenciosa). Campos mínimos: `policy_epoch`, modo, raiz, identidade do arquivo, `argv`, elevação, `grant_id`, veredito, motivo, resultado, sessão contaminada. Legível, filtrável e exportável na UI.

### 5.6 Catálogo do v1 e porto para clientes MCP

Escopo do v1 fechado pelo dono (Q3): **arquivos + mídia + calendário em rascunho**, mais **abrir apps**, e o escopo **cresce por níveis** — família nova entra com manifesto, testes e classe de risco, nunca esticando uma tool existente (ADR-0010).

| Família | Capacidades do v1 | Classe predominante |
|---|---|---|
| núcleo | `status`, `ask_user`, `search_catalog`, `read_notification`, `cancel` | leitura/controle |
| `files.*` | `search_in_roots`, `list_dir`, `read_metadata`, `read_text`, `move_to_trash`, `restore_from_trash`, `copy`, `move`, `make_dir`, `write_text` (com `dry_run`), `reveal_in_file_manager` | leitura local e escrita recuperável |
| `apps.*` | `list_installed`, `list_windows`, `launch`, `focus_window`, `close_window`, `quit_app` | transitório reversível |
| `media.*` | `get_now_playing`, `play`, `pause`, `next`, `previous`, `set_volume` (limitado) — MPRIS no Linux, SMTC no Windows | transitório reversível |
| `calendar.*` | `list_events`, `get_event`, `create_draft_event`, `propose_update` — **rascunho local, não envia convite** | leitura e escrita recuperável |
| `system.read.*` | bateria, rede, espaço em disco, sessão | leitura local |

- **`apps.launch`** resolve `app_id` de um registro versionado derivado do índice do SO (`.desktop` no Linux, Menu Iniciar/AppX no Windows). Sem shell, sem `argv` livre, ambiente saneado, sem elevação; o único argumento opcional é um caminho que já passou pela checagem de raiz (§5.5). Abrir app que renderiza conteúdo de terceiro (navegador, e-mail) **marca a sessão como contaminada** e sobe o rigor.
- **Calendário no v1 não envia nada.** Envio é `egress_representacao` e confirma no momento do envio. Qual backend (ICS local, Evolution Data Server, API de nuvem) é **decisão aberta D2**, resolvida quando a família entrar em F4.
- **Fora do v1, de propósito:** ler área de transferência, casa/IoT, navegador automatizado, e qualquer escrita de calendário que saia da máquina.

**Porto MCP (Orchestrator e outros):**

1. Cliente MCP é **adaptador do `executor`**, um filho isolado por servidor, sem rede a menos que o servidor declare e o dono conceda.
2. **Tool remota não é capacidade até ser promovida:** cada uma gera um **rascunho** de manifesto (§4) que o dono aprova na UI ou o arquiteto comita. Antes disso, invisível ao planejador.
3. `risk_class`, `confirmation`, `data_egress` e `access_level_min` são **nossos**. Anotação do servidor (`readOnlyHint`, `destructiveHint`) é dica, não enforcement (relatório 04) — um servidor comprometido mentiria justamente nesse campo.
4. **Identidade pinada:** comando/URL + hash do binário ou imagem + hash da lista de tools. Lista mudou (rug-pull), as capacidades promovidas daquele servidor ficam **suspensas** até reaprovação.
5. **Saída de MCP é `trust: third_party`, sempre** (P6): validada por schema, truncada por orçamento, entregue ao S2 em envelope de dado. Não amplia `allowed_tools`, não cria grant, não muda cenário, não vira memória durável sozinha; conteúdo que imita chamada de ferramenta é neutralizado.
6. **Orchestrator entra por allowlist estreita** (`retrieve_memory`, `get_memory_chunk`, `store_memory`, `log_decision`, `ask_owner`, `cli_ping`, `jev`). `shell_exec`, `ssh_exec`, `cli_send` e afins são **proibidos de promoção**: a proibição de canivete suíço da §4 não se contorna chamando por MCP. Chamada carrega contador de salto e Jarvis→Orchestrator→Jarvis é recusado.

## 6. Memória

### 6.1 Camadas

| Camada | Conteúdo / vida | Onde | Entra no prompt |
|---|---|---|---|
| Trabalho | turnos recentes, estado da tarefa, tools em curso (minutos) | RAM (§3.4) | sempre, com orçamento fixo |
| Episódica | observação datada com proveniência | SQLite + índice | por relevância, tempo, entidade, projeto |
| Semântica | fatos/preferências normalizados | SQLite + índice | só assertivas `active` com evidência |
| Procedural | regras e playbooks aprovados | arquivo versionado + SQLite | só o que foi aprovado por humano |
| Grafo pessoal (entidades/temporal) | pessoas, apps, arquivos, projetos e arestas com validade | tabelas SQLite (§6.7) | ativação por propagação de **1–2 saltos**, dentro de orçamento (§6.8) |
| Arquivo | bruto cifrado, anexos | cofre local | nunca automático |

### 6.2 Esquema (livro-razão SQLite, fonte de verdade)

```sql
episode(id, occurred_at, ingested_at, session_id, actor, source, kind,
        raw_cipher_ref, sha256, trust, pii_class, retention_until)
entity(id, type, canonical_name, aliases_json, created_at, status)
assertion(id, subject_entity, predicate, value_json, scope, confidence,
          observed_at, valid_from, valid_to, status,          -- proposed|active|superseded|retracted|quarantined
          source_episode_id, supersedes_id, approved_by)
memory_unit(id, episode_id, assertion_id, text_redacted, embedding_version,
            content_hash, importance, access_count, last_accessed_at)
procedure(id, trigger, instruction, version, state, evidence_ids, approver)  -- draft|approved|disabled
entity_edge(id, src, relation, dst, source_episode_id, valid_from, valid_to, confidence, status)
outbox(id, memory_unit_id, op, attempts, next_attempt_at, content_hash)      -- indexação idempotente
```

Integridade: (a) todo fato aponta para ≥1 episódio; (b) contradição encerra `valid_to` e cria nova assertiva — não apaga; (c) `observed_at` ≠ `valid_from/to`; (d) vetores são índice descartável, reconstituível por `content_hash` + `embedding_version`; (e) segredo e PII sensível entram no índice só como ponteiro/redação.

### 6.3 Interface de índice (trocável — o ponto central da medição)

```text
MemoryIndex:
  upsert(items: [{id, text_redacted, embedding?, metadata, content_hash}]) -> ack
  delete(ids | filter) -> contagem
  search(query, k, filter{scope, status, tempo, tipo}, mode: dense|lexical|hybrid) -> [{id, score, rank_source}]
  stats() -> {count, bytes, embedding_version}
```

Duas implementações desde F1: `ChromaIndex` (padrão, por decisão do dono — reaproveita o que já roda no Orchestrator, ChromaDB + reranker) e `LanceIndex` (candidato da pesquisa: embutido, BM25/FTS e RRF na própria API). A escolha final sai da medição (§8.1), não de preferência.

Pipeline de recuperação (versão completa com grafo em §6.8): `filtro ACL+tempo+status → top 40 léxico + top 40 denso + ativação de grafo → RRF → top 20 no cross-encoder de licença comercial (se houver orçamento) → MMR → 4–8 evidências com IDs e com o caminho que as justificou`. Pontuação baixa ⇒ "não encontrei evidência", nunca lembrança inventada.

### 6.4 Escrita e consolidação

Caminho crítico só grava episódio + outbox. Worker assíncrono redige, embeda **apenas o delta** e indexa; falha é reexecutável por `content_hash`. Consolidação roda em ociosidade (p.ex. 2 min de silêncio, fim de tarefa ou N episódios) com orçamento, comparando só o lote novo com candidatos do mesmo sujeito/predicado. Ela pode propor assertiva, confirmar, revisar, marcar conflito e resumir. Nunca apaga bruto, nunca aprova procedimento, nunca guarda credencial.

### 6.5 Esquecimento

| Classe | Retenção | Esquecimento |
|---|---|---|
| Preferência estável confirmada | até ser contradita | substituição temporal; apagável pelo dono |
| Episódio trivial | TTL 30–90 dias **[SUPOSIÇÃO: calibrar em F3]** | expira índice e conteúdo |
| Decisão/ação do Jarvis | longa, com evidência | tombstone auditável |
| Estado mutável (agenda) | entre `valid_from/to` | nunca responder estado vencido como atual |
| Credencial, saúde, finanças, íntimo | opt-in, cofre separado, ACL estrita | TTL curto; apagar sob pedido e reindexar |

### 6.6 Gates de memória (antes de qualquer escrita autônoma)

1. 100% dos fatos citados trazem episódio fonte. 2. Exclusão remove raw, FTS, vetor, resumo, cache **e grafo** (menção e aresta que só aquele episódio sustentava) — verificado por teste. 3. Nenhum segredo sintético aparece em consulta sem escopo. 4. Conflito temporal não retorna fato vencido como atual. 5. Texto recuperado não vira política nem amplia ferramenta (teste de injeção). 6. **Toda evidência devolvida traz o caminho que a justificou** (acerto denso/léxico direto, ou aresta por aresta) — sem caminho, não entra no prompt nem na UI.

---

### 6.7 Grafo de conhecimento pessoal (no mesmo SQLite)

Pedido do dono: memória **semântica com grafo**, mais natural e instantânea. Decisão em ADR-0008; o livro-razão continua sendo a fonte de verdade (P7) e o vetor continua descartável.

```sql
-- além das tabelas da §6.2:
entity_mention(id, episode_id, memory_unit_id, entity_id, span_json, confidence,
               extractor, extractor_version, status)        -- proposed|active|rejected
entity_resolution(alias_norm, entity_id, score, method)      -- apelido/diminutivo/sigla → entidade
graph_node_stats(entity_id, degree, hubness, updated_at)     -- penalidade de hub, recalculada em ociosidade
-- entity_edge ganha: weight, support_count, last_seen_at, extractor, extractor_version
-- índices obrigatórios:
--   entity_edge(src, relation, status), entity_edge(dst, relation, status)
--   assertion(subject_entity, predicate, status, valid_from)
--   memory_unit(assertion_id), entity_mention(entity_id), entity_resolution(alias_norm)
```

Regras do grafo:

- **Construir é trabalho de segundo plano.** Extração de entidade e relação roda na consolidação (§6.4), nunca no caminho da voz. Aresta nasce `proposed` e vira `active` só com (a) duas evidências independentes, (b) extrator determinístico de alta confiança (caminho de arquivo → app, participante de evento → pessoa, remetente → pessoa) ou (c) confirmação do dono.
- **Toda aresta tem proveniência e validade:** `source_episode_id`, `valid_from/valid_to`, `confidence`. Contradição encerra a validade e cria aresta nova — não apaga (P7). Convergente com o que Zep/Graphiti faz com `invalid_at` (arXiv 2501.13956).
- **Peso é derivado, não digitado:** função de `support_count`, recência (`last_seen_at`), confiança do extrator e confiança da fonte. Fonte `third_party` entra com peso reduzido e nunca sozinha promove aresta (P6).
- **Hub é penalizado:** `1/log(1+degree)`. Sem isso, "arquivo", "pasta" e o nome do dono viram atalho para tudo.
- **Apagar episódio derruba o que ele sustentava:** menção sai, aresta sem outro suporte sai, `support_count` cai. É o gate 6 da §6.6.

### 6.8 Recuperação combinada: ativação por propagação + índice semântico

Na hora da consulta o grafo é **SQL puro e limitado — zero chamada de LLM**. Isso não é economia, é requisito: nos benchmarks publicados, consulta de grafo com LLM no laço fica em segundos (LightRAG local 2,54–3,17 s; GraphRAG local 3,53–4,27 s; busca global do GraphRAG de 8,57 s a 162,66 s, com medição de referência de ~42,8 s e ~196 chamadas de LLM por consulta — arXiv 2609.10239 e material correlato, **não replicado por nós**). Nosso orçamento é SLO-7/SLO-12: dezenas a centenas de milissegundos.

**Algoritmo (determinístico):**

1. **Semear.** (a) termos da consulta → `entity_resolution` (exato, normalizado, trigrama) → entidades; (b) top-k denso da `MemoryIndex` → suas `memory_unit` → entidades e assertivas. Peso inicial = escore normalizado.
2. **Propagar.** BFS limitada, **máximo 2 saltos**, energia decaindo por salto, multiplicada por peso de aresta × confiança da fonte × filtro de validade temporal, com penalidade de hub. Tetos simultâneos: nós expandidos por salto, nós visitados, arestas lidas e **orçamento em milissegundos**. Estourar devolve o que tem com `graph_truncated: true` e segue — nunca espera (P9).
3. **Fundir.** Três listas ranqueadas — densa, léxica (FTS5) e ativação de grafo — por RRF; depois cross-encoder de **licença comercial** (ADR-0011) no top-20 se houver orçamento; depois MMR; depois 4–8 evidências com ID **e com o caminho** (acerto direto ou aresta por aresta). O caminho alimenta tanto o prompt quanto a tela "o que sei sobre você" — é o "por que eu lembrei disto".
4. **Tempo manda.** Tudo filtrado por `status='active'` e por `valid_from/valid_to` contra o instante de que a pergunta fala (agora, ou "terça passada"). Havendo contradição, responde o vigente e avisa que há histórico; nunca entrega o vencido como atual (§6.6, gate 4).
5. **Abstinência.** Escore fundido abaixo do limiar e grafo sem evidência nova ⇒ "não encontrei evidência". Limiar calibrado nos negativos do corpus C2.

**Nada de parâmetro mágico** (pedido explícito do dono). Saltos, decaimento, pesos de fusão, tetos e limiar:

- são **calibrados em corpus anotado**, com calibração em 70% e números reportados nos 30% retidos — para não escolher parâmetro no mesmo dado que mede;
- ficam em **arquivo versionado** com o hash do corpus e a data; mudar parâmetro é commit, não ajuste em produção;
- são **adaptativos dentro de limites**, por degraus, escalando só enquanto a resposta não se sustenta e o orçamento permite:

| Degrau | O que roda | Quando escala |
|---|---|---|
| 0 | memória de trabalho (§3.4), cache da sessão | sempre primeiro |
| 1 | denso k≈8, sem reranker, sem grafo | pergunta factual direta |
| 2 | + léxico + **1 salto** de grafo | pergunta relacional, apelido/sigla, entidade ambígua |
| 3 | + **2 saltos** + reranker | 1–2 não sustentaram, pergunta multi-salto ou temporal, e há orçamento |
| 4 | modo "fundo": PPR amplo, fora do caminho da voz | só na UI de exploração e na consolidação |

Evidência de que grafo ajuda multi-salto: HippoRAG ranqueia passagens por Personalized PageRank sobre um grafo construído por LLM e relata ganho de ~3 e ~20 pontos em MuSiQue e 2WikiMultiHopQA, sendo 10–30× mais barato e 6–13× mais rápido que o IRCoT iterativo (arXiv 2405.14831, NeurIPS 2024; números do abstract, variam entre versões). Zep/Graphiti relata 94,8% vs 93,4% no DMR e até +18,5% de acurácia com −90% de latência no LongMemEval (arXiv 2501.13956) — **números do próprio fornecedor, em benchmark que o blog deles relativiza**: servem de motivação, não de meta. A ideia de ativação por propagação vem da literatura clássica de memória associativa (Collins & Loftus, 1975; ACT-R) — usamos o mecanismo, não números de lá. **Confirmado pela medição** (ADR-0013, cartões F0-05 e F0-08): a travessia limitada em SQLite cabe no orçamento de voz com uma a duas ordens de grandeza de folga, inclusive no corpus real do dono (128 episódios, 676 arestas `active`, grau máximo 131) e num grafo sintético 100× maior. Duas condições saíram da medição e passaram a valer como requisito: o teto de fan-out é aplicado **dentro** da varredura (uma consulta por nó, `ORDER BY ... LIMIT`), e `WITH RECURSIVE` sem teto está fora — ficou 100–200× mais lenta e estourou o orçamento.

## 7. SLOs

Medidos **do microfone ao alto-falante do usuário**, não no servidor. Metas de produto, não promessa de fornecedor. Âncoras externas: Voice-Light mediu mediana de 758 ms do endpoint VAD ao primeiro áudio em 36 turnos (estudo de caso pequeno, inglês); Moshi relata ~200 ms práticos em S2S nativo; Semantic VAD de 2023 reporta −53,3% de latência média em conjunto interno (relatório 01).

| # | Caminho | p50 | p95 | Observação |
|---|---|---:|---:|---|
| SLO-1 | Captura → AEC/VAD → evento de fala | ≤ 40 ms | ≤ 80 ms | local |
| SLO-2 | Início de fala do usuário → playback silenciado | ≤ 80 ms | **≤ 150 ms** | não esperar transcrição |
| SLO-3 | Primeiro parcial ASR utilizável | ≤ 250 ms | ≤ 450 ms | hipótese, não compromisso |
| SLO-4 | Pausa → decisão semântica de turno | ≤ 120 ms | ≤ 250 ms | medir falso corte à parte |
| SLO-5 | Fim de turno aceito → primeiro áudio (pergunta simples) | ≤ 600 ms | ≤ 900 ms | ponte curta se tool demora |
| SLO-6 | Evento relevante → revisão do S2 | ≤ 400 ms | ≤ 1 s | com coalescing |
| SLO-7 | Recuperação de memória (k=8, com filtro) | ≤ 80 ms | ≤ 200 ms | sem reranker |
| SLO-8 | Recuperação + reranker top-20 | ≤ 250 ms | ≤ 600 ms | reranker é feature flag |
| SLO-9 | Falso corte de turno (interromper o usuário) | — | ≤ 3% dos turnos | **[SUPOSIÇÃO: alvo inicial; recalibrar com o corpus pt-BR de F1]** |
| SLO-10 | Efeitos externos iniciados sem confirmação exigida | 0 | 0 | absoluto |
| SLO-11 | Ativação de grafo, 1 salto (dentro dos tetos da §6.8) | ≤ 15 ms | ≤ 40 ms | **Confirmado** pelo harness da F0-05 e pelo corpus real da F0-08: p95 de 0,22 ms com 1 salto e 3,29 ms com 2 saltos no C1 do dono (ADR-0013) |
| SLO-12 | **"Instantâneo"**: memória pronta para o S2 (grafo+vetor fundidos, sem reranker) | ≤ 120 ms | **≤ 250 ms** | **Confirmado** pelo harness da F0-05: p95 de 62 ms na escala 100× (ADR-0013). Com reranker: p95 ≤ 600 ms (SLO-8), que é feature flag |
| SLO-13 | Turnos em que a recuperação estourou o orçamento e voltou truncada | — | ≤ 2% | e **0** turnos em que a memória atrasou o primeiro áudio além de SLO-5 |

**O que "instantâneo" significa neste projeto:** não é adjetivo, é SLO-12 medido na máquina do dono, no corpus do dono, com 2 saltos e os tetos da §6.8 — p50 ≤ 120 ms e p95 ≤ 250 ms sem reranker. Acima de tudo, **memória não atrasa a voz**: SLO-5 (≤ 900 ms p95 até o primeiro áudio) continua valendo *com* a memória no caminho; se não couber, a resposta sai com a evidência que já havia e o grafo chega depois, nunca o contrário.

O que se otimiza é a **curva falso corte × atraso**, não um número único de latência.

---

## 8. Planos de medição

### 8.1 Chroma vs LanceDB (decide F1→F2)

A pesquisa recomenda LanceDB; o dono escolheu ChromaDB como padrão por já estar em produção no Orchestrator com reranker. Em vez de discutir, medir. **Nenhuma das duas é fonte de verdade** — o ledger SQLite é (P7), então a troca é barata por construção.

**Corpus real (não sintético):**
- C1: memórias/decisões já existentes do Orchestrator exportadas para o esquema §6.2 (volume real; registrar `n` no relatório).
- C2: 100–300 consultas pt-BR anotadas pelo dono e pelo arquiteto, cobrindo: diminutivos e apelidos, datas relativas ("terça passada"), code-switch PT/EN, siglas, nomes de arquivo/app, contradição temporal e **casos que devem retornar nada** (abstinência correta).
- C3: 10 consultas de carga para latência sob indexação concorrente.

**Protocolo:** mesmo hardware (máquina do dono), mesmo embedding, mesma versão de reranker, mesmo `k`, mesmo filtro de ACL/tempo. Três execuções; relatar mediana e p95. Embeddings a comparar no mesmo arcabouço: `intfloat/multilingual-e5-base` (baseline CPU, 278M, 94 idiomas) e, se a GPU permitir, `BAAI/bge-m3` e `Qwen3-Embedding-0.6B`. Reranker: medir com e sem; atenção à licença (`jina-reranker-v2-base-multilingual` é CC-BY-NC-4.0 — incompatível com uso comercial; alternativas `bge-reranker-v2-m3`, `Qwen3-Reranker-0.6B`).

| Métrica | Como mede | Peso na decisão |
|---|---|---|
| `recall@20` e `nDCG@10` em C2 | gabarito anotado | **alto** |
| Abstinência correta (consulta sem resposta) | taxa de "não encontrei" correto | **alto** |
| Híbrido nativo (BM25/FTS + fusão RRF) | precisa de código externo? quanto? | **alto** |
| p50/p95 de `search` (SLO-7/8) | 3 execuções, carga fria e quente | alto |
| Custo de indexação do delta | tempo e CPU por 1k unidades | médio |
| RSS e disco com o corpus inteiro | medir processo | médio |
| Filtro por metadado + tempo antes do ranking | funciona sem pós-filtro? | alto |
| Deleção em cascata verificável (§6.6) | teste de exclusão | **veto** |
| Operação em Windows e Linux sem serviço extra | instalar do zero nos dois | **veto** |

**Regra de decisão (fechada antes de medir, para não escolher depois do resultado):**
1. Quem falhar num critério de **veto** está fora.
2. Se a diferença de `recall@20` for ≤ 2 pontos absolutos e a de p95 ≤ 30%, **fica Chroma** (menor custo de migração, dono já opera).
3. Se LanceDB ganhar > 5 pontos de `recall@20` **ou** reduzir o p95 em > 2×, **troca para LanceDB** e o Chroma vira importador somente-leitura.
4. Zona cinzenta entre 2 e 5 pontos: decide o dono, com a tabela na mão.
5. O resultado vira ADR-0005-amendment com os números e a data.

---

### 8.2 Grafo+vetor vs vetor puro vs híbrido (decide se o grafo entra no caminho da voz)

O dono pediu grafo; medir se o grafo paga o próprio custo **no corpus dele** é o que impede isso de virar fé. Três braços, mesmo ledger, mesmo embedding, mesmo `k`, mesma máquina, mesmo filtro de ACL/tempo, três execuções:

| Braço | O que é |
|---|---|
| **A — vetor puro** | denso k=8 na `MemoryIndex`, sem léxico, sem grafo, sem reranker |
| **B — híbrido** | denso ∪ léxico (FTS5) → RRF → reranker comercial no top-20 → MMR |
| **C — grafo+vetor** | B + ativação por propagação de 1–2 saltos (§6.8), tetos e orçamento ligados |

**Corpus** (o C2 da §8.1, estratificado em subconjuntos anotados, 100–300 consultas no total):

- **C2a factual de 1 salto** ("qual meu editor padrão")
- **C2b relacional/multi-salto** ("o arquivo que o fulano mandou na terça sobre o contrato", "o app que eu uso para aquilo que o cliente pediu")
- **C2c contradição temporal** (preferência que mudou; estado vencido que não pode voltar como atual)
- **C2d negativos** — devem retornar nada; abstinência correta é métrica, não falha

**Métricas:** `recall@20` e `nDCG@10` por subconjunto; **taxa de resposta sustentada** (a evidência devolvida bastava para responder, anotado); abstinência correta em C2d; p50/p95 de cada braço; custo de indexação (o grafo tem o extra da extração); disco e RSS; e **precisão de aresta** por amostragem de 100 arestas `active` revisadas à mão.

**Regra de decisão (fechada antes de medir):**

1. **Veto:** braço que falhe qualquer gate da §6.6 ou que estoure SLO-12 (p95 > 250 ms sem reranker) está fora do caminho da voz — pode sobrar como degrau 4 (modo "fundo").
2. **C vira o padrão** se, em C2b+C2c, ganhar **≥ 5 pontos de `recall@20` ou ≥ 0,05 de nDCG@10** sobre B, **sem** piorar a abstinência correta em mais de 2 pontos e **sem** passar de 250 ms de p95.
3. Ganho de C sobre B entre **2 e 5 pontos**: C fica como **degrau adaptativo** (§6.8, degraus 2–3), acionado só quando B não sustenta a resposta — não como padrão de todo turno.
4. Ganho **< 2 pontos**: o grafo **não entra no caminho crítico** nesta fase; fica na consolidação e na UI de exploração. ADR-0008 é emendada com os números e o motivo.
5. Precisão de aresta **< 80%** na amostra: C está fora até a extração melhorar, qualquer que seja o ganho de recuperação — aresta errada é memória errada, e memória errada é pior que memória rasa.
6. Se **B perder de A** em C2b, a hipótese mais provável é bug de implementação, não resultado: reexecutar uma vez com revisão antes de concluir qualquer coisa.
7. Parâmetros (saltos, decaimento, pesos de RRF, limiar) são calibrados em **70%** do corpus e os números do relatório saem dos **30% retidos**. Calibrar e medir no mesmo dado invalida a rodada.
8. O resultado vira **ADR-0008-amendment** com números, data, hash do corpus, commit e hardware.

Este experimento roda em **F3**, depois que o harness da **F0-05** já disse se 2 saltos cabem no orçamento. Se F0-05 mostrar que não cabem, o braço C entra com 1 salto e isso é registrado antes de medir.

## 9. Fases e critérios de aceitação

Cada fase só fecha com os testes **automatizados** passando nos dois sistemas operacionais.

### F0 — Esqueleto, medição e portas de qualidade
**Cartões delegáveis em `docs/F0-tarefas.md`** (F0-01 a F0-10), cada um com objetivo, entrega, aceite testável, fora de escopo e dependência. Resumo:

| Cartão | Entrega |
|---|---|
| F0-01 | repositório, licença comercial, linter, CI em Linux **e** Windows |
| F0-02 | barramento com os tipos fechados da §3, prioridades, coalescing, log append-only encadeado por hash |
| F0-03 | os sete processos como esqueleto; evento sintético atravessa tudo com `epoch` preservado |
| F0-04 | **harness de latência de captura e decisão D1** (Rust vs Python+ONNX, com piso de ruído do dispositivo) |
| F0-05 | **harness da memória em grafo**: esquema §6.2+§6.7, ativação em SQL puro, confirma SLO-11/SLO-12 |
| F0-06 | esqueleto de política: raízes dos 4 modos, lista de negação, canonicalização, **suíte de TOCTOU** nos dois SOs |
| F0-07 | ferramental de manifesto (§4) com validador, codegen e lint anti-canivete-suíço |
| F0-08 | estrutura de `corpus/` + exportador das memórias do Orchestrator para o esquema §6.2 (C1, com `n`) |
| F0-09 | **porta de licença no CI**: falha em qualquer modelo ou dependência não comercial |
| F0-10 | ADRs com os números medidos (D1; emenda da ADR-0008; emenda da ADR-0011 se preciso) |

Aceite: (a) um evento sintético atravessa `audio-io → agentd → s2 → policy → executor` e volta, com epoch preservado; (b) p95 de captura→evento medido e publicado nas duas linguagens candidatas, com `n`, hardware e 3 execuções; (c) CI verde nos dois SOs; (d) D1 decidido por número em ADR; (e) SLO-11 e SLO-12 confirmados ou corrigidos pelo harness de grafo, com o limite real de saltos; (f) suíte de TOCTOU da §5.5 passando em Linux e Windows; (g) porta de licença verde; (h) `n` do corpus C1 publicado.

**F0 não decide:** índice (Chroma vs LanceDB, §8.1), grafo no caminho crítico (§8.2) nem backend de calendário (D2) — isso precisa de corpus e vem em F3/F4.

### F1 — Conversa que sabe calar
**Cartões delegáveis em `docs/F1-tarefas.md`** (F1-01 a F1-16), um commit cada, com aceite verificável, o que **não** se verifica sem hardware real e a separação do que só o dono pode validar na máquina dele. Doze dos dezesseis fecham sem microfone (áudio gravado/sintético e dispositivos falsos).
Entrega: AEC/VAD/ASR incremental, detector de turno, S1, TTS streaming cancelável, PTT, indicador de microfone, corpus pt-BR de turno (≥500 pausas reais, consentidas).
Aceite: (a) SLO-1, SLO-2, SLO-3, SLO-4 atingidos na máquina do dono; (b) suíte de cancelamento: interromper em 20 pontos distintos de uma resposta → 0 casos de áudio velho tocando, 0 de entrada no histórico, 0 de tool disparada depois; (c) histórico contém só `played_ms` real; (d) curva falso corte × atraso publicada, com A/B entre silêncio fixo e detector semântico; (e) sem rede, cai para PTT e diz isso.

### F2 — Tools por julgamento, com política
Entrega: manifesto (§4), SDK de tool, PDP com os 4 modos de acesso (§5.5), auditoria encadeada, Jev de cenário/intenção, recuperação híbrida de tools, 15–25 capacidades **só leitura/transitórias** das famílias do v1 (§5.6: `files` leitura, `apps` listar/focar/abrir, `media`, `calendar` leitura, `system.read`), porto MCP com promoção de manifesto, simulador de tools, corpus de 200–500 enunciados por cenário (com negativos e ambíguos).
Aceite: (a) `recall@5` do roteador de tools publicado por família; (b) 100% das chamadas validadas por schema antes de executar; (c) nenhuma ação disparada por frase/keyword (auditoria de código + teste de paráfrase inédita); (d) suíte de prompt injection, **incluindo saída de servidor MCP e rug-pull de lista de tools**: 0 casos em que conteúdo `third_party` amplia `allowed_tools`, muda cenário, vira memória ou muda nível de acesso; (e) replay de sessão reproduz plano, decisão de política e latências.

### F3 — Memória com proveniência
Entrega: ledger SQLite cifrado, outbox, **grafo pessoal das §6.7/§6.8 com extração em segundo plano**, `MemoryIndex` com as duas implementações, consolidação, tela "o que sei sobre você" com editar/apagar/exportar **e o caminho de cada lembrança**, medição do §8.1 **e do §8.2**.
Aceite: (a) os **6** gates de §6.6 passam; (b) SLO-7, SLO-8, **SLO-11, SLO-12 e SLO-13** atingidos; (c) relatórios de §8.1 e §8.2 publicados, com ADR-0005 e ADR-0008 emendadas pelos números; (d) exclusão em cascata verificada por teste que varre raw, FTS, vetor, resumo, cache **e grafo**; (e) corpus pt-BR de 100–300 casos com `recall@20`, nDCG@10, resposta sustentada e abstinência correta publicados por subconjunto (C2a–C2d); (f) precisão de aresta amostrada em 100 arestas `active`.

### F4 — Escrita, desktop e confirmação
Entrega: `dry_run`, lixeira/undo, grants com TTL na UI, **seletor de nível de acesso e interruptor de elevação na UI (§5.5)**, capacidades de escrita recuperável, `calendar.create_draft_event`, adaptadores UIA (Windows) e AT-SPI (Linux), depois portal Wayland; fallback visual isolado por último.
Aceite: (a) toda tool de escrita tem pós-condição verificada e desfazer testado; (b) confirmação de `alto_impacto` só pela UI, uma chamada por vez; (c) testes de árvore acessível ausente, janela mudando, DPI/escala, multi-monitor, modal inesperado e perda de foco; (d) grant revogado deixa de valer no próximo turno, e reduzir o nível cancela chamada em voo; (e) 0 efeitos externos por especulação (SLO-10); (f) com elevação desligada, capacidade que a exige não chega à allowlist do turno; ligada, cada uso é confirmado na UI, uma chamada por vez, com `argv` auditado.

### F5 — Experimento S2S e proatividade sob contrato
Entrega: adaptador de diálogo para API speech-to-speech (Realtime/Gemini Live) ou Moshi, mantendo AEC, event log, epoch, PDP e executor **externos**; proatividade só como compromisso criado pelo usuário, com quiet hours e orçamento.
Aceite: (a) comparação contra a cascata no **mesmo corpus** de F1, reportando falso corte, atraso, auditabilidade, custo e qualidade pt-BR; (b) adotar só se melhorar sem piorar nenhum dos quatro; (c) proatividade desligada por padrão e sem nenhuma ação de efeito sem confirmação; (d) derrubar a rede no meio do experimento degrada para a cascata local sem perder o epoch.

---

## 10. Riscos

| Risco | Consequência | Controle | Fase |
|---|---|---|---|
| Falso barge-in (eco, TV, terceiro falando) | o assistente se cala sem parar | AEC antes do VAD, fones no alpha, limiar por cenário, PTT | F1 |
| Falso fim de turno em hesitação | corta o dono no meio do pensamento — a falha mais perceptível | VAD + modelo semântico + timeout conservador; otimizar a curva, não um número | F1 |
| Fala/resultado obsoleto após interrupção | responde pergunta velha ou age errado | epoch, cancelamento propagado, histórico pelo que tocou | F1 |
| Especulação com efeito | ação indevida ou invasão de privacidade | especular só leitura idempotente; SLO-10 | F2 |
| Prompt injection por tela/e-mail/MCP/voz de terceiro | exfiltração ou ação não autorizada | `trust: third_party`, sessão contaminada, PDP fora do modelo, sandbox | F2/F4 |
| Recuperação esconde a tool certa | o modelo inventa ou desiste | `search_catalog` + perguntar ao dono; segunda recuperação ao ramificar | F2 |
| Deriva de memória por consolidação | resumo errado vira a única verdade | bruto imutável, `proposed` por padrão, rollback, proveniência | F3 |
| Envenenamento de memória | poucos textos corrompem respostas (PoisonedRAG) | confiança por fonte, quarentena, nada de auto-save de conteúdo externo | F3 |
| Vazamento entre escopos / extração de memória | PII de um escopo aparece em outro | ACL antes da busca, namespaces, redação pré-embedding, cache por sessão | F3 |
| Licença de modelo | reranker CC-BY-NC bloqueia uso comercial futuro | avaliar licença como requisito de produto; alternativas Apache/MIT medidas em F3 | F3 |
| Diferença Linux/Windows de áudio e de automação | duplex quebra, automação age na janela errada | abstração de dispositivo, teste por driver, âncora semântica, foco verificado | F1/F4 |
| "Always-on" virar vigilância | perda de confiança do dono | wake/VAD local, retenção opt-in, indicador inequívoco, kill switch, nada de áudio bruto por padrão | F1 |
| Custo/calor/bateria do loop | UX piora e a máquina sofre | coalescing, orçamento por prioridade, modelos pequenos na percepção, suspensão ociosa | F1/F2 |
| Dependência de fornecedor | o assistente morre se a API morrer | providers trocáveis, modo local degradável, dados exportáveis | F5 |
| Extração de grafo errada vira memória errada | o Jarvis "lembra" de uma relação que nunca existiu | aresta nasce `proposed`, duas evidências ou extrator determinístico, precisão de aresta amostrada, veto da §8.2 regra 5 | F3 |
| Hub explodindo a travessia | recuperação estoura o orçamento e a voz atrasa | penalidade de hub, tetos de nó/aresta, orçamento em ms, `graph_truncated`, SLO-13 | F3 |
| Grafo virar dívida de latência | a memória "mais natural" fica mais lenta | zero LLM na consulta, degraus adaptativos, harness antes da F3 (F0-05) | F0/F3 |
| TOCTOU/link simbólico furando a raiz | escrita fora do nível escolhido pelo dono | descritor confinado (`openat2`/handle), identidade de arquivo, suíte de corrida obrigatória | F0/F4 |
| Elevação virando hábito | uma confirmação distraída dá root ao assistente | interruptor separado desligado por padrão, filtragem antes do catálogo, por ação, TTL curto, `argv` auditado, segredo só no prompt do SO | F4 |
| "PC inteiro" alcançando credenciais | vazamento catastrófico | lista de negação vence até no `total`; ler cofre é negado, não confirmável | F4 |
| Servidor MCP comprometido ou rug-pull | ação não autorizada com cara de ferramenta legítima | promoção manual, identidade pinada por hash, suspensão quando a lista muda, saída sempre `third_party`, allowlist estreita do Orchestrator | F2 |
| Licença não comercial entrando sem alarde | passivo jurídico num produto comercial | porta de licença no CI desde F0 (ADR-0011) | F0 |

---

## 11. Pendências para o dono

**Fechadas em 2026-10-15** (viraram texto nesta v0.1): Q2 — uso comercial **permitido**, logo licença não comercial fora desde já (ADR-0011). Q3 — escopo do v1 = **arquivos + mídia + calendário em rascunho**, mais abrir apps, crescendo por níveis (§5.6, ADR-0010). Q4 — o **orquestrador** grava o corpus pt-BR em `J.A.R.V.I.S/corpus` (estrutura na F0-08). Q5 — regra de decisão **pode fechar antes de medir**, e agora há duas (§8.1 e §8.2). Acesso — quatro níveis + elevação separada (§5.5, ADR-0009). Memória — **com grafo** (§6.7, §6.8, ADR-0008).

| # | Pendência | Por que precisa de você |
|---|---|---|
| Q1 | Linguagem/IPC (D1) — decidir pelo número medido na F0-04 | custo de reescrita depois é alto; a medição decide, você confirma |
| Q6 | **Qual modo de acesso o v1 começa** — sugestão do arquiteto: `padrao` (pastas padrão), subindo para `concedido` conforme o uso pedir | é a sua decisão por definição (P12); muda o que a F2/F4 precisa testar primeiro |
| Q7 | **Elevação ligada ou desligada no v1** — sugestão: desligada, e nenhuma capacidade do v1 a exige | ligar isso é decisão de risco, não de conveniência |
| Q8 | **Backend de calendário (D2)**: ICS local, Evolution Data Server ou API de nuvem | conta de nuvem é egress e PII; sem a sua escolha, a família fica em rascunho local |
| Q9 | Ler a §5.5 e dizer se a lista de negação (chaves SSH/GPG, chaveiro, perfis de navegador, `.env`, cofres) deve ter mais alguma pasta sua | só você sabe onde guarda segredo fora do padrão |

## ADRs

`docs/adr/0001` arquitetura C · `0002` epoch/cancelamento · `0003` capacidade e PDP · `0004` papel do Jev · `0005` memória e índice trocável (item 4 emendado pela 0008) · `0006` camadas de atuação no desktop · `0007` processos e barramento · **`0008` memória em grafo e ativação por propagação** · **`0009` níveis de acesso e elevação** · **`0010` catálogo do v1 e clientes MCP** · **`0011` reranker de licença comercial**.

Cartões de tarefa: F0 em `docs/F0-tarefas.md`, F1 em `docs/F1-tarefas.md`.
