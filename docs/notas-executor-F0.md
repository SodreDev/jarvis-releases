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
