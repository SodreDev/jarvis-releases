# Plano 07 — Memória & Persistência

> Nota do usuário: "para a memória, não precisa de nada dessas bases avançadas". Mantemos simples; bases mais robustas só atrás de toggle e/ou Docker opcional.

## Estado Atual

- `comandos/memoria_ctrl.py` — fatos chave:valor + notas (JSON).
- `comandos/memoria_jarvis.py` — histórico de turnos (JSONL), agora **8 turnos** persistidos.
- `historico.jsonl` — log de comandos.
- `notif_history.jsonl` — log de notificações.
- `vision_cache.jsonl` — cache de análises de tela.
- `contatos.json` — contatos.

## Problema

- JSON puro escala mal acima de ~10k entradas (carregamento inteiro a cada query).
- Sem índice de busca semântica → "lembra daquilo que falei sobre X" só funciona se a chave bate exata.
- Logs JSONL crescem sem rotação.

## Plano

### Camadas (todas opt-in via toggle, default em arquivo)

1. **Tier 0 — Arquivos JSON/JSONL (atual)** — default, sempre ON. Funciona para usuário comum.
2. **Tier 1 — SQLite local** (toggle `MEMORY_SQLITE=False`) — `data/jarvis.db`. Schemas: facts, notes, turns, contacts, notif_history.
3. **Tier 2 — Embeddings opt-in** (toggle `MEMORY_EMBEDDINGS=False`) — `sentence-transformers` local (CPU) ou `ollama`/Groq embed API. Armazena em SQLite + FAISS index local. Sem ChromaDB/Postgres por enquanto.
4. **Tier 3 — Docker compose** (toggle `MEMORY_DOCKER=False`, recipe em `docker/memory.yml`) — Postgres + ChromaDB. Apenas usuários avançados.

### Migração

- `migrate.py` lê JSON → popula SQLite mantendo JSON intocado.
- Engine de memória detecta tier ativo e usa o mais alto disponível.

### Rotação de logs

- `historico.jsonl`, `notif_history.jsonl`, `vision_cache.jsonl` rotacionam:
  - Tamanho: > 10 MB → roda.
  - Idade: > 30 dias → arquiva em `data/archive/YYYY-MM.jsonl.gz`.
- Implementação: `core/log_rotation.py` rodando em thread baixa prioridade.

### Memória persistente de personalidade

- `memoria_ctrl.py` já guarda "fatos" (preferências do usuário). Manter.
- Cap de 8 turnos do `memoria_jarvis.py` — manter (já corrigido).
- Adicionar campo `tags` por fato/nota para filtragem futura.

## Decisões pendentes

1. **SQLite schema**: criar `data/schema.sql` versionado com migrations (`alembic-light`).
2. **Embeddings model**: `paraphrase-multilingual-MiniLM-L12-v2` (rápido, multilíngue, ~120MB). Toggle.
3. **Quando o Docker é justificável?** Recomendação: nunca para usuário casual. Documentar como "advanced".

## Riscos

- SQLite + threading: usar `check_same_thread=False` ou conexão por thread.
- Embeddings carregam ~500MB em RAM. Toggle obrigatório.

## Referências de código

- [comandos/memoria_ctrl.py](../../comandos/memoria_ctrl.py)
- [comandos/memoria_jarvis.py](../../comandos/memoria_jarvis.py)
- [data/](../../data/)

## Histórico

- 2026-05-25 — Plano criado.
