# Laço canônico: prova com modelo real (ADR-0072, Fase C)

2026-11-16. Uma passada por modelo, ferramentas FALSAS (a página falsa do WhatsApp do avaliador, a
máquina falsa de janelas e processos dos testes de fechar/encerrar, memória num livro em memória),
nada do navegador, das contas, do microfone nem do áudio do dono. Chave só por ambiente, nunca lida.
Os alvos de cada conjunto foram commitados ANTES da passada: `tools/corpus_laco.toml` (30 falas
novas, `9ce94e6`) e `tools/corpus_laco_validacao.toml` (6 falas, `31c0ec4`). O avaliador é
`tools/avaliar_parametros.py` (`--laco`, `--laco-validacao`); conferido com motores falsos (ideal
30/30, o «copião» do bug do print 0/30).

Motores: **Claude** pelo `claude -p` (o padrão da CLI do dono, protocolo de texto) e **DeepSeek V4.1
Flash** pelo OpenRouter, agora com **chamada nativa** (`tools`/`tool_calls`, ADR-0072).

## Resumo

| conjunto | Claude | DeepSeek | antes (ADR-0071): Claude / DeepSeek |
|---|---:|---:|---:|
| ajuste (40) | **37/40** | **38/40** | 39/40 / 38/40 |
| validação (21) | **20/21** | **21/21** | 21/21 / 15/21 |
| novo do laço (30) | **28/30** | **30/30** | — |
| separado do conserto (6) | **5/6** | **6/6** | — |

**Leitura honesta:**

- **DeepSeek, com a chamada nativa, deixou de falhar pelo protocolo.** Validação de 15/21 para
  21/21; as três respostas vazias e o `<</pensar>>` solto da rodada anterior sumiram. O 1º delta
  por chamada ficou em ~0,5 s (p50) e ~0,8 s (p90). As duas falhas no ajuste são de entendimento,
  as mesmas do Claude (abaixo).
- **Claude oscilou um a dois casos para baixo** (ajuste 39→37, validação 21→20). Com uma passada
  não dá para separar ruído de efeito. Nenhuma falha dele foi parâmetro copiado da fala, ação antes
  do modelo ou plano faltando: o plano apareceu sozinho nos 21 casos da medição do item 5 e a
  barreira que saiu teria disparado 0 vez.
- **O sim só no destrutivo funcionou nos dois:** nenhum envio pediu o sim (`sem_pergunta` em todos
  os envios do conjunto novo), e matar/encerrar pediu o sim sem executar antes (3/3 nos dois).

## O que falhou, e o que foi feito

| caso | modelo | o que aconteceu | causa | o que foi feito |
|---|---|---|---|---|
| `l-lembrete-varal` (1ª passada) | os dois | `timer.alarm.set` não estava ligada no avaliador; o DeepSeek procurou e disse que não dava, o Claude ofereceu outro caminho | **avaliador** (sem agenda) | agenda de produção numa pasta temporária (`5c12871`); o caso, refeito uma vez: ✅ nos dois |
| (avaliador caiu) | DeepSeek | o modelo chamou `tarefa.iniciar` e o corpo simulado não trazia `tarefa_id` | **avaliador** | `tarefa.*`/`timer.*` rodam de verdade no avaliador (`fcb78b0`); os dois casos que não rodaram, rodados uma vez |
| fala com `<ferramenta>` | Claude | «<ferramenta> Não consegui…», «<ferramenta>Anotado…» na voz | **protocolo de texto**: a marca com um colchete passava como fala | o leitor reconhece a forma (`19f2dc4`), sem frase nem regra de conteúdo |
| `l-mae-mandou`, `v-avisa-pai-carro` (item 5) | Claude | buscou na memória e perguntou/ofereceu abrir o WhatsApp | **prompt**: a persona mandava buscar em `memoria.*` quando o dono pergunta o que foi dito | persona: o que alguém mandou, ou contato fora da memória, se vê no WhatsApp (`9719a0b`); reavaliado no conjunto separado: Claude 5/6, DeepSeek 6/6 |
| `l-fecha-aquele` | Claude | «fecha aquele programa lá» → fechou a janela em foco; o sim foi pedido e nada rodou | **alvo × regra do dono**: a regra «resolva pelo contexto (o que está em foco…)» autoriza; o alvo fixado pedia pergunta | fica registrado, sem reajuste; decidir antes da próxima passada se «aquele» + janela em foco é pergunta ou ação |
| `ambigua-sem-pontuacao`, `contato-literal-errado` | os dois | mandou/abriu em vez de perguntar | **entendimento**: a fala admite uma leitura plausível e o modelo a seguiu | sem conserto nesta rodada |
| `envio-ruido-stt` | Claude | `browser.launch` negado pelo PDP («navegador não liberado» no avaliador), abriu pelo `sites.open` e desistiu | o avaliador não configura navegador para `browser.launch` | registrado |
| `v-rodrigo-inexistente` | Claude | perguntou sem «?» | **verificador** rígido (já registrado na ADR-0071) | sem reajuste |
| `lv-ana-clara-sai` | Claude | o subagente terminou com resposta vazia depois de `browser.tabs` | modelo | registrado |

## Latência (p50 / p90, ms)

| | Claude ajuste | Claude validação | Claude laço | DeepSeek ajuste | DeepSeek validação |
|---|---:|---:|---:|---:|---:|
| 1º token do turno | 2 958 / 5 206 | 2 629 / 4 544 | 2 657 / 4 102 | 1 798 / 2 667 | 1 270 / 4 194 |
| 1ª fala do turno | 3 945 / 5 968 | 3 981 / 17 580 | 3 800 / 6 564 | 1 811 / 2 714 | 1 314 / 4 286 |
| 1º delta por chamada | 2 082 / 2 955 | 2 038 / 3 130 | 2 044 / 2 855 | 533 / 793 | 501 / 719 |
| total do caso (turno + tarefa) | 10 838 / 41 144 | 14 736 / 53 962 | 11 392 / 48 471 | 6 392 / 23 947 | 7 619 / 17 656 |

O DeepSeek no conjunto do laço não gerou a tabela de latência (o avaliador caiu no caso 29 antes do
relatório; os 28 casos anteriores estão no log, todos ✅).

## Por caso — conjunto novo do laço

| caso | tipo | Claude | DeepSeek |
|---|---|---|---|
| l-contato-mae-apelido | memoria | ✅ | ✅ |
| l-lembra-remedio | memoria | ✅ | ✅ |
| l-anota-reuniao | memoria | ✅ | ✅ |
| l-pediatra | memoria | ✅ | ✅ |
| l-nao-gosta-de-audio | memoria | ✅ | ✅ |
| l-mae-atrasado | envio, sem pedir o sim | ✅ | ✅ |
| l-bruno-jogo | envio, sem pedir o sim | ✅ | ✅ |
| l-trabalho-reuniao | envio, sem pedir o sim | ✅ | ✅ |
| l-carla-bolo-sem-pontuacao | envio, fala sem pontuação | ✅ | ✅ |
| l-pai-presente | envio redigido | ✅ | ✅ |
| l-abre-ana-paula | clique lendo antes | ✅ | ✅ |
| l-entra-trabalho | clique lendo antes | ✅ | ✅ |
| l-chat-irmao | clique pela memória fixa | ✅ | ✅ |
| l-carla-respondeu | abre, lê e responde | ✅ | ✅ |
| l-mae-mandou | abre, lê e responde | ❌ | ✅ |
| l-trabalho-horario | abre, lê e responde | ✅ | ✅ |
| l-pesquisa-jogo | delegação e retorno | ✅ | ✅ |
| l-receita-bolo | delegação e retorno | ✅ | ✅ |
| l-ana-almoco | pergunta (ambíguo) | ✅ | ✅ |
| l-joao-nao-existe | pergunta (não existe) | ✅ | ✅ |
| l-apaga-aquilo | pergunta, sem agir | ✅ | ✅ |
| l-fecha-aquele | pergunta, sem agir | ❌ | ✅ |
| l-mata-discord | pede o sim (matar) | ✅ | ✅ |
| l-encerra-steam | pede o sim (encerrar) | ✅ | ✅ |
| l-kate-inteiro | pede o sim (encerrar) | ✅ | ✅ |
| l-abre-spotify | sem pedir o sim | ✅ | ✅ |
| l-volume-vinte | sem pedir o sim | ✅ | ✅ |
| l-abre-youtube | sem pedir o sim | ✅ | ✅ |
| l-lembrete-varal | sem pedir o sim (refeito com a ferramenta ligada) | ✅ | ✅ |
| l-conversa-elogio | conversa | ✅ | ✅ |

Apagar arquivo ficou fora: `files.move_to_trash` tem manifesto e não tem corpo nesta versão, então
a ferramenta não chega ao modelo.

## O que só a máquina do dono prova

O navegador real com a extensão e o WhatsApp de verdade, as contas, o microfone e o áudio, e o
`claude -p` dele com a conta e a cota dele. Nada disto foi tocado. O roteiro está em
[teste-real-dono.md](../teste-real-dono.md).
