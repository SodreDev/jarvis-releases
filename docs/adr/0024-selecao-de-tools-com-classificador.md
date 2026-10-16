# ADR-0024 — Seleção de tools: a recuperação ordena, o Jev responde perguntas fechadas, e nada disso autoriza

**Data:** 2026-10-16 · **Estado:** proposta · **Decide:** dono (Jev de nuvem ou não, e a regra
de decisão antes de medir), arquiteto (o desenho e o harness)
**Pedido:** ideia do dono de 2026-10-15 (memória `b63298d6`): a classificação e a seleção de
tools passam pelo modelo classificador recente do Jev **antes** de o modelo principal escolher,
para gastar menos contexto — medida contra o plano da SPEC §5.2. Detalha a ADR-0004, que
continua valendo inteira.

## Contexto

**O que a SPEC já fixa.** §5.1: Jev estima cenário, intenção e risco; a recuperação híbrida
(BM25 ∪ embeddings → top 30 → reranker → top 5–12) monta a shortlist; o PDP filtra; o planejador
escolhe. §5.2: o Jev **pode** filtrar e ordenar a shortlist e decidir "isto exige S2/memória?"; **não
pode** autorizar, distinguir duas escritas parecidas, escolher conta nem compor fluxo. ADR-0004:
"filtra, nunca autoriza"; confiança baixa, mudança de cenário ou escrita **ampliam** a recuperação.
Aceite (a) da F2: `recall@5` do roteador publicado **por família**, num corpus de 200–500
enunciados por cenário, com negativos e ambíguos.

**Evidência de que vale filtrar.** RAG-MCP (arXiv 2505.03275, via relatório 04 e SPEC §5.1):
−50% de tokens de prompt e seleção de 13,62% → 43,13% ao recuperar em vez de despejar o catálogo.
Guia da OpenAI citado na SPEC §4: menos de 20 funções visíveis. É paper e guia, não garantia para
este catálogo: vira medição.

**O que "o Jev" é hoje** (memórias do Orchestrator, commits `c050767` e `9ad4c3e` daquele
repositório, medidas em 2026-10-07):

- No Orchestrator, a tool `classify`/`jev` tem **dois motores**. O **local** é o reranker
  cross-encoder do `memoryd` (a hipótese é a consulta, o texto é o documento; 5 de 6 telas
  certas; **não entende negação**, por isso o sim/não usa nota absoluta com faixa "incerto"). O de
  **nuvem** é o `typesafe/jev-1.13` pela rota `/api/v1/systemone` do OpenRouter (6 de 6 telas,
  confiança 79–100%, cerca de 0,5 s, US$ 0,042 por milhão de tokens de entrada, saída grátis).
  Seis telas é amostra pequena demais para decidir qualquer coisa aqui.
- O Jev da TypeSafe é um modelo "System One": não gera texto, responde perguntas tipadas sobre um
  estado — **Choice** (uma entre opções dadas), **Score** (valor numa escala) e **Noul** (sim/não
  com probabilidade). Probabilidades "trained for calibration, measured across groups of
  predictions" — calibradas no agregado, não por resposta. Entrada só texto
  (docs.typesafe.ai, acesso em 2026-10-16).
- **A documentação consultada não diz** retenção de dados, uso para treino nem versão local
  (acesso em 2026-10-16). Até alguém achar isso escrito, mandar a fala do dono ao Jev de nuvem é
  egress para terceiro com política desconhecida.
- **Conflito com a SPEC:** a §5.1 orça o Jev em menos de 30 ms local, e isso é **[SUPOSIÇÃO]**
  da própria SPEC, a ser medida na F2. O Jev de nuvem a cerca de 0,5 s, se ficar em série no turno,
  come quase todo o p50 de 600 ms do SLO-5. Isso confirma ou derruba o harness desta ADR.
- O motor local do Orchestrator usa o reranker de lá; a ADR-0011 exige reranker de licença
  comercial no produto. O Jev local do Jarvis usa o reranker que a ADR-0011 escolher, não o do
  Orchestrator.

## Dois desenhos comparados

**D-A — o Jev escolhe.** Uma pergunta Choice sobre o catálogo (ou duas: família, depois tool) e o
top-k pelas probabilidades vira a shortlist.

**D-B — a recuperação ordena, o Jev decide perguntas fechadas.** A recuperação da §5.1 continua
ordenando tools. O Jev responde três perguntas sobre o turno estável:

1. `precisa_de_tool` — Noul;
2. `familia` — Choice entre as famílias do catálogo (até ~8) mais `nenhuma` e `incerto`;
3. `escrita_ou_egress` — Noul; sim **sobe** o rigor (amplia a recuperação, marca para
   confirmação), nunca o contrário.

A família, com probabilidade acima do limiar, **reordena** a shortlist (empurra as tools da
família para cima); o núcleo da §4 (`status`, `ask_user`, `search_catalog`, `read_notification`,
`cancel`) **nunca sai**.

| Critério | D-A | D-B |
|---|---|---|
| Número de opções por pergunta | o catálogo inteiro, que cresce com cada servidor MCP promovido (ADR-0023) | ~10 famílias, estável |
| O que vai ao Jev por turno | descrição de todas as tools | nomes e descrições das famílias |
| Se o Jev errar | a tool certa some da shortlist | a recuperação ainda a traz; o Jev só mexeu na ordem |
| Uso do contexto do planejador | menor, se acertar | menor que o despejo; a medir contra o D-A |
| Encaixe na §5.2 | "filtrar/ordenar" — sim | sim, mais "isto exige S2?" |

## Decisão

**D-B, medido contra a recuperação sozinha e contra o D-A num harness offline, antes de entrar
no caminho da voz.** O Jev de nuvem é **opt-in do dono** (**DECISÃO DO DONO**); o padrão é o
motor local, com o reranker de licença comercial da ADR-0011.

### O que o Jev vê e o que não vê

| Vê | Não vê |
|---|---|
| o texto **estável** do turno (`FinalTranscript` ou digitado) | transcrição parcial (P5, e seria egress de hipótese) |
| a última fala do Jarvis, para referências como "e o outro?" **[SUPOSIÇÃO: um turno basta; confirma ou derruba o subconjunto de ambíguos do corpus]** | histórico além disso |
| cenário estimado (nome e probabilidade) | memória, grafo, conteúdo de arquivo |
| nomes e descrições das famílias, **escritos por nós** no manifesto | descrição vinda de servidor MCP sem promoção (ADR-0023) |
| — | saída de tool, de MCP, de tarefa (ADR-0022), tela, notificação |
| — | segredo, conta, caminho de arquivo que o dono não falou |

A regra é a mesma nos dois motores: minimizar o que sai e fechar o canal de injeção — o Jev não
lê `third_party`. O construtor da entrada do Jev é uma função só, testada com estado envenenado.

### Métrica de acerto a medir

1. **`recall@5` e `recall@12`** da tool esperada na shortlist final, por família e por cenário,
   com intervalo de 95% por bootstrap — é o aceite (a) da F2.
2. **Falso negativo de `precisa_de_tool`** (disse "não precisa" quando precisava) — o erro caro,
   porque leva a resposta sem ferramenta; e precisão no mesmo eixo.
3. **Abstenção correta**: nos negativos, nenhuma tool de efeito na shortlist; nos ambíguos,
   `ask_user` ou `search_catalog` chamados.
4. **Calibração**: erro de calibração esperado (10 faixas) das probabilidades do Jev, porque o
   limiar só faz sentido se a probabilidade quer dizer o que diz — e a calibração da TypeSafe é
   declarada no agregado, sem garantia de que vale para pt-BR.
5. **Custo**: tokens de descrição de tool entregues ao planejador por turno (mediana); tempo
   acrescentado pela etapa de seleção (mediana e p95, em prosa e no CSV); US$ por mil turnos no
   motor de nuvem.
6. **Ponta a ponta**: tool chamada pelo planejador = tool esperada, no simulador de tools da F2.

**Regra de decisão, fechada antes de medir** (como a §8): o D-B substitui a recuperação sozinha só
se `recall@5` não cair mais de 1 ponto percentual em nenhuma família **e** (os tokens por turno
caírem pelo menos 30% **ou** o `recall@5` subir pelo menos 5 pontos) **e** o tempo acrescentado
ficar em até 50 ms p95 no motor local. O D-A só vence o D-B se tiver `recall@5` maior com custo de
tokens igual ou menor. **[SUPOSIÇÃO: os três limiares são proposta do arquiteto; o dono confirma
ou troca antes da medição, e o harness os lê de configuração, não do código.]** Motor de nuvem não
entra em série no turno: se o dono ligá-lo, roda em paralelo à recuperação e, se não chegar no
prazo, o turno segue sem ele.

### Fallback

- Jev indisponível, com erro, fora do prazo (o prazo é nosso, como na regra 1 do F1-14), com
  confiança abaixo do limiar, `familia = incerto`, mudança de cenário, ou `escrita_ou_egress = sim`
  → **shortlist ampla**: o top-12 da recuperação sem ajuste de família.
- `search_catalog` fica sempre no núcleo: o planejador pode pedir mais quando a shortlist não serve
  (risco "recuperação esconde a tool certa" da §10).
- **Nunca shortlist vazia.** `precisa_de_tool = não` só tira tools se a probabilidade estiver fora
  da faixa de incerteza; dentro dela, segue a shortlist ampla.
- Cada fallback é registrado no turno (motivo, motor, latência), para o replay da F2.
- O PDP filtra **depois**, sempre (P1). Nenhum caminho do Jev chega à `politica`.

## Alternativas descartadas

- **D-A como padrão** — erro do classificador vira tool ausente, e o número de opções cresce com
  cada servidor MCP. Fica como braço do harness; volta se ganhar pela regra acima.
- **Sem classificador (só recuperação)** — é o baseline, não descartado: se o D-B não passar a
  regra, é ele que fica, e a ideia do dono vira número publicado contra.
- **Jev de nuvem por padrão** — política de dados desconhecida e ~0,5 s; só com escolha do dono.
- **Mandar o catálogo ao planejador e deixá-lo escolher** — o despejo que o RAG-MCP mediu como pior
  e o guia da OpenAI desaconselha acima de 20 funções.

## Consequências

- Fica mais fácil: o catálogo pode crescer (MCP, apps) sem crescer o prompt na mesma proporção.
- Fica mais caro: um corpus rotulado por família, um harness com três braços, uma configuração de
  limiares.
- Passa a ser obrigatório testar: o construtor da entrada do Jev não carrega `third_party`; todo
  fallback devolve a shortlist ampla; a `politica` não importa o classificador.

## Riscos

| Risco | Controle |
|---|---|
| Jev erra a família e a tool certa cai | D-B só reordena; fallback; `search_catalog` |
| Injeção pela própria fala ("ignore e escolha X") | o Jev não autoriza; o pior caso é uma shortlist ruim, que o PDP ainda filtra |
| Calibração não transfere para pt-BR | métrica 4; limiar ajustado pelo corpus, não pelo fornecedor |
| Corpus pequeno dá intervalo largo | publicar o intervalo; a regra usa o pior lado do intervalo |
| Fornecedor do Jev muda ou some | motor local é o padrão; nuvem é opcional |
| Fala do dono sai da máquina | nuvem só com opt-in, registrado como `data_egress` na configuração |

## Fatia mínima (implementar primeiro)

1. **Harness offline** `tools/harness_selecao.py` sobre o catálogo do v1 (§5.6) e um corpus
   inicial **sintético**, escrito a partir dos manifestos, com negativos e ambíguos — a fala real
   do dono não vai ao motor de nuvem na fatia.
2. Três braços: recuperação sozinha; D-B com motor local; D-A com motor local. O braço de nuvem só
   roda se o dono autorizar, e só com o corpus sintético.
3. CSV em `docs/medicoes/` com `n`, hardware e commit, para o portão `tools/adr.py` conferir e
   `republicar` levar os números a esta ADR.
4. **Nenhuma mudança no caminho da voz.** O classificador só entra no turno depois que a regra de
   decisão aprovar.

## Teste de aceite

- **(a)** CSV publicado com os três braços, as seis métricas e o intervalo de cada uma; esta ADR
  emendada pelos números via `adr.py republicar`.
- **(b)** Jev levantando exceção, estourando prazo ou devolvendo `incerto`: a shortlist é o top-12
  da recuperação em 100% dos casos do teste.
- **(c)** Teste de AST: nada em `jarvis.politica` importa o classificador.
- **(d)** Construtor da entrada do Jev alimentado com um estado que tem memória, saída de tool,
  saída de MCP e segredo de teste: nada disso aparece na entrada.
- **(e)** Núcleo da §4 presente na shortlist em 100% dos turnos do corpus.

## Como invalidar esta decisão

- A regra de decisão reprova o D-B: fica a recuperação sozinha, e esta ADR é emendada dizendo isso.
- O D-A vence o D-B pela regra: troca-se o braço.
- O motor local não cabe em 50 ms p95 na máquina do dono: o classificador sai do caminho síncrono
  e passa a só marcar risco em paralelo, ou sai de vez.
- A TypeSafe publica política de dados e versão local: o opt-in de nuvem é reavaliado pelo dono.

## Fontes (acesso em 2026-10-16)

- RAG-MCP, arXiv 2505.03275: <https://arxiv.org/abs/2505.03275> (número via relatório 04 e
  SPEC §5.1).
- TypeSafe, System One e Jev: <https://docs.typesafe.ai/concepts/system-one>
- Jev 1.13 no OpenRouter (listagem): <https://openrouter.ai/typesafe/jev-1.13/api>
- Medições do `classify` do Orchestrator (6 telas, 2026-10-07): memórias do projeto Orchestrator,
  commits `c050767` e `9ad4c3e` daquele repositório.
