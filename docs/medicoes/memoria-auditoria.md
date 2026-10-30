# Auditoria da memória do Jarvis (2026-10-30) — o que existe, o que está ligado, quanto custa e o que falta

Pedido do dono: «reranker + classificador + Jev na consulta + embeddings + grafo para ligar tudo de
forma natural e instantânea». Diagnóstico do **código real** (`src/jarvis/memoryd`, as `memoria.*`,
`jarvis.s2.memoria_do_turno`, `jarvis.politica.memoria`) contra as ADRs 0005/0008/0011/0013/0024/
0026/0029, e a latência medida ponta a ponta com dados sintéticos. Só uma ligação trivial e segura
foi feita (o aquecimento do embedding, abaixo); o resto é plano para o dono aprovar.

## 1. Tabela: existe / ligado / medido / falta

| Peça | Existe? | Ligada no caminho do app? | Medido | Falta |
|---|---|---|---|---|
| Embedding `multilingual-e5-small` (ONNX, CPU, 384 dim) | sim — `memoryd/embedding.py` | **sim**, se o modelo está no cache (está: `~/.cache/jarvis/modelos/intfloat--multilingual-e5-small`); sem ele, cai para termos em memória sem avisar | abrir + 1ª inferência 764 ms; aquecido 5 ms | ~~aquecer~~ (feito nesta auditoria); avisar na tela quando cai para o índice de termos |
| Índice vetorial LanceDB (busca exata, filtro antes do ranking) | sim — `memoryd/indice_vetorial.py` | **sim** (`memoryd/conversa.py:_indice_do_dono`) | dentro dos 15 ms do turno | reconstruir o índice a partir do livro (a outbox é apagada depois do upsert: o que entrou no modo sem embedding não volta) |
| Léxico FTS5 (`unicode61`, sem acento) | sim — `schemas/memoria.sql` | **sim** (memórias e turnos) | idem | — |
| Fusão RRF (k=60) | sim — `memoryd/fusao.py`, `recuperacao.py` | **sim** | idem | MMR (diversidade) não existe |
| Reranker cross-encoder | **não há código** — só candidatos de licença (`licenses/modelos.toml`: bge-reranker-v2-m3, Qwen3-Reranker-0.6B, mxbai-rerank-large-v2; o Jina é vetado, ADR-0011) | não | — | baixar, medir e ligar (fatia M3) |
| «Jev na consulta» (classificador filtrando candidatos) | **não**, e **excluído por desenho**: ADR-0024 e ADR-0026 regra 1 dizem que o Jev não vê memória; o Jev existe como portão de **ação** (inclusive das `memoria.*`), desligado na configuração do dono (`enderecamento = ""`) | não | — | decisão do dono (fatia M6): é mudar uma regra de privacidade, não só ligar |
| Grafo com ativação por propagação (1–2 saltos, teto de nós/arestas, orçamento 40 ms, `graph_truncated`) | sim — `memoryd/grafo.py` | **não**: só no braço C; o app usa o braço B (`parametros.toml`, decisão da F3-02); `graph_node_stats` (penalidade de hub) nunca é calculado no app | no harness: 1 salto p95 ≤ 0,27 ms; caminho completo p95 62 ms (F0-05) | consolidação que crie arestas (M5) e nova rodada da regra da F3-02 |
| Consolidação / construção do grafo em segundo plano | **parcial**: `processar_outbox` indexa e liga menção por apelido exato | parcial | — | extrair entidade e relação dos turnos, promover aresta proposta → ativa com 2 evidências (só existe no importador do Orchestrator) |
| Memória injetada em todo turno | sim — `s2/memoria_do_turno.consultar` (≤ 6 itens, ~300 tokens, só memória ativa) | **sim**, síncrona, antes do motor | p50 15,2 / p95 17,6 ms | registrar o tempo na trilha; mostrar «lembrei: …» (`ao_lembrar` nunca é ligado) |
| Parâmetros calibrados (`parametros.toml`, limiar 0,8545) | sim | **não**: `Parametros.do_arquivo()` não tem quem chame; o app usa limiar 0,0 — a abstinência («não encontrei») nunca dispara | na F3-02: com o limiar, o B se abstém **indevidamente em 50%** das consultas retidas | recalibrar antes de ligar (M4) — ligar como está piora a memória |
| `memoria.buscar_historico` com modelo de nuvem | código pronto | **bloqueada na prática**: `AlcanceDeMemoria.historico_na_nuvem` é vazio e nada o preenche (a tela de escopo da ADR-0026 não foi feita); com o Claude (nuvem), todo histórico volta `achados: []` + «não encontrei» | 15,4 / 17,1 ms (a busca roda; o filtro esconde) | **decisão do dono** (M2): deixar o histórico ir ao modelo de nuvem escolhido, por escopo |
| Prazo de 300 ms das `memoria.*` (manifesto) | declarado | **não imposto**: só decide se a chamada roda no turno ou em tarefa | — | impor com cancelamento (M7) |

## 2. Latência ponta a ponta (dados sintéticos)

`uv run --frozen python -m tools.medir_memoria --consultas 300` (resultado em
`docs/medicoes/memoria-consulta.md`): corpus C2 sintético (semente fixa, 842 fatos, 1 500 turnos de
conversa à toa, 3 612 itens indexados), LanceDB + e5 de verdade, nesta máquina.

| caminho | p50 (ms) | p95 (ms) | instantâneo? |
|---|---:|---:|---|
| 1ª consulta da sessão, modelo frio (antes) | 764 | — | **não** — era o 1º turno de toda sessão |
| 1ª inferência com o modelo aquecido ao abrir o livro (agora) | 5 | — | sim |
| memória do turno (`consultar`, todo turno) | 15,2 | 17,6 | **sim** (alvo < 150–250 ms) |
| `memoria.buscar_historico` | 15,4 | 17,1 | sim |
| memória do turno com o indexador gravando ao lado | 46,9 | 78,8 | sim, mas 4,5× pior: o indexador e a busca dividem uma trava só |

**Veredito:** o caminho quente que existe (vetor + léxico + RRF) **é instantâneo** — 6–14× abaixo
do alvo. O que **não** existe não pesa nada porque não roda: reranker, grafo no caminho da voz e
qualquer filtro por classificador. O «natural» é o que falta: sem reranker, sem grafo, sem
consolidação e com o histórico bloqueado para o modelo de nuvem, a memória acerta menos do que o
desenho prometia — não é lenta.

## 3. O que foi ligado nesta auditoria (trivial e seguro)

- **Aquecer o embedding ao abrir o livro** (`EmbedderE5.aquecer_em_segundo_plano`, chamado em
  `memoryd/conversa.py:_indice_do_dono`), com trava para abrir uma vez só mesmo com a 1ª consulta
  chegando junto (`tests/unit/memoria/test_threads_do_embedding.py`). Tira ~760 ms do 1º turno de
  cada sessão. Nada mais muda: mesma busca, mesmos resultados.
- **Não ligado de propósito:** o limiar calibrado (piora a abstinência indevida para 50%) e o
  histórico para a nuvem (é privacidade: decisão do dono).

## 4. Plano de fatias (para aprovar), em ordem de valor por risco

| # | Fatia | O que muda para o dono | Custo / risco | Prova |
|---|---|---|---|---|
| M1 | **Observar a memória**: `ms_memoria`, itens e abstinência na trilha (só números); «lembrei: …» na tela (`ao_lembrar`) | ver quando a memória ajudou ou atrasou | pequena; mexe em `trilha.py` e `voz/app.py` (combinar com a outra CLI) | teste da trilha |
| M2 | **Histórico para o modelo escolhido**: a tela de escopo da ADR-0026 (por motor: o histórico pode ir ao Claude/Groq?) | «o que eu te disse ontem» volta a funcionar com o Claude | média; **decisão de privacidade do dono** | teste de política + janela offscreen |
| M3 | **Reranker cross-encoder** depois do RRF (top-20 → 6), ONNX local, com orçamento (p95 ≤ 40 ms) e queda para o RRF se estourar | lembra o fato certo primeiro | média: baixar ~600 MB, conferir a licença no model card (ADR-0011) | `tools/harness_recuperacao.py` antes/depois em C2 (recall@6, nDCG@10, abstinência) |
| M4 | **Recalibrar e ligar o limiar** (com o reranker, a nota sobe e o limiar faz sentido) | para de injetar lembrança fraca | pequena depois de M3 | a regra da F3-02 (abstinência indevida ≤ 5%) |
| M5 | **Consolidação e grafo**: extrator determinístico de entidade/relação nos turnos, aresta proposta → ativa com 2 evidências, `graph_node_stats`; braço C com `ativar_por_no` no caminho da voz **só** se passar a regra da ADR-0008/0013 | ligar «a minha irmã» ao nome dela, «o projeto» ao repositório | grande; o grafo em si já cabe no orçamento (62 ms p95 completo) | C2b/C2c + corpus C1 do dono |
| M6 | **Jev escolhendo candidatos** (o pedido do dono): o classificador decide, entre os candidatos, quais servem ao pedido | menos lembrança fora de contexto | exige **mudar a ADR-0024/0026** (hoje o Jev não vê memória) e roda na nuvem (+~0,5 s); alternativa: só com Jev local | medir com o C2 e a trilha |
| M7 | **Trava dividida e prazo imposto**: leitura sem a trava do indexador (WAL), `timeout_ms` das `memoria.*` com cancelamento, reconstruir o índice do livro | o p95 com indexação volta dos 79 para ~18 ms | pequena-média | `tools/medir_memoria.py` (linha do indexador) |

## 5. O que não foi provado

O livro de verdade do dono (não foi lido), a latência na máquina dele com o app rodando (voz +
ASR + TTS dividindo a CPU), o reranker (não existe) e o efeito de qualquer fatia do plano.
