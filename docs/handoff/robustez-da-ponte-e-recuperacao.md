# Handoff — a ponte que não prende e a recuperação de falha (2026-10-30)

Pedido do dono depois de testar os pacotes de 30/10: (1) «o app trava» e «o Jarvis não sabe mais
usar a extensão»; (2) «não consegui executar o passo» e a tarefa para. ADR-0027 e ADR-0038
emendadas nesta data; COMO-TESTAR §0.49 e §0.50.

## O que a trilha do dono mostrou (só códigos, 30/10, 10 turnos)

| Achado | Medida | Causa |
|---|---|---|
| 5 turnos em `fim: erro`, `erro: ""`, 0 ferramenta | 38–1226 ms cada, 10:55–10:58 | o preset do cérebro era um de Groq e a sessão recusava (`MotorRecusado`: «é de nuvem e está desligado») — a janela tinha ligado o Groq só para ela; ver a emenda da ADR-0056 |
| a trilha não dizia o motivo nem o motor | `erro` só pegava exceção; `motor` sempre `[fora_da_forma]` | `turno.fim` ignorava `resposta.detalhe`; o nome «Groq · …» não cabe na forma `CODIGO` |
| 3 tarefas do navegador em `entrega: falha` | 4–7 s depois de `browser.navigate`/`browser.read` **ok** | a rodada seguinte do motor caiu e a tarefa morreu na primeira (`ErroDeTarefa`) |
| cérebro lento | 1º token p50 8,4 s / p90 14,9 s (29/10: 2,6 / 5,1 s) | o preset ativo «claude» é sonnet com esforço médio (antes, haiku) |
| ponte pendurada | 0 `ferramenta.inicio` sem fim, 0 `cerebro_preso` | não aconteceu nesse dia — mas nada impedia: 30 s de espera, sem cancelar |

O processo do host do Brave do dono foi relançado às 11:01:31 (depois das falhas); o socket dele
está vivo. Não toquei no navegador, no app nem no host do dono.

## Onde mora cada peça

- `src/jarvis/navegador/protocolo.py`: `VERSAO_DA_PONTE`, `ponte.versao`, `host.versao`,
  `prazo_do_metodo` (8 s curtos / 25 s longos).
- `src/jarvis/navegador/host.py`: `host.versao` respondido no host (`versao_do_host`).
- `src/jarvis/navegador/cliente.py`: `TransporteUnix._bater` espera em fatias de 100 ms com prazo
  e `cancelado`; `ChamadaCancelada`, `SemResposta`, `ExtensaoDesatualizada`, `VersaoDaPonte`,
  `ClienteDoNavegador.versao()`, `sob(concessao, cancelado)`.
- `src/jarvis/navegador/estado.py`: `sondar(conferir_versao=True)`, `desatualizada`,
  `linha_da_versao`; `src/jarvis/navegador/ferramentas.py` passa o `cancelado` ao cliente e traduz
  a extensão de antes; `src/jarvis/executor/ferramentas.py` devolve `ChamadaCancelada` como
  `cancelado`.
- `extensao/background.js`: `VERSAO_DA_PONTE = 2`, `versaoDaPonte()`; manifesto 0.2.0.
- `src/jarvis/navegador/quadro.py` e `src/jarvis/s2/motor_claude_cli.py`: `replace` no UTF-8; a
  escrita do `stdin` que falha vira `Fim(ERRO)` com motivo, e o `TimeoutExpired` não sobe mais.
- `src/jarvis/voz/app.py`: confere a extensão uma vez por sessão (linha à parte); `turno.inicio`
  grava o código do motor (`MotorDosPresets.codigo` = `provedor/modelo`); `turno.fim` grava o
  motivo do erro do motor; liga `Cerebro.ao_raciocinio` à tela (`↻ …`).
- `src/jarvis/s2/recuperacao.py`: `Recuperacao` (orçamento, histórico, era de cada falha,
  `repetida`, `nota`, `linha_na_tela`), `codigo_da_falha`, `vazio`, `nota_do_turno`.
- `src/jarvis/s2/tarefa_do_pedido.py`: `MotorDoObjetivo` usa a recuperação, `MotorFalhou` (rodada
  do motor que cai, tentada de novo), `_desistir`, `explicacao_para_ouvir`, `FRASES_SEM_SAIDA`.
- `src/jarvis/s2/cerebro.py`: a rodada do turno depois de um passo que falhou leva a nota;
  `ao_raciocinio` vai ao `MotorDoObjetivo`.
- `tools/diagnostico_navegador.py`: o que o dono roda e cola.

## Armadilhas

1. **«Repetida» é por era:** a mesma ação só é repetição se nada deu certo depois da falha — ler de
   novo depois de rolar é outro caminho (o primeiro desenho recusava e a tarefa desistia).
2. `runtime_checkable` só confere o nome do método: os transportes falsos das suítes têm
   `chamar(metodo, **params)`; o cancelamento só vai ao `TransporteUnix` (`isinstance`).
3. `mypy` estreita `@property` depois de um `if`: `esgotou()`, `ultima()` e `sem_saida()` são
   métodos de propósito.
4. A outra CLI (tom de voz) mexe em `src/jarvis/voz/app.py` ao mesmo tempo: os meus trechos foram
   para o índice com o blob HEAD+meus (`git hash-object -w` + `git update-index --cacheinfo`).
5. `tests/unit/voz/test_app.py::test_modo_texto_responde_e_sintetiza` já falha no HEAD
   9185033 (sem as minhas mudanças): não é desta fatia.

## O que não foi provado em máquina real

O Brave do dono com a extensão carregada nele, o tempo real de `ponte.versao`, o `claude -p` real
seguindo a nota de replanejar, e se a causa das 3 tarefas que caíram era a mesma (a trilha antiga
não guardava o motivo — a nova guarda).
