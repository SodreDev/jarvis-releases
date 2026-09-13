# Plano 01 — Arquitetura Modular

## Estado Atual

- `main.py` tem ~10.380 linhas: GUI tkinter + webview, router, regex de comandos, classificador, streaming LLM, state machine de pending flows.
- Subdiretórios bem definidos existem: [comandos/](../../comandos/), [core/](../../core/), [classifiers/](../../classifiers/), [security/](../../security/), [entity/](../../entity/), [ui/](../../ui/), [gesture_interface/](../../gesture_interface/).
- Mas vários domínios moram dentro do `main.py`: detecção regex Spotify/sistema, pending flows, wake-word loop, scrub de disclaimer, classificador adapter.
- Tools registradas em [comandos/tool_registry.py](../../comandos/tool_registry.py) — bom ponto de extensibilidade.

## Problema

- Mudar uma linha exige carregar mental-model de 10k+ linhas.
- Risco de regressão a cada commit.
- Difícil testar unidades isoladas.
- Quando um conector novo for plugado, ninguém sabe onde encaixar.

## Plano (incremental, sem big-bang)

### Fase A — Esqueleto de domínios (sem mover código)

Criar diretórios vazios com `__init__.py` e um `README.md` declarando responsabilidade:

```
jarvis/
├── core/           (já existe — orquestrador, event bus, presence)
├── connectors/     (novo — Discord, WA, IG, Telegram, Gmail, etc.)
├── browser/        (novo — Playwright pool, perfis isolados)
├── messaging/      (novo — abstração acima de connectors p/ msg unif.)
├── memory/         (novo — fatos, notas, embeddings opt-in)
├── tools/          (renomear comandos/ futuramente — não agora)
├── dashboard/      (novo — painel web "Stark")
├── credentials/    (já existe — virar cofre)
├── monitor/        (novo — health, métricas, logs)
├── filesystem/     (novo — abstração para abrir/listar/baixar)
├── plugins/        (novo — third-party plugins format)
├── mcp/            (novo — MCP server/client adapters)
└── api/            (novo — FastAPI para dashboard + tools remotas)
```

### Fase B — Extração de regex de comandos do `main.py`

- Mover `_SP_*`, `_SYS_*`, `_MSG_*` regex para `core/intent_patterns.py`.
- Funções `_detectar_comando_*` viram `core/intent_router.py` com testes unitários.
- `main.py` importa e delega.

### Fase C — Extração das pending state machines

- `_pending_*` viram `core/pending_state.py` (classe com métodos `start/resolve/clear`).
- Cada fluxo (envio, pesquisa, reply, confirm) = subclasse com sua transição.

### Fase D — LLM client unificado

- 4 métodos hoje: `_lm_chat`, `_lm_chat_stream`, `_groq_chat`, `_groq_chat_stream`.
- Consolidar em `core/llm_client.py` com `chat(messages, stream=bool, provider=auto)` — uma interface, scrub aplicado em um único ponto.

### Fase E — `main.py` vira só GUI + bootstrap

- Após A-D, `main.py` deve ter < 2000 linhas, focado em GUI/eventos/bootstrap.
- Toda lógica de negócio fora.

## Decisões pendentes

1. **Renomear `comandos/` → `tools/`?** Prós: alinha com vocabulário moderno. Contras: rompe imports, scripts externos. Recomendação: **adiar** até depois das fases A-D.
2. **`jarvis/` como pacote raiz vs. flat?** Hoje é flat (módulos em raiz). Recomendação: criar `jarvis/` como pacote e migrar gradualmente — `main.py` continua na raiz mas só importa de `jarvis.*`.
3. **Teste automatizado**: pytest? Recomendação: sim, começar em fase B com testes dos detectores de intenção (regex é fácil de cobrir).

## Riscos

- Refator pode quebrar imports de `vscode_extension/` e `gesture_interface/` que importam `main` direto.
- Build PyInstaller (`JARVIS.spec`) pode precisar de ajustes a cada fase.

## Referências de código

- [main.py](../../main.py) — 10380 linhas, orquestrador atual
- [comandos/tool_registry.py](../../comandos/tool_registry.py) — registro de tools (manter como ponto de entrada)
- [core/](../../core/) — onde mora event_bus, presence, vad — bom ponto para crescer

## Histórico

- 2026-05-25 — Plano criado, sem execução.
