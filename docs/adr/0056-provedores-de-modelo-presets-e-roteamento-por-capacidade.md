# ADR-0056 — Provedores de modelo, presets e roteamento por capacidade

**Data:** 2026-10-29 · **Estado:** aceita (implementada nas fatias B–E — `33f67bf`, `2952dc8`, `1b5fb61`, `8a31b9e` e a janela —, provada só com provedores falsos, servidor HTTP local e executáveis falsos; o uso real é do dono) · **Decide:** dono (o pedido: mais provedores, todos os modelos, esforço, presets, troca por voz e roteamento), arquiteto (a interface, o registro, o formato dos presets, as regras de fallback e de segurança)
**Pedido:** dono, 2026-10-29 — "hoje a escolha de modelo é por TIPO (ex.: Haiku) e limitada. Quer mais autonomia: (1) listar TODOS os modelos que o provedor disponibiliza (consultando o endpoint de modelos do provedor quando existir, com cache e fallback estático […]); (2) poder escolher entre provedores: OpenAI, Codex (via a CLI/assinatura quando aplicável), OpenCode (provider/CLI), OpenRouter e outros routers, Groq (que tem modelos com visão), além do Anthropic/Claude que já existe; (3) escolher MODELO + EFFORT […] e SALVAR COMO PRESET numa lista (nome, provedor, modelo, effort, papel: cérebro / Jev-classificador / visão / resumo), escolher o preset ativo pela GUI e por voz ('usa o preset rápido'); (4) capacidades por modelo (visão, tools, contexto, custo/latência quando o provedor informa) mostradas na escolha e usadas para ROTEAR (ex.: pedido com imagem vai para um modelo com visão)."

## Contexto

O que existe hoje, lido no código em 2026-10-29 (`97c7b63`):

- O cérebro tem **dois** motores (`jarvis.voz.s2_provisorio.nomes_de_gerador`): `eco` (local, o
  padrão) e `claude` (a CLI `claude -p`, ADR-0018/0025). O modelo é um texto livre
  (`modelo_do_s2`, vai em `--model`) que a janela não mostra; o esforço é fixo por modo
  (`ESFORCO_POR_MODO`: `low` no rápido, `high` no pensar).
- O Jev (ADR-0029) roda pelo OpenRouter com o modelo fixado em `typesafe/jev-1.13`, porque os
  limiares foram calibrados nele.
- ASR e TTS já têm escolha de provedor e de modelo (ADR-0017, emenda "Escolha de modelo"), com um
  registro de motores (`licenses/motores.toml`) que barra o que não tem licença e termos lidos na
  origem, e a nuvem desligada até o dono ligar na janela.
- O motor de conversa é uma fronteira estreita (`jarvis.s2.motor.MotorDeConversa`: `gerar` em
  deltas, cancelável, sem estado), e ferramenta é **proposta** pelo protocolo de texto
  (ADR-0038) — quem decide é o PDP, que lê o tier do catálogo e nada do modelo.

## Decisão

### 1. A interface de provedor (`jarvis.provedores.interface`)

Um provedor faz três coisas, e nenhuma decide segurança:

| método | o que faz | falha |
|---|---|---|
| `listar()` | os modelos **de agora**, pelo endpoint ou comando oficial | `ListagemIndisponivel` |
| `Modelo.capacidades` | visão, ferramentas, esforços aceitos, contexto, saída máxima, preço por milhão de tokens, latência — o que o provedor informa | campo `None` = **não informado**, nunca "não" |
| `motor(modelo, esforco, capacidades)` | um `MotorDeConversa` com o modelo e o esforço — o cérebro não muda | `ProvedorIndisponivel` |

O esforço tem um vocabulário só, do menor para o maior: `none`, `minimal`, `low`, `medium`,
`high`, `xhigh`, `max`. Cada provedor traduz para o parâmetro dele (`--effort`,
`reasoning_effort`, `reasoning.effort`, `model_reasoning_effort`, `--variant`). O esforço do preset
vale no modo rápido; o modo `pensar` (ADR-0025, regra 4) sobe para ao menos `high` e nunca desce.
Quando o modelo diz quais aceita, vale o mais perto por baixo do pedido.

### 2. O registro de provedores (`licenses/provedores-de-modelo.toml`)

Um `[[motor]]` por provedor, **no formato e com as regras** de `licenses/motores.toml`, conferidas
pela mesma função (`jarvis.voz.registro.exigir_motor`, com outro `arquivo`): licença do cliente
permissiva, `fonte` e `data_de_acesso` sempre, os quatro campos de termos para quem é de nuvem
(campo vazio barra, salvo o dono aceitar em `nuvem_sem_termos`), e **nuvem desligada** até o id
estar em `nuvem_ligada`. Os ids têm o prefixo `conversa-` e não colidem com os da voz. O que este
registro acrescenta:

- `modelos` é a **lista estática** de cada provedor, conferida na página oficial com data — o
  último recurso do catálogo, não um limite do que o dono escolhe;
- `[[capacidade]]` diz o que um grupo de modelos faz (`padrao` estilo `fnmatch`, com `fonte` e
  `data`) quando o provedor não informa — a OpenAI, por exemplo, lista modelos sem dizer qual vê.
  O que o provedor informa vence o registro.

Ao contrário da voz (`exigir_modelo`), **o modelo não precisa estar numa lista para ser
chamado**: a lista de um provedor de LLM tem centenas de itens e muda toda semana, e o termo de
serviço é do provedor, não do modelo. O id só precisa ter a forma de um id (`FORMA_DO_ID`: sem
espaço, aspas nem controle, porque vai num argumento de processo ou no corpo do pedido); quem diz
se ele existe é o provedor, e a recusa dele volta ao dono como recusa.

`s2 = "claude"` no `jarvis-voz.toml` conta como `conversa-claude-cli` ligado: era a escolha do
dono de mandar a conversa para a CLI do Claude antes desta ADR, e nada muda para ele.

### 3. A lista de modelos: ao vivo, guardada ou do registro (`jarvis.provedores.catalogo`)

1. guardada e fresca (menos de 24 h): vale a guardada, sem rede;
2. senão, ao vivo, e o resultado é guardado em `$XDG_CACHE_HOME/jarvis/modelos/<id>.json`;
3. a ao vivo falhou (sem chave, sem rede, sem o comando): vale a guardada, de qualquer idade, com
   o aviso de quando ela é;
4. nem isso: vale a do registro, com a data da conferência.

Listar **não passa pelo interruptor da nuvem**: não leva nada do dono — só a chave, no
cabeçalho —, como a lista de vozes da ElevenLabs (ADR-0017, emenda). Sob `CI=1`, a base não local
é recusada antes do socket. O cache não tem segredo nem dado do dono, e o que vem do provedor
passa pela forma (id) e pela limpeza (nome sem controle, com teto) na ida e na volta do disco.

### 4. Os provedores

| id | lista | chama | chave | visão e esforço |
|---|---|---|---|---|
| `conversa-eco` | fixo | repete o que o dono disse | — | — |
| `conversa-claude-cli` | registro (a CLI não tem comando de listar; com `ANTHROPIC_API_KEY`, `GET /v1/models`, que traz `capabilities.image_input` e os esforços) | `claude -p` em stream (ADR-0018) | a assinatura do dono | todos veem; `--effort low…max` |
| `conversa-openai` | `GET /v1/models` (só ids; capacidades pelo registro) | Chat Completions em SSE | `OPENAI_API_KEY` | `reasoning_effort` |
| `conversa-openrouter` | `GET /api/v1/models` (contexto, preço, `input_modalities`, `supported_parameters`) | Chat Completions em SSE, com `provider.data_collection = "deny"` | `OPENROUTER_API_KEY` (a do Jev) | `reasoning.effort` |
| `conversa-groq` | `GET /openai/v1/models` (`context_window`) | Chat Completions em SSE | `JARVIS_GROQ_API_KEY` (a do ASR) | visão nos modelos que a página de visão lista; `reasoning_effort` por modelo |
| `conversa-codex-cli` | `codex debug models` (o catálogo da CLI) | `codex exec --json`, sem shell e sem busca na web | o login do dono (`codex login`) | `model_reasoning_effort`; imagem por `-i` |
| `conversa-opencode-cli` | `opencode models` (1.x) | `opencode run --format json`, com as permissões da CLI negadas; a 2.x é reconhecida pela versão e recusada com a frase do que fazer | os provedores que o dono configurou no OpenCode | `--variant` |
| `conversa-compativel-local` | `GET {base}/models` | Chat Completions (Ollama, LM Studio) | — | pelo registro, quando houver |
| `conversa-compativel-nuvem` | `GET {base}/models` | Chat Completions (Together, DeepInfra e outros) | `JARVIS_COMPATIVEL_API_KEY` | termos desconhecidos: só com `nuvem_sem_termos` |

Regras que valem para os quatro de API: o prompt de sistema e a conversa vão como o cérebro monta
para todo motor (o catálogo de ferramentas pelo protocolo de texto), a imagem só vai a modelo que
vê, e o raciocínio que volta (`delta.reasoning`, `reasoning_content`, `reasoning_details`, ou um
bloco `<think>` no meio do texto) vira `Raciocinio` — **nunca** vai à voz nem à tela (ADR-0031).

As duas CLIs novas rodam como a do Claude (ADR-0018): processo avulso por pedido numa pasta
vazia, a conversa pelo `stdin`, morto no cancelamento, e o ambiente do filho **sem** as chaves que
o Jarvis conhece (o login delas é delas). O Codex roda com `--sandbox read-only`,
`approval_policy="never"`, `features.shell_tool=false`, `web_search="disabled"` e `--ephemeral`. O
OpenCode 1.x roda com as permissões da CLI negadas pelo `OPENCODE_CONFIG_CONTENT` (`*`, `bash`,
`edit`, `webfetch`, `websearch`); a 2.x trocou permissões, credenciais e a sintaxe do variante
(`modelo#variante`) sem documentar a saída do `run --format json`, então fica recusada até haver
leitura confirmada dela. Se a CLI não está instalada, não tem login ou é de uma versão que o Jarvis
não sabe ler, o motor responde com a frase do que fazer, sem tentar outra coisa. Item de
ferramenta da própria CLI na saída aborta o pedido.

### 5. Presets (`jarvis.provedores.presets`)

O padrão mora no repositório (`src/jarvis/provedores/presets.toml`); o do dono, em
`~/.config/jarvis/presets.toml` (a pasta do `jarvis-voz.toml`), e vence quando existe — o mesmo
desenho das regras do dono (ADR-0047). Formato:

```toml
versao = 1

[ativos]
cerebro = "rápido"
jev = "jev"
visao = "visão groq"
resumo = ""

[[preset]]
nome = "rápido"
papel = "cerebro"
provedor = "conversa-openai"
modelo = "gpt-6-luna"
esforco = "low"
```

- **Sem segredo.** Campo com nome de segredo ou valor com forma de chave (`sk-`, `sk-proj-`,
  `sk-or-`, `sk-ant-`, `gsk_`, `xi-`) recusa o arquivo inteiro; as chaves continuam no ambiente e
  no chaveiro, onde estão hoje.
- **Cérebro ativo vazio** = o da configuração (`s2`, `modelo_do_s2`). O preset que representa isso
  só existe em memória e nunca é gravado: até o dono escolher, nada muda.
- A janela lista provedor → modelos (com as capacidades e de onde a lista veio) → esforço (só os
  que o modelo aceita, quando ele diz) → nome e papel, grava o arquivo do dono e escolhe o ativo.
- A voz troca o ativo de um papel pela ferramenta `modelo.preset` ("usa o preset rápido"):
  tier moderado, desfazível por `acao.desfazer`, só com o que o dono disse neste turno (nunca a
  partir de conteúdo lido). Ela **não liga nuvem**: preset de provedor desligado é recusado com a
  frase de onde se liga.

### 6. Roteamento por capacidade

O cérebro continua com um motor só: um roteador (`MotorDosPresets`) que, a cada pedido, monta o
motor do preset ativo do cérebro. Com imagem no contexto (a tela da aba, ADR-0032):

1. o modelo do cérebro vê → vai a ele;
2. senão, o preset ativo de `visao` vê → aquele pedido vai a ele (o nome na tela e no livro é o
   dele);
3. senão, a imagem não vai: o pedido segue só com texto, como hoje com um motor que não vê.

"Vê" é `Capacidades.visao is True`: não informado não conta. O roteador declara `aceita_imagem`
só quando há rota que vê, e o cérebro, que já pergunta isso ao motor, não captura à toa.

### 7. Regras de fallback

- **Lista:** guardada fresca → ao vivo → guardada velha → registro, sempre dizendo qual vale.
- **Motor:** o preset que não pode rodar (nuvem desligada, falta chave, falta a CLI, falta login)
  **não troca de provedor sozinho** — trocar é mandar a conversa a outra empresa, e isso é escolha
  do dono. O turno termina com o motivo dito em voz e na tela; o dono escolhe outro preset.
- **Visão:** sem rota que vê, o pedido vai sem a imagem (nunca a um provedor que o dono não ligou).
- **Jev:** preset de Jev indisponível é `DecisaoIndisponivel`, e a regra do produto continua:
  na dúvida, não agir (ADR-0029).

### 8. Regras de segurança

1. **O que vem do provedor é dado.** Nome, descrição e preço de modelo passam pela forma e pela
   limpeza, aparecem na tela como texto puro e nunca vão ao prompt. A resposta do modelo segue o
   caminho de sempre: proposta pelo protocolo, decisão do PDP.
2. **O tier de cada ferramenta não muda com o modelo.** O PDP lê o catálogo; nada em
   `jarvis.provedores` importa `jarvis.politica`, `jarvis.policy` ou `jarvis.executor` (teste de
   fronteira). Trocar de modelo não afrouxa nem aperta uma confirmação.
3. **Nada de enviar segredo.** A chave só no cabeçalho; o corpo é conferido antes de sair; presets
   e cache sem segredo; argumento de processo conferido (`proibir_segredo_em_argv`); o ambiente das
   CLIs sem as chaves do Jarvis.
4. **Jev na nuvem só com o necessário.** O preset do Jev muda o id do modelo e nada mais: o estado
   enviado continua o que o detector de endereçamento monta (ADR-0029).
5. **Nuvem só liga pela janela, com o aviso** montado do registro (ADR-0017, políticas 2 e 3) —
   nunca por voz, por preset ou por argumento de ferramenta.
6. **No OpenRouter**, o pedido leva `provider.data_collection = "deny"`: só vai a provedor que não
   guarda o que recebe.

## Alternativas descartadas

- **Um `[[motor]]` por modelo, como a Groq na voz.** Funciona com dois modelos de ASR; com as
  centenas do OpenRouter, o registro viraria uma cópia velha do catálogo deles.
- **Uma biblioteca de abstração (LiteLLM e afins).** Traz dezenas de dependências para fazer o que
  aqui são dois formatos (Chat Completions e as CLIs) e não sabe do nosso portão de termos.
- **Ferramenta nativa (`tool_calls`) por provedor.** Cada um tem o seu formato e as suas exceções
  (a OpenAI exige a Responses API para ferramenta em alguns modelos novos); o protocolo de texto
  (ADR-0038) já funciona com todos e passa pelo mesmo PDP.
- **Cair para outro provedor quando o escolhido falha.** Mandaria a conversa a uma empresa que o
  dono não escolheu para aquele pedido.

## Consequências

- O dono escolhe qualquer modelo que o provedor lista, salva combinações com nome e troca pela voz.
- Pedido com a tela da aba chega a um modelo que vê, mesmo com um cérebro que não vê.
- Cada provedor novo é uma linha no registro, uma classe e as regras de capacidade com fonte.

## Riscos

- **As CLIs mudam depressa.** A 2.x do OpenCode saiu no dia desta ADR e trocou a API do servidor,
  as permissões e o armazenamento de credenciais; o formato do `--format json` não é documentado.
  O leitor é defensivo e, sem texto reconhecível, diz que não entendeu a saída.
- **`codex debug models` é comando de depuração.** Se a saída mudar, a lista cai no registro.
- **Capacidade "não informada"** deixa o roteamento conservador: um modelo que vê, mas que nem o
  provedor nem o registro declaram, não recebe imagem.

## Teste de aceite

(a) listar com cache, fallback e forma, contra provedor falso; (b) cada provedor de API contra um
servidor HTTP local (`CI=1`), com a chave só no cabeçalho, o raciocínio fora da fala, o esforço no
campo certo e o cancelamento no meio do stream em até `PRAZO_DE_CANCELAMENTO_S`; (c) as CLIs com um
executável falso que confere o `argv` e o ambiente; (d) presets: ler, gravar, recusar segredo,
trocar por voz e desfazer; (e) a janela offscreen escolhendo e salvando um preset; (f) o roteador
mandando o pedido com imagem ao preset de visão. **Nenhum teste fala com provedor de verdade nem
gasta cota.**

## Como invalidar esta decisão

Se um provedor passar a cobrar ou a guardar dados por modelo de um jeito que o aviso por provedor
não represente, ele volta ao desenho de um `[[motor]]` por modelo. Se o protocolo de texto errar
mais que a ferramenta nativa num provedor (medido no harness de ferramentas), aquele provedor ganha
ferramenta nativa atrás da mesma proposta ao PDP.

## Fontes (acesso em 2026-10-29)

- Claude Code: <https://code.claude.com/docs/en/cli-reference> (`--model`, `--effort low…max`,
  `claude auth status`), <https://code.claude.com/docs/en/model-config> (apelidos),
  <https://code.claude.com/docs/en/data-usage>, <https://code.claude.com/docs/en/legal-and-compliance>.
- Anthropic API: <https://platform.claude.com/docs/en/api/models/list> (`capabilities`, esforços),
  <https://platform.claude.com/docs/en/build-with-claude/effort>,
  <https://platform.claude.com/docs/en/build-with-claude/vision>,
  <https://www.anthropic.com/legal/commercial-terms>.
- OpenAI: <https://developers.openai.com/api/reference/resources/models/methods/list>,
  <https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create>
  (`reasoning_effort`, `image_url`, `stream_options`),
  <https://developers.openai.com/api/docs/guides/reasoning>,
  <https://developers.openai.com/api/docs/guides/your-data>.
- OpenRouter: <https://openrouter.ai/docs/api/api-reference/models/get-models>,
  <https://openrouter.ai/docs/guides/best-practices/reasoning-tokens>,
  <https://openrouter.ai/docs/api/reference/streaming>,
  <https://openrouter.ai/docs/guides/routing/provider-selection> (`data_collection`, `zdr`),
  <https://openrouter.ai/docs/guides/privacy/data-collection>.
- Groq: <https://console.groq.com/docs/api-reference>, <https://console.groq.com/docs/vision>,
  <https://console.groq.com/docs/reasoning>, <https://console.groq.com/docs/your-data>,
  <https://console.groq.com/docs/legal/services-agreement>.
- Codex CLI: <https://learn.chatgpt.com/docs/non-interactive-mode>,
  <https://learn.chatgpt.com/docs/developer-commands?surface=cli>,
  <https://learn.chatgpt.com/docs/config-file/config-reference>,
  <https://learn.chatgpt.com/docs/auth>, <https://learn.chatgpt.com/docs/agent-approvals-security>.
- OpenCode: <https://opencode.ai/docs/cli/>, <https://opencode.ai/docs/permissions/>,
  <https://opencode.ai/docs/config/>, <https://opencode.ai/v2/docs/models/>,
  <https://opencode.ai/v2/docs/permissions/>, <https://opencode.ai/legal/terms-of-service>,
  <https://github.com/anomalyco/opencode/releases>.
- Compatíveis: <https://docs.together.ai/docs/openai-api-compatibility>,
  <https://docs.deepinfra.com/chat/overview>, <https://docs.ollama.com/api/openai-compatibility>,
  <https://lmstudio.ai/docs/developer/openai-compat>.

## Emenda de 2026-10-30 — ligar na janela vale na hora, e cada bloqueio diz o quê, por quê e como

**Pedido:** dono, 2026-10-30 — tentou ligar o Groq num preset e o app «não deixou por causa de
outros modos», sem explicar.

**Causa medida** (trilha dele, 30/10 10:55–10:58: 5 turnos em `fim: erro`, 0 ferramenta, 38–1226
ms; `jarvis-voz.toml` com `conversa-groq` em `nuvem_ligada` gravado às 10:56, a conversa aberta
às 10:55): a janela liga a nuvem **só para ela** (`Ponte.ligarNuvem` muda a configuração da janela),
e a conversa aberta montou os `Provedores` com a `nuvem_ligada` do começo e nunca mais releu —
enquanto os presets são relidos a cada pedido. O preset do Groq passava a ser o ativo e o portão o
recusava («motor 'conversa-groq' é de nuvem e está desligado … (ADR-0017 …)»), embora a janela
mostrasse o Groq ligado. A frase ia só para a tela (a ADR dizia «em voz e na tela»).

**Decisão:**

1. **Nuvem viva.** `FonteDePresets.nuvem` devolve `(ligados, sem_termos)` da configuração **viva**
   da janela; a janela a passa à conversa junto com a fonte de presets. O roteador
   (`MotorDosPresets.acompanhar_a_nuvem`) lê a cada pedido: ligar vale no pedido seguinte, sem
   reabrir; desligar tira do cache o motor do provedor. A troca pela voz (`TrocaPorVoz`) lê o mesmo.
   Sem janela (terminal), vale o que a conversa leu ao abrir. Continua: **nunca troca de provedor
   sozinho** e a voz nunca liga nuvem.
2. **Bloqueio em português** (`jarvis.provedores.bloqueio`): cada recusa do portão (nuvem
   desligada, falta de chave, licença, modelo ou esforço inválido, provedor indisponível) vira
   **o que** bloqueou, **por que** a trava existe e **como** destravar (o caminho na janela ou a
   frase «usa o preset claude»), sem citar ADR; a versão curta vai à voz e a inteira à tela e ao
   card. A chave é dita pelo nome da variável, nunca pelo valor.
3. **Assistente curto na janela** (`PonteDeModelos.conferir`, no painel «resposta»): provedor →
   chave (da sondagem que já roda numa thread: existe/não existe) → nuvem ligada nesta conversa →
   modelo → esforço que o modelo aceita → papel (visão só com modelo que vê) → salvar, cada passo
   com ✓ ou o que falta. O Groq com visão (`qwen/qwen3.8-27b`) entra num preset de visão em seis
   toques: Groq → li o aviso — ligar → modelo → papel visão → nome → salvar → ativar.

**Testes:** `tests/unit/gui/test_assistente_de_preset.py` (janela offscreen: cada passo e a frase
dele; ligar na janela com a conversa aberta muda o roteador na hora, e desligar também; os seis
bloqueios com o quê/por quê/como; o painel desenha o passo da nuvem ✗ → ✓) e
`tests/unit/provedores/test_roteador.py` (a recusa fala curto e mostra inteiro).

**Não provado:** o Groq de verdade com a chave do dono (nenhuma chamada saiu nos testes) e o painel
na tela dele.
