# ADR-0073 — O agente monitor das redes: um subagente que encaminha ou descarta

**Data:** 2026-11-16 · **Estado:** aceita (implementada; provada com fakes de ponta a ponta e com modelo real — Claude haiku pelo `claude -p` — contra eventos falsos; o uso real, com o WhatsApp Web e a voz, é do dono) · **Decide:** dono (um subagente só para monitorar, que decide se encaminha; o Jarvis decide se fala), orquestrador (o evento triado não espera o teto de fala)
**Pedido:** dono, 2026-11-16 («ao receber alguma notificação com o monitoramento ativo ele não me fala»). Emenda a ADR-0060 (redes) e a ADR-0070 (eventos ao LLM); usa o laço da ADR-0072. Diagnóstico: [docs/estudos/monitor-ate-a-fala.md](../estudos/monitor-ate-a-fala.md).

## Contexto

Na ADR-0070, o «agente monitor» era uma rodada de modelo sem ferramentas que rotulava cada conversa
(mensagem, ligação…) e passava o evento cru ao Jarvis. Ninguém decidia se aquilo importava ao dono;
o Jarvis, com evidência de terceiros e a instrução de calar se nada merecesse a voz, calava diante
de mensagem comum (10/10 com o modelo real). A trilha ainda escondia a causa (`[fora_da_forma]`).

## Decisão

1. **Um subagente de longa duração.** `jarvis.social.agente.AgenteMonitor` nasce no primeiro evento
   da sessão e vive com ela: uma fila e uma linha próprias, um evento por vez. Cada evento é uma
   notificação estruturada (o `Notificacao.evento` do monitor + o modo do dono) e roda o **mesmo
   laço** do Jarvis e do subagente (`rodada_do_agente`, `quem="monitor"`), com o motor da conversa.
2. **Ferramentas próprias, decisão dele.** `monitor.encaminhar_ao_jarvis(resumo, tipo, urgencia,
   remetentes)` e `monitor.descartar(motivo)`; tipos, urgências e motivos são listas fechadas. O
   código só valida: a proposta inválida volta ao modelo com o veredito (até 3 rodadas). Ele vê as
   suas últimas 12 decisões — é o que deixa descartar o spam repetido sem regra no código.
3. **Falha é notificação, não silêncio.** Sem motor, motor caído ou nenhuma ferramenta chamada: o
   evento vai ao Jarvis marcado `decisao_do_monitor = sem_decisao`, e ele decide.
4. **O Jarvis recebe como evento e decide** (ADR-0070): o encaminhado entra na fila de avisos com a
   confiança de terceiros, a origem `monitor · <rede>`, o resumo do monitor (dado) e a evidência
   crua. A nota dos eventos diz que aquilo já foi triado e que o dono ligou o monitoramento para
   saber; ele fala com as palavras dele, ou deixa no card se o contexto pedir. Nenhuma frase pronta.
5. **Ocioso fala na hora; falando, na fronteira.** A origem do monitor não espera o teto de fala
   espontânea (D22, 2 min) — a triagem contra o falatório é o agente —, mas o piso livre vale:
   nunca por cima da fala do dono nem do TTS, um por vez.
6. **Trilha só com códigos.** `monitor.decisao` {`rede`, `decisao`, `tipo_do_evento`, `urgencia`,
   `motivo`, `rodadas`, `ms`}; `entrega` dos avisos de rede com `falada/jarvis_falou`,
   `silenciosa/jarvis_calou` ou `silenciosa/motor`. O resumo e os nomes nunca vão à trilha.

## Fora

- **Ler a conversa inteira** (`ler_conversa`): pediria CDP na aba da rede (ADR-0060 recusa por
  risco de detecção). O agente decide com o que a lista mostra.
- Sem conversa aberta, o evento fica só no cartão da rede (não há Jarvis para receber).

## Consequências

- `social/agente.py` reescrito (o classificador sai; `contexto_do_dono` fica); `voz/app.py`
  (`evento_de_rede` → `agente_monitor.receber`; `_encaminhado_pelo_monitor`); `agentd/
  fila_de_avisos.py` (`ORIGEM_DO_MONITOR`, `SEM_TETO`); `s2/avisos.py` (a nota do triado);
  `trilha.py`; `s2/laco.py` (`QUEM_MONITOR`).
- Prova: `tests/unit/social/test_monitor_ate_a_fala.py` (página falsa → monitor → agente → fila →
  turno → TTS paramétrico: ligação perdida vira fala, propaganda é descartada, spam repetido passa
  uma vez, a ligação em andamento espera a fronteira, o teto não segura, o calado aparece na
  trilha), `tests/unit/social/test_agente.py`, `tests/e2e/test_no_aplicativo.py`.
- Medição: `tools/avaliar_monitor.py` + `tools/corpus_monitor.toml` →
  [docs/medicoes/monitor-das-redes.md](../medicoes/monitor-das-redes.md): Claude haiku 10/10
  (monitor 8/8, Jarvis 6/6).
- Custo: uma chamada de modelo a mais por evento de rede (~2–3 s com o haiku pela CLI), fora do
  laço da voz.
