# ADR-0064 — Harness de acerto em pt-BR: a fala do dono → a ferramenta ou a decisão certa, com gate por categoria

**Data:** 2026-11-12 · **Estado:** aceita (implementada; o gate roda no `verificar.py` só com o código, sem motor de verdade) · **Decide:** arquiteto (formato, nota, gate); dono (nada muda no que ele vê; nunca API real nem chave na verificação)
**Pedido:** backlog do núcleo, item B1 (`docs/estudos/openjarvis-nucleo.md` §8), autorizado pelo dono em 2026-11-12.

## Contexto

- Mudar a persona, o prompt (no teto de 16 000 caracteres), o catálogo ou as regras de fala era validado à mão ou só pela latência. Nada dizia se «abre o Discord» ainda vira `apps.launch` ou se «não, pode seguir» continua ambíguo.
- O OpenJarvis tem o ToolCall15 (`OJ/evals/datasets/toolcall15.py`, `OJ/evals/scorers/toolcall15.py:108-160`, commit 13706f2): ferramentas falsas e nota 0/1/2 por cenário, sem juiz. E um gate de regressão por grupo (`OJ/learning/spec_search/gate/regression.py`). Nenhum código foi copiado.

## Decisão

1. **Cenários em TOML** (`src/jarvis/acerto/cenarios.toml`): id, categoria, tipo, fala e o esperado (`ferramenta` e `args`, ou `decisao`; `nenhuma` = não deve responder). Mudar um esperado é mudar o comportamento, e a razão vai no commit.
2. **Quem responde é o código**, por tipo: `atalho` (ADR-0045, com o motivo do roteador), `metodo` (ADR-0035), `resposta` (sim/não, ADR-0048), `continuar` (teto, ADR-0059), `nota` (ADR-0063). Apps e navegadores "instalados" são fixos (`Ambiente`), iguais em toda máquina.
3. **Nota sem juiz:** 2 = ferramenta e argumentos esperados (argumento a mais não tira ponto) ou a decisão certa; 1 = ferramenta certa com argumento errado; 0 = o resto.
4. **Motor:** os cenários `motor` pontuam a primeira proposta de um `MotorDeConversa` passado por código (`jarvis.acerto.rodar(..., motor=...)`). Sem motor, não rodam. Na verificação e nos testes só entra motor falso. Rodar com um preset do dono é à mão, fora da verificação.
5. **Gate** (`tools/harness_acerto.py --gate`, etapa «acerto pt-BR» do `verificar.py`): reprova se o total cai, ou se uma categoria cai mais de 5 pontos percentuais contra `linha_de_base.json`. Categoria com menos de 5 cenários não reprova. 3 rodadas, vale a mediana. `--gravar-base` regrava a base, e a nova base vai no commit com a razão.
6. **Hoje:** 54 cenários do código em 8 categorias (apps, janelas, navegador, web, roteamento, sim/não, teto, nota), todos em 2/2, e 5 de motor.

## Alternativas descartadas

- **Juiz por modelo:** custa chamada e varia. Fica para o que não se mede sem juiz (B11).
- **Motor real na verificação:** precisaria de chave e rede, e o resultado variaria com o provedor. O dono roda à mão quando quiser comparar presets (o B5 depende disso).
- **Esperado de cada cenário tirado do comportamento atual sem olhar:** cada esperado foi conferido contra o que o dono pediu nas ADRs citadas. Onde o atual está certo, ele é a base.

## Consequências

- A etapa custa menos de 1 s no `verificar.py`.
- Regressão no atalho, no roteador ou na leitura do sim/não aparece como categoria que caiu, com o cenário e o que veio.
- Testes: `tests/unit/acerto/test_harness.py` (nota 0/1/2, motor falso, gate, id repetido, o script).

## Como invalidar esta decisão

Se um caso real do dono falhar na trilha e a categoria dele seguir em 100% aqui, faltam cenários: o caso entra no TOML. Se o gate reprovar mudança que o dono aprovou, o esperado muda no mesmo commit, com a razão.
