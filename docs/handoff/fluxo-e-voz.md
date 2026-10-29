# Handoff — o lote fluxo/voz de 2026-10-25 a 2026-10-29: uma resposta, o sim certo, persona e regras, confirmação por voz, e o «Jarvis» por cima

Pedidos do dono de 2026-10-25 (depois de testar a versão da ADR-0045), retomados em 2026-10-29. Um
commit por parte; as ADRs saíram juntas no fim. Para cada parte: o que mudou, onde está, como testar
e o que **não** foi provado.

| parte | commit | ADR | COMO-TESTAR |
|---|---|---|---|
| A — uma resposta por pedido | `b0a2774` | 0046 | §0.33 |
| B — o sim só no que é arriscado; B3 — navegador fechado | `233d486`, `fd6639d`, `8ee2cd4` | 0046 | §0.34 |
| C — persona v15, regras do dono, catálogo gerado | `f103936` | 0047 | §0.35 |
| D — confirmação por voz | `a84a004` | 0048 | §0.36 |
| E — o «Jarvis» por cima da fala corta | `cd42601` (harness WIP), `1dc5223` | 0040 (emenda) | §0.37 |

## A — Uma resposta por pedido (ADR-0046)

- `src/jarvis/s2/cerebro.py` — `passos_no_turno` (2) e `segundos_no_turno` (12 s): a primeira
  ferramenta roda no turno; `_vai_para_tarefa` decide. O objetivo que precisa conferir passa à
  tarefa depois do primeiro passo.
- `src/jarvis/s2/entrega.py` — `so_o_novo`: a frase do motor que repete o já dito vai à tela.
- `src/jarvis/voz/app.py` — `_resposta_da_tarefa`: entrega uma vez por id; calada se repete,
  cancelada ou recusada; evento `entrega` na trilha (`src/jarvis/trilha.py`).
- `src/jarvis/s2/tarefa_do_pedido.py` — a tarefa sem o sim acaba sem repropor.

## B — A tabela do sim (ADR-0046)

- `src/jarvis/executor/fechar.py` — ordem explícita × alvo não citado; trabalho não salvo pela marca
  no título; jogo; fora da lista; travas (PID 1, compositor, o Jarvis, outro uid).
- `src/jarvis/politica/abertura.py`, `src/jarvis/executor/lancador.py` — instalado fora da lista
  pergunta e o lançamento confirmado acha o app no catálogo do sistema.
- «O navegador» e «meu Brave»: `src/jarvis/politica/atalho.py` e `fechar.py`.
- B3 (`cerebro.py`): `browser.*` sem navegador → `sites.open` com endereço, ou `browser.launch` +
  espera da extensão (até 12 s) + repete uma vez.

## C — Persona, regras, catálogo (ADR-0047)

- `src/jarvis/s2/persona.md` (v15), `src/jarvis/s2/regras.py` + `src/jarvis/s2/regras.toml` (padrão),
  `docs/exemplos/regras.toml`; o arquivo do dono é `~/.config/jarvis/regras.toml`.
- Catálogo de uma linha por ferramenta: `src/jarvis/s2/motor_claude_cli.py` com `quando`/`exemplos`
  dos manifestos; `tools/medir_prompt.py` → `docs/medicoes/prompt-do-turno.md`.

## D — Confirmação por voz (ADR-0048)

- `src/jarvis/voz/resposta.py` — `ler_resposta` (tira a palavra e o eco da pergunta → sim/nao/eco/outra).
- `src/jarvis/s2/pendencias.py` — `marcar_ouvida_a_aberta`, `foi_ouvida`; `src/jarvis/s2/fluxo_de_acao.py`
  aceita `portao=None`; `Cerebro.pendencia_sem_portao` (o app liga).
- `src/jarvis/voz/interrupcao.py` — `Motivo.RESPOSTA_A_PERGUNTA` e `SO_NA_TELA`;
  `src/jarvis/voz/app.py` — `_pergunta_aberta`, `interromper(resposta=True)`, o turno da resposta sem a
  palavra; `MotivoDoRuido.ECO_DA_PERGUNTA`.
- Teste de ponta a ponta: `tests/unit/voz/test_confirmacao_por_voz.py`.
- **Ficou para depois:** literais além de `resposta_literal` («pode encerrar», «melhor não») caem em
  `outra` (não confirmam); relaxar os sinais fortes do «sim» por cima não foi medido.

## E — O «Jarvis» por cima da fala corta (ADR-0040, emenda de 2026-10-29)

**O problema (trilha do dono, 29/10):** toda fala por cima terminava em `pausar/suspeita` →
`retomar/prazo_da_pausa`. Causas e números em `docs/medicoes/interrupcao-por-cima.md`.

- `src/jarvis/rede.py` — `id_da_instancia()`; `src/jarvis/voz/groq.py`, `elevenlabs.py`, `edge.py` —
  `_instancia` no `call_id` (os descartados da regra 5 ficam no disco entre sessões e matavam a 7ª,
  11ª, 15ª e 41ª–47ª transcrição de toda sessão). **Regra para motor remoto novo:** nunca o contador
  sozinho no `call_id`.
- `src/jarvis/voz/interrupcao.py`:
  - `PortaoDeEco.ver` — perda pico contra pico (`_microfone`, a mesma janela de 300 ms);
  - `PortaoDeEco.aprender` — falso com um trecho aberto;
  - `VigiaDeInterrupcao.cancelador` (o `CanceladorDeEco` do F1-04) + `referencia()` +
    `_sem_o_eco_do_quadro`: o resíduo vai ao portão, ao ASR e ao corte;
  - `_acompanhar` — o teto de 3 s vale; `_descartar` guarda os últimos 400 ms como o "antes";
  - `FALA_PARA_SUSPEITAR_MS` = 160.
- `src/jarvis/voz/app.py` — `fila.escuta = vigia.referencia`; `_montar_a_vigia` liga o cancelador.
- `tools/harness_interrupcao.py` — `--so-portao` (segundos, sem ASR) e a matriz com o whisper
  (`--enxuto --variantes N`, uma variante por processo; ~10 min cada com 3 em paralelo).
- Testes: `tests/unit/voz/test_interromper_por_voz.py` (perda com vales entre as sílabas, o cancelador
  com o dono no nível do eco, o teto de 3 s), `test_groq.py`/`test_elevenlabs.py`/`test_edge.py`
  (`test_o_que_caiu_numa_sessao_*`).

**Medido (sintético):** corte com o nome 31/32, falso corte pelo eco 0/8; o portão de antes deixava
passar 3–64% dos quadros do eco; sem o cancelador, o portão honesto cortava 1/32.

**Não provado:** a sala, a caixa, o microfone e a voz do dono; o atraso real do PipeWire; a Groq no
lugar do whisper small; distorção de alto-falante de notebook. **Em aberto:** o filtro da ADR-0043
custa ~600 ms no corte (fica, por segurança); na contínua o resíduo do eco pausou à toa 2 de 8
respostas; a vigia manda à Groq um pedido por suspeita (cobrança mínima de 10 s cada) — vale olhar o
limite de requisições por minuto da conta do dono se a trilha mostrar degradação de novo.

## Armadilhas

- `TMPDIR` curto (`/home/sodre/.cache/jt`) para o pytest: o longo do orquestrador quebra testes de
  AF_UNIX/D-Bus.
- O harness com o portão de antes leva horas: cada trecho sem fim vai inteiro ao ASR.
- `.claude/orchestrator-rules.md` e `.orchestrator/` não são deste lote.
