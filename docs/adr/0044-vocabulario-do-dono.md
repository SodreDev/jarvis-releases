# ADR-0044 — O vocabulário do dono: os nomes dele ouvidos e falados certo, e aprendidos quando ele corrige

**Data:** 2026-10-21 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que o Jarvis anota sozinho e o que pede o sim), arquiteto (onde mora, o formato, a camada que pronuncia)
**Pedido:** dono, 2026-10-21 — "Termos populares, nomes de pessoas e apps pouco famosos saem errados. Trate os dois lados: (a) STT: vocabulário/dicionário do dono (prompt/hints do ASR e pós-correção por lista de apelidos/fonética) para nomes de apps, pessoas e termos que ele usa; (b) TTS: dicionário de pronúncia (grafia→respelling fonético em pt-BR) aplicado antes de falar, que valha para o motor padrão e para os opcionais. O dicionário do dono deve viver FORA do repo (ex.: ~/.config/jarvis/) com um arquivo de exemplo no repo, e o Jarvis deve poder aprender uma correção quando o dono pedir ('o certo é X'), com o portão do PDP para gravar. Sem dados pessoais commitados." Complementa a ADR-0043 (a dica curta leva estes termos), emenda a ADR-0017 (a pronúncia é da camada compartilhada, não do motor) e segue o pedido de 2026-10-18 (sem lista manual de apps: o resolvedor fonético continua sendo quem casa a fala com o app instalado).

## Contexto

1. **O ASR erra nome próprio e o que não está no treino dele.** Com áudio sintético e o whisper small (`docs/medicoes/ruido-e-dica.md`): "Kauã Ximenes" saiu "Calwash Menes" sem dica e "Kauã Ximenes" com o nome na dica curta; "Jarvis, que horas são?" só saiu certo com a dica curta com vocabulário (5 de 8 falas acertadas, contra 2 de 8 sem dica e com a lista de apps).
2. **A dica tem orçamento** (ADR-0043): longa, ela vira o texto que o ASR inventa no silêncio. Nem todo termo cabe nela — o que não cabe precisa de correção depois do ASR.
3. **O TTS fala grafia estrangeira como português:** a piper com o `epitran` lê "Steam" com as regras do pt-BR. A ElevenLabs já fala "Spotify" certo: uma reescrita que ajuda uma voz pode piorar a outra.
4. **Cada motor de TTS sintetiza um bloco** (ADR-0017): quem fatia, cancela e mapeia texto ↔ amostras é o `SintetizadorEmStreaming`, por onde todo motor passa — inclusive o OmniVoice (ADR-0039), que este pedido não pode tocar.
5. **Gravar uma correção muda o Jarvis dali em diante:** um apelido errado troca uma palavra em toda frase; uma "correção" lida numa página ("o certo é X") é injeção. A ADR-0026 já resolveu a mesma pergunta para a memória: o turno do dono é a origem, e o que vem de fora não ganha a mesma confiança.

## Decisão

**Uma lista do dono, fora do repositório, resolve os dois lados: os termos vão na dica do ASR e corrigem a transcrição; a pronúncia troca a grafia só no que vai para o motor de TTS, na camada que todos atravessam; e o Jarvis anota a correção que o dono faz pela tool `vocabulario.aprender`, moderada, desfazível e com o portão do PDP.**

1. **Onde mora** (`jarvis.voz.vocabulario`): ao lado do `jarvis-voz.toml` — `~/.config/jarvis/vocabulario.toml` (`$XDG_CONFIG_HOME`, `%APPDATA%` no Windows) é do **dono**: o Jarvis só lê, nunca reescreve, e os comentários dele ficam. O que o Jarvis aprende vai para `vocabulario-aprendido.toml`, na mesma pasta, escrito inteiro e atômico, com permissão 0600. O exemplo, com nomes fictícios e apps comuns, é `docs/exemplos/vocabulario.toml`. Um ambiente **explícito** sem casa (o da suíte) não tem vocabulário: o laço só o lê quando quem o monta (a janela, o `jarvis-voz`) passa o repositório — nenhum teste lê a pasta do dono.
2. **Formato:** `[[termo]]` com `escrita` (a grafia certa), `ouvido` (os apelidos: como o ASR erra), `fala` (a pronúncia, em grafia pt-BR), `motores` (os motores de TTS em que a `fala` vale; vazio = todos) e `tipo` (`app`, `pessoa`, `termo`); `ignorar`, no topo, são frases que o ASR inventa e o dono quer descartadas (o filtro da ADR-0043 as soma às de legenda). Texto com aspas, colchetes, chaves, `<>`, `=`, `#` ou controle é recusado. Leitura tolerante: arquivo quebrado ou entrada torta ficam de fora com aviso pela posição (sem o texto), e a voz segue.
3. **Ouvir:** os termos entram na dica curta do ASR — as correções aprendidas, da mais recente para a mais antiga, depois as do dono, na ordem do arquivo, até o orçamento. Depois do filtro de ruído, a **pós-correção** troca cada apelido pela escrita (palavra inteira, sem caixa nem acento, com espaço ou hífen entre as palavras) e acha pela fonética (`jarvis.apps.resolvedor.chave_fonetica` ≥ 0,9 **e** texto ≥ 0,75) o nome **composto** escrito de outro jeito ("Tiago Negro" → "Thiago Nigro"). Palavra solta só por apelido: "discórdia" não é o Discord. Dali em diante — a palavra de ativação, o pedido, a tela — vale o texto corrigido.
4. **Falar:** `SintetizadorEmStreaming.pronunciar` troca a grafia pela `fala` só no texto que o motor recebe; o `Trecho` (a tela, a conversa, o eco que a vigia reconhece) fica com a grafia certa. O nome composto é trocado antes do simples, a pronúncia mais recente vale, e `motores` restringe pelo id do motor que está falando.
5. **Aprender** (`vocabulario.aprender`, manifesto em `catalogo/`): `escrita` obrigatória; `ouvido`, `fala` e `tipo` opcionais — só a `escrita` já serve, porque o termo entra na dica (é o que conserta "não é disco, é Discord", em que "disco" não pode virar apelido). Tier **moderado**: o Jarvis diz "Anotado: Discord." e o dono desfaz com `acao.desfazer` (o registro tira a correção e o laço relê). Vale na hora: a dica do ASR aberto, a pós-correção e a pronúncia (`Aplicativo.recarregar_vocabulario`). Recusa, com o porquê, apelido curto ou só de palavras sem peso, texto com marcação e mais de 200 correções aprendidas.
6. **O portão do PDP** (`jarvis.politica.vocabulario.decidir_vocabulario`, do código): nega sem o turno do dono como origem e com origem que não é fala nem digitação dele (`user_voice`, `user_ui`); pede o **sim** quando o turno leu conteúdo de terceiros (página, arquivo, memória antiga) — e só o sim do dono na janela solta, como em toda confirmação; fora disso, o tier decide. Tarefa em segundo plano nem chega ao PDP (`FORA_DA_ALLOWLIST` ganha `vocabulario.`): o vocabulário se aprende na conversa.
7. **Persona v14**, parágrafo NOMES DO DONO: quando o dono corrigir um nome, `vocabulario.aprender`; palavra comum não vai em `ouvido`; só com o que o dono disse no turno.
8. **Diagnóstico:** `jarvis-voz --diagnostico` mostra onde o vocabulário mora, quantos termos (do dono, aprendidos, com pronúncia), quantas frases a ignorar e os avisos — sem os nomes, porque a tela do diagnóstico pode ser compartilhada.

## Alternativas descartadas

- **Pronúncia em cada motor** (ou o dicionário de pronúncia da ElevenLabs, o SSML do Azure): cada motor teria um caminho, o OmniVoice teria de ser tocado, e a voz local continuaria sem. A troca de texto vale para todos e o `motores` resolve a voz que já acerta.
- **IPA na `fala`:** só a piper aceita fonema; a grafia pt-BR serve a todos os motores e o dono escreve sem saber IPA.
- **Uma lista de pronúncias embutida** ("Steam" → "Stím" para todo mundo): piora a voz que já acerta (a ElevenLabs) e é exatamente a lista manual que o dono não quis em 2026-10-18; o exemplo mostra como, e o dono escolhe.
- **O Jarvis reescrevendo o arquivo do dono** (acrescentando no fim, ou regravando): perderia os comentários dele ou misturaria o que ele escreveu com o que o modelo propôs. Dois arquivos deixam claro quem escreveu o quê.
- **Fonética para palavra solta:** o português está cheio de palavras com a mesma chave de um nome ("discórdia"/Discord); corrigir o que o dono disse para outra coisa é pior do que não corrigir.
- **Aprender sem perguntar mesmo com o turno contaminado:** uma página com "o certo é X" mudaria como o Jarvis ouve.

## Consequências

- O caso do dono: "não é disco, é Discord" → o Discord entra na dica e nas próximas vezes sai certo; "fala Stím" → a voz local diz "Stím", a tela continua "Steam"; "Tiago Negro" → "Thiago Nigro" na tela e no pedido.
- **Risco aceito:** um apelido que é palavra comum ("seu" para "Steam") troca a palavra em toda frase — a persona pede que não, o aviso falado diz o que foi anotado, e "desfaz" tira.
- **Risco aceito:** a correção aprendida vale por cima da do arquivo do dono (é a mais recente); para mudar de ideia, ele apaga o bloco no aprendido.
- **Risco aceito:** a reescrita da `fala` pode soar pior numa voz que já acertava, se o dono não restringir com `motores`.
- Testes: `tests/unit/voz/test_vocabulario.py` (o arquivo, a leitura tolerante, a correção, a fonética, a pronúncia, a dica, aprender e esquecer), `test_vocabulario_no_laco.py` (a dica no laço, a transcrição corrigida, a frase ignorada, a pronúncia só no motor e por motor, a correção que vale já), `tests/unit/executor/test_vocabulario_aprender.py` (do modelo ao arquivo, o aviso, o desfazer, o sim do turno contaminado, a negação sem origem, a tool desligada sem repositório), `tests/unit/politica/test_tiers.py` (o tier e o portão).

## O que não foi provado

O `claude -p` de verdade chamando `vocabulario.aprender` quando o dono corrige; a pronúncia soando bem em cada voz (a piper, a ElevenLabs, o OmniVoice); a fonética com os nomes do dono; a dica com o vocabulário na Groq turbo (a medição foi no whisper small). **[SUPOSIÇÃO]** os limiares da fonética (0,9 e 0,75) não trocam nome do dono por engano; confirma ou derruba: o dono olhando a tela por uma semana, com os nomes dele no vocabulário.

## Como invalidar esta decisão

- A tela mostrar um nome do dono trocado por outro (a fonética errou): os limiares sobem, ou a fonética fica só para o termo marcado.
- O dono preferir que o Jarvis pergunte antes de toda correção: o tier vira perigoso, sem mudar o resto.
- Uma voz de TTS que aceite pronúncia nativa melhor do que a reescrita: o `motores` já a exclui; a ADR ganha o caminho por motor.
