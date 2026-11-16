# Parâmetros do modelo: prova com modelo real (ADR-0071, Fase 3)

opus-parametros, 2026-11-16. OK do dono para gastar: Claude pelo plano dele (o `claude -p` que o
Jarvis já usa, Haiku, sem chave) e o DeepSeek V4.1 Flash pelo OpenRouter
(`deepseek/deepseek-v4.1-flash`, chave só no ambiente, o provedor ligado só em memória para esta
avaliação). Cada modelo fez UMA passada dos 40 casos; depois, só os casos que falharam foram
reavaliados, depois de cada conserto. Ritmo baixo (2–3 s entre casos).

**Nada real foi tocado.** `tools/avaliar_parametros.py` roda o cérebro de produção (plano
obrigatório, objetivo formulado, conferência de cópia e de alvo, PDP, gestor de tarefas, motor do
objetivo) contra uma página FALSA do WhatsApp (Mãe, Pai, Bruno, Carla, Ana Paula, Ana Clara,
Trabalho, Vó Lúcia), um livro de memória em RAM e corpos de sistema simulados. Corpus:
`tools/corpus_parametros.toml`.

## Resumo

| | Claude (Haiku, claude -p) | DeepSeek V4.1 Flash (OpenRouter) |
|---|---:|---:|
| acerto na 1ª passada | 27/40 | 35/40 |
| acerto depois dos consertos (só os que falharam, reavaliados) | 39/40 | 38/40 |
| 1º token do turno, p50 / p90 (ms) | 3991 / 7312 | 1791 / 2884 |
| 1ª fala do turno, p50 / p90 (ms) | 6331 / 10181 | 1455 / 2111 |
| total do caso (turno + tarefa), p50 / p90 (ms) | 7408 / 29971 | 4170 / 14206 |
| 1º delta por chamada ao motor, p50 / p90 (ms) | 2882 / 3738 | 429 / 630 |
| plano presente (casos) | 30/40 | 40/40 |
| plano cobrado | 0 | 0 |

O **caso do print** («o contato da minha mãe é literalmente mãe salve para não esquecer depois»)
passou nos dois modelos desde a 1ª passada: o plano separou «guardar» de «abrir»,
`memoria.lembrar` gravou o trecho «o contato da minha mãe é literalmente mãe» (ativa, pela regra da
ADR-0026), e nada foi aberto.

## O que a 1ª passada achou, e o conserto (sem regex nem frase fixa)

1. **`alvo` e `ref` juntos (Claude: 0/8 nos envios).** Com as descrições novas, o modelo manda
   `{"alvo": "Mãe", "ref": "m1.0", "esperado": "Mãe"}`, e o corpo recusava com «um dos dois». O
   subagente desistia depois de repetir o erro. **Conserto no contrato:** com os dois, o `ref`
   vence e o `alvo` vira o nome conferido no rótulo, como o `esperado`
   (`navegador/ferramentas._alvo_ou_ref`/`_esperado`). Depois disso, os 11 envios e cliques que
   falhavam passaram.
2. **App não dito («manda pro bruno que…», «abre o grupo do trabalho»).** O modelo perguntava em que
   app, ou procurava janelas. **Conserto no prompt:** «Mensagem, contato, conversa ou grupo sem app
   dito é no WhatsApp Web dele» (o mesmo padrão `REDE_PADRAO` do código).
3. **Promessa sem ação (DeepSeek: «Vou abrir o WhatsApp Web e procurar o grupo.» e nenhuma
   ferramenta).** **Conserto genérico, como evento:** se o PLANO do próprio modelo cita uma
   ferramenta do catálogo e a rodada acaba sem proposta, ele recebe `NOTA_DO_PLANO_SEM_ACAO` (uma
   vez) e decide: propor ou dizer por que não. A trilha conta `plano_sem_acao`.
4. **Avaliador mais fiel (não é o modelo):** as memórias fixas passaram a ir ao turno como no app; a
   página falsa ganhou `page.eval`, a navegação conferida e o «enviar»/Enter no campo do chat; uma
   busca (`memoria.buscar`, `web.buscar`) pode citar as palavras do dono sem contar como cópia.
5. **Bug de produção achado no caminho:** `provedores/stream.py`. Quando quem consome fecha a
   conexão no fim do SSE, o fio leitor levava `AttributeError` (o `http.client` sem `fp`), com um
   traceback no stderr a cada resposta. Agora encerra calado.

## O que continua falhando, e por quê

- **`ambigua-sem-pontuacao`** («fala com o bruno a carla vem amanhã»), nos dois modelos: os dois
  leram «diga ao Bruno que a Carla vem amanhã» e mandaram. É a leitura mais plausível. A
  expectativa do corpus (perguntar) é discutível e fica registrada como falha, sem forçar o prompt.
- **`contato-literal-errado`** («abre a conversa mãe salve para não esquecer depois»), só no
  DeepSeek: na 1ª passada ele abriu a conversa «Mãe» e perguntou o que salvar; na reavaliação, não
  abriu nada, mas também não perguntou. Nenhuma das vezes usou a frase como nome (a cópia não
  aconteceu); o que falta é perguntar.

## O interruptor do raciocínio escondido (Claude, mesmos 10 casos, com e sem)

| | com raciocínio escondido (1ª passada) | sem (`MAX_THINKING_TOKENS=0`) |
|---|---:|---:|
| acerto | 10/10 | 10/10 |
| 1º delta por chamada, p50 (ms) | 2 572 | 2 260 (−12%) |
| 1º delta por chamada, p90 (ms) | 3 947 | 2 798 (−29%) |
| tokens de saída, total | 8 140 | 5 157 (−37%) |
| 1º token do turno, mediana (ms) | 3 683 | 3 694 |

**Decisão, com número:** sem o raciocínio escondido no modo rápido de esforço baixo (o do dono).
O acerto ficou igual, a cauda de latência e os tokens caíram, e o plano visível, que é obrigatório,
faz o papel do raciocínio. O `pensar`, e um preset com esforço `medium` ou mais, continuam pensando
(`ESFORCOS_SEM_RACIOCINIO`). A amostra é pequena (10 casos, 25–31 chamadas) para poupar a cota do
Claude, que estava em ~85% da semana.

## Latência

O DeepSeek V4.1 Flash é mais rápido em tudo: 1º delta por chamada p50 429 ms contra 2 882 ms; 1ª
fala p50 1,5 s contra 6,3 s. Isso porque o `claude -p` sobe um processo por chamada (piso de ~1,7 s,
f2-02) e pensa. Escolher o provedor do cérebro é do dono (ADR-0056, presets); o `conversa-openrouter`
**não** está no `nuvem_ligada` dele, e este trabalho não o ligou.

## Por caso

| caso | tipo | Claude 1ª → final | DeepSeek 1ª → final | o que falhou (1ª passada) |
|---|---|---|---|---|
| print-do-dono | memoria | ✅ → ✅ | ✅ → ✅ | — |
| print-com-virgula | memoria | ✅ → ✅ | ✅ → ✅ | — |
| salva-contato-mae | memoria | ✅ → ✅ | ✅ → ✅ | — |
| anota-irmao | memoria | ✅ → ✅ | ✅ → ✅ | — |
| lembra-cafe | memoria | ✅ → ✅ | ✅ → ✅ | — |
| nao-esquece-reuniao | memoria | ✅ → ✅ | ✅ → ✅ | — |
| guarda-vo | memoria | ✅ → ✅ | ✅ → ✅ | — |
| salva-ruido | memoria | ✅ → ✅ | ✅ → ✅ | — |
| envio-mae-te-amo | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Mãe»; não mandou nada a «Mãe» |
| manda-bruno-atraso | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Bruno»; não mandou nada a «Bruno» |
| manda-irmao-sem-nome | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Bruno»; não mandou nada a «Bruno» |
| fala-pra-carla-sem-pontuacao | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Carla»; não mandou nada a «Carla» |
| whatsapp-pai-literal | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Pai»; não mandou nada a «Pai» |
| diz-vo-saudade | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Vó Lúcia»; não mandou nada a «Vó Lúcia» |
| envio-ruido-stt | envio | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Bruno»; não mandou nada a «Bruno» |
| clica-bruno | clique | ✅ → ✅ | ✅ → ✅ | — |
| abre-conversa-mae | clique | ✅ → ✅ | ✅ → ✅ | — |
| abre-trabalho | clique | ❌ → ✅ | ❌ → ✅ | a conversa aberta é «», não «Trabalho»; cópia da fala em memoria.buscar: «grupo do trabalho» |
| abre-conversa-vo | clique | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Vó Lúcia» |
| salva-e-manda | envio_e_memoria | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Mãe»; não mandou nada a «Mãe» |
| anota-e-abre | envio_e_memoria | ❌ → ✅ | ✅ → ✅ | a conversa aberta é «», não «Carla» |
| ana-ambigua | pergunta | ✅ → ✅ | ✅ → ✅ | — |
| joao-inexistente | pergunta | ✅ → ✅ | ❌ → ✅ | não perguntou ao dono |
| clica-inexistente | pergunta | ✅ → ✅ | ✅ → ✅ | — |
| ambigua-sem-pontuacao | pergunta | ❌ → ❌ | ❌ → ❌ | abriu conversa sem saber qual: ['Bruno']; mandou mensagem num pedido ambíguo; mandou para quem não devia: ['Bruno']; não perguntou ao dono |
| contato-literal-errado | pergunta | ✅ → ✅ | ❌ → ❌ | abriu conversa sem saber qual: ['Mãe']; não perguntou ao dono |
| abre-discord | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| abre-discord-e-lembra | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| fecha-steam | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| busca-flamengo | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| youtube-gatos | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| site-g1 | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| volume | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| que-horas | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| lembra-o-que-eu-disse | ferramenta | ✅ → ✅ | ✅ → ✅ | — |
| bom-dia | conversa | ✅ → ✅ | ✅ → ✅ | — |
| obrigado | conversa | ✅ → ✅ | ✅ → ✅ | — |
| piada | conversa | ✅ → ✅ | ✅ → ✅ | — |
| pergunta-geral | conversa | ✅ → ✅ | ✅ → ✅ | — |
| ruido-palavra-trocada | envio | ❌ → ✅ | ❌ → ✅ | a conversa aberta é «», não «Bruno»; não mandou nada a «Bruno» |

Os relatórios brutos de cada passada (com as ações e os erros de cada caso) ficaram no scratchpad
da sessão; para refazer: `uv run --frozen python -m tools.avaliar_parametros --motor real [--provedor
conversa-openrouter --modelo deepseek/deepseek-v4.1-flash] [--caso ID …] --json saida.json`.

## Conjunto de validação (falas que o ajuste não viu)

O ajuste de esquemas e prompt olhou os 40 casos que ele mesmo mede, então o 39/40 podia ser
sobreajuste. `tools/corpus_validacao.toml` traz 21 falas novas: nomes com instrução misturada,
«salva/guarda/anota/lembra», ruído de STT sem pontuação, ambíguo e inexistente (devem virar
pergunta), duas intenções, «manda/avisa/fala pro X que…» e clicar num item da lista. Elas foram
escritas depois do ajuste, e os alvos foram fixados e **commitados antes** de qualquer passada
(`f962ca3`). Foi UMA passada por modelo, e **nada foi ajustado depois**.

| | Claude (Haiku, claude -p) | DeepSeek V4.1 Flash (OpenRouter) |
|---|---:|---:|
| **acerto na validação** | **21/21 (100%)** | **15/21 (71%)** |
| acerto no corpus de ajuste (depois dos consertos) | 39/40 | 38/40 |
| 1º token do turno, p50 / p90 (ms) | 4 020 / 8 796 | 2 607 / 20 852 |
| 1ª fala do turno, p50 / p90 (ms) | 4 275 / 9 193 | 2 683 / 21 010 |
| 1º delta por chamada, p50 / p90 (ms) | 2 416 / 3 419 | 484 / 4 318 |
| total do caso, p50 / p90 (ms) | 16 823 / 45 808 | 6 923 / 39 449 |

| caso | tipo | Claude | DeepSeek | o que falhou (DeepSeek) |
|---|---|---|---|---|
| v-salva-nome-irma | memoria | ✅ | ✅ | — |
| v-guarda-aniversario | memoria | ✅ | ✅ | — |
| v-lembra-estacionamento | memoria | ✅ | ✅ | — |
| v-anota-chefe | memoria | ✅ | ✅ | — |
| v-manda-vo-domingo | envio | ✅ | ✅ | — |
| v-avisa-pai-carro | envio | ✅ | ❌ | não mandou nada a «Pai»; a conversa aberta é «», não «Pai» |
| v-abre-e-manda-carla | envio | ✅ | ❌ | não mandou nada a «Carla»; a conversa aberta é «», não «Carla» |
| v-pai-sem-pontuacao | envio | ✅ | ❌ | não mandou nada a «Pai» |
| v-fala-mae-comi | envio | ✅ | ✅ | — |
| v-grupo-falta | envio | ✅ | ✅ | — |
| v-clica-grupo | clique | ✅ | ✅ | — |
| v-chat-irmao | clique | ✅ | ✅ | — |
| v-conversa-ana-clara | clique | ✅ | ✅ | — |
| v-conversa-avo | clique | ✅ | ✅ | — |
| v-ana-ambigua | pergunta | ✅ | ✅ | — |
| v-rodrigo-inexistente | pergunta | ✅ | ❌ | não perguntou ao dono |
| v-endereco-desconhecido | pergunta | ✅ | ❌ | não perguntou ao dono |
| v-dentista-e-manda | envio_e_memoria | ✅ | ❌ | não mandou nada a «Carla»; a conversa aberta é «», não «Carla» |
| v-spotify-e-anota | ferramenta | ✅ | ✅ | — |
| v-previsao | ferramenta | ✅ | ✅ | — |
| v-conversa-solta | conversa | ✅ | ✅ | — |

**Leitura honesta:**

- **Claude (o motor do dono): sem sinal de sobreajuste.** Ele acerta 21/21 em falas novas, contra
  39/40 no ajuste.
- **DeepSeek: caiu de 95% para 71%.** Nenhuma falha foi de parâmetro copiado (a cópia da fala não
  apareceu em nenhum argumento). As causas:
  1. **Resposta vazia** (`v-avisa-pai-carro`, `v-abre-e-manda-carla`, `v-rodrigo-inexistente`): o
     turno ou a tarefa termina sem texto e sem ferramenta. É coerente com o `<</pensar>>` solto que
     ele já tinha escrito na fala do corpus de ajuste: o protocolo de TEXTO (`<<pensar>>`,
     `<<ferramenta>>`) que o Jarvis usa para todo motor não combina com o jeito de esse modelo
     separar raciocínio e resposta.
  2. **Pede confirmação para enviar** («Confirma que eu envio?», `v-dentista-e-manda`) e
     **seleciona sem digitar** (`v-pai-sem-pontuacao`). A persona diz «pedido direto é para
     executar», mas a regra padrão do dono põe «enviar mensagem» entre o que pede o sim, e ele
     obedece à regra.
  3. `v-endereco-desconhecido`: ele **perguntou** («Me passa o endereço que eu mando pro
     Bruno.»), mas sem «?», e o verificador conta isso como falha. É rigidez do verificador; fica
     registrado sem reajuste.
- **Consertos propostos, na causa, para medir de novo NO CORPUS DE AJUSTE (não neste):**
  (a) para provedores compatíveis com OpenAI (OpenRouter), usar o `tool_calls` e o campo de
  raciocínio nativos do provedor em vez do protocolo de texto. É o que tira a resposta vazia e o
  marcador solto. É mudança de arquitetura do motor (ADR nova), não de prompt. (b) a regra do sim
  ao enviar é do dono e conflita com «pedido direto é para executar»: o sim já é pedido pelo
  sistema (PDP/risco no clique de enviar), não pelo modelo. Mudar o texto da regra é decisão do
  dono. (c) o verificador pode aceitar pergunta sem «?»; isso se decide antes da próxima passada,
  não depois desta.
