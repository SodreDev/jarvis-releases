# ADR-0061 — Tokens, custo e tempo até o 1º token de cada chamada ao motor vão à trilha

**Data:** 2026-11-12 · **Estado:** aceita (implementada e testada com motores falsos; os números reais são da máquina do dono) · **Decide:** arquiteto (formato e onde mede); dono (nada muda no que ele vê ou ouve além do `--diagnostico`)
**Pedido:** backlog do núcleo, item B2 (`docs/estudos/openjarvis-nucleo.md` §8), autorizado pelo dono em 2026-11-12.

## Contexto

- O dono escolhe o preset do cérebro (ADR-0056) sem ver quanto cada turno custa.
- Os números já chegavam e se perdiam: o `usage` do stream vira `Fim.uso` em `provedores/compativel.py` e `provedores/codex.py`, e a CLI do Claude manda `usage` e `total_cost_usd` no evento `result` (`s2/motor_claude_cli.py`). O preço por milhão está em `Capacidades.preco_entrada/preco_saida` (`provedores/interface.py`). O cérebro descartava o `Fim.uso`.
- A trilha (`src/jarvis/trilha.py`) é por allowlist de metadados: campo novo precisa entrar em `CAMPOS` e no evento.
- A ideia vem do `TelemetryRecord` do OpenJarvis (`OJ/core/types.py`, `OJ/engine/_base.py:117`, commit 13706f2). Nenhum código foi copiado (estudo §7: [ideia]).

## Decisão

Medir cada chamada ao motor com um envoltório do gerador de deltas (`jarvis.s2.consumo.medir`) e gravar só números na trilha.

1. **Onde mede:** cada rodada do cérebro (`Cerebro._rodada`, `origem=turno`) e cada passo da tarefa do pedido (`MotorDoObjetivo`, `origem=tarefa`). O envoltório não muda os deltas nem a ordem. O `close()` continua parando o motor. Falha ao anotar não derruba o turno.
2. **O que grava:** o evento `motor.chamada` leva `motor` (código do preset), `origem`, `tokens_entrada`, `tokens_saida`, `tokens_estimados`, `custo_microusd`, `ms_primeiro_token`, `ms` e `fim`. O `turno.fim` leva a soma do turno: `chamadas_ao_motor`, tokens, `tokens_estimados` e `custo_microusd`.
3. **Tokens:** reportado vence estimado. Sem `usage` (motor que não informa, chamada cortada), a conta é `ceil(caracteres / 4)` e a marca `tokens_estimados` vai junto. Na CLI do Claude, o que vem do cache conta como entrada.
4. **Custo em micro-dólares** (inteiro): tokens × US$ por milhão, sem perder precisão no arredondamento de 3 casas da trilha. Sem preço no catálogo, o custo é `None` («sem preço»), nunca zero. Se uma chamada do turno não tem preço, a soma do turno também é `None`. O custo reportado pela CLI do Claude vence a conta.
5. **TTFT por chamada:** do começo da chamada ao **primeiro delta de qualquer tipo** (texto, raciocínio ou proposta de ferramenta). O `ms_primeiro_token` do `turno.fim` continua sendo o primeiro **texto** do turno (ADR-0045), sem mudar de sentido.
6. **Resumo legível:** o `--diagnostico` mostra tokens e custo no último turno e uma linha por dia (`trilha.consumo_por_dia`): chamadas, tokens, custo, 1º token mediano e quantas chamadas foram estimadas ou ficaram sem preço.
7. **O preço** vem do motor dos presets (`MotorDosPresets.precos`): é o do preset que atendeu o último pedido (o de visão, quando a imagem foi para ele), pelo catálogo sem rede.

## Alternativas descartadas

- **Gravar o custo em dólar com float:** a trilha arredonda float em 3 casas, e um turno barato (US$ 0,0004) viraria zero.
- **Contar tokens com um tokenizador local:** seria mais uma dependência por provedor. O `usage` já vem dos provedores que cobram, e a estimativa só cobre o resto, marcada como estimada.
- **Medir no provedor:** cada provedor teria a própria medição, e o motor falso dos testes ficaria de fora. O envoltório no consumidor cobre todos os motores de uma vez.

## Consequências

- O orçamento do prompt não muda: nada disto vai ao modelo.
- Ficam de fora, por ora: o Jev (`decisao/openrouter.py`), o redator do social e o motor genérico de `tarefas/motores.py`, que chamam o modelo por caminhos próprios. O custo da delegação ao Claude Code também fica de fora. Entram quando houver motivo; o envoltório serve igual.
- O `motor.chamada` de uma tarefa fica no turno corrente da trilha (a tarefa roda depois do turno que a criou). A `origem=tarefa` é o que distingue.
- Testes: `tests/unit/s2/test_consumo.py` e `tests/unit/provedores/test_roteador.py`, só com motores falsos.

## Como invalidar esta decisão

Se o custo do `--diagnostico` divergir em mais de 20% da fatura do provedor numa semana de uso, a conta muda: preço por tipo de cache, ou o custo reportado pelo provedor sempre que ele informar. Se o envoltório aparecer na medição de velocidade (`medir_velocidade.py`) com mais de 1 ms por chamada, a medição sai do caminho da voz.
