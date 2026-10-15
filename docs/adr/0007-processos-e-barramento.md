# ADR-0007 — Sete processos separados em torno de um barramento de eventos tipado

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** arquiteto

## Contexto
O caminho de áudio tem orçamento de dezenas de milissegundos (SLO-1/SLO-2); o reasoner e a memória têm picos de centenas de ms a segundos. Misturar os dois num processo faz a indexação ou o LLM engasgar o barge-in. Os relatórios 01 e 02 convergem na separação: percepção, controlador rápido, reasoner, executor, política e memória, com um event log curto e fila de prioridades.

## Decisão
Sete áreas com fronteira de processo e um barramento tipado: `audio-io`, `agentd` (percepção + S1 + dono do epoch), `s2`, `policy` (PDP), `executor`, `memoryd`, `ui`. Todo evento usa o envelope comum (`event_id`, `session_id`, `epoch`, relógio monotônico, `source`, `trust`, `priority`). Prioridade P0–P4 decide qual computação preempta qual, nunca qual comando executa. Coalescing é obrigatório na percepção.

## Alternativas descartadas
- **Monolito com threads:** mais simples no começo; impede reiniciar o reasoner sem derrubar o áudio e borra a fronteira de confiança entre PDP e modelo.
- **Microsserviços em rede:** latência e operação injustificadas num desktop.

## Consequências
- IPC local autenticado; nenhum processo confia em `trust` declarado por quem está fora.
- Cada processo é reiniciável e testável sozinho; o replay de sessão reproduz o event log (F2).
- Custo: serialização no caminho quente. Mitigação: envelope pequeno, payload grande por referência (`payload_ref`).
- Decisão de linguagem/IPC (D1) fica para F0 e se decide por medição de SLO-1, não por preferência.

## Como invalidar
Se em F0 a medição mostrar que o IPC sozinho come o orçamento de SLO-1 (≤80 ms p95), `audio-io` e `agentd` se fundem num processo — mantendo as outras cinco fronteiras.
