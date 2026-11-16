# ADR-0071 — O Jarvis decide os parâmetros: entender antes de agir, objetivo formulado, alvo conferido

**Data:** 2026-11-16 · **Estado:** aceita (implementada e testada só com fakes; o motor real espera o OK do dono para gastar crédito, e o uso real é dele) · **Decide:** dono (o princípio: o modelo processa, pensa e decide os parâmetros por conta própria; não repassa a fala), arquiteto (onde o plano mora, como a tarefa o recebe, onde a realidade confere)
**Pedido:** dono, 2026-11-16, depois do print: «o contato da minha mãe é literalmente mãe, salve para não esquecer depois» → «Vou abrir a conversa "mãe salve para não esquecer depois".» Continua a ADR-0070 (o Jarvis é agente). Emenda: ADR-0026 (o texto da memória), ADR-0047 (o catálogo), ADR-0066 (o relato verdadeiro), ADR-0069 (ler a página). Diagnóstico com arquivo:linha: [docs/estudos/parametros-do-modelo.md](../estudos/parametros-do-modelo.md).

## Contexto

A frase do print não está no código: foi o modelo que pôs a fala do dono inteira como nome da conversa e ignorou o «salve». A trilha do turno mostrou o resto: o 1º token levou 5 067 ms, a saída teve 727 tokens para 58 caracteres falados (uns 650 de raciocínio escondido, que o motor descarta), não houve nenhum caractere de `<<pensar>>`, e a ferramenta foi à tarefa com a **fala crua como objetivo** e o «Vou abrir a conversa…» errado como âncora. O subagente clicou num `ref` sem nada conferir. `memoria.lembrar` nunca foi chamada.

Os e2e da ADR-0070 passavam porque o motor deles era roteirizado: provavam o encanamento, não que um modelo de verdade decide os parâmetros.

## Decisão

**O princípio:** o modelo **entende antes de agir**. Ele separa as intenções da fala, escolhe ele mesmo o valor de cada parâmetro, e é esse entendimento (não a fala) que vira o objetivo de quem executa. O código não extrai parâmetro da fala: ele confere o que o modelo escolheu **contra a realidade** (a página, a fala, a memória) e devolve a divergência como **notificação**, e quem decide é o modelo.

### 1. Plano antes de agir (`9229134`)

- Persona v20, seção ENTENDER ANTES DE AGIR: antes da 1ª ferramenta e de qualquer palavra em voz, o plano entre `<<pensar>>`: cada intenção separada (guardar ≠ abrir), a ferramenta e os valores escolhidos, nunca a frase do dono. A frase curta antes da ação não cita nome nem valor ainda não conferido.
- `Cerebro.exigir_plano` (o app liga): a 1ª proposta sem plano **não roda** e volta como `NOTA_DO_PLANO`, uma vez (`COBRANCAS_DO_PLANO`). `Resposta.plano` é o raciocínio antes da 1ª proposta. A trilha conta `caracteres_do_plano` e `plano_cobrado`.

### 2. A tarefa persegue o objetivo formulado (`c175e17`)

- `MotorDoObjetivo.plano` → `NOTA_DO_OBJETIVO`: siga as intenções e os valores do Jarvis; a fala é contexto e autorização, nunca o valor a digitar, procurar ou clicar. Sem plano, `NOTA_SEM_PLANO` (entenda e planeje antes do 1º passo). `NOTA_DO_JA_DITO`: o que o dono ouviu não é decisão.
- O título da tarefa é a 1ª linha do plano (`titulo_do_plano`).
- **A política continua com a fala do dono** (`Objetivo.do_pedido`: escopo, guarda, cópia na delegação): ela autoriza; o plano não alarga a autorização.

### 3. Esquemas com sentido, e validação de cópia (`c0a1f67`)

- `description` em 18 argumentos de valor nos manifestos, mostrada no catálogo entre colchetes (`alvo [o rótulo como está na página («Mãe»; «Enviar»); nunca a frase do dono]`). Regra geral no catálogo: «ARGUMENTO é só o valor que VOCÊ decidiu… o que mais ele disse é outra ação», com o errado/certo do caso.
- `x-nome: true` nos argumentos de nome. `executor/copia.py`: o argumento de nome com 4 ou mais palavras que é um trecho da fala volta ao modelo como erro (`argumento_copiado`) com o porquê. A mesma proposta repetida passa: o código avisa uma vez por valor.
- `TETO_DO_PROMPT` 16 000 → 18 000.

### 4. O alvo conferido contra a página (`2b5ef0f`)

- `navegador/alvo.py` e `CorposDoNavegador._elemento_conferido` (clique, acionar, gesto): o `alvo` por texto que a extensão não acha, ou o `ref` cujo rótulo não é o `esperado` (argumento novo), **não vira ação**. Volta como `alvo_nao_confere`, com os rótulos mais parecidos da página e o caminho: aja no certo pelo ref, procure de outro jeito ou pergunte ao dono, nunca por palpite.

### 5. Memória (`4ca7463`, conserto `fb15a93`)

- Mandar lembrar, salvar, anotar ou guardar é uma ação: `memoria.lembrar` com **`texto` = o trecho exato da fala do dono que diz o fato, sem a ordem** («o contato da minha mãe é mãe», sem «salva»). A ADR-0026 (regra 3) só deixa nascer ativa a memória com palavras do dono (é trava contra injeção, e não muda). `sujeito` e `predicado` são do Jarvis. A 1ª versão do item mandava «reescrever o fato» e teria toda gravação negada; o avaliador achou, e `fb15a93` consertou.
- O filtro da verdade ganha `GUARDOU` («guardei», «anotei», «salvei», «está salvo», «vou lembrar»…): só passa com `memoria.lembrar`/`atualizar`/`criar_no`/`criar_aresta` ou `vocabulario.aprender` ok neste pedido.
- A memória de voz chega à tarefa: ao delegar, o livro é consultado **pelo plano** (com a mesma regra D20) e vai como `MotorDoObjetivo.lembrancas`. Assim, «salva que o contato da minha mãe é Mãe» passa a servir a «manda pra minha mãe…».

### 6. A fala vem da voz (`b7112c5`)

- `Mensagem.da_voz` (trust `user_voice`) → `como_texto` acrescenta «(pela voz; a transcrição vem sem pontuação e pode trocar palavras)», no turno e na tarefa. A persona manda pontuar antes de entender e, com duas leituras que mudam a ação, perguntar em vez de chutar.

### 7. Regex do envio vira dica (`128162b`)

- O contato e a mensagem que `pedido_de_envio` tira da fala vão como `CABECALHO_DA_DICA` («palpite… vale o objetivo que o Jarvis formulou»). As travas do envio valem sempre e falam do contato **do objetivo**. A dica do atalho manda conferir no plano. Sai o código morto `Cerebro._envio_do_pedido`.

### 8. Latência (`dbedb9c`)

- Prompt do turno de 15 967 para 17 994 caracteres (4 703 → 5 329 tokens e5, +626), medido em `docs/medicoes/prompt-do-turno.md`. No turno real, o que pesa é o raciocínio escondido (~650 tokens antes do 1º token), não o prompt.
- `MotorClaudeCli.raciocinio_escondido` / esforço `none`/`minimal` no preset → `MAX_THINKING_TOKENS=0` no modo rápido. **Desligado por padrão:** a documentação da CLI diz que nem todo modelo deixa desligar, e o ganho só se confirma com o modelo real.

### Prova (`e830d64`)

`tools/avaliar_parametros.py` + `tools/corpus_parametros.toml` (40 falas, o print incluso). O cérebro de produção roda contra uma página **falsa** do WhatsApp, um livro em RAM e corpos de sistema simulados: nada real é tocado. Ele mede parâmetro certo, memória gravada e ativa, pergunta quando ambíguo, plano e latência. O motor `ideal` (falso) dá 40/40; o `copiao` (o bug do print) dá 0/40. **O motor real não foi rodado: espera o OK do dono.** O relatório vai em `docs/medicoes/parametros-do-modelo.md`.

## Consequências

- Uma rodada a mais quando o modelo propõe sem plano (~3 s), contada na trilha. O plano visível (~40–100 tokens) vem antes da 1ª palavra falada.
- Os testes que roteirizam a 1ª ferramenta sem plano não mudam (`exigir_plano` é do app). O teste do teto do prompt sobe para 18 000.
- **Só a máquina do dono prova:** o Haiku real escrevendo o plano, separando «salvar» de «abrir» e pondo só o nome no argumento; o `MAX_THINKING_TOKENS=0` fazendo efeito; e a latência real de 1º token e de 1ª fala. Para isso: `tools/avaliar_parametros.py --motor real` (e `--sem-raciocinio-escondido`), com o OK, e o roteiro de `docs/teste-real-dono.md`.
