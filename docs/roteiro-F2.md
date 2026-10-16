# Roteiro da F2 — ordem sugerida, dependências e o que é do dono

**Data:** 2026-10-16 · **Autor:** planejador · **Estado:** proposta para o dono
**Base:** SPEC §9 (F2), ADR-0022 (subagentes), ADR-0023 (MCP cliente e servidor), ADR-0024
(seleção de tools com classificador), todas **propostas**. Este roteiro **não decide** nada que
seja do dono: cada ponto desses está marcado **DECISÃO DO DONO**, com as opções e o que ele trava.

## O que a F2 já pede (SPEC §9)

Manifesto e SDK de tool, PDP com os 4 modos, auditoria encadeada, Jev de cenário/intenção,
recuperação híbrida de tools, 15–25 capacidades **só de leitura ou transitórias** das famílias do
v1, porto MCP com promoção de manifesto, simulador de tools e corpus de 200–500 enunciados por
cenário. Aceite: `recall@5` por família; 100% das chamadas validadas por schema; nenhuma ação por
frase; suíte de prompt injection com saída de MCP e rug-pull; replay de sessão.

Parte disso já existe desde a F0 (`src/jarvis/politica/pdp.py`, `auditoria.py`, `modos.py`,
`src/jarvis/manifesto/` com validador, lint e codegen, `catalogo/` com três manifestos). A F2
completa e liga as peças; as ADRs 0022–0024 acrescentam três frentes.

## Ordem sugerida

| # | Passo | Depende de | Por que nesta posição | Aceite |
|---|---|---|---|---|
| 1 | Completar o SDK de tool, o simulador de tools e as 15–25 capacidades de leitura/transitórias | F0 (PDP, manifesto) | tudo abaixo chama capacidade por ele | o da F2 (b) e (c) |
| 2 | Corpus da F2: enunciados por cenário e por família, com negativos e ambíguos — primeiro **sintético**, a partir dos manifestos | 1 | serve aos passos 3, 4 e 8 e ao aceite (a) da F2 | corpus versionado em `corpus/` com contagem por família |
| 3 | **ADR-0024, fatia mínima:** harness offline de seleção com três braços (recuperação sozinha, D-B local, D-A local) | 1, 2; reranker da ADR-0011 | não toca o caminho da voz e produz o número que decide o resto | ADR-0024 (a)–(e) |
| 4 | **ADR-0023, cliente, fatia mínima:** um servidor `stdio` de teste + um real de leitura, promoção, pin, suspensão | 1; caixa de areia por sistema | é o porto MCP que a F2 já exige e cobre o aceite (d) | ADR-0023 (a)–(d), (h), (i) |
| 5 | **ADR-0023, servidor, fatia mínima:** `jarvis mcp --cliente orchestrator` por `stdio`, teto `jarvis` | 1, 4 (mesma regra de teto e de segredo) | o Orchestrator passa a ler o Jarvis sem atalho | ADR-0023 (e)–(g) |
| 6 | **ADR-0022, fatia mínima:** processo `tarefas` com motor **stub**, um modelo `pesquisa_leitura` | 1; emenda da SPEC §2, §3.2, §3.4 | o encanamento é provado sem LLM e sem custo | ADR-0022 (a)–(h) |
| 7 | Motor de verdade para as tarefas, atrás da interface do passo 6 | 6; S2 de verdade (a ADR-0018 é provisória e sem ferramenta) | precisa de um planejador que proponha `tool_call` | ADR-0022 (a) e (e) repetidos com o motor real |
| 8 | Classificador no turno de voz | 3 **aprovado pela regra de decisão** | só entra se o número disser que vale | SLO-5 mantido; `recall@5` publicado do turno real |
| 9 | Apps como MCP: **PDF** primeiro; depois **`web.capturar`** | 4 | PDF é leitura local sem egress; `web.capturar` é leitura com egress de GET | promoção + suíte de injection por app |
| 10 | Apps com envio (Discord, WhatsApp, redes sociais) | 4, 9 **e a F4** (confirmação de `egress_representacao` na UI) | enviar é representar o dono; a UI de confirmação é da F4 | confirmação no envio em 100% dos casos |
| 11 | Servidor de conversa (S-B): o Orchestrator delega uma tarefa ao Jarvis | 5, 6, 7; extensão Tasks do MCP | herda as regras de teto e de confirmação dos dois | ADR-0023 (S-B) + ADR-0022 com `source: mcp-in` |

Os passos 3, 4 e 6 não dependem um do outro e podem correr em paralelo por CLIs diferentes,
desde que cada um mexa só nos próprios arquivos.

## Dependências em uma linha cada

- **Tudo** depende do passo 1: capacidade sem manifesto não existe (§4).
- O **classificador no turno** (8) depende do número do harness (3), não de opinião.
- O **motor real das tarefas** (7) depende de um S2 com `tool_call`, que hoje não existe.
- **Envio por app** (10) depende da UI de confirmação da F4: não dá para confirmar por voz
  `egress_representacao` (§5.3).
- O **S-B** (11) depende da ADR-0022 inteira e da extensão Tasks, que ainda está em rascunho
  (`tasks.extensions.modelcontextprotocol.io`, acesso em 2026-10-16).
- A **caixa de areia** do passo 4 é a dependência de maior risco: se não rodar em algum sistema,
  aquele sistema fica só com servidor sem disco (ADR-0023, "Como invalidar").

## O que é do dono

Nada aqui está decidido. Cada linha diz as opções, o que o planejador **propõe** e o que fica
travado até a resposta.

| # | DECISÃO DO DONO | Opções | Proposta (não é decisão) | Trava |
|---|---|---|---|---|
| D1 | Aceitar a ADR-0022 (um oitavo processo, `tarefas`) | aceitar / pedir outro desenho | aceitar | passos 6, 7, 11 |
| D2 | Motor de raciocínio das tarefas | local / nuvem (o objetivo e o que a tarefa lê saem da máquina) | local quando existir; nuvem só com o egress mostrado na delegação | passo 7 |
| D3 | Como o Jarvis avisa que a tarefa terminou | falar na fronteira de turno / só na UI | falar na fronteira, com "não perturbe" que deixa só a UI | passo 6 |
| D4 | Tarefa com efeito no v1 | só leitura / leitura e escrita recuperável | só leitura no v1 | modelos de tarefa do passo 7 |
| D5 | Teto de tarefas simultâneas | 1 / 2 / outro | 2, a confirmar pela medição (a) da ADR-0022 | passo 6 |
| D6 | Aceitar a ADR-0023 e qual servidor real entra primeiro | qualquer servidor de leitura | o de teste + um de leitura que o dono use | passo 4 |
| D7 | Servidor local **sem** caixa de areia | nunca / aceitar por servidor, pelo nome | aceitar por servidor, só sem disco e sem rede | passo 4 nos sistemas sem caixa |
| D8 | Teto máximo de um app que chama o Jarvis | `jarvis` / `padrao` / `concedido` / `total` | até `concedido`; `total` por MCP fica de fora | passo 5 |
| D9 | Servidor do Jarvis por HTTP local | só `stdio` / também HTTP em 127.0.0.1 com token | só `stdio` na F2 | passo 5 |
| D10 | Quais apps podem chamar o Jarvis | Orchestrator / outros | Orchestrator primeiro | passo 5 |
| D11 | Conta do WhatsApp | WhatsApp Business Platform oficial / não ligar | só a oficial; sem cliente não oficial | passo 10 |
| D12 | Navegador do `web.capturar` | escolher depois de medir duas opções | medir duas, com licença conferida | passo 9 |
| D13 | Jev de nuvem | não / sim só com corpus sintético / sim também com a fala real | não por padrão; se sim, só sintético no harness | braço de nuvem do passo 3 e o passo 8 |
| D14 | Limiares da regra de decisão da ADR-0024 | os propostos ou outros | −1 p.p. de `recall@5` no máximo; −30% de tokens **ou** +5 p.p.; até 50 ms p95 local | passo 3 (têm de estar fechados antes de medir) |
| D15 | Orçamento do Jev na SPEC §5.1 (menos de 30 ms local) | manter / mudar | manter como alvo; o harness confirma ou derruba | passo 8 |

**Pendências antigas da SPEC §11 que também mexem na F2:** Q6 (modo de acesso com que o v1
começa — muda o que testar primeiro nos passos 4 e 5), Q7 (elevação no v1), Q9 (pastas suas que
devem entrar na lista de negação — vale também para o que nunca é montado na caixa de areia do
passo 4).

## Fatos que mudaram desde a SPEC e que o dono deve saber

- O MCP mudou de forma na revisão **2026-07-28**: sem estado, sem handshake, sem sessão; pedido do
  servidor ao cliente virou `input_required`; Tasks virou extensão; Roots, Sampling, Logging,
  HTTP+SSE e Dynamic Client Registration ficaram obsoletos com janela de 12 meses. O porto MCP da
  ADR-0010 continua de pé; o que muda é o SDK (`mcp` 2.x, MIT) e onde viaja o contador de saltos.
- O "Jev" de nuvem disponível hoje (`typesafe/jev-1.13`) leva cerca de 0,5 s, medido no
  Orchestrator em 6 telas, e a documentação consultada não diz o que a TypeSafe faz com o texto.
  A SPEC orçava o Jev local em menos de 30 ms.
- Servidor MCP local é processo do usuário e lê o que quiser: os níveis da ADR-0009 só o prendem
  com caixa de areia. A ADR-0010 não tinha tratado isso.
