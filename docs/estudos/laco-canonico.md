# O laço canônico: o que ainda acontece fora do modelo (diagnóstico)

2026-11-16. Pedido do dono (memória 391a8b23): o Jarvis é **um agente-CLI com voz**. A
transcrição do STT é só a mensagem do usuário; o modelo, com todas as ferramentas, a memória e as
skills à mão, processa, pensa, decide os parâmetros e age; ao delegar, o subagente faz **o mesmo**
com a etapa delegada. O código só (1) valida segurança e permissão e devolve o veredito ao modelo,
(2) executa a ferramenta, (3) mede e limita (passos, tempo) devolvendo notificação e (4) fala o
que o modelo mandou falar.

Este documento mapeia, com arquivo:linha (HEAD `8ebf084`), tudo o que no turno do Jarvis e na
tarefa do subagente ainda roda **fora** dessa forma, e classifica cada item: **manter**
(segurança, permissão, verdade do relato, limite), **virar nota** (o fato vai ao modelo, que
decide) ou **remover**.

## Os laços que existem hoje

Não há um laço: há **quatro** lugares que chamam o modelo, cada um com o seu jeito de ler a
resposta.

| Onde | O que é | Como lê o modelo |
|---|---|---|
| `s2/cerebro.py:483` `Cerebro.responder` + `:1538` `_rodada` | o turno do Jarvis (voz) | `LeitorDoProtocolo` próprio (`:1570`), fatiador, filtros |
| `s2/cerebro.py:1854` `_texto_sem_ferramentas` | rodada de evento (aviso, fim) | outro `LeitorDoProtocolo` (`:1859`) |
| `s2/tarefa_do_pedido.py:428` `MotorDoObjetivo._rodada` | o subagente do pedido | outro `LeitorDoProtocolo` (`:479`), outro contexto, outras notas |
| `tarefas/motores.py:55` `MotorDeAgente.proximo` | o subagente do `tarefa.iniciar` (motor «agente») | **sem** leitor do protocolo, prompt próprio `SISTEMA_DA_TAREFA` (`:33`), **sem** persona, memória nem regras do dono |

E o laço externo também é duplicado: o turno itera em `responder` (`:701`–`:933`); a tarefa
itera em `GestorDeTarefas._passos` (`tarefas/gestor.py:505`) chamando `proximo`. O que cada um
injeta é diferente (tabela «Diferenças» abaixo), então o mesmo pedido se comporta de um jeito no
turno e de outro no subagente.

O formato também é um só para todo provedor: o **protocolo de texto** (`<<ferramenta>>{json}`,
`<<pensar>>`, `s2/protocolo.py`; catálogo no prompt por `sistema_com_ferramentas`,
`s2/motor_claude_cli.py:182`). Até o motor compatível com OpenAI (`provedores/compativel.py:116`)
manda **uma** mensagem de usuário com a conversa achatada em texto (`Contexto.como_texto`,
`s2/motor.py:120`) e nenhum `tools`. É a causa das falhas do DeepSeek na validação (resposta
vazia, `<</pensar>>` solto): o provedor tem function calling nativo e não é usado.

## (A) O que roda ANTES do modelo, no turno

| # | arquivo:linha | O que faz | Classe |
|---|---|---|---|
| A1 | `s2/cerebro.py:529` `fluxo.ler_a_resposta` | Lê a fala contra a pergunta pendente («sim»/«não») e resolve a pendência sem o modelo | **manter** — é a resposta do dono a um pedido de permissão (matar/apagar); o resultado vai ao modelo como evento (`_responder_ao_evento`) |
| A2 | `s2/cerebro.py:546` `comando_de_permissao(texto_do_dono)` → `voz/app.py:1044` | Regex na transcrição **troca o modo de permissão** e só depois avisa o modelo | **remover** como gatilho: vira ferramenta `jarvis.permissao` que o modelo chama; o código só **valida** (a troca tem de estar na fala do dono deste turno, nunca em página ou resultado) e devolve o veredito |
| A3 | `s2/cerebro.py:562` `ao_pedir_estilo(texto_do_dono)` → `voz/app.py:1005` | Regex na transcrição **troca o estilo da voz** antes do modelo | **remover** como gatilho: vira ferramenta `voz.estilo` que o modelo chama |
| A4 | `s2/cerebro.py:580` `metodo.nota()` | O roteador de método diz o caminho direto | **manter como nota** (já é dica, ADR-0070) |
| A5 | `s2/cerebro.py:585` `_receitas` | Receita da família do assunto | **manter como nota** (é a «skill» carregada sob demanda) |
| A6 | `s2/cerebro.py:592` `_memorias_fixas`, `:609` `consultar` | Memória do dono no contexto | **manter** (é a memória à mão do modelo) |
| A7 | `s2/cerebro.py:680` `_atalho` + `nota_do_atalho` (`:169`) | Regex na transcrição propõe ferramenta **e argumentos** («DICA DO CÓDIGO») | **remover**: é exatamente o trecho do Whisper virando parâmetro; o modelo tem as ferramentas e decide |
| A8 | `s2/cerebro.py:225` `NOTA_DO_PLANO` + `:852` `_falta_o_plano` (`exigir_plano`, ligado em `voz/app.py:954`) | A 1ª ferramenta sem `<<pensar>>` **não roda** e volta | **remover**: exigência de formato; o modelo pensa como quiser (nativo: o raciocínio do provedor) |
| A9 | `s2/motor_claude_cli.py:84` `INSTRUCAO_DE_FERRAMENTAS` («ENTENDER ANTES DE AGIR… escreva o plano entre <<pensar>>») | Formato do plano no prompt | **virar nota**: pensar antes continua como conselho, sem formato obrigatório |
| A10 | `s2/regras.toml:31` `sim_so_no_risco` («enviar mensagem» pede o sim) | O modelo obedece e pergunta antes de enviar | **remover** «enviar mensagem» (decisão do dono 2026-11-14): pedido direto executa; só matar/encerrar e apagar pedem permissão |

## (B) O que fala ou decide DEPOIS do modelo, no turno

| # | arquivo:linha | O que faz | Classe |
|---|---|---|---|
| B1 | `s2/cerebro.py:751` `FiltroDaVerdade`, `:957` rodada do `falta` | Corta a frase que afirma o que nenhuma ferramenta confirmou; o fato volta ao modelo | **manter** (verdade do relato) — já devolve ao modelo, sem frase pronta |
| B2 | `s2/cerebro.py:801`–`:815` `NOTA_DE_SEGUIR` | Cobra o modelo que parou antes do objetivo | **manter como nota** (é notificação ao modelo) |
| B3 | `s2/cerebro.py:786` `_plano_sem_acao` + `NOTA_DO_PLANO_SEM_ACAO` (`:235`) | Lê o plano do modelo à procura de id de ferramenta | **remover** junto com A8 (só existia por causa do plano obrigatório) |
| B4 | `s2/cerebro.py:743` `FiltroDoJaDito` | Tira da **voz** a frase que repete o que o dono já ouviu (a tela recebe tudo) | **manter**: não escreve nem decide, só não repete na voz; o modelo já recebe o `ja_dito` |
| B5 | `s2/cerebro.py:862` `leitura_antes` | O código **troca** a ação proposta por `browser.inspecionar` e a executa | **virar veredito**: a regra do dono (ler antes de agir) fica, mas a ação volta recusada ao modelo com o motivo, e é ele quem lê |
| B6 | `s2/cerebro.py:877` `_vai_para_tarefa` | Execução vai ao subagente | **manter** (regra do dono, ADR-0070) — e o subagente passa a rodar o **mesmo** laço |
| B7 | `s2/cerebro.py:898` `NOTA_DO_NAVEGADOR_FECHADO`, `:914` aviso da moderada | Fato ao modelo | **manter como nota** |
| B8 | `s2/cerebro.py:912` `_perguntar_ao_dono` | Pendência de permissão: o modelo pergunta com as palavras dele | **manter** (permissão) |
| B9 | `s2/cerebro.py:942` `_rodada_do_limite` | Teto do turno vira notificação | **manter** (limite → notificação) |

## (C) No subagente (`MotorDoObjetivo`, `MotorDeAgente`)

| # | arquivo:linha | O que faz | Classe |
|---|---|---|---|
| C1 | `s2/tarefa_do_pedido.py:89` `NOTA_SEM_PLANO` | Exige plano em `<<pensar>>` antes do 1º passo | **remover** (formato); vira a etapa: o que o Jarvis disse/pensou ao delegar, ou a conversa |
| C2 | `s2/tarefa_do_pedido.py:454` `roteiro(objetivo.pedido, …)` → `roteiro_do_navegador.py:197` `_fatos_do_envio` | **Regex na fala crua** tira contato e mensagem e os dá como «fatos» | **remover** os fatos tirados da fala; fica só a orientação geral do navegador (como uma skill) |
| C3 | `s2/tarefa_do_pedido.py:383` `_com_leitura` / `leitura_antes` | Troca a ação por leitura | **virar veredito** (igual a B5) |
| C4 | `s2/tarefa_do_pedido.py:274` `recuperacao.repetida` | Recusa repetir a ação que falhou | **manter** (veredito ao modelo) |
| C5 | `s2/tarefa_do_pedido.py:291`/`:557` `conferir_relato` + `_explicar` | Verdade do relato, devolvida ao modelo | **manter** |
| C6 | `s2/tarefa_do_pedido.py:460` `NOTA_DE_CONFERIR` | Pede leitura antes de dizer «pronto» | **manter como nota** |
| C7 | `tarefas/laco.py` guarda de laço, `RODADAS_POR_PASSO`, `LimiteDaTarefa` | Limites → notificação | **manter** |
| C8 | `tarefas/motores.py:33` `SISTEMA_DA_TAREFA` + `:55` `MotorDeAgente.proximo` | Outro prompt, sem persona/regras/memória; lê `Texto` sem o leitor do protocolo | **remover** o laço próprio: passa pelo núcleo comum |

## Diferenças entre o laço do Jarvis e o do subagente

| | Jarvis (turno) | Subagente (`MotorDoObjetivo`) | `MotorDeAgente` |
|---|---|---|---|
| leitura da resposta do modelo | `LeitorDoProtocolo` em `_rodada` | outro `LeitorDoProtocolo` | nenhum |
| prompt | persona + regras + memória + notas | o do turno + `NOTA_DA_TAREFA` + objetivo | `SISTEMA_DA_TAREFA` só |
| ferramentas | catálogo inteiro | catálogo sem `tarefa.*` (profundidade 1) | idem |
| exigência de formato | plano obrigatório (A8) | plano obrigatório (C1) | — |
| fatos da fala por regex | atalho (A7) | roteiro (C2) | — |
| ler antes de agir | o código troca a ação (B5) | o código troca a ação (C3) | não |
| verdade do relato | filtro + rodada | `conferir_relato` + `_explicar` | não |
| resultado das ferramentas | `Mensagem("ferramenta", texto)`, sem a chamada | idem | idem |

## Meta e o que muda (Fase B, um commit por item)

1. **Núcleo comum** (`s2/laco.py`): o ÚNICO ponto que chama o modelo e lê a resposta (protocolo de
   texto ou chamada nativa), a ÚNICA montagem das mensagens de ferramenta (com a chamada que as
   gerou) e a ÚNICA validação da proposta (veredito ao modelo). Turno, rodada de evento,
   subagente do pedido e `MotorDeAgente` passam por ele.
2. **`tool_calls` nativo** no motor compatível com OpenAI (OpenRouter e afins): `tools` com o
   esquema do manifesto, a conversa em mensagens de verdade (user/assistant/tool com
   `tool_call_id`), `delta.tool_calls` lido no stream (ADR-0072).
3. **«Enviar mensagem pede o sim» sai do padrão** (A10); a conferência do contato
   (`alvo_nao_confere`) e as travas do envio autônomo (ADR-0060) ficam.
4. **Sem gatilho antes do modelo**: atalho (A7) sai; permissão (A2) e estilo (A3) viram
   ferramentas que o modelo chama, com a validação devolvendo o veredito.
5. **Sem exigência de formato**: plano obrigatório (A8, B3, C1) sai; o conselho de pensar fica (A9).
6. **Ler antes de agir vira veredito** (B5, C3).
7. **Sem fatos tirados da fala por regex no subagente** (C2).
8. **`MotorDeAgente` no núcleo comum** (C8).

**Fica, com motivo:** A1, B8 (permissão), A4–A6 (contexto e memória, não decidem), B1, B2, C4–C6
(verdade do relato e cobrança como notificação), B4 (eco na voz), B6 (regra do dono: execução vai
ao subagente), B7, B9, C7 (limites e fatos como notificação).

## Estado (2026-11-16, depois da Fase B)

| Item | Commit | O que ficou |
|---|---|---|
| 1. Núcleo comum | `0b4ef4b` | `s2/laco.py`: `rodada_do_agente` é o único ponto que chama o modelo para o turno, a rodada de evento, o subagente do pedido e o do `tarefa.iniciar`; `mensagens_das_ferramentas` devolve cada resultado com a chamada |
| 2. Chamada nativa | `5dc1d67` | ADR-0072; `tools` + par `tool_calls` → `tool` no OpenRouter, OpenAI, Groq e no servidor que declara `tools` |
| 3. Envio sem o sim | `2ca29a5` | a regra padrão só pede o sim no destrutivo; o PDP já fazia isso no modo automático |
| 4. Nada antes do modelo | `52fe04d` | atalho fora; `jarvis.permissao` (validada contra a fala do dono deste turno) e `jarvis.estilo_da_voz` são ferramentas que o modelo chama |
| 5. Sem plano obrigatório | `cb68cbd` | nenhuma barreira de formato; o conselho de pensar antes fica na instrução. **B3 mudou de classe:** a nota do plano que previa ferramenta e não propôs nenhuma ficou como notificação (lê só o raciocínio do próprio modelo e não bloqueia nada). Medido: Claude 20/21 na validação, plano presente nos 21 casos, a barreira teria disparado 0 vez — a única falha não vem dela |
| 6. Ler antes vira veredito | `c7f8426` | `motivo_para_ler`: a ação sem leitura não roda e o porquê volta ao modelo (causa `pagina_nao_lida`) |
| 7. Sem fatos da fala no subagente | `28ff604` | a orientação do navegador nem recebe a fala; levam-se as travas e o tom das memórias |
| 8. `MotorDeAgente` no mesmo laço | `a30eb9a` | é o `MotorDoObjetivo` com a etapa delegada (a `descricao`), a persona, as regras e a memória do turno |

**Fora do escopo, com motivo:** três agentes que não são o Jarvis nem o subagente ainda chamam o
modelo direto — o redator e o agente monitor das redes (`social/redator.py`, `social/agente.py`,
ADR-0060) e o `acerto` (classificador). Não executam ferramenta do dono; ficam para uma rodada
própria. `files.move_to_trash` tem manifesto e não tem corpo: o Jarvis não apaga arquivo nesta
versão, e o caso de apagar ficou fora do conjunto novo.
