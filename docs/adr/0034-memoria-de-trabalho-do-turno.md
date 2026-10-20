# ADR-0034 — Memória de trabalho do turno: o que as ferramentas trazem vale só para ele

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que fica e o que some), arquiteto (o orçamento)
**Pedido:** dono, 2026-10-20 — "MEMÓRIA TEMPORÁRIA DE TURNO: texto de página, árvore, scripts e imagens lidos durante a tarefa são só do turno: resumir/podar resultados grandes conforme o contexto cresce e DESCARTAR tudo ao fim da tarefa (nunca acumular no histórico persistente nem na memória longa, a menos que o modelo decida salvar um fato curto via memoria.*)". Emenda a ADR-0028 (o laço levava todos os resultados inteiros a cada rodada) e a ADR-0022 (o motor `agente` das tarefas, idem).

## Contexto

Cada rodada do laço é um pedido novo ao motor com **todos** os resultados do turno até ali, cada um com até 6000 caracteres: doze passos de navegação (páginas, mapas, telas) eram 72 mil caracteres a cada rodada, e o motor `agente` das tarefas fazia o mesmo. O descarte no fim já valia por construção — a conversa guarda só o que o dono disse e o que tocou do Jarvis (P4), o livro grava esses mesmos turnos, a imagem e o raciocínio morrem com o turno (ADR-0032, ADR-0031), os passos de uma tarefa morrem com ela (só o resumo fica) —, mas nada o provava de ponta a ponta.

## Decisão

1. **Orçamento por rodada** (`jarvis.s2.rascunho.textos_no_contexto`, 18 000 caracteres). O resultado **mais novo** vai sempre inteiro — é dele que o próximo passo depende; os anteriores vão inteiros enquanto couberem, do mais novo para o mais velho; o que não couber vai **podado**.
2. **O resultado podado** (`ResultadoDeFerramenta.resumo_para_o_modelo`, até 600 caracteres): ferramenta, status, motivo, aviso, `acao_id`, os valores pequenos (endereço, título, números, `tab_id`, o objeto pequeno como o id da tela) e, no lugar do volume — texto de página, mapa, links, scripts —, só a medida do que saiu (`[podado: 3500 caracteres]`, `[podado: 10 itens]`). O modelo sabe o que já fez e pode ler de novo.
3. **Também nas tarefas:** o motor `agente` monta o contexto da tarefa pelo mesmo orçamento.
4. **O descarte é provado:** depois do turno, o pedido seguinte ao motor, a conversa e o livro não têm nada do que as ferramentas trouxeram (teste com uma marca no texto lido). Guardar um fato curto continua sendo decisão do modelo, com `memoria.*` (persona v10: o que se lê para um pedido vale só para ele).
5. **Trilha:** só a contagem — `resultados_podados` no fim do turno ("passos antigos podados N").

## Alternativas descartadas

- **Resumir com um modelo:** custo e latência a cada rodada, e o resumo de um modelo do que uma página disse é mais um texto de terceiros no contexto. O resumo estrutural é do código e não inventa.
- **Guardar os resultados num arquivo do turno para reler:** é o "acumular" que o dono não quer; quem precisa reler chama a ferramenta de novo.

## Consequências

- O contexto de um turno longo fica perto de 18 mil caracteres de resultados mais o passo novo.
- **Risco aceito:** um passo antigo podado pode ser preciso de novo (um trecho de uma página lida há cinco passos); o modelo lê de novo — a persona e o resumo dizem que foi podado.
- Testes: `tests/unit/s2/test_memoria_de_trabalho.py` (o orçamento, o resumo, seis páginas grandes, o descarte na conversa, no livro e no pedido seguinte, a tarefa), `tests/unit/test_trilha.py`.
