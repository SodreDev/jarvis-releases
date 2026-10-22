# Handoff — o foco do app aberto (apps.launch → tarefa de foco → window.focus_app)

## Decisão do dono (2026-10-20, Lote C, C4; ADR-0037)

1. Ao abrir um app, o Jarvis confere se o foco virou o app; se não, põe o app em foco.
2. App lento (jogo pelo Steam): acompanhar em intervalos, sem prender a conversa, listando as
   janelas em primeiro e em segundo plano a cada ciclo; a conta do Steam é escolha do dono.
3. Janela de nome genérico não é focada por palpite: só com evidência ligada ao que foi lançado; na
   dúvida, pergunta ou espera. Prazo configurável e mensagem honesta.
4. Nada na sessão real do dono: contêiner, X virtual ou fakes.

## O fluxo

```text
apps.launch (executor, pelo PDP)
  → janelas.listar()                   as de antes: a que aparecer depois é "nova"
  → lancar_app(app) → pid              devolve na hora: {app, pid, foco, tarefa_do_foco}
  → GestorDeTarefas.iniciar(motor=MotorDeFoco, prazo_s=prazo_do_foco_s + 60)
        ciclo (1, 2, 3, 5, 8 s, depois 10 s; o cancelar olhado a cada 0,2 s)
          janelas.listar() → avaliar(janelas, pista, antes)   a evidência (ADR-0037, item 3)
            alvo já na frente      → FimDaTarefa (sem aviso se < 10 s)
            alvo atrás             → PedidoDeTool("window.focus_app", {app, janela_id})
                                        → executor → PDP (livre) → janelas.focar → ativar
                                        → confere na frente (até 1 s), espera 3 s:
                                          sumiu (janela de abertura) → volta ao ciclo
            empate por 3 ciclos    → FimDaTarefa(pergunta, aviso=pergunta)
            prazo                  → ErroDeTarefa(o que viu: não apareceu, conta do Steam,
                                                  janela «tal» sem ligação, não deu para ver)
  → _tarefa_concluida (app)            aviso "" = só o card; texto = o que o dono ouve
```

## Onde mora cada peça

- `src/jarvis/executor/janelas.py`: a porta (`Janelas`: `listar`, `ativar`), as duas
  implementações (`JanelasPorKdotool` — uma chamada encadeada por ciclo, com o caminho lento se os
  blocos desalinharem; `JanelasPorWmctrl` — `wmctrl -lxp` + `xprop`), `janelas_do_ambiente` (o
  critério de `jarvis.entrada.foco`), `focar`/`listar_para_o_modelo` (o que as `window.*` fazem com
  a porta), os processos (`ProcessosDoProc`: pai, executável, linha de comando — **nunca** o
  ambiente) e a evidência (`PistaDoApp`, `avaliar`, `GENERICOS`, `DO_SISTEMA`).
- `src/jarvis/tarefas/foco.py`: o `MotorDeFoco` (ciclo, carência de 5 s para janela que já
  existia, empate que precisa durar, conferência depois do foco, fim rápido calado, frase do prazo).
- `src/jarvis/tarefas/gestor.py`: `FimDaTarefa.aviso` e `iniciar(..., prazo_s=)` — do código, nunca
  do modelo.
- `src/jarvis/executor/ferramentas.py`: `_acompanhar_o_foco` (só do turno; sem porta ou sem gestor,
  nada muda) e o campo `prazo_do_foco_s`.
- `src/jarvis/executor/nativas.py`: `window.list` e `window.focus_app` pela porta quando há
  (`Nativas.janelas`); sem ela, o `wmctrl` de `desktop.py`, como antes. (2026-10-21: a `window.close_app` virou `window.close` + `apps.quit`, pela mesma porta — ADR-0042.)
- `src/jarvis/voz/app.py` e `config.py`: a porta ligada em `abrir` (fora de `CI=1`), o
  `prazo_do_foco_s` (10 a 1800, padrão 300) e o aviso do fim.
- `catalogo/window.focus_app.yaml` (`janela_id`), `catalogo/window.list.yaml`, persona v12 e a nota
  do roteiro de método (`jarvis.politica.metodo`).

## Limites (de propósito)

- No Wayland, só o `kdotool` (KDE) vê as janelas dos outros apps: sem ele, não há acompanhamento —
  o `wmctrl` pelo XWayland veria só as janelas X11, com a ativa possivelmente velha.
- Num jogo do Steam o PID não conta (tudo descende do Steam); vale a classe `steam_app_<id>` ou o
  `reaper` com `AppId=<id>` acima do processo da janela. A janela da conta nunca é focada.
- A tarefa ocupa uma das duas vagas enquanto espera; com o teto cheio, o app abre e o resultado diz
  que o foco não vai ser acompanhado.
- Depois do foco confirmado, a tarefa acaba: não persegue o dono se ele for para outra janela.

## Testes

- `tests/unit/executor/test_janelas.py`: as saídas do `kdotool` e do `wmctrl` (inclusive o título
  que o `wmctrl` não lê, `N/A`), o ambiente, os ids recusados, a tabela de evidência, o Steam, a
  carência e o executável da instância que já rodava.
- `tests/unit/tarefas/test_foco.py`: o motor no tempo, com relógio falso.
- `tests/unit/executor/test_foco_do_app.py`: ponta a ponta no executor (PDP, auditoria, gestor).
- `uv run --frozen python -m tools.harness_janelas --detalhes`: X de verdade em contêiner (openbox
  sem foco em janela nova, `wmctrl`/`xprop`, apps `xterm`, Steam e `reaper` falsos) — 14 conferências.

## Não verificado

- O KWin de verdade e o `kdotool` rodando: o formato da saída encadeada saiu do código-fonte dele.
- O Steam de verdade (a linha de comando do `reaper`, a classe dos jogos do Proton).
- O título com acento de app X11 antigo no `wmctrl` sai `N/A` (o Jarvis o trata como desconhecido):
  no contêiner, os casos usam nomes sem acento.

## Continua em `velocidade-e-foco.md` (2026-10-21)

A porta de janelas lê o KWin numa chamada (`kdotool kwinscript`): monitores (o principal primeiro),
a ativa, a da frente de cada monitor, a pilha e a área de trabalho — e não quebra sem janela ativa.
Ferramenta nova `window.focused`; o `kdotool` ganha a `KDE_SESSION_VERSION` que exige; roteiro no KWin
virtual com dois monitores (`tools/harness_foco.py`) e o diagnóstico de 1 comando
(`tools/diagnostico_foco.py`).
