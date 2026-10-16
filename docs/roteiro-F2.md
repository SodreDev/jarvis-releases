# Roteiro da F2 — ordem sugerida, dependências e o que é do dono

**Data:** 2026-10-16 · **Autor:** planejador · **Estado:** proposta para o dono, **revista em
2026-10-16** depois das respostas do dono (ver "Histórico" no fim)
**Base:** SPEC §9 (F2); ADRs 0022 (subagentes), 0023 (MCP cliente e servidor), 0024 (seleção de
tools), todas propostas e emendadas em 2026-10-16; ADRs 0025 (cérebro único, stream e fila de
avisos) e 0026 (ferramentas de memória), propostas. **DECISÃO DO DONO** marca só o que é dele:
o que ele já respondeu está escrito como resposta; o que falta, com as opções e a proposta.

## O que o dono decidiu em 2026-10-16

- **Aviso:** o Jarvis recebe a notificação e decide sozinho se avisa; nunca corta fala; o aviso
  espera o TTS parar ou a próxima mensagem do dono e vai junto com ela; pode virar card.
- **Motor das tarefas:** configurável (local ou nuvem, por tarefa e cenário, com egress
  mostrado), não fixo.
- **Um cérebro** com conversa contínua: interrompível, rápido, "pensar" só quando precisa.
- **Streaming:** começa a falar enquanto gera; interrompido, para de falar e de gerar.
- **Memória:** histórico de conversa e contexto; ler mensagens passadas, gravar, alterar, criar
  grafo e memória, e lembrar.

Consequência para a ordem: **o cérebro vem antes das ferramentas.** Stream S2→TTS cancelável e
histórico entram antes de subagentes e de MCP, porque as duas coisas dependem deles (a tarefa
avisa pela fila; o MCP manda pedidos do servidor remoto para a mesma fila) e porque é o que o dono
vai ouvir.

## O que a F2 já pede (SPEC §9)

Manifesto e SDK de tool, PDP com os 4 modos, auditoria encadeada, Jev de cenário/intenção,
recuperação híbrida de tools, 15–25 capacidades **só de leitura ou transitórias** das famílias do
v1, porto MCP com promoção de manifesto, simulador de tools e corpus de 200–500 enunciados por
cenário. Aceite: `recall@5` por família; 100% das chamadas validadas por schema; nenhuma ação por
frase; suíte de prompt injection com saída de MCP e rug-pull; replay de sessão.

Parte disso já existe desde a F0 (`src/jarvis/politica/pdp.py`, `auditoria.py`, `modos.py`,
`src/jarvis/manifesto/` com validador, lint e codegen, `catalogo/` com três manifestos).

**Esta revisão puxa para a F2 uma parte da F3:** a gravação do histórico e as tools de memória
por pedido do dono (fatias M1 e M2 da ADR-0026), com os gates da §6.6 que as protegem. O grafo
por tool (M3) e a escrita por iniciativa do Jarvis (M4) continuam na F3.

## Ordem sugerida

| # | Passo | Depende de | Por que nesta posição | Aceite |
|---|---|---|---|---|
| 1 | **ADR-0025, stream cancelável:** interface do motor de conversa, motor stub e `claude -p` em `stream-json`, `fatiar` incremental, `ResponseChunk`, TTS consumindo pedaços, cancelamento do pedido ao motor, conversa do `s2` só com o tocado | F1 (TTS cancelável, epoch) | é o que o dono pediu primeiro e o que tudo abaixo usa para falar | ADR-0025 (a), (b), (g), (h) |
| 2 | **Harness do SLO-5 por trecho** (montagem, 1ª fronteira, TTS, dispositivo) | 1 | sem o número por trecho, a escolha do motor (passo 5) é opinião | CSV em `docs/medicoes/` com `n`, hardware e commit |
| 3 | **ADR-0026 M1, histórico:** turno gravado com o tocado e cifrado, `memoria.buscar_historico`, `memoria.ler_mensagem`, apagar turno e sessão em cascata | 1; manifesto e PDP da F0 | o turno do Jarvis só existe com o tocado depois do 1; é o "lembra do que eu disse" | ADR-0026 (a)–(f); gates 2, 3, 5 e 6 |
| 4 | **ADR-0025, fila de avisos:** `Notification`, `NotificationRelease`, card `notificacoes`, com um produtor de teste | 1 | a tarefa (10) e o MCP (12) só têm como avisar com isto pronto | ADR-0025 (d), (e), (f) |
| 5 | **Motor real do cérebro, com `tool_call`** (API ou local), medido pelo harness do 2 | 1, 2; D18 | o `claude -p` não cabe no SLO-5 (medido) e não tem tool | ADR-0025 (c); 1ª fronteira dentro de ~600 ms de p95 ou a ponte da regra 8 |
| 6 | Completar o SDK de tool, o simulador de tools e as 15–25 capacidades de leitura/transitórias | F0 (PDP, manifesto) | base de toda tool; mexe em arquivos diferentes do 1–4 e pode correr em paralelo desde já | o da F2 (b) e (c) |
| 7 | **ADR-0026 M2:** `memoria.lembrar`, `memoria.atualizar`, `memoria.esquecer(retratar)`, `memoria.buscar` sem grafo, por pedido do dono | 3, 5, 6 | precisa de motor com `tool_call` e do SDK | ADR-0026 (d), (e), (g); gates 1 e 4 |
| 8 | Corpus da F2: enunciados por cenário e por família, com negativos e ambíguos — primeiro **sintético** | 6 | serve aos passos 9 e 14 e ao aceite (a) da F2 | corpus versionado em `corpus/` |
| 9 | **ADR-0024, harness de seleção com quatro braços** (C0 catálogo fixo em cache, recuperação, D-B, D-A) | 5, 6, 8; reranker da ADR-0011 | o tempo até a 1ª fronteira com cache só existe com o motor real | ADR-0024 (a)–(e) e a métrica da emenda |
| 10 | **ADR-0022, `tarefas` com motor stub**, publicando `Notification` | 4, 6; emenda da SPEC §2, §3.2, §3.4 | o aviso já tem para onde ir | ADR-0022 (a)–(c), (e)–(h); ADR-0025 (d) com tarefas reais |
| 11 | Motor das tarefas configurável (local/nuvem por tarefa e cenário) | 5, 10 | mesmo tipo de motor do cérebro | ADR-0022 (a) e (e) com o motor real; egress no card em 100% das delegações |
| 12 | **ADR-0023, cliente:** servidor `stdio` de teste + um real de leitura | 4, 6; caixa de areia por sistema | o que o servidor remoto pede vai para a fila do 4 | ADR-0023 (a)–(d), (h), (i) |
| 13 | **ADR-0023, servidor:** `jarvis mcp --cliente orchestrator` | 6, 12 | mesma regra de teto e de segredo | ADR-0023 (e)–(g) |
| 14 | Classificador no turno | 9 **aprovado pela regra de decisão** | só entra se o número disser que vale | SLO-5 mantido; `recall@5` publicado do turno real |
| 15 | Apps como MCP: **PDF**, depois **`web.capturar`** | 12 | PDF é leitura local sem egress | promoção + suíte de injection por app |
| 16 | Apps com envio (Discord, WhatsApp, redes sociais) | 12, 15 **e a F4** | enviar é representar o dono | confirmação no envio em 100% |
| 17 | Servidor de conversa (S-B) como tarefa | 10, 11, 13; extensão Tasks | herda teto e confirmação; nunca entra na conversa do dono | ADR-0023 (S-B) + ADR-0022 com `source: mcp-in` |
| — | ADR-0026 M3 (grafo por tool) e M4 (escrita autônoma) | F3 | dependem dos 6 gates | aceite da F3 |

**Paralelo possível**, cada CLI nos próprios arquivos: o 6 desde já, junto com o 1; o 3 e o 4
juntos, depois do 1.

## Dependências em uma linha cada

- **Falar enquanto gera** (1) depende só do que a F1 entregou (TTS cancelável, epoch); o que
  falta é o `fatiar` incremental e o motor em stream.
- **Histórico** (3) depende do 1: sem stream não há "texto tocado" da resposta interrompida.
- **Motor real do cérebro** (5) depende do número do harness (2) e da escolha do dono (D18).
- **Tarefa** (10) depende da fila (4): o aviso do jeito que o dono decidiu não existe sem ela.
- **Seleção de tools** (9) depende do motor real (5): a regra de decisão agora mede tempo até a
  1ª fronteira com cache, e o cache é do motor.
- **Envio por app** (16) depende da UI de confirmação da F4.
- A **caixa de areia** do 12 continua sendo a dependência de maior risco do lado MCP.

## O que é do dono

| # | DECISÃO DO DONO | Opções | Proposta (não é decisão) | Trava |
|---|---|---|---|---|
| D1 | Aceitar a ADR-0022 (um oitavo processo, `tarefas`) | aceitar / pedir outro desenho | aceitar | 10, 11, 17 |
| D2 | ~~Motor de raciocínio das tarefas~~ **respondida em 2026-10-16:** configurável, local ou nuvem por tarefa e cenário, egress mostrado | — | desenho na emenda da ADR-0022: a configuração do dono escolhe, nunca o LLM; local por padrão | — |
| D3 | ~~Como o Jarvis avisa~~ **respondida em 2026-10-16:** ele decide; fila até o piso livre ou a próxima mensagem; card | — | desenho na ADR-0025, regras 11–15 | — |
| D4 | Tarefa com efeito no v1 | só leitura / leitura e escrita recuperável | só leitura no v1 | modelos de tarefa do 11 |
| D5 | Teto de tarefas simultâneas | 1 / 2 / outro | 2, a confirmar pela medição (a) da ADR-0022 | 10 |
| D6 | Aceitar a ADR-0023 e qual servidor real entra primeiro | qualquer servidor de leitura | o de teste + um de leitura que o dono use | 12 |
| D7 | Servidor local **sem** caixa de areia | nunca / aceitar por servidor, pelo nome | aceitar por servidor, só sem disco e sem rede | 12 nos sistemas sem caixa |
| D8 | Teto máximo de um app que chama o Jarvis | `jarvis` / `padrao` / `concedido` / `total` | até `concedido`; `total` por MCP fica de fora | 13 |
| D9 | Servidor do Jarvis por HTTP local | só `stdio` / também HTTP em 127.0.0.1 com token | só `stdio` na F2 | 13 |
| D10 | Quais apps podem chamar o Jarvis | Orchestrator / outros | Orchestrator primeiro | 13 |
| D11 | Conta do WhatsApp | WhatsApp Business Platform oficial / não ligar | só a oficial | 16 |
| D12 | Navegador do `web.capturar` | escolher depois de medir duas opções | medir duas, com licença conferida | 15 |
| D13 | Jev de nuvem | não / sim só com corpus sintético / sim também com a fala real | não por padrão | 9 e 14 |
| D14 | Limiares da regra de decisão da ADR-0024 | os propostos ou outros | −1 p.p. de `recall@5` no máximo; −30% de tokens **ou** +5 p.p.; até 50 ms p95 local; **e** (emenda) no máximo +50 ms na mediana até a 1ª fronteira contra o C0 | 9 (fechar antes de medir) |
| D15 | Orçamento do Jev na SPEC §5.1 (menos de 30 ms local) | manter / mudar | manter como alvo | 14 |
| D16 | Aceitar a ADR-0025 (cérebro único, stream, fila) | aceitar / pedir outro desenho | aceitar | 1, 2, 4, 5 |
| D17 | Aceitar a ADR-0026 (ferramentas de memória) | aceitar / pedir outro desenho | aceitar | 3, 7 |
| D18 | Motor padrão do **cérebro** (a conversa) | local / API de nuvem / os dois, escolhidos por cenário como nas tarefas | medir os dois no harness do 2 e escolher pelo número; local por padrão se couber em ~600 ms de p95 até a 1ª fronteira | 5 |
| D19 | Retenção do histórico de conversa | 30 / 90 dias / até o dono apagar | 90 dias para turno que nenhuma memória cita; o citado vive enquanto a memória viver | 3 |
| D20 | Histórico e memória podem ir para motor de **nuvem**? | não / só `historico` / também `sensivel` | `sensivel` nunca (ADR-0026 regra 8); `historico` desligado por padrão, o dono liga | 3, 5, 7 |
| D21 | "Lembrar" no pedido quer dizer **gravar**? | gravar / recuperar | gravar (`memoria.lembrar`); recuperar é `memoria.buscar`, que o planejador acrescentou | 7 |
| D22 | Limiares de naturalidade da ADR-0025 | os propostos ou outros, depois de ouvir | ponte aos 700 ms sem 1ª fronteira; no máximo 1 aviso falado a cada 2 min; piso livre = 1,5 s sem fala depois do fim do playback | 1, 4 |

**Pendências antigas da SPEC §11 que também mexem na F2:** Q6 (modo de acesso com que o v1
começa), Q7 (elevação no v1), Q9 (pastas da lista de negação).

## Fatos que o dono deve saber

- **O S2 provisório não cabe no SLO-5.** Medido hoje (`docs/medicoes/s2-provisorio-primeira-fala.md`,
  `n` pequeno): o `claude -p` em stream chega à 1ª fronteira de fala em 992 ms de mediana no melhor
  caso (`haiku`, processo contínuo) e em 1388 ms com um processo por pergunta; o modelo padrão da
  conta passa de 2 s. Com os 116 ms do TTS, o melhor caso já passa do p95 de 900 ms do SLO-5. Ao
  testar no `jarvis-voz`, o atraso que o dono ouvir é do motor, não da voz.
- **A sessão da CLI guarda o texto gerado, não o tocado.** No modo contínuo, interromper funciona
  (8 ms) e o processo sobrevive, mas a CLI "lembra" do que gerou até o corte. Por isso a conversa é
  do Jarvis e o motor é sem estado (ADR-0025).
- **Mudar a lista de tools derruba o cache de prefixo inteiro** (documentação de *prompt caching*,
  acesso em 2026-10-16). Selecionar tools por turno pode economizar tokens e custar tempo até a
  primeira fala; por isso o harness da 0024 mede também o catálogo inteiro fixo.
- O MCP mudou de forma na revisão **2026-07-28** (sem estado, sem sessão; Tasks virou extensão).
- O "Jev" de nuvem (`typesafe/jev-1.13`) leva cerca de 0,5 s, medido no Orchestrator em 6 telas.
- Servidor MCP local é processo do usuário e lê o que quiser: os níveis da ADR-0009 só o prendem
  com caixa de areia.

## Histórico

- **2026-10-16, versão 1** (`9dc3a33`): ordem SDK de tool → corpus → harness de seleção (0024) →
  MCP cliente e servidor (0023) → tarefas (0022) → motor das tarefas → classificador → apps →
  S-B. D1–D15 abertas.
- **2026-10-16, versão 2** (esta): o dono respondeu D2 e D3 e deu os requisitos do cérebro. Entraram
  as ADRs 0025 e 0026; o stream cancelável, o harness do SLO-5, o histórico e a fila de avisos foram
  para a frente (passos 1–4), seguidos do motor real do cérebro (5). O SDK de tool continua cedo
  (6), em paralelo. Seleção (0024) foi para depois do motor real, porque passou a medir tempo até
  a fala com cache. Tarefas (0022) e MCP (0023) foram para depois da fila. Acrescentadas D16–D22.
