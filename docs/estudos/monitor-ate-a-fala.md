# Por que a notificação das redes não virava fala (diagnóstico, 2026-11-16)

**Relato do dono:** «ao receber alguma notificação com o monitoramento ativo ele não me fala».
**Decisão que saiu daqui:** [ADR-0073](../adr/0073-agente-monitor-das-redes.md). **Prova:**
`tests/unit/social/test_monitor_ate_a_fala.py` (fakes) e
[docs/medicoes/monitor-das-redes.md](../medicoes/monitor-das-redes.md) (modelo real).

## O caminho, peça por peça

| # | Peça | Onde | Morria aqui? |
|---|---|---|---|
| 1 | a extensão lê a lista de conversas (nome, trecho, rótulos dos ícones) | `extensao/social.js` | não — a trilha do dono tem `rede.estado` `conectada` com a extensão v5/v6 |
| 2 | a ponte valida o evento `social` | `navegador/protocolo.validar_evento` | não |
| 3 | `EstadoDoMonitor.receber`: a contagem subiu → `Notificacao.evento` | `social/monitor.py` | não — `notificar = true` no `redes.toml` do dono; «não avisa» é contexto, não filtro |
| 4 | `Ponte._avisar_da_rede` → `Aplicativo.evento_de_rede` | `gui/ponte.py`, `voz/app.py` | só sem conversa aberta (`sessao` morta): o evento fica no cartão da rede. Não foi o caso |
| 5 | o classificador (uma rodada de modelo, sem ferramentas) | `social/agente.py` (antigo) | não: medido com o modelo real, classificava certo |
| 6 | a fila de avisos libera no piso livre | `agentd/fila_de_avisos.py` | **às vezes**: o teto de fala espontânea (2 min, D22) segurava o evento de rede que chegasse logo depois de o Jarvis falar |
| 7 | o turno de eventos do Jarvis decide | `s2/cerebro.Cerebro.avisar` | **sim**: o modelo respondia `[silencio]` |
| 8 | a trilha registra a entrega | `trilha.py` | **escondia a causa**: `jarvis_calou` e `motor` não estavam na allowlist `CAUSAS` e viravam `[fora_da_forma]` |

## A evidência

**A trilha do dono** (`~/.local/state/jarvis/voz/diagnostico/turnos.jsonl`, só códigos): três
eventos de rede chegaram ao turno do Jarvis (`entrega` com turno `rede-…`), todos `silenciosa` com
motivo `[fora_da_forma]`. A chamada ao motor imediatamente antes de cada um (`motor.chamada`,
`origem=turno`) terminou `concluido`, com 166, 276 e 73 tokens de saída — o motor não caiu nem
estourou prazo: **o Jarvis decidiu calar** e a trilha não conseguia dizer isso.

**O mesmo turno com o modelo real** (Claude haiku pelo `claude -p`, a persona e as regras padrão,
uma conversa curta antes, nenhuma ferramenta real):

| Evento | Antes do conserto |
|---|---|
| mensagem comum sem classificação (Carlos, grupo, «oi») | calado 6/6 |
| mensagem comum classificada `mensagem/baixa` e `mensagem/media` | calado 4/4 |
| ligação perdida | falou 2/2 |
| o mesmo evento **sem** conversa antes | falou |

Ou seja: com o evento cru de terceiros e a instrução «se nenhum merece a voz agora, responda
`[silencio]`», o modelo trata mensagem de gente como ruído. Nada no turno dizia que **o dono ligou
o monitoramento para saber disso**, nem havia um agente que tivesse decidido que aquilo importava.

**Reprodução com fakes no código antigo** (`git stash` de `src/`, o mesmo cenário do teste novo): o
Jarvis calado grava `('silenciosa', '[fora_da_forma]')`; nenhuma decisão de monitor na trilha; e a
segunda ligação, logo depois de um aviso falado, não sai (`entregar_avisos` → `False`) — fica presa
pelo teto de 2 min.

## As causas

1. **Desenho:** não havia agente que decidisse encaminhar. O classificador só rotulava; quem
   recebia o evento cru era o Jarvis, que, sem saber o que o dono queria do monitoramento, calava.
   O dono já tinha pedido um subagente só para monitorar.
2. **Fila:** o teto de fala espontânea (D22) valia para o evento de rede como para qualquer aviso.
3. **Diagnóstico:** `jarvis_calou` e `motor` fora da allowlist da trilha — a causa ficava invisível.

## O conserto (ADR-0073)

- `social/agente.AgenteMonitor`: um **subagente de longa duração**, com fila e linha próprias, que
  roda o laço canônico (`rodada_do_agente`, `quem=monitor`) com as ferramentas dele —
  `monitor.encaminhar_ao_jarvis(resumo, tipo, urgencia, remetentes)` e `monitor.descartar(motivo)`.
  Lembra as últimas 12 decisões (o spam repetido aparece ali). Proposta inválida volta com o
  veredito; sem decisão, o evento vai ao Jarvis marcado `sem_decisao`.
- O encaminhado entra na fila com origem `monitor · <rede>`: não espera o teto (a triagem já foi
  feita), mas espera o piso livre — ocioso, o Jarvis fala na hora; falando, na fronteira.
- A nota dos eventos diz ao Jarvis que o que veio do monitor já foi triado e que o dono ligou o
  monitoramento para saber disso. Ele decide e fala com as palavras dele.
- Trilha: `monitor.decisao` (`decisao`, `tipo_do_evento`, `urgencia`, `motivo`, `rodadas`, `ms`) e
  `entrega` com `falada/jarvis_falou`, `silenciosa/jarvis_calou` ou `silenciosa/motor`.

**Depois do conserto, o mesmo modelo:** 10/10 no corpus com alvos fixados antes — o monitor
descartou a propaganda e o spam repetido, encaminhou ligação (perdida, em andamento, repetida),
mensagem de gente, trabalho e alerta de conta; o Jarvis falou em todos os encaminhados com alvo.

## O que só a máquina do dono prova

O DOM real do WhatsApp Web (se o trecho e o rótulo «chamada de voz perdida»/«recebendo» aparecem
na lista), o tempo de ponta a ponta com a voz de verdade e se a decisão do monitor com o histórico
real da conversa continua no alvo. Roteiro: [docs/teste-real-dono.md](../teste-real-dono.md) (c).
