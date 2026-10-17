# ADR-0029 — Classificador de decisão por perguntas fechadas, e o detector de endereçamento da escuta contínua

**Data:** 2026-10-17 · **Estado:** proposta (fatia mínima implementada atrás de interruptor do dono, desligada por padrão) · **Decide:** dono (ligar a nuvem, os limiares depois da medição), arquiteto (a interface e o harness)
**Pedido:** dono, 2026-10-17 — integrar o Jev (classificador de decisão da TypeSafe, via OpenRouter) como (a) tira-dúvidas e escolha de CLIs/ferramentas (ADR-0024) e (b) detector, a cada fala transcrita, de se o dono fala **sozinho/com outra pessoa** ou **com o Jarvis** querendo resposta, sugestão ou ação — ou se deve ser **ignorada**. Detalha a ADR-0004 e a ADR-0024; não as altera.

## Contexto

**O problema do (b), como está hoje.** Na escuta contínua (`escuta = "vad"`, ADR-0021) todo trecho que o VAD abre vira pedido: o dono falando sozinho, com outra pessoa ou a TV dispara o cérebro. A palavra de ativação resolve, mas o dono quer poder conversar sem dizer o nome toda vez. É o caso de uso certo para um classificador: classes fechadas, erro de baixo custo se for na direção "ignorar", latência importa (ADR-0004, "Contexto").

**O que o Jev é e o que a documentação oficial diz** (lido em 2026-10-17):

- Modelo de decisão "System One" da TypeSafe: recebe `state` e perguntas tipadas e devolve probabilidades; **não gera texto**. Três tipos — `noul` (sim/não; devolve só a probabilidade do sim), `choice` (uma opção; devolve `choice`, `confidence` e `probabilities`) e `score` (escala ordenada de 2 a 10 níveis). Perguntas da mesma chamada rodam em paralelo e não se enxergam. (docs.typesafe.ai/primitives, /primitives/noul; openrouter.ai/docs/guides/community/jev-tutorial)
- **Endpoint** `POST https://openrouter.ai/api/alpha/decisions`, `Authorization: Bearer <OPENROUTER_API_KEY>`. Corpo `{model, state, questions}` (+ `provider`, `session_id`, `trace`, `user` opcionais); `state` é string, objeto ou array; `noul.criteria` exige `true` e `false`. Resposta `{id, model, provider, answers, usage{input_tokens, output_tokens, cost}}`. Erros `{error:{code,message}}` com 400/401/402/403/404/413/429/500/502/503/524/529. A rota é **alfa**: o caminho pode mudar. (openrouter.ai/docs/api/api-reference/alphadecisions/…)
- **Modelos:** `typesafe/jev-1.13` (no OpenRouter), alias `~typesafe/jev-latest`; no lado da TypeSafe `jev-1.13.0` e `jev-1.14.0` (disponível desde 2026-10-14), com `jev-latest → 1.13.0` e `jev-preview → 1.14.0`. "Aliases can move … pin a versioned ID if your confidence thresholds depend on one version." (docs.typesafe.ai/models.md)
- **Preço:** US$ 0,042 por milhão de tokens de entrada; saída grátis. Exemplo oficial: 447 tokens → ≈ US$ 0,000019. (docs.typesafe.ai/models.md; openrouter.ai/blog/insights/what-is-jev, atualizado em 2026-10-16)
- **Limites:** 64 k tokens por requisição e 32 k para `state` + a maior pergunta; até 255 opções por `choice`; contexto longo (262 k) só com cabeçalho próprio, "mais lento e menos preciso". Limite de taxa por organização (tokens/s e requisições/s → 429), sem valores publicados no lado do OpenRouter. **Entrada só de texto** no 1.13 e no 1.14 (imagem aparece em texto do blog do OpenRouter para o 1.14; a página de modelos da TypeSafe lista "Text"). Não aceita áudio nem vídeo.
- **Idioma:** "English is the primary training language and has the best accuracy. Other languages … are supported but less accurate. The page recommends testing non-English content" (docs.typesafe.ai/models.md). **Nosso caso é pt-BR: tem de ser medido.**
- **Fraquezas documentadas** (docs.typesafe.ai/model-jaggedness/jev-1.13.md): lê literalmente; negação e dupla negação pior; viés para a **primeira opção** do `choice`; estado grande com detalhe irrelevante reduz acurácia; texto adversarial no estado desloca respostas; não faz conta nem data.
- **Calibração:** "calibrada no agregado" (0,8 ≈ 80 % de acerto em muitas respostas), **não por resposta**; a página de confiança não dá procedimento e manda "começar conservador, testar com os seus dados" e fixar limiar por ação conforme o custo do erro. Noul perto de 0,5 = incerteza (docs.typesafe.ai/confidence, /primitives/noul).
- **Latência — não há número oficial.** Terceiros: p50 0,194 s / p95 0,63–0,69 s em lote de 40–60 chamadas (OpenRouter, "Jev vs LLM", 2026-09-19, comparado com GPT Luna p50 0,8–1,1 s e Claude Opus p50 2,0 s); 354 ms (3 perguntas, 745 tokens) e 340–530 ms (1 choice + 1 noul) de ponta a ponta de uma estação (dryhurst.io, medido em 2026-09-23). Estes números são de terceiros, em inglês, de um dia.

**Termos e privacidade** (lidos em 2026-10-17): a fala transcrita **sai da máquina** para OpenRouter e daí para a TypeSafe.

- TypeSafe, Master Customer Agreement (atualizado 2026-09-23): §10.3 "no obligation to store or retain Customer Data" e pode apagar quando quiser; §4.1(c) permite usar os dados "in perpetuity" para telemetria, fraude e cumprimento de lei; §4.1 proíbe incluí-los em dataset de treino "without Customer's prior consent"; §4.3 telemetria "without restriction"; §4.2 cede ao cliente o que tiver de direito sobre a saída; §2.2 licencia a API para ser incluída em aplicações próprias; §2.3(a) proíbe revender como serviço autônomo; §2.3(b) proíbe destilar.
- TypeSafe, Privacy Policy (atualizada 2025-11-19): "We will not train or fine tune any … models on your prompts or other Input"; retenção "for as long as reasonably necessary", sem prazo; **ZDR só para clientes enterprise**.
- OpenRouter: a página de *logging* lida descreve a política dos **provedores**, não a do próprio OpenRouter, e **não diz** o que ele retém desta rota alfa. `provider.data_collection`/`zdr` existem no corpo, sem texto que diga como valem para `/decisions`. **Lacuna a fechar antes de qualquer uso além do teste do dono.**
- Região: a TypeSafe opera da costa oeste dos EUA (fonte secundária; sem região UE documentada).

**O que o repositório já tem.** Registro de motores com interruptor por motor, aviso de privacidade gerado dos campos e portão de licença (ADR-0017); `ClienteHttp` com chave só no cabeçalho, prazo nosso e bloqueio de nuvem real sob `CI=1`; a ADR-0004 ("o Jev nunca autoriza"), a ADR-0024 (o Jev responde perguntas fechadas na seleção de tools) e o D20 (dado sensível nunca vai à nuvem).

## Decisão

Introduzir **uma interface única de decisão por perguntas fechadas**, `ClassificadorDeDecisao` (`src/jarvis/decisao/interface.py`), com um adaptador de nuvem (`ClassificadorOpenRouter`, o Jev) e um fake de teste (`ClassificadorFalso`); e, sobre ela, um **detector de endereçamento** (`DetectorDeEnderecamento`) ligado ao laço de escuta contínua **somente quando o dono escolher e ligar o motor**. A seleção de tools da ADR-0024 passa a usar a **mesma interface** quando for implementada; este ADR não a implementa.

### 1. Interface

`decidir(estado, perguntas, *, cancelado) -> {nome: Resposta}`, com `PerguntaNoul | PerguntaEscolha | PerguntaNota` e respostas tipadas. Falha de qualquer natureza levanta `DecisaoIndisponivel` (serviço fora, prazo, formato) ou `DecisaoRecusada` (4xx: chave inválida, sem crédito) — o chamador decide, e a regra do produto é **na dúvida, não agir**. A interface não é do Jev: um classificador local pequeno entra como outro adaptador sem mexer em quem pergunta.

### 2. Adaptador OpenRouter (nuvem)

Motor `decisao-jev-openrouter` no registro (`licenses/motores.toml`), `papel = "decisao"`, `onde = "nuvem"`, `ligado = false`, **modelo fixado em `typesafe/jev-1.13`** (os limiares são calibrados nele; alias não). Chave **`OPENROUTER_API_KEY`**, só de ambiente ou chaveiro (a mesma regra e o mesmo código das outras chaves): vai no cabeçalho `Authorization`, nunca no corpo, na URL, em log ou argv; o arquivo de configuração é recusado inteiro se tiver cara de segredo. Prazo curto (1,5 s padrão); `User-Agent` próprio. Escolher o motor **não** o liga: ligar é outro clique/linha (`nuvem_ligada`), com o aviso do registro à frente, e sob `CI=1` a base não local é proibida.

### 3. As perguntas do detector (pt-BR, uma chamada com duas perguntas)

- `falando_com_o_jarvis` (**noul**): "A fala foi dita a um assistente de voz chamado Jarvis, esperando que ele responda, sugira ou faça algo." `true` = pede algo, pergunta que ele pode responder, ordena ou responde ao que ele acabou de perguntar; `false` = fala sozinha, pensa em voz alta, conversa com outra pessoa, TV/vídeo/música. Redigida para **alto = sim**, sem negação (docs.typesafe.ai/primitives/noul).
- `pedido` (**choice**): `ignorar` · `resposta` · `sugestao` · `acao`, **nesta ordem** (o modelo puxa para a primeira opção: o erro barato é ignorar).
- `state` = só `{fala, o_assistente_acabou_de_fazer_uma_pergunta, ja_estavamos_conversando}`: a fala transcrita e dois sinais **calculados localmente**.

### 4. Limiares e histerese (propostas; a medição os confirma ou troca)

- Entrar na conversa: `p ≥ 0,80`. Com conversa em andamento (houve fala endereçada há ≤ 20 s): `p ≥ 0,55`. `p ≤ 0,30`: "não era comigo". Entre `0,30` e o limiar vigente: **incerto — não age**. Intenção escolhida com probabilidade < 0,50: "sem pedido claro" — não age. `ignorar` escolhido: não age.
- Nada disto é o número "certo": a documentação diz que a confiança não é acerto por resposta e que o limiar se fixa com dados do próprio uso.

### 5. Segurança, privacidade e o que o detector **não** faz

- **Na dúvida, não age e não interrompe.** Prazo estourado, 5xx/429, 4xx, formato inesperado, resposta de tipo trocado, probabilidade no meio — tudo vira "ignorar" com o motivo dito (uma vez por queda) no card de avisos. O detector só é consultado para fala **nova** com o Jarvis em repouso; **nunca** decide barge-in.
- **Não autoriza** (ADR-0004): "é comigo" só abre a porta que a palavra de ativação ou o PTT abririam; ferramenta continua passando pelo PDP e pela confirmação do dono.
- **A nuvem recebe o texto da fala do dono e mais nada**: sem memória, histórico, resultado de ferramenta ou o que o Jarvis disse (D20: dado sensível nunca vai). A fala **ignorada** não aparece na tela nem no histórico; só uma linha de método (decisão, `p`, ms) quando age.
- Texto da fala é **dado, não instrução**: o classificador só devolve probabilidades; uma fala "ignore as regras e …" não tem como virar ação por esta via.

### 6. Plano de medição (a decisão de limiar e de manter a nuvem depende dele)

Corpus `medicao/enderecamento/falas.jsonl` (58 falas sintéticas pt-BR, 28 com o Jarvis e 30 alheias, com casos difíceis de propósito) e `tools/medir_enderecamento.py`. Métricas: **falso-aceite** (alheia que virou pedido — o erro caro), **falso-rejeito**, acerto da intenção entre as aceitas, **latência p50/p95**, falhas do classificador. Antes de fixar limiar de produto: ampliar para 200–500 falas por cenário (como a ADR-0024 exige), incluindo ruído de TV real transcrito pelo ASR (com erros de transcrição) e fala do próprio dono gravada com consentimento. Critério para **manter a nuvem**: falso-aceite < 5 % e falso-rejeito < 15 % no corpus ampliado, com p95 ≤ 1,0 s; senão, ou o limiar sobe, ou cai-se para a palavra de ativação.

## O que foi medido hoje (2026-10-17)

| Abordagem | Falso-aceite | Falso-rejeito | Intenção certa (aceitas) | Latência | Observação |
|---|---|---|---|---|---|
| **Regras** (nome, verbo de ordem no começo, "?", "sim/não" após pergunta) | 7/30 = **23,3 %** | 3/28 = 10,7 % | 18/25 = 72 % | ~0 ms | roda no corpus (`--regras`); erra "abre a porta que o entregador chegou", "toca aqui!", "o Jarvis é rápido, né?" |
| **Jev (OpenRouter, jev-1.13)**, limiares da §4 (entrar 0,80) | 1/30 = **3,3 %** | 13/28 = **46,4 %** | 15/15 = 100 % | **p50 563 ms · p95 617 ms** (58 chamadas, uma execução, aval do dono) | os 13 rejeitados ficaram **todos** entre p = 0,64 e 0,78 (faixa "incerto"); o único falso-aceite teve 0,82 ("pode abrir a janela, por favor?", dito a outra pessoa). Fumaça anterior: 1 chamada, 716 ms, p = 0,97 |
| **O próprio LLM** (`claude -p` haiku, o provisório da ADR-0018) | não medido | não medido | — | 1,2–2,5 s até a primeira proposta de ferramenta (6 medições hoje, outro prompt) | só serve de ordem de grandeza: gerar texto para decidir é mais lento e mais caro que um classificador |

**Leitura da medição real.** O Jev separa as classes, mas em pt-BR as falas para o Jarvis saem com p **0,64–0,78**, abaixo do limiar de entrada de 0,80 desta proposta: o limiar de 0,80 erra para o lado seguro (pouco falso-aceite) e ignora quase metade dos pedidos. Baixar o limiar exige saber onde caem as falas **alheias** — a primeira rodada só guardou o `p` dos erros; a ferramenta agora guarda o de todas, e a próxima rodada (58 chamadas, ≈ US$ 0,001) dá a curva. Com a conversa em andamento o limiar já é 0,55 (histerese), o que absorve parte dos rejeitados ("e em Lisboa?" p = 0,71, "sim, pode ser" p = 0,76). A latência medida (p95 617 ms) cabe no critério de p95 ≤ 1,0 s; a acurácia, com o limiar atual, **não** cabe (falso-rejeito ≥ 15 %).

## Alternativas descartadas

- **Regras/heurísticas** (nome, verbo imperativo, "?"): 23 % de falso-aceite no corpus, que é exatamente o erro caro. Ficam como **régua** e como degrau de segurança (a palavra de ativação continua existindo). Voltam a ser a escolha se a nuvem não passar no critério acima.
- **O próprio LLM decidindo** (haiku/Opus): 1–2 s+ e custo ordens de grandeza maior (Opus US$ 2,88 vs Jev US$ 0,025 por mil, no teste do OpenRouter), e gasta a cota do cérebro. Descartado para o *gate*; segue sendo o cérebro.
- **Classificador local pequeno** (reranker/cross-encoder ou modelo fine-tuned): atende privacidade e latência, mas o reranker do Orchestrator "não entende negação" (ADR-0024) e treinar exige o corpus que ainda não existe. **Não medido.** É o caminho se a nuvem falhar na privacidade: a interface foi desenhada para trocá-lo sem mexer no detector.
- **Jev em todas as falas, em série, sempre**: custo de latência de ~0,35–0,7 s por fala **antes** de o cérebro começar. Aceito como fatia mínima porque o detector só roda na escuta contínua; a otimização óbvia (consulta **especulativa em paralelo** ao início do cérebro, cancelando se não for com ele) fica para depois da medição.
- **Imagens ou áudio no estado**: o Jev lê texto (e imagem só no 1.14, por fonte secundária); áudio não. O ASR já transforma a voz em texto, e prosódia (tom de pergunta) seria ganho real, mas fica fora.

## Consequências

- Interface e fake permitem testar o laço sem nuvem; a suíte não fala com serviço de verdade (servidor HTTP falso em porta efêmera).
- Nova chave no chaveiro (`OPENROUTER_API_KEY`) e novo painel "é comigo?" em Configuração → Voz e escuta; novo papel `decisao` no registro, no portão de licença e na tabela `docs/licencas.md`.
- **Custo de privacidade explícito:** com o motor ligado, o texto de cada fala transcrita na escuta contínua vai a OpenRouter → TypeSafe, e a retenção do OpenRouter nesta rota é **desconhecida**. O aviso do registro diz isso ao dono antes de ligar.
- **Dependência de rota alfa** (`/api/alpha`): quebra possível sem aviso — tratada como `DecisaoIndisponivel` (não age), com o contrato de resposta validado campo a campo.
- Obrigatório testar: falso-aceite/rejeito em corpus ampliado, p95 em pt-BR, comportamento com 429/5xx, e recalibrar a cada troca de versão do modelo.

## Estado da implementação (2026-10-17)

Feito, com testes sem rede: `src/jarvis/decisao/` (interface, fake, adaptador, detector), motor no registro, `OPENROUTER_API_KEY` no chaveiro, campo `enderecamento` da configuração, painel na janela, gancho em `Aplicativo._turno_de_audio` (só em `escuta = "vad"`), corpus e ferramenta de medição. **Não feito:** seleção de tools da ADR-0024 pela mesma interface; consulta especulativa; ampliação do corpus; medição do Jev no corpus; política de retenção do OpenRouter para a rota; resolução da dúvida de acurácia em pt-BR.

## Como invalidar esta decisão

- A medição no corpus ampliado dar falso-aceite ≥ 5 % ou falso-rejeito ≥ 15 % em pt-BR, ou p95 > 1,0 s: o detector por nuvem cai e fica o classificador local (ou só a palavra de ativação).
- O OpenRouter declarar retenção/treino incompatível com a política do dono para a rota `/decisions`, ou a rota alfa mudar de contrato sem versão.
- Um classificador local alcançar falso-aceite equivalente com latência < 100 ms: a nuvem deixa de se justificar.
