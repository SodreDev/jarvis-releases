# F0 — Cartões de tarefa para o executor

**Data:** 2026-10-15 · **Autor:** arquiteto (Opus 5) · **Base:** SPEC-v0.1 §9 (F0), ADR-0008/0009/0010/0011
**Como usar:** cada cartão é delegável sozinho. O executor entrega **esqueleto, teste e número** — nenhuma capacidade real, nenhum código de produto de voz. Nada aqui depende de decisão pendente do dono, exceto onde está escrito.

**Regras que valem para todos os cartões:**
- Sem tool genérica, sem shell irrestrito, sem `run_command` (SPEC §4). Revisão recusa.
- Tudo roda em Linux e Windows no CI; o que não roda nos dois não fecha a tarefa (P11).
- Nenhum número inventado: medição vem com hardware, `n`, 3 execuções, mediana e p95, e vai para arquivo no repositório.
- Toda tarefa termina com `cli_ping` (resumo + estado `pronto|precisa_decisao|falhou`).
- Ordem sugerida: F0-01 → (F0-02, F0-09 em paralelo) → F0-03 → (F0-04, F0-05, F0-06, F0-07 em paralelo) → F0-08 → F0-10.

---

## F0-01 — Repositório, licença e CI nos dois sistemas

**Objetivo:** base onde todo o resto entra sem discussão de formato.
**Entrega:** estrutura de workspace com os sete processos como pacotes vazios; `LICENSE` compatível com uso comercial (ADR-0011); formatador e linter obrigatórios; CI que roda em `ubuntu-latest` e `windows-latest`; `CONTRIBUTING` curto com as proibições da §4.
**Aceite:** (a) CI verde nos dois SOs em um commit vazio; (b) linter recusa um arquivo mal formatado proposital; (c) `README` descreve como rodar tudo em uma linha por SO.
**Fora do escopo:** escolher a linguagem definitiva dos processos de áudio — isso é F0-04.
**Depende de:** nada.

## F0-02 — Barramento de eventos com tipos fechados e log persistido

**Objetivo:** o contrato da §3 existir em código e ser impossível de burlar por descuido.
**Entrega:** envelope da §3.1 e os 11 tipos da §3.2 como tipos fechados com validação de schema na borda; fila com prioridades P0–P4 e coalescing; log de eventos append-only em SQLite com **encadeamento por hash** (cada registro carrega o sha256 do anterior); `trust` atribuído por quem recebe do mundo, nunca pelo emissor.
**Aceite:** (a) evento com tipo desconhecido é recusado, não ignorado; (b) as **seis** regras de epoch da §3.3 têm um teste cada, incluindo descarte de evento com `epoch` antigo e exceção do `ToolResult` de leitura; (c) P0 preempta P1–P4 em teste com fila cheia; (d) 10 parciais em 200 ms geram 1 revisão, não 10; (e) adulterar um registro do log quebra a verificação da cadeia; (f) emissor remoto que declara `trust: system` é rebaixado.
**Fora do escopo:** áudio real, ASR, LLM.
**Depende de:** F0-01.

## F0-03 — Os sete processos como esqueleto e o evento que atravessa tudo

**Objetivo:** provar a fronteira de processo, não a lógica.
**Entrega:** `audio-io`, `agentd`, `s2`, `policy`, `executor`, `memoryd`, `ui` como processos separados que só se falam pelo barramento; cada um reiniciável sozinho; `s2`, `policy` e `executor` com stub determinístico (sem LLM).
**Aceite:** (a) um evento sintético faz `audio-io → agentd → s2 → policy → executor` e volta, com `epoch` e `session_id` preservados ponta a ponta; (b) matar e reabrir qualquer processo no meio não perde o log nem duplica efeito; (c) `s2` não consegue publicar fala de epoch morto (teste); (d) `executor` não tem caminho de código para shell.
**Fora do escopo:** desempenho — é F0-04.
**Depende de:** F0-02.

## F0-04 — Harness de latência de captura e a decisão D1 (linguagem/IPC)

**Objetivo:** fechar D1 por número, não por preferência (SPEC §2).
**Entrega:** dois esqueletos equivalentes do caminho `captura → AEC/VAD barato → evento` — um em Rust, um em Python+ONNX — medidos na máquina do dono; medição de **piso de ruído** (loopback do dispositivo, sem o nosso código) para separar latência do hardware da nossa; relatório em CSV + tabela markdown no repositório.
**Aceite:** (a) p50/p95/p99 e jitter de SLO-1 publicados para os dois, com `n` ≥ 10 000 frames de 20 ms, 3 execuções, hardware descrito; (b) pausas de alocação/GC medidas à parte (a cauda é o que decide); (c) os dois rodam em Linux e Windows; (d) o número vai para ADR (cartão F0-10).
**Fora do escopo:** ASR, detector semântico de turno, TTS.
**Depende de:** F0-03.
**Decisão que habilita:** Q1/D1 do dono.

## F0-05 — Harness de latência da memória em grafo (confirma SLO-11 a SLO-13)

**Objetivo:** descobrir **antes da F3** se a ativação por propagação cabe no orçamento de voz (ADR-0008).
**Entrega:** esquema SQLite das §6.2 e §6.7 criado por migração, com os índices listados; gerador de grafo sintético dimensionado pelo corpus real do dono (`n` vindo do cartão F0-08, mais escalas de 10× e 100×); implementação da ativação por propagação **em SQL puro** com os tetos da §6.8 (saltos, nós, arestas, orçamento em ms, penalidade de hub); medidor da fusão das três listas (densa simulada, léxica FTS5, grafo) com RRF.
**Aceite:** (a) p50/p95 de 1 salto e de 2 saltos publicados nas três escalas; (b) orçamento estourado devolve resultado parcial com `graph_truncated: true` e **nunca** espera; (c) hub sintético com grau 10 000 não explode a travessia (teto comprovado); (d) comparação entre travessia recursiva em SQL e travessia em memória, com o número; (e) relatório diz explicitamente se SLO-11/SLO-12 são alcançáveis, e com qual limite de saltos.
**Fora do escopo:** qualidade de recuperação (`recall`, nDCG) — isso é F3/§8.2; extração de entidade por LLM.
**Depende de:** F0-01 (pode correr em paralelo a F0-04).

## F0-06 — Esqueleto de política: raízes, canonicalização e suíte de TOCTOU

**Objetivo:** provar que o modelo de acesso da ADR-0009 resiste a corrida e a link simbólico, antes de existir qualquer tool de escrita.
**Entrega:** resolução dos quatro modos (`jarvis`, `padrao`, `concedido`, `total`) em `root_set` canônico com permissão por raiz; lista de negação que vence até no `total`; canonicalização por SO; abertura de raiz uma vez e operação **relativa ao descritor** (`openat2` com `RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS` no Linux; handle + `GetFinalPathNameByHandle` no Windows), com conferência de identidade do arquivo; auditoria encadeada por hash, escrita **antes** do efeito; `policy_epoch` com invalidação de grant.
**Aceite:** suíte que passa nos dois SOs cobrindo (a) troca de link simbólico em corrida durante a operação; (b) hardlink para fora da raiz; (c) travessia por `..` e por unicode equivalente; (d) ponto de montagem trocado; (e) raiz apagada no meio da operação; (f) Windows: ADS (`a.txt:oculto`), nome 8.3, `CON`/`NUL`/`COM1`, UNC e `\\?\`, `C:foo`, ponto/espaço final, case-folding; (g) nível reduzido cancela chamada em voo; nível ampliado só vale após confirmação; (h) **nenhuma capacidade no catálogo muda nível ou elevação** (teste que varre o catálogo); (i) com elevação desligada, capacidade `requires_elevation: true` não aparece na allowlist do turno.
**Fora do escopo:** capacidades reais de arquivo (F2/F4); sandbox do SO (bwrap/AppContainer) — fica para fase posterior como camada extra.
**Depende de:** F0-02.

## F0-07 — Ferramental de manifesto de capacidade

**Objetivo:** o manifesto da §4 ser verificado por máquina, não por boa vontade.
**Entrega:** schema do YAML (incluindo `access_level_min`, `roots`, `requires_elevation`); validador; geração de stub tipado a partir do manifesto; lint de catálogo.
**Aceite:** (a) manifesto sem `postcondition`, `risk_class`, `tests` ou `access_level_min` é recusado pelo CI; (b) lint recusa id de canivete suíço (`*.run_command`, `*.do_anything`, `*.exec`, shell); (c) manifesto de exemplo (`files.move_to_trash` da §4) valida e gera stub que compila; (d) lint recusa promoção de tool de MCP sem `risk_class` nosso (ADR-0010).
**Fora do escopo:** implementar as capacidades.
**Depende de:** F0-01.

## F0-08 — Estrutura do corpus e exportador do Orchestrator (C1)

**Objetivo:** dar lugar e forma ao corpus pt-BR que o orquestrador vai gravar, e medir o `n` real.
**Entrega:** pasta `J.A.R.V.I.S/corpus/` com `turnos/` (áudio de pausa, F1), `consultas/` (C2 anotado, F3), `cenarios/` (F2), `README` de anotação, modelo de termo de consentimento, e manifesto de hashes; exportador das memórias e decisões do Orchestrator para o esquema da §6.2 (C1), com relatório de contagem.
**Aceite:** (a) exportador roda e publica `n` de episódios, assertivas e entidades, sem copiar segredo (redação verificada por teste); (b) manifesto de hashes detecta arquivo alterado; (c) estrutura documentada em uma página; (d) `n` de C1 entregue ao cartão F0-05 para dimensionar o grafo.
**Fora do escopo:** gravar o corpus (é do orquestrador); anotar C2 (F3).
**Depende de:** F0-02.

## F0-09 — Porta de licença no CI

**Objetivo:** uso comercial permitido significa zero dependência não comercial desde o primeiro commit (ADR-0011).
**Entrega:** script que inventaria dependências **e modelos** (embedding, reranker, VAD, ASR, TTS) com licença e origem, e falha em NC/research-only; verificação dos model cards oficiais de `bge-reranker-v2-m3`, `Qwen3-Reranker-0.6B`, `mxbai-rerank-large-v2`, `multilingual-e5-base`, `bge-m3`, `Qwen3-Embedding-0.6B`.
**Aceite:** (a) script falha num NC injetado de propósito; (b) tabela licença×modelo×fonte comitada, com data de acesso; (c) roda no CI dos dois SOs.
**Fora do escopo:** escolher o reranker — é medição de F3.
**Depende de:** F0-01.

## F0-10 — ADRs com os números de F0

**Objetivo:** decisão medida vira decisão registrada.
**Entrega:** ADR de D1 (linguagem/IPC) com a tabela de F0-04; emenda da ADR-0008 com os números de F0-05 (saltos viáveis e limites reais); emenda da ADR-0011 se algum model card divergir do esperado.
**Aceite:** (a) cada ADR traz número, hardware, `n`, data e commit; (b) nenhuma afirmação sem fonte ou sem marca **[SUPOSIÇÃO]**; (c) SPEC §7 atualizada se SLO-11/SLO-12 tiverem de mudar.
**Depende de:** F0-04, F0-05, F0-09.

---

## Fechamento da F0

F0 só fecha com: CI verde nos dois SOs; evento atravessando os sete processos com epoch preservado; D1 decidido por número em ADR; SLO-11/SLO-12 confirmados ou corrigidos pelo harness; suíte de TOCTOU passando; porta de licença verde; `n` de C1 publicado.

**O que F0 não decide:** qual índice (Chroma vs LanceDB, §8.1), se o grafo entra no caminho crítico (§8.2), e o backend de calendário (D2). Esses são F3/F4, com corpus na mão.
