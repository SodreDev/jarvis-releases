# ADR-0002 — Epoch como unidade de validade e cancelamento por barge-in

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** arquiteto (decorre de ADR-0001)

## Contexto
A falha mais visível de assistentes de voz é responder à pergunta antiga depois de ser interrompido, ou tratar como ouvido um áudio que ficou na fila. A documentação da API Realtime descreve exatamente esse problema de truncamento: em WebSocket, o cliente precisa parar o playback e truncar o que não tocou (relatório 01, S3). Sem um identificador de validade, cada componente inventa a própria regra.

## Decisão
Todo evento carrega `epoch` (u64 monotônico por sessão). `speech_started` local incrementa o epoch e emite `Cancel(epoch_anterior)` **antes** de qualquer transcrição. Resultado de epoch morto não entra no histórico, não vira memória e não executa ação. O histórico registra apenas `played_ms` efetivamente reproduzido.

## Alternativas descartadas
- **Cancelar por timeout ou por "nova mensagem":** chega tarde demais para o SLO-2 (≤150 ms p95).
- **Deixar cada processo decidir se descarta:** a regra vira implícita e intestável.

## Consequências
- `audio-io` precisa reportar progresso real de playback; TTS precisa ser chunked e cancelável.
- Tool de leitura pode sobreviver ao cancelamento, mas só entra se o S2 reavaliar; tool de efeito nunca é especulativa e exige `idempotency_key`.
- Nasce uma suíte de teste obrigatória: interromper em 20 pontos de uma resposta, com zero vazamento (F1).

## Como invalidar
Não se invalida; só muda de implementação. Se um adaptador S2S gerenciar o cancelamento internamente, o epoch continua do lado de cá como verdade do histórico e da auditoria.
