# ADR-0004 — Jev filtra cenário e shortlist de tools; nunca autoriza

**Data:** 2026-10-15 · **Estado:** aceita (decisão do dono) · **Decide:** dono

## Contexto
Um classificador local pequeno é adequado quando as classes são fechadas, o custo de errar é baixo e a latência importa — `casa` vs `mídia`, "consulta" vs "controle de reprodução". Não é adequado para distinguir duas operações de escrita parecidas, escolher entre conta pessoal e profissional ou compor um fluxo (relatório 04, §2). Recuperar ferramentas em vez de despejar o catálogo tem evidência inicial: RAG-MCP relata −50% de tokens e seleção de 13,62% → 43,13% (arXiv 2505.03275) — um paper, não uma garantia para desktop.

## Decisão
O Jev estima `P(cenário)`, `P(intenção)` e risco, e com isso filtra o overlay de contexto e a shortlist de capacidades (BM25 ∪ embeddings → top 30 → reranker → 5–12). Ele **nunca** concede autorização. Confiança baixa, mudança de cenário ou qualquer escrita/efeito externo ampliam a recuperação e/ou escalam para confirmação. Cenário é hipótese com TTL, combinável (até dois em transição), não verdade.

## Alternativas descartadas
- **Jev decidindo a ação:** devolveria o acoplamento intenção→comando do Jarvis antigo.
- **Só recuperação semântica, sem classificador:** confunde tools vizinhas e não dá o corte barato de "isto nem precisa do S2".
- **Só o LLM grande escolhendo em todo o catálogo:** caro, lento e com mais tool errada.

## Consequências
- Precisa de corpus rotulado de 200–500 enunciados por cenário, com negativos e ambíguos (F2).
- Métricas obrigatórias: `recall@5` por família de tool, falso positivo de cenário, taxa de "não sei", p95 e tokens.
- Previsão, confiança, shortlist e desfecho são logados para recalibrar — sem treinar com conteúdo sensível.

## Como invalidar
Se em F2 o `recall@5` do roteador ficar abaixo do LLM escolhendo direto, com diferença de latência irrelevante, o Jev vira só detector de cenário e a shortlist passa a vir só da recuperação híbrida.
