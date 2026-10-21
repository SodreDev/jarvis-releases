# ADR-0031 — Pensar não é falar: o raciocínio é do turno, a fala é o resultado

**Data:** 2026-10-20 · **Estado:** aceita (pedido do dono depois de testar o app) · **Decide:** dono (o que se fala), arquiteto (onde mora o canal)
**Pedido:** dono, 2026-10-20 — "o Jarvis está gastando TTS demais. Separe canal de raciocínio (interno, não falado, não mostrado passo a passo; pode ficar no log de diagnóstico) do canal de resposta (curto, falado). Dono NÃO quer acompanhar passo a passo: remover a narração por passo que pedimos antes (status curto entre passos) — agora só fala quando há resultado ou pergunta realmente necessária; frase de ack curta no início (no máximo uma) é aceitável." Emenda a ADR-0028 (sai o status curto entre passos, de 7096c1a), a ADR-0025 (o que do motor vai para o TTS) e o tier moderado do controle por voz (cde99b6, "o Jarvis fala o que fez": exceção para os passos de navegação). Mantém o P10 ("não exigimos nem exibimos CoT privado").

## Contexto

Numa tarefa de navegação ("abra o canal do Thiago Nigro") o dono ouvia, a cada passo, três coisas: a frase do modelo antes da ferramenta (a persona v5 pedia "antes de usar uma ferramenta, diga em uma frase o que vai fazer; depois, diga o resultado"), o status "Passo N terminou; avaliando o resultado." na fila de avisos e o aviso falado de cada moderada do navegador ("Naveguei para youtube.com", "Digitei o texto no campo «Pesquisar»", "Cliquei em «O Primo Rico»").

Mais dois achados do código: cada rodada do laço é um pedido **novo** ao motor, que não sabia o que já tinha dito no turno — o "vou ver" podia voltar a cada passo; e o texto que o modelo escrevia **depois** de propor uma ferramenta ("pronto, abri!") ia para a fala antes de o resultado voltar.

## Decisão

1. **Canal de raciocínio no protocolo.** No protocolo de texto do `claude -p` (ADR-0028), o que vem entre `<<pensar>>` e `<</pensar>>` sai do `LeitorDoProtocolo` como `Raciocinio`, delta novo do contrato (`jarvis.s2.motor`) — também partido entre deltas e com caixa e espaço tolerados. Sem a marca de fim, o raciocínio vai até a próxima proposta ou o fim da geração: na dúvida, o texto **não** vai para a fala. O `thinking` nativo da CLI continua descartado e contado (`pensamento_descartado`). Obrigação nova de todo motor: raciocínio nunca sai como `Texto`, porque todo `Texto` pode ir para o TTS.
2. **O cérebro consome, com teto.** `Resposta.raciocinio` guarda até `LIMITE_DO_RACIOCINIO` (2 000 caracteres); o que passa é contado em `raciocinio_descartado`. O raciocínio volta ao motor na rodada seguinte **do mesmo turno** (`Contexto.raciocinio`), junto com o que o dono já ouviu no turno (`Contexto.ja_dito`, até 300 caracteres) — para seguir o plano sem narrá-lo e sem repetir o aviso. Nunca vai à fala, à tela, à conversa (P4), ao livro de memória nem à trilha: morre com o turno. Na trilha de diagnóstico vai só o tamanho (`caracteres_de_raciocinio`, `raciocinio_descartado`, `narracao_retida`).
3. **No máximo um aviso curto.** Na primeira rodada o texto sai como antes: é a resposta, ou o aviso curto que sai antes da primeira ferramenta. Nas rodadas depois de uma ferramenta o texto espera até ter o tamanho de um lote de fala (14 palavras, `PALAVRAS_MINIMAS_POR_PEDACO`): se uma proposta chega antes, era narração de passo e vai para o raciocínio (`narracao_retida`); senão, é a resposta e sai. O lote de fala só fecha com 14 palavras, então segurar **não atrasa a voz**; só a tela, nessas rodadas, espera o primeiro lote em vez de crescer a cada delta. O texto que vem **depois** de uma proposta, na mesma geração, é palpite (o resultado ainda não voltou) e também vai para o raciocínio.
4. **Sem status entre passos.** O `ao_status` do laço não é mais chamado a cada ferramenta. O status do desfecho de uma pendência (confirmada e despachada, ou que falhou) continua: é resultado.
5. **Passo de navegação sem aviso falado.** `aviso_silencioso: true` no manifesto de `browser.navigate`, `browser.click`, `browser.type` e `browser.scroll`: a frase do `aviso_falado` fica na auditoria ("moderado: passo sem aviso falado «…»"), a trilha marca `aviso: silencioso`, o modelo não recebe `aviso_ao_dono` e conta o resultado na resposta final. O validador do manifesto só aceita a chave em `moderado` de efeito passageiro (`side_effect: ephemeral`): o que escreve de forma persistente (pasta, mover, memória, lembrete, rascunho) e o teclado e o mouse virtuais o dono continua ouvindo.
6. **Persona v6** (`persona.md`, "PENSAR NÃO É FALAR"): não narra os passos; fala o resultado ou a pergunta que ele precisa responder; no máximo uma frase curta antes da primeira ferramenta; o raciocínio vai no bloco. A instrução do protocolo (`INSTRUCAO_DE_FERRAMENTAS`) e o fecho do contexto com resultados ("se o pedido ainda não está pronto, siga com a próxima ferramenta sem falar") dizem o mesmo.

## Alternativas descartadas

- **Cortar a narração só pela persona.** O modelo nem sempre obedece, e o "vou ver" de cada rodada vinha de ele não saber o que já tinha dito: o código segura e devolve o contexto.
- **Segurar o texto de todas as rodadas, inclusive a primeira.** Pegaria o aviso que passa de uma frase, mas a tela deixaria de crescer a cada delta na resposta comum, sem ferramenta (pedido do dono de 2026-10-19).
- **Juntar os avisos das moderadas e falar no fim.** O aviso de efeito que fica é resultado e é o que permite o "desfaz"; o de navegação o dono vê no navegador.
- **Guardar o texto do raciocínio na trilha.** A trilha é só de metadados (2026-10-20): o raciocínio carrega o que o dono pediu e o que as páginas disseram.

## Consequências

- O caso do dono: no máximo "vou ver" e o resultado conferido; nada entre os passos.
- **Risco aceito:** narração de 14 palavras ou mais antes de uma proposta, numa rodada depois da primeira, já saiu em parte quando a proposta chega (a persona pede o contrário; a trilha não conta esse caso).
- **Risco aceito:** um modelo que escreve a resposta inteira dentro de `<<pensar>>` deixa o dono sem resposta; a trilha mostra `caracteres_falados` 0 com raciocínio maior que 0.
- **Não provado:** o `claude -p` real seguindo o bloco e a regra de um aviso só — os testes usam o motor roteirizado e o leitor do protocolo, sem rede.
- O teto de 2 000 caracteres é por turno; podar resultados grandes de ferramenta conforme o contexto cresce é a memória temporária de turno (Lote B, item 7).
- Testes: `tests/unit/s2/test_pensar_nao_e_falar.py` (protocolo, cérebro, teto, lote sem atraso, aviso de efeito que fica), `tests/unit/s2/test_laco_de_ferramentas.py` (o laço do vídeo sem status), `tests/unit/navegador/test_ferramentas_browser.py` (passos sem aviso falado), `tests/unit/politica/test_tiers.py` (o validador), `tests/unit/s2/test_persona.py`, `tests/unit/voz/test_trilha_do_app.py` (só o tamanho na trilha).

## Como invalidar esta decisão

O dono pedir de volta o acompanhamento passo a passo, ou a trilha mostrar `narracao_retida` alta com a resposta final faltando informação que só a narração tinha.

## Emenda de 2026-10-21 — falar menos: a voz cabe num orçamento, a tela recebe tudo

**Pedido:** dono, 2026-10-21 — "FALAR MENOS. No system prompt/persona (e no que couber em código): resumir a EXECUÇÃO de ações em 3 a 4 frases curtas, a menos que o dono peça para detalhar o que achou/fez; resposta falada curta por padrão, texto longo vai para a tela (não para o TTS) quando o dono não pediu detalhe; sem narração passo a passo. Idealmente com um teto verificável (ex.: orçamento de frases para o que vai ao TTS) e teste."

1. **O teto é do código** (`jarvis.s2.orcamento_da_fala.OrcamentoDaFala`), entre o texto do motor e o fatiador de fala: até **quatro frases e 60 palavras** vão para o TTS. Passou disso, a voz diz as três primeiras e o fecho «O resto está na tela.» — quatro frases no total, nunca mais. A quarta frase espera para saber se vem uma quinta (o lote da terceira ainda está tocando: a espera não se ouve). Uma frase só, comprida demais, é cortada na última vírgula (ou palavra) dentro das 60 palavras. Fim de frase é `.`, `!`, `?`, `…` ou quebra de linha; abreviação ("Sr.", "etc."), inicial ("J.") e decimal ("3.5") não fecham frase.
2. **A tela recebe tudo**, como antes (`mostrar`, e a linha "Jarvis: …" do fim). O que ficou só na tela entra na conversa do modelo marcado ("[só na tela, não falado: …]"), para ele saber que o dono viu e não ouviu; o livro de memória guarda o que tocou, como sempre (P4). A trilha conta o tamanho (`caracteres_so_na_tela` no `turno.fim`), nunca o texto.
3. **Sem teto quando o dono pede detalhe** (`quer_detalhe`, pela fala dele, nunca pelo modelo): "explica", "detalha", "o que você achou", "o que você fez", "lê pra mim", "passo a passo", "me conta", uma história…
4. **Vale para a resposta do turno e para a resposta de uma tarefa** (ADR-0038: a tela/o card mostram a resposta inteira; a voz, o resumo). **Nunca** para uma pergunta — cortada, ela não poderia ser respondida (o "sim" só vale depois de ela tocar inteira) — nem para as frases do código (o aviso de uma moderada, a frase ao delegar).
5. **Persona v13**, parágrafo FALAR POUCO: resumir a execução em três ou quatro frases curtas; detalhar só quando o dono pedir; o que é longo vai para a tela.

**Risco aceito:** a lista de pedidos de detalhe é por palavras: um "fala tudo sobre isso" dito de outro jeito não tira o teto, e o dono ouve o resumo e lê o resto. **Não provado:** o `claude -p` de verdade seguindo o parágrafo novo da persona (os testes usam o motor roteirizado). Testes: `tests/unit/s2/test_falar_menos.py` (o orçamento em stream e de uma vez, a quarta que espera, a frase comprida, abreviação, lista, detalhe; o cérebro; a resposta de tarefa; a pergunta que não é cortada; a persona).

