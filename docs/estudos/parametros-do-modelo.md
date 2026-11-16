# Parâmetros do modelo: por que o Jarvis repassou a fala do dono (diagnóstico)

opus-parametros, 2026-11-16. Fase 1: só leitura, nenhum código mudou. HEAD `a87156f`.

## O caso

O dono disse «o contato da minha mãe é literalmente mãe, salve para não esquecer depois». A
transcrição chegou **sem pontuação**: «o contato da minha mãe é literalmente mãe salve para não
esquecer depois» (72 caracteres). O Jarvis respondeu «Vou abrir a conversa "mãe salve para não
esquecer depois".» A frase não está no código: é fala do modelo.

A trilha do dono (`~/.local/state/jarvis/voz/diagnostico/turnos.jsonl`, só metadados, turno
`…75a732`, 11:16:39) e a auditoria (`auditoria.sqlite`) mostram o resto:

| quando | o que | números |
|---|---|---|
| 11:16:39 | `turno.inicio`, método `conversa` (sem método específico) | pedido de 72 car. |
| 11:16:45 | motor `conversa-claude-cli/haiku`, origem turno | entrada 8 440 tok, **saída 727 tok**, 1º token **5 067 ms** |
| 11:16:45 | o motor propôs `sites.open {url: web.whatsapp.com, nova_aba}` → foi à **tarefa** | |
| 11:16:50 | `turno.fim` | 58 caracteres falados, **0 de raciocínio**, total 10 666 ms |
| 11:16:51–17:02 | a tarefa: `browser.tabs` → `browser.inspecionar` → **`browser.click {ref: t75i1.23}`** → `browser.read` | 4 rodadas, ~2,5–3,9 s de 1º token cada |
| 11:17:03 | o dono cancelou | |

`memoria.lembrar` **nunca foi chamada**. Um turno antes (`…871784`), o modelo tinha procurado
`memoria.buscar «nome da mãe do dono»`, `memoria.buscar_historico «mãe»` e
`memoria.buscar «minha mãe contato»`, sem achar nada. Por isso o dono mandou guardar.

Os 727 tokens de saída para 58 caracteres falados e uma linha de ferramenta (~60 tokens) mostram
que **~650 tokens foram raciocínio escondido** (`thinking_delta`), que o motor descarta
(`src/jarvis/s2/motor_claude_cli.py:401`). O modelo «pensou», nós não vimos, e o que ele pensou não
voltou para ninguém: nem para a tarefa nem para a trilha.

## O caminho da fala até os argumentos

```
STT (sem pontuação) → app._reconciliar (só troca de som, sem pontuar)
  → Cerebro.responder(texto_do_dono)                          s2/cerebro.py:451
      contexto = persona + regras + [método] + [receitas] + [memórias fixas] + [memória] + [atalho]
      → MotorClaudeCli.gerar: `claude -p --effort low --model haiku`, 1 processo por pedido
           sistema = sistema_com_ferramentas(...)              s2/motor_claude_cli.py:165
           stdin   = Contexto.como_texto() (a fala crua)       s2/motor.py:118
      ← Texto «Vou abrir a conversa …» (vai à voz) + <<ferramenta>> {"tool_id": "sites.open", …}
  → _vai_para_tarefa (não é FICAM_NO_TURNO)                   s2/cerebro.py:1140
  → _delegar: objetivo = a FALA CRUA, ja_dito = o que o modelo falou, raciocínio = (vazio)
                                                               s2/cerebro.py:1186-1199
  → MotorDoObjetivo._rodada: NOTA_DA_TAREFA + roteiro(objetivo.pedido)   s2/tarefa_do_pedido.py:410
      o subagente re-deriva TUDO da fala crua, ancorado no «Vou abrir a conversa "mãe salve…"»
```

### (a) O que o modelo recebe

- **Persona v19** (`src/jarvis/s2/persona.md`, 4 705 car.) + **regras do dono** + **catálogo**:
  15 967 caracteres no total com as 69 ferramentas (medido com `tools/medir_prompt.py`). O teto do
  teste `test_o_prompt_do_turno_cabe_no_teto` é 16 000: **sobram 33 caracteres**.
- **O catálogo leva só o NOME dos argumentos.** `assinatura()` (`s2/motor_claude_cli.py:116`)
  escreve `alvo, ref, tab_id:int`: nome, `*`, tipo e enum. Não há descrição de argumento em nenhum
  manifesto (`catalogo/*.yaml`, `input_schema.properties` só tem `type`/`maxLength`), e o
  `description` da ferramenta é trocado pelo `quando` (`linha_da_ferramenta`, `:133`). Exemplos:
  - `browser.click(tab_id:int, alvo, ref)`: «clicar num elemento da página pelo texto (alvo)…».
    Nada diz que `alvo` é **só o rótulo que está na página**.
  - `browser.type(… texto* …)`, `sites.open(url*)`, `apps.launch(nome*)`, `memoria.lembrar(texto*,
    sujeito, predicado)`: nenhuma diz o que é o valor, o que não é, nem dá um exemplo certo/errado.
- **Não há ferramenta de contato/WhatsApp.** Abrir uma conversa é `sites.open`/`browser.navigate`
  + `browser.inspecionar` + `browser.click`. O «contato» só existe como texto dentro do raciocínio
  do modelo, e nenhum argumento tem o nome `contato`. Por isso nada no esquema pode dizer «o
  contato é só o nome».
- **O protocolo é texto, não `tool_use` nativo.** `INSTRUCAO_DE_FERRAMENTAS` (`:74`) pede uma linha
  `<<ferramenta>> {json}`, e o `claude -p` roda com `--tools ""`. Não há saída estruturada: o
  `--json-schema` da CLI existe (2.1.325), mas mata o stream da voz. Há validação de **tipo** e de
  contrato depois (`capacidades/*.validar_entrada`); de **sentido**, nenhuma.

### (b) Caminhos que copiam a fala para o argumento ou o objetivo

| # | onde | o que faz | peso no caso |
|---|---|---|---|
| b1 | `s2/cerebro.py:1199` (`_delegar`) e `executor/ferramentas.py:510` (`Objetivo.do_pedido`) | **o objetivo da tarefa é a fala crua** (cortada em `CARACTERES_DO_PEDIDO`). O subagente recebe a fala, não o que o Jarvis decidiu | **alto**: a tarefa clicou sem saber o quê |
| b2 | `s2/cerebro.py:1190` (`ja_dito=resposta.gerado`) | o subagente recebe «Vou abrir a conversa "mãe salve…"» como o que o dono já ouviu e se ancora nele | **alto** |
| b3 | `s2/roteiro_do_navegador.py:51-56,135` (`_CONTATO`, `_PARA`, `pedido_de_envio`) | **regex** tira o contato e a mensagem da fala e põe «Contato: «…»» nas notas do subagente (`tarefa_do_pedido.py:410`). Na frase do print não casou (não há verbo de envio), mas `_CONTATO` captura «minha mãe é literalmente mãe salve para não esquecer depois» e casa em «clica na conversa do Bruno». É exatamente «repassar a fala» | médio (latente) |
| b4 | `politica/atalho.py` + `nota_do_atalho` (`s2/cerebro.py:171`) | regex que monta `{tool, args}` com pedaços da fala, como «DICA DO CÓDIGO». Não casou aqui | baixo |
| b5 | `s2/cerebro.py:1124` `_envio_do_pedido`, `roteiro_do_navegador.copia_da_mensagem` | código morto: definidos e não chamados | nenhum |
| b6 | `delegacao/pedido.py` (`RECUSA_DE_COPIA`) | o **contrário**: recusa a cópia da fala no pedido ao Claude Code. É o único lugar que confere sentido | — |

Não há `default = texto do usuário` em argumento de ferramenta: todos os argumentos vêm do modelo.
A cópia é do **modelo** (ele pôs a fala no plano), e o código a propaga por b1, b2 e b3.

### (c) Ferramenta de memória

- Existe e está no catálogo do turno: `memoria.lembrar(texto*, sujeito, predicado)` (fica no turno,
  `FICAM_NO_TURNO`/`memoria.*`). A persona manda usá-la: «Quando o dono pedir para lembrar, anotar ou
  guardar algo, use memoria.*» (`persona.md:17`). Só que:
  - o `quando` é «guardar um fato curto que o dono pediu para lembrar», com **um** exemplo («lembra
    que eu tomo café sem açúcar»). «Salve», «anota», «não esquece», «guarda» não aparecem nela; o
    «guarda que…» é exemplo de `memoria.criar_no`;
  - nada diz que guardar é uma ação **separada** de outra que venha na mesma fala, nem como
    escrever o fato (o modelo tem de reescrever em 3ª pessoa: «o contato da mãe do dono se chama
    Mãe»);
  - o aviso ao dono `aviso_falado: 'Anotei: {texto}'` sai do resultado da ferramenta, e isso está
    certo: só depois de gravar.
- **Duas memórias que não se falam.** `memoria.lembrar` grava no livro (memoryd). Os contatos que a
  tarefa de envio confere vêm das **memórias fixas**, outro arquivo, a aba da janela
  (`voz/app.py:1714`, `_contatos_das_memorias`). O que o dono manda guardar por voz só volta pelo
  `memoria.buscar` do modelo ou pela consulta por turno (`cerebro.py:576`), nunca pela resolução do
  contato.

### (d) Espaço para pensar

- **Visível:** o protocolo tem `<<pensar>>…<</pensar>>` (persona, VOZ E TELA). É **opcional** e,
  neste turno, ficou vazio (0 caracteres). Nada obriga um plano antes da 1ª ferramenta.
- **Escondido:** o `claude -p --effort low` do Haiku pensa (~650 tokens neste turno), e o motor
  **descarta** isso (`motor_claude_cli.py:401`). O raciocínio custa a latência e não deixa rastro.
- **A persona empurra a agir no 1º token:** «Quando o pedido é claro, faça: não pergunte…»
  (`persona.md:7`); «Ações no computador vão a um subagente: diga curto o que vai fazer»
  (`persona.md:9`). Daí sai o «Vou abrir a conversa X», dito antes de qualquer conferência. O
  parâmetro errado vira **fala** e depois **âncora** da tarefa (b2).
- Não há «rodada de entendimento». O roteador de método (`politica/metodo.py`) só escolhe a
  família, e aqui escolheu `conversa`.

### (e) Pontuação

A transcrição chega **sem pontuação** ao modelo. O `app._reconciliar` só troca som parecido
(vocabulário); não pontua nem separa frases. Nem a persona nem a instrução dizem ao modelo que a
fala vem do reconhecimento de voz, sem pontuação e com palavras trocadas. Sem a vírgula, «mãe salve
para não esquecer depois» vira um sintagma depois de «literalmente», e o modelo o leu como o nome
literal.

### (f) Onde vão os 5 s do 1º token

1. **Raciocínio escondido**: ~650 tokens de saída antes do 1º texto. No ritmo do Haiku, é a maior
   parcela, uns 3 s.
2. **Piso do `claude -p`**: um processo por pedido. Medido em `docs/medicoes/f2-02-piso-do-claude.md`,
   1º token p50 ≈ 1,7 s (p95 2,3 s) com `--safe-mode` e prompt pequeno.
3. **Prompt**: ~8,4 mil tokens por chamada (sistema ~4,3 mil + conversa + memória). Cada rodada
   da tarefa paga isso de novo (8,8–12,5 mil tokens, 2,5–3,9 s cada). O cache de prefixo da API
   vale dentro da CLI, mas a CLI não o informa, e o prefixo muda quando muda a nota do turno.
4. **Modelo**: Haiku com `--effort low` é o mais rápido dos presets. Trocar de modelo não é a causa.

## As causas, em ordem de peso

1. **O modelo decide os parâmetros sem um passo de entendimento.** Ele age no 1º token, sem plano
   visível, sem separar as intenções (guardar ≠ abrir), e anuncia o parâmetro em voz antes de
   conferir (persona `:7`, `:9`). O raciocínio escondido existe, mas não é cobrado nem visto.
2. **O que o Jarvis decidiu não vai para a tarefa; vai a fala crua** (b1), mais a frase errada
   como âncora (b2). O subagente volta a interpretar a fala e age (clicou em `t75i1.23`).
3. **O esquema não diz o que é cada argumento** (a): sem descrição de parâmetro, sem certo/errado,
   sem a regra «o argumento é só o valor; o que mais o dono disse é outra ação».
4. **O alvo não é conferido contra a realidade antes de agir**: o clique por `alvo` ou `ref` não é
   comparado com o que o Jarvis quis, e não há passo «não achei esse contato na lista → pergunte».
5. **«Salve» não é reconhecido como ação de memória**: a descrição é estreita e não há regra de
   decompor. A memória de voz também não alimenta a resolução de contato (as duas memórias).
6. **Transcrição sem pontuação e sem aviso**: o modelo não sabe que precisa pontuar, nem que pode
   perguntar quando há duas leituras.
7. **Regex que extrai parâmetro da fala** (b3, b4): não causou este caso, mas é o mesmo erro de
   princípio («repassar a fala») e vai causar o próximo, como em «clica na conversa do Bruno e diz…».
8. **Latência**: raciocínio escondido (maior parcela), piso da CLI e ~8 mil tokens por rodada.

## O que a Fase 2 muda (um commit por item)

1. Esquemas: descrição em cada argumento que leva nome ou valor, mais a regra geral do catálogo
   («só o valor, nunca a frase») com um exemplo certo/errado. Validação de sentido: o argumento de
   nome que copia um trecho longo da fala volta ao modelo como erro, e ele decide.
2. Plano antes de agir: um `<<pensar>>` curto, **obrigatório antes da 1ª ferramenta do pedido**, que
   separa as intenções e diz os parâmetros escolhidos. Sem plano, a proposta não roda e volta ao
   modelo. O plano vai à tarefa como **o que o Jarvis decidiu**, no lugar da fala crua como
   objetivo. Sai a regex do envio (b3): o contato e a mensagem são decididos pelo modelo.
3. Alvo contra a realidade: o `alvo` do clique ou da digitação é conferido contra a última leitura da
   página. Sem par exato, não executa: volta ao modelo com os rótulos mais parecidos, e ele confirma
   com o dono ou escolhe.
4. Memória: «salve/guarde/anote/não esquece» → `memoria.lembrar` com o fato reescrito, como intenção
   própria; relatado só com o resultado ok.
5. Pontuação/ambiguidade: o modelo sabe que a fala vem da voz sem pontuação; com duas leituras que
   levam a ações diferentes, pergunta.
6. Latência: medir e cortar o raciocínio escondido quando o plano visível é obrigatório, e enxugar
   o prompt para caber as descrições sem passar do teto.
