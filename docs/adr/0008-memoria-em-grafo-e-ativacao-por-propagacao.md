# ADR-0008 — Memória em grafo no próprio SQLite, com ativação por propagação e fusão com o índice semântico

**Data:** 2026-10-15 · **Estado:** aceita (emenda o item 4 da ADR-0005); **item 7 emendado em 2026-10-16** pela medição da §8.2 com corpus sintético (grafo fora do caminho da voz, provisório) · **Decide:** dono (pediu grafo), arquiteto (desenho)

## Contexto

O dono pediu memória **mais natural e instantânea, semântica COM GRAFO, não dependente de parâmetros fixos**. A ADR-0005 havia fechado o contrário ("sem grafo gerado por LLM no início, `entity_edge` simples e expansão de 1 salto"); esta ADR emenda esse item. O que não muda: o livro-razão SQLite continua sendo a fonte de verdade (P7) e o índice vetorial continua descartável atrás da `MemoryIndex`.

Fatos que moldam o desenho:

1. **Grafo ajuda em pergunta relacional e multi-salto.** HippoRAG monta um grafo de conhecimento com LLM e ranqueia passagens por Personalized PageRank; relata ganho de ~3 e ~20 pontos sobre RAG anterior em MuSiQue e 2WikiMultiHopQA, e ser 10–30× mais barato e 6–13× mais rápido que o IRCoT iterativo (arXiv 2405.14831, NeurIPS 2024; números do abstract, variam entre versões). Não replicamos.
2. **Grafo temporal ajuda em memória de agente.** Zep/Graphiti registra quando o fato ocorreu e quando foi ingerido, e invalida aresta contraditória com `invalid_at` em vez de apagar; relata 94,8% vs 93,4% (MemGPT) no DMR e até +18,5% de acurácia com −90% de latência no LongMemEval (arXiv 2501.13956). São números do próprio fornecedor, em benchmark que o blog deles mesmo relativiza: servem de motivação, **não** de meta. Nosso esquema já fazia isso (`valid_from/valid_to`, `supersedes_id`) desde a v0 — a convergência é um bom sinal, não uma prova.
3. **Grafo com LLM no caminho da consulta é incompatível com voz.** Nos benchmarks publicados, consulta local do LightRAG fica em 2,54–3,17 s e do GraphRAG em 3,53–4,27 s; a busca global do GraphRAG vai de 8,57 s a 162,66 s, e uma medição de referência reporta ~42,8 s e ~196 chamadas de LLM por consulta global (arXiv 2609.10239 e material correlato; não replicado por nós). O nosso orçamento é SLO-7/SLO-12: **dezenas a centenas de milissegundos**. Logo o grafo não pode custar chamada de LLM na hora da pergunta.
4. **Ativação por propagação é literatura clássica de memória associativa** (Collins & Loftus 1975; ACT-R de Anderson). Usamos a ideia, não um número de lá: energia entra pelos nós semeados e decai por salto, com penalidade de hub.

## Decisão

1. **O grafo mora no mesmo SQLite do livro-razão** (entidades, menções, arestas com validade, assertivas temporais). Nenhum banco de grafo novo, nenhum serviço extra — P11.
2. **Na hora da consulta o grafo é SQL puro e limitado:** ativação por propagação de **1 a 2 saltos**, com teto de nós/arestas visitados, penalidade de hub e **orçamento em milissegundos**. Zero chamada de LLM. Estourar o orçamento devolve resultado parcial marcado `graph_truncated`, nunca espera (P9).
3. **Construir o grafo é trabalho de segundo plano** (consolidação, §6.4): extração de entidade/relação roda fora do caminho crítico, aresta nasce `proposed` e só vira `active` com duas evidências independentes, extrator determinístico de alta confiança ou confirmação do dono.
4. **A recuperação é a fusão de três listas** — densa (`MemoryIndex`, Chroma por padrão), léxica (FTS5) e ativação de grafo — por RRF, depois reranker de **licença comercial** (ADR-0011) quando há orçamento, depois MMR. Toda evidência devolvida carrega o caminho que a justificou (vetor direto ou aresta por aresta).
5. **Nada de parâmetro mágico:** salto, decaimento, pesos de fusão e limiar de abstinência são **calibrados em corpus anotado** (calibração em 70%, números reportados nos 30% retidos), versionados em arquivo com o hash do corpus, e **adaptativos dentro de limites** — a recuperação escala por degraus (trabalho → densa → +léxica +1 salto → +2 saltos +reranker) só enquanto a resposta não se sustenta e o orçamento permite.
6. **"Instantâneo" é SLO medido, não adjetivo:** SLO-11 a SLO-13 da SPEC §7, confirmados ou corrigidos pelo harness de latência da F0 (tarefa F0-05) antes de a F3 começar.
7. **A escolha entre vetor puro, híbrido e grafo+vetor sai do experimento da SPEC §8.2, com regra de decisão fechada antes de medir.** Esta ADR é emendada com os números, a data, o hash do corpus e o commit.

   **Emenda (2026-10-16, fatia 7; `docs/medicoes/f3-02-grafo.{csv,md}`, commit `9d615ef`,
   corpus sintético `688097187be8340a`, `n` = 175 consultas, 52 retidas; Ryzen 5 5600G):** no
   caminho da voz fica o **braço B** (densa no LanceDB ∪ FTS5 → RRF, sem reranker), com o
   limiar de abstinência calibrado em `src/jarvis/memoryd/parametros.toml`. O resultado foi
   **inconclusivo pela regra**: o braço C (mais 1–2 saltos de grafo) ganhou 8,3 pontos de
   recall@20 em C2b+C2c sobre o B e baixou a abstinência indevida de 0,50 para 0,02, mas a
   abstinência correta caiu de 0,70 para 0,60 — uma negativa em dez retidas, acima dos 2 pontos
   que a regra 2 tolera —, e a regra 3 só cobre ganho de 2 a 5 pontos. Pelo combinado
   ("inconclusivo: publica o número e fica o mais simples"), o grafo fica **fora do caminho
   crítico** nesta fase, disponível em `jarvis.memoryd.recuperacao` (braço C) para o degrau
   de fundo e para a próxima medição. Os três braços cabem com folga no SLO-12 (p95 de 21 a
   34 ms **com** o embedding da pergunta), e nenhum devolveu memória vencida (gate 4) nem
   evidência sem caminho (gate 6). A regra 5 (precisão de aresta) **não foi medida**: as
   arestas do corpus vêm do gabarito do gerador.

   Duas coisas que a primeira rodada ensinou e viraram código: (a) contar como "evidência nova
   do grafo" a propagação a partir dos próprios acertos densos zerava a abstinência do C — agora
   só conta o que vem de entidade que a pergunta nomeia; (b) a ligação de menção por apelido
   exato (§6.7 b) roda na consolidação, e sem ela o passo 1b não tem de onde partir.

   **[SUPOSIÇÃO] provisória:** com o C2 real do dono os números mudam. O que a confirma ou
   derruba: repetir `tools/harness_recuperacao.py` com o C2 anotado, com mais negativas (dez
   retidas dão degraus de 10 pontos).

   **Pergunta ao dono:** o B abstém em metade das perguntas que têm resposta (0,50) — o Jarvis
   "esquece" mais do que inventa. O degrau adaptativo da §6.8 (rodar o C **só** quando o B
   abstém e a pergunta nomeia alguém ou algo conhecido) é o candidato óbvio para isso, e não
   foi medido; ligar sem medir seria escolher depois do resultado. Medir esse degrau é a
   próxima fatia de memória?

## Alternativas descartadas

- **Banco de grafo dedicado (Neo4j/Kùzu) ou Graphiti/Cognee prontos:** mais um serviço, mais um formato de verdade, e o Graphiti puxa LLM para o caminho da ingestão com API própria. Volta à mesa se a medição mostrar que a travessia em SQLite não cabe no orçamento (contexto 3 vs SLO-11).
- **PPR global no estilo HippoRAG a cada pergunta:** custo e variância incompatíveis com SLO-5/SLO-7 num corpus que cresce. A ativação limitada é a versão barata da mesma ideia; PPR fica como modo "fundo" para a UI de exploração, fora do caminho da voz.
- **Grafo só no índice vetorial (metadado de entidade sem aresta):** não resolve pergunta relacional de 2 saltos, que é exatamente a queixa de "memória não natural".
- **Extração de grafo no caminho crítico:** mata o SLO-5 e transforma erro de extração em erro de resposta imediata, sem janela de revisão.

## Consequências

- Mais fácil: pergunta relacional e temporal ("o arquivo que o fulano mandou na terça sobre o contrato"), explicação de **por que** o Jarvis lembrou de algo, e esquecimento em cascata (apagar episódio derruba menções e arestas que só ele sustentava).
- Mais caro: consolidação passa a ter extração; o esquema ganha tabelas e índices; o teste de exclusão em cascata (§6.6) passa a varrer grafo também.
- Passa a ser obrigatório testar: teto de hub, orçamento estourado, aresta de episódio apagado, aresta vencida não respondida como atual, e precisão de extração amostrada (100 arestas).
- O caminho da voz nunca espera o grafo: se a ativação não cabe no orçamento, a resposta sai com a evidência densa que já havia.

## Como invalidar esta decisão

O experimento da SPEC §8.2. Se o braço grafo+vetor ganhar menos de 2 pontos de `recall@20` nos subconjuntos relacional e temporal, o grafo sai do caminho crítico e fica só na consolidação e na UI. Se a travessia de 2 saltos não couber em SLO-11 no corpus real, cai para 1 salto ou vira tier assíncrono.
