# ADR-0005 — SQLite como livro-razão, índice de recuperação trocável (Chroma padrão, LanceDB medido)

**Data:** 2026-10-15 · **Estado:** aceita; **item 4 emendado pela ADR-0008** (grafo entra); **itens 2–3 emendados em 2026-10-16 pela medição da §8.1** (fatia 7, corpus sintético: LanceDB, por veto) · **Decide:** dono

## Contexto
A pesquisa (`pesquisa/03-memoria.md`, 2026-10-15) recomenda SQLite+FTS5 como livro-razão e **LanceDB** como índice embutido, por ter FTS/BM25 e fusão RRF na própria API e não exigir serviço separado em Windows/Linux. Posiciona ChromaDB como ótimo para o stack já conhecido, mas lembra que BM25/fusão teriam de ser montados por fora.

O dono decidiu **ChromaDB + reranker por padrão**, atrás de uma interface trocável, porque é exatamente o que já roda em produção no Orchestrator — com reranker cross-encoder e chunking — e o custo de operar é conhecido. Essa é uma decisão de custo de operação, não uma refutação da pesquisa.

## Decisão
1. **SQLite cifrado é a fonte de verdade**: episódios imutáveis, assertivas com validade temporal, entidades, procedimentos e outbox de indexação. Vetor é índice descartável, reconstituível por `content_hash` + `embedding_version`.
2. A recuperação fica atrás da interface `MemoryIndex` (`upsert`/`delete`/`search`/`stats`), com duas implementações desde F1: `ChromaIndex` (padrão) e `LanceIndex`.
3. A escolha definitiva sai da **medição no corpus real** (SPEC §8.1), com regra de decisão fechada **antes** de medir: empate técnico (≤2 pontos de `recall@20` e ≤30% de p95) mantém Chroma; LanceDB só entra se ganhar >5 pontos de `recall@20` ou cortar o p95 em >2×; zona cinzenta vai para o dono com a tabela.
4. ~~Sem grafo gerado por LLM no início. `entity_edge` simples e expansão de 1 salto; Graphiti/Cognee só se as avaliações mostrarem falha repetida de multi-hop/temporal.~~
   **Emendado em 2026-10-15 pela [ADR-0008](0008-memoria-em-grafo-e-ativacao-por-propagacao.md):** o dono pediu memória semântica **com grafo**. O grafo entra no mesmo SQLite, com ativação por propagação de 1–2 saltos em SQL puro (zero LLM na consulta) e extração em segundo plano. O resto desta ADR continua valendo.

5. **Emenda (2026-10-16, fatia 7; medição da §8.1 em `docs/medicoes/f3-01-indice.{csv,md}`,
   commit `fd6e40e`):** o índice do produto é o **LanceDB** (`jarvis.memoryd.indice_vetorial.
   IndiceLance`), pela **regra 1 (veto)**: depois de apagar uma memória, o ChromaDB 1.5.9
   continua com os bytes do vetor no disco (no `data_level0.bin` do HNSW e no `chroma.sqlite3`)
   mesmo depois do `chroma vacuum` documentado e de reabrir o cliente — a exclusão em cascata
   do gate 2 não fica verificável pela API pública. O LanceDB 0.40.0 também deixa o vetor depois
   do `delete` e, numa tabela de um fragmento só, depois do `optimize`; reescrever a tabela e
   limpar as versões (`expurgar`, API pública) tira — cerca de 20 ms com 3184 unidades. Fora o
   veto, os dois **empatam em qualidade** (mesmo recall@20 nas consultas retidas, 99% do top-20
   em comum) e o **Chroma é mais rápido e mais leve** na busca e na RAM; os números estão no
   relatório, sem arredondar a favor de ninguém. Embedding dos dois: `intfloat/multilingual-
   e5-small` local (o mesmo do Orchestrator; a §8.1 citava o e5-base como baseline, que não foi
   medido). Hardware: Ryzen 5 5600G, 31 GiB; `n` = 175 consultas, 3184 unidades, 3 execuções.

   **[SUPOSIÇÃO] provisória:** o corpus é **sintético** (`tools/corpus_c2.py`), não o C1/C2 do
   dono; o veto não depende do corpus, o empate de qualidade sim. O que a confirma ou derruba:
   repetir `tools/harness_indice.py` com o C2 anotado pelo dono.

   **Pergunta ao dono:** o veto contraria a preferência original (Chroma, que já opera no
   Orchestrator). Se o dono preferir Chroma mesmo assim, há dois caminhos, e nenhum foi
   adotado: aceitar que "esquecer" deixe o vetor no disco até reconstruir o índice, ou um
   contorno que apaga a pasta órfã do segmento — fora da API pública, frágil a cada versão.
   Enquanto não responde, fica o LanceDB (a troca é reindexar, item 1).

## Alternativas descartadas
- **LanceDB direto, como a pesquisa sugere:** venceria no papel, mas ninguém mediu no corpus do dono; trocar por recomendação em vez de número contraria a regra de "fatos, não propaganda".
- **Chroma como fonte de verdade:** nega P7 (episódio imutável, auditável, apagável em cascata).
- **sqlite-vec minimalista:** fallback aceitável; exige montar fusão, filtros e migração à mão agora.

## Consequências
- O ledger absorve o custo de troca: migrar de índice é reindexar, nunca perder dado.
- A interface precisa suportar filtro por metadado **antes** do ranking (ACL, status, tempo), senão o filtro vira pós-filtro e o `recall@k` mente.
- Licença entra como requisito: `jina-reranker-v2-base-multilingual` é CC-BY-NC-4.0 e fica fora se houver uso comercial (pendência Q2).
- Emendada em 2026-10-16 (item 5) com a medição sintética; a do C2 real ainda deve emendá-la.

## Como invalidar
A medição de F3. Qualquer troca posterior exige novo corpus e nova tabela, não impressão de uso.
