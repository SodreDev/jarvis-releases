# ADR-0011 — Reranker tem de ser de licença comercial; Jina CC-BY-NC está fora desde já

**Data:** 2026-10-15 · **Estado:** aceita, pendente de verificação de model card na F0 · **Decide:** dono (uso comercial permitido)

## Contexto

Pendência Q2 fechada: o Jarvis **pode ser comercial**, logo licença não comercial está fora desde o primeiro commit — não é dívida para depois. O `jina-reranker-v2-base-multilingual`, usado como referência na pesquisa, é CC-BY-NC-4.0 e portanto incompatível. O Orchestrator hoje opera Chroma + reranker cross-encoder; o que estiver lá e for NC precisa ser trocado antes de qualquer reuso de pipeline.

Busca de 2026-10-15 em agregadores aponta `BAAI/bge-reranker-v2-m3` e `Qwen/Qwen3-Reranker-0.6B` como Apache-2.0, e `mxbai-rerank-large-v2` também como Apache-2.0, mas as fontes são diretórios de terceiros e uma delas divergiu (MIT para o bge). **Model card oficial e arquivo de licença do repositório são a única fonte válida** — verificar é tarefa da F0-09.

## Decisão

1. Licença é **requisito de produto**, não detalhe de ML: modelo, peso ou dependência com cláusula não comercial, "research only" ou proibição de uso comercial **não entra no repositório**.
2. Candidatos a medir em F3, nesta ordem de preferência inicial: `bge-reranker-v2-m3`, `Qwen3-Reranker-0.6B`, `mxbai-rerank-large-v2`. Embeddings na mesma régua: `intfloat/multilingual-e5-base` (baseline CPU), `BAAI/bge-m3`, `Qwen3-Embedding-0.6B`.
3. **CI tem porta de licença** (F0-09): script que lista cada modelo e dependência com licença e **falha** em qualquer NC/research-only. Sem o script verde, F0 não fecha.
4. Reranker continua **feature flag** atrás da `MemoryIndex`/fusão: se nenhum candidato comercial atingir SLO-8, a recuperação roda sem reranker e a decisão vai medida ao dono — nunca se usa um modelo NC "só para testar" no caminho do produto.

## Alternativas descartadas

- **Usar Jina e trocar quando houver cliente:** o custo de troca cresce com o corpus calibrado e os números publicados em ADR; e mede-se o que não se vai usar.
- **Reranker de API paga:** some com o modo local degradável (P9) e manda texto do dono para fora em todo turno.
- **Sem reranker nunca:** a pesquisa indica ganho real em recuperação; medir com e sem é mais barato que supor.

## Consequências

- Mais fácil: qualquer conversa comercial futura não encontra passivo de licença.
- Mais caro: o reranker que o dono já opera talvez tenha de ser trocado, e a medição de F3 ganha mais um braço.
- Passa a ser obrigatório testar: a porta de licença do CI e o caminho sem reranker (degradação).

## Como invalidar esta decisão

O dono declarar que o Jarvis nunca será comercial — e mesmo então a porta de licença fica, porque custa quase nada.
