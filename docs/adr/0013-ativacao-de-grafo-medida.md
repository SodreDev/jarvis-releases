# ADR-0013 — Ativação de grafo cabe no orçamento de voz, e o teto vai dentro da varredura

**Data:** 2026-10-15 · **Estado:** aceita · **Decide:** executor (medição), emenda a ADR-0008
**Emenda:** ADR-0008 (memória em grafo e ativação por propagação) — substitui a
**[SUPOSIÇÃO]** da §6.8 pelos números do harness da F0-05.

## Contexto

A ADR-0008 e a §6.8 assumiam, marcado como suposição, que "a travessia limitada em SQLite cabe
no orçamento de voz no corpus do dono", e os alvos SLO-11 e SLO-12 eram alvos iniciais.

O harness do cartão F0-05 mediu isso em 2026-10-15, na máquina do dono (AMD Ryzen 5 5600G,
31 GiB de RAM, Linux 7.2.9, Python 3.12.14, SQLite 3.53.1), com grafo sintético determinístico
dimensionado pelo corpus real (122 episódios — as memórias que o Orchestrator guarda para este
projeto), em três escalas (1×, 10×, 100×), 200 consultas por execução, 3 execuções, mediana e
p95. Relatório completo em `docs/medicoes/f0-05-grafo.md` e `docs/medicoes/f0-05-grafo.csv`.

O que os números mostram:

- **1 salto:** p95 de **0,11 ms** (1×), **0,11 ms** (10×), **0,16 ms** (100×) e **0,24 ms**
  no grafo com hub (meta SLO-11: 40 ms).
- **2 saltos:** p95 de **1,54 ms** na escala 100× (12 200 episódios, ~97 600 arestas).
- **Caminho completo sem reranker** (densa simulada + léxica FTS5 + 2 saltos, fundidos por
  RRF): p95 de **62 ms** na escala 100×, com **0** consulta truncada (meta SLO-12: 250 ms).
- **O que aperta é o hub, não o tamanho:** com um nó de grau 10 029, a travessia de 2 saltos
  sai de 1,54 ms para **12,6 ms** p95.
- **Teto depois da varredura é caro:** aplicar o corte de fan-out com
  `ROW_NUMBER() ... WHERE pos <= teto` obriga o SQLite a ranquear todas as arestas do nó antes
  de cortar; no hub, isso custou **40,7 ms** p95 — truncando 26 de 150 consultas por orçamento
  e alcançando só 15,8 nós — contra 12,6 ms e 67,6 nós da versão que corta dentro da varredura
  (uma consulta por nó, `ORDER BY ... LIMIT`). A propagação em Python, que lê as ~10 200
  arestas do hub, ficou em 30,7 ms.
- **Variação entre execuções:** no caso do hub, o p95 de 2 saltos variou entre 9,4 ms e
  12,6 ms em execuções diferentes, com a máquina em uso. Por isso o relatório publica as três
  execuções e também p99, e por isso as conclusões usam ordem de grandeza, não o dígito.
- **`WITH RECURSIVE` sem teto de fan-out não serve:** 100–200× mais lenta e estourando o
  orçamento na maioria das consultas das escalas maiores.

## Decisão

Manter SLO-11 e SLO-12 como estão (os alvos deixam de ser **[SUPOSIÇÃO]** e passam a ter
folga medida), fixar **2 saltos** como limite viável do caminho de voz e implementar a
travessia de produção com o **teto de fan-out dentro da varredura**, uma consulta por nó da
fronteira.

## Alternativas descartadas

- **Travessia recursiva em SQL** (`WITH RECURSIVE`): elegante e lenta; estoura o orçamento.
  Fica no repositório apenas como medição.
- **Propagação em memória**: mais rápida no grafo pequeno, mas lê todas as arestas do hub, que
  é justamente o caso ruim. Serve de piso teórico.
- **Baixar os alvos de SLO-11/SLO-12**: não há motivo — a folga medida é de uma a duas ordens
  de grandeza.
- **Subir para 3 saltos agora**: o custo não é o problema, a qualidade é desconhecida. Isso é
  decisão da §8.2, com corpus anotado, em F3.

## Consequências

- Mais fácil: o grafo pode entrar no caminho da voz sem ameaçar o SLO-5, e o degrau 3 da §6.8
  (2 saltos) deixa de ser aposta.
- Mais caro: a travessia de produção faz **mais consultas** (uma por nó da fronteira), o que
  exige os índices da §6.7 presentes — sem eles, o ganho desaparece.
- Passa a ser obrigatório testar: que as implementações concordam no conjunto de nós (senão
  comparar custo não quer dizer nada), que o orçamento estourado devolve parcial com
  `graph_truncated: true` sem esperar, e que um hub de grau 10 000 não explode a travessia.
- Continua **não medido**: qualidade de recuperação (recall, nDCG, abstinência), que é a
  medição da §8.1/§8.2 em F3; corpus real de C1 (cartão F0-08); e execução em Windows.

## Como invalidar esta decisão

O corpus real de C1 (F0-08) mostrar grau médio muito acima do grafo sintético, ou a medição de
qualidade da §8.2 exigir mais de 2 saltos no caminho da voz. Nos dois casos, o harness já está
no repositório e refaz os números com um comando.
