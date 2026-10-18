# Como abrir e testar o Jarvis

São duas formas do **mesmo** laço de voz: a **janela** (`jarvis`, ADR-0019) e o **terminal**
(`jarvis-voz`, ADR-0017/0018). A janela não substitui o terminal — ela usa o mesmo núcleo, o
mesmo epoch e a mesma configuração.

Não é o produto da SPEC §2 (os sete processos): é o laço de voz da F1 montado num processo só,
com um gerador de resposta provisório (ADR-0018).

---

## 0. Abrir a janela

```bash
cd /home/sodre/GranaFacil/J.A.R.V.I.S
uv sync --frozen --group dev --group gui --group voz --group asr --group dispositivo --group memoria
uv run jarvis
```

Para abrir pelo **menu de aplicativos** (sem instalar pacote nenhum, sem sudo):

```bash
uv run jarvis --instalar-atalho     # escreve o .desktop e o ícone em ~/.local/share
```

O que a janela tem:

- **o núcleo no meio** diz em que pé o Jarvis está — parado, ouvindo você, pensando, falando.
  Os anéis **só giram quando há processamento**; parado é parado;
- **segurar para falar**: o botão "falar" ou a **barra de espaço**. Soltar fecha o turno na
  hora — é o PTT de verdade, que o terminal não tem como oferecer. Apertar também
  **interrompe** o Jarvis no meio da fala (o mesmo barge-in da barra no terminal). Vale com a
  janela em foco **depois de qualquer clique**; com texto no campo, a barra digita (Esc ou
  Enter devolvem o atalho);
- **escrever** na barra de baixo funciona a qualquer momento: a linha vira um turno no mesmo
  laço, com a mesma voz e a mesma interrupção;
- **`Esc`** interrompe, **`Ctrl+B`** fixa a barra lateral, **`1`/`2`/`3`** trocam de modo;
- **três modos**: *assistente* (núcleo grande, pouca coisa na tela), *pesquisa* (o núcleo
  encolhe e o conteúdo manda) e *execução* (várias visões ao mesmo tempo);
- **provedores e diagnóstico** abrem pela barra lateral, como módulos: lá você escolhe quem
  ouve e quem fala, liga (ou não) a nuvem, cola a chave de API — que vai para o **chaveiro do
  sistema**, nunca para um arquivo nosso — e roda o diagnóstico, o teste de microfone e o de
  voz.

**O que é demonstração, e está escrito na tela.** Não há busca na web, navegador nem terminal
ligados: os módulos dos modos *pesquisa* e *execução* são um roteiro com conteúdo deste
repositório, e cada um deles leva o selo **DEMONSTRAÇÃO** na moldura. O que é real: o estado
do laço, a transcrição, o PTT, o parar, o indicador de microfone, a configuração, o chaveiro,
o diagnóstico e os indicadores desta máquina (lidos de `/proc`).

**O que encosta na sua máquina pede confirmação.** Navegador, console, arquivos e captura de
tela existem no catálogo e **não entram sem você dizer que sim** — a faixa de confirmação
aparece acima da barra de conversa, com o motivo.

### 0.0 Os consertos de 2026-10-17 — como conferir cada um

> Atenção ao `uv sync`: ele **remove** o que não estiver na lista de grupos. Use a linha de
> cima inteira (com `--group memoria`); uma lista antiga apaga o índice da memória.

1. **Chave no chaveiro vale em todo lugar.** Guarde em Configuração → Chaves de API. Depois:
   `uv run jarvis-voz --diagnostico` deve dizer `definida (chaveiro do sistema)`, e "testar
   voz" na aba Diagnóstico usa a mesma chave. Exportada no shell, a do shell ganha. Sem chave
   em lugar nenhum, a frase diz onde guardar.
2. **O estado de cada motor é o que o laço vai fazer.** Na aba de provedores, o motor
   escolhido mostra `LIGADO`, `DESLIGADO` ou `NÃO RODA` com o motivo (falta a chave, falta
   baixar a voz, falta biblioteca, motor barrado pela licença). É a mesma frase com que o
   laço recusaria. Com o seu arquivo de 16/10 (`nuvem_ligada = ["tts-elevenlabs"]`), a
   ElevenLabs aparece `LIGADO`. Se ainda aparecer `DESLIGADO`, a janela leu outro arquivo: o
   caminho dele está na caixa "Arquivo".
3. **Outros motores.** `tts-piper-epitran` (local) funciona: `uv run jarvis-voz --texto --tts
   tts-piper-epitran --s2 eco`. `tts-piper-espeak` **não roda de propósito**: o espeak-ng é
   GPL-3.0, e a tela diz isso. Se falhar, o motivo aparece na conversa e no card de avisos.
4. **"Minha voz não sai."** Com `asr = "asr-groq-…"` e a Groq **fora** de `nuvem_ligada`, o
   Jarvis não te ouve. Agora a conversa diz `não estou ouvindo: …` e o caminho: ligue a Groq
   em Configuração → Voz — ouvir (e salve) **ou** escolha `asr-whisper-local`. O ASR local é
   o padrão e foi conferido sem rede (transcreve o corpus; ~1,9 s por frase nesta CPU).
5. **Atalhos.** Clique em qualquer lugar e segure a barra de espaço: deve aparecer "ouvindo".
   O atalho **global** (Configuração → Escuta → "usar como atalho global") abre o diálogo do
   sistema; depois de aceitar, **salve a configuração**, e a janela pede o mesmo atalho ao
   sistema toda vez que abrir. A frase ao lado diz o estado real ("ligado pelo sistema: …"
   ou o motivo da recusa).
6. **Tempo de cada trecho.** Depois de cada resposta aparece uma linha
   `[enviado → contexto · 1º token · 1ª fronteira · 1º áudio · fala inteira]`. O `claude -p`
   provisório agora sobe com `--safe-mode`: 1º token p50 de 2145 para 1691 ms
   (`docs/medicoes/f2-02-piso-do-claude.md`). A ElevenLabs passa a ter
   `eleven_flash_v2_5` como padrão, mas **o seu arquivo fixa `modelo_elevenlabs =
   "eleven_v3"`**: para o mais rápido, clique em `eleven_flash_v2_5` na linha da ElevenLabs e
   salve.

### 0.0b Os consertos de 2026-10-17 (noite): som, ouvido, botão e configuração

1. **Som de verdade.** A causa raiz de "nunca sai som": o aplicativo usava por padrão o backend
   `sintetico` (a voz ia para uma lista em memória e o microfone era um gerador de teste), e o
   modo texto — onde a janela cai quando o ASR escolhido não roda — sintetizava e jogava fora.
   Agora, fora do CI e sem `JARVIS_AUDIO_BACKEND`, abre a placa; `entrada`/`saida` do
   `jarvis-voz.toml` (índice ou nome do `--diagnostico`) chegam ao PortAudio. Conferido
   gravando o monitor do sink padrão: piper local rms ≈ 1170 e ElevenLabs rms ≈ 2400 (silêncio = 0).
2. **Groq desligada não deixa surdo.** O laço ouve pelo whisper local e diz numa linha.
3. **Botão/espaço de falar** não interrompe mais a si mesmo: a tecla só interrompe com o Jarvis
   falando, preparando a fala ou esperando confirmação. "Mic fechado" durante o carregamento
   virou "preparando o microfone…".
4. **Ativação por voz** (palavra e VAD): VAD do produto (silero), 400 ms de áudio guardados antes
   do disparo e o nome "Jarvis" como dica para o whisper local. Provado com sink virtual
   (PipeWire privado, sem microfone real): a frase gerada pelo piper entra como microfone e o
   Jarvis responde nos dois modos.
5. **Privacidade** em texto longo: uma vez por execução; depois só no painel de Configuração.
6. **Configuração → abas** "pastas e arquivos" (seletor nativo, só leitura / leitura e escrita,
   negações fixas à mostra), "aplicativos" (marcar os instalados, ou escolher programa/.desktop) e
   "navegadores" (detectados, binário de cada um, principal). Cada clique grava na hora só os
   campos de acesso e vale na conversa aberta. `sites.open` abre no navegador principal.
   Limite honesto: acesso é por **pasta** (arquivo solto é recusado), e "escrita" fica guardada mas
   nenhuma ferramenta grava fora da pasta do Jarvis ainda.

### 0.0c Os consertos de 2026-10-17 (madrugada): ASR da Groq e abrir app marcado

1. **ASR da Groq dava "o serviço recusou o pedido (403): error code: 1010".** A causa **não** era
   o modelo: o `urllib` se anuncia `Python-urllib/3.x`, e o Cloudflare da Groq barra essa
   assinatura antes de olhar chave ou modelo. O cliente de nuvem agora manda `User-Agent:
   jarvis/<versão>`. Provado ao vivo: áudio sintético do piper → `whisper-large-v3-turbo` →
   texto devolvido (qualidade de voz sintética, não de microfone). O modelo da Groq **já era**
   próprio: cada modelo é um motor do registro (`asr-groq-whisper-large-v3-turbo`, o padrão, e
   `asr-groq-whisper-large-v3`); `modelo_do_asr` ("small") é só do whisper **local** e nunca vai
   à Groq (teste cobra). Para trocar de modelo: Configuração → Voz — ouvir → Groq → escolher o
   modelo → **ligar** (cada modelo tem o seu interruptor, porque o preço difere) → salvar. Se um
   dia aparecer o 1010 de novo, a mensagem agora diz que é o Cloudflare, e não manda conferir a
   chave.
2. **Abrir app que você marcou não pede confirmação.** Marque em Configuração → Aplicativos e
   diga "abre o discord": abre direto, sem a faixa. App **não** marcado é negado com os parecidos
   que estão autorizados; **site** fora de `sites_sem_confirmar` continua pedindo o seu sim.
   Não consegui reproduzir a faixa para app marcado no código atual (política e config do dono
   dão `allow`); achei e corrigi o caso vizinho: o nome **parcial** ("brave" para "Brave Web
   Browser") era aceito pelo executor mas negado pela política, e o modelo não sabia quais apps
   existem — agora o executor alinha o nome ao app marcado antes da política, e o catálogo que o
   modelo vê termina com "Autorizados agora: …". Se a faixa ainda aparecer para um app marcado,
   mande a frase que você disse e a linha da faixa (o motivo vem escrito nela).
3. **Como conferir sem tocar na sua máquina:**
   `uv run pytest tests/unit/gui/test_janela_abrir_apps.py tests/unit/voz/test_groq.py -q` —
   janela offscreen com motor roteirizado: app marcado pela aba abre sem faixa, nome parcial
   também, não marcado é negado com sugestão, site fora da lista confirma e só abre depois do
   sim. O lançador e o abridor de site são falsos nesses testes: nada abre de verdade.

### 0.0d Os consertos de 2026-10-17 (madrugada, 2ª leva): abrir app, protocolo, navegador, tela e "é comigo?"

1. **Abrir app de verdade.** O erro `NotImplementedError: posix_spawn: setsid unavailable on this
   platform` era do lançador: agora ele usa `subprocess.Popen(start_new_session=True)`, que existe
   em todo Python POSIX. Prova feita: `apps.launch` abriu o **KCalc** de verdade, sem
   confirmação, em sessão própria (`getsid(pid) == pid`), e foi encerrado pelo PID conferido
   (`comm == kcalc`). Na sua máquina: marque o KCalc em Configuração → Aplicativos e diga "abre
   a calculadora". O teste automático usa um `sleep`, não um aplicativo gráfico.
2. **Proposta de ferramenta ("às vezes dá erro ou demora").** Medido com o `claude -p` (haiku) em
   "abre o discord": a proposta só saía no fim da geração e o encerramento ainda esperava
   ~0,5 s de "cortesia" — **2,0–2,6 s → 1,3–1,9 s** do pedido até a proposta em mãos. O leitor
   do protocolo `<<ferramenta>>` agora aceita a marca em qualquer ponto da linha, JSON em várias
   linhas, com cerca ```` ```json ````, com texto depois, `tool`/`arguments` no lugar de
   `tool_id`/`args`, e emite a proposta **quando o objeto fecha**; JSON que nunca fecha vira
   "malformado" (4 000 caracteres) em vez de segurar a fala. Limite honesto: o 2º turno (o modelo
   ler o resultado e dizer "abri") ainda é outro processo do `claude -p`, ~1,5–2 s.
3. **"Abre o navegador" sem site.** Ferramenta nova `browser.launch`: abre só o navegador
   principal (ou o que você nomear entre os configurados em Configuração → Navegadores), **sem
   confirmar**; sem principal configurado, nega e diz onde escolher. Sites continuam em
   `sites.open`, com a regra de `sites_sem_confirmar`.
4. **Os blocos "um por segundo".** A causa: o texto da resposta só ia à janela quando o tocador
   puxava o próximo pedaço, e ele só puxa depois de **tocar** o anterior — a tela andava na
   velocidade da fala. Agora sai na linha do cérebro, no instante em que o pedaço nasce. Medido
   (12 frases, "alto-falante" simulado de 0,5 s por pedaço): intervalo entre pedaços **572 ms →
   47 ms** (p50), último pedaço na tela em **6,9 s → 0,6 s**. O áudio continua no ritmo da fala;
   o que você ouve não mudou.
5. **"É comigo?" (escuta contínua).** Configuração → Voz e escuta → painel **é comigo?**: escolha
   "OpenRouter → TypeSafe", leia o aviso, **ligue** e salve; precisa de `OPENROUTER_API_KEY` (em
   Chaves de API ou exportada). Com a escuta em **contínua**, cada trecho transcrito é
   classificado pelo Jev: fala alheia é descartada sem aparecer na tela; fala para o Jarvis vira
   pedido e a linha `(endereçamento: acao · p=0.97 · 716 ms)` diz o quê. Se o serviço cair, **não
   age** e o card de avisos diz uma vez. Medição: `uv run python tools/medir_enderecamento.py
   --regras` (baseline local: falso-aceite 23,3 %) e `--openrouter` (**58 chamadas** reais,
   ≈ US$ 0,001). Rodado com o seu aval: falso-aceite **3,3 %**, falso-rejeito **46,4 %**, p50 563 ms /
   p95 617 ms. Os pedidos ignorados ficaram todos com p 0,64–0,78, abaixo do limiar de entrada (0,80):
   o limiar está alto para pt-BR e vai ser recalibrado com uma nova rodada. ADR-0029 tem as fontes e o plano.

### 0.1 Pedir para o Jarvis fazer coisas (ferramentas, fatia 6)

O Jarvis não monta comando: ele **propõe** uma ferramenta tipada (listar pasta, ler arquivo,
procurar, gravar rascunho, rascunho de evento, abrir app, abrir site) e o **código** decide —
política de acesso, confirmação na tela e só então a execução. Não existe shell em lugar nenhum.

**1. Escolha o motor que entende pedido.** O padrão (`eco`) só repete o que você disse: ele não
propõe ferramenta. Para testar ferramentas, use o `claude -p` **provisório** (manda o texto da
conversa para a nuvem da Anthropic; precisa da CLI `claude` instalada e logada nesta máquina).
Edite `~/.config/jarvis/jarvis-voz.toml` (a janela cria o arquivo na primeira vez que você
salva a configuração; se não existir, crie só com estas linhas):

```toml
s2 = "claude"
# Alcance. "jarvis" (padrão) = nenhuma pasta sua, só a área do Jarvis.
# "padrao" = + Documentos, Downloads, Imagens, Música, Vídeos, Área de Trabalho.
# "concedido" = + as pastas de `raizes`, só leitura.
acesso = "padrao"
raizes = []
# Apps que ele pode abrir pelo nome (o id do .desktop, sem ".desktop"):
apps_autorizados = ["org.kde.dolphin", "org.kde.kcalc", "org.kde.kate"]
# Sites que abrem sem perguntar (o resto pede confirmação na faixa):
sites_sem_confirmar = ["wikipedia.org"]
```

Chaves, cofres, `.env`, perfis de navegador e `~/.ssh` ficam **negados em qualquer modo**, até no
`total` — eles nem aparecem numa listagem.

**2. Abra a janela e clique em "começar"** (`uv run jarvis`). A conversa mostra, logo no início,
`respondendo com: claude-cli … [nuvem]` e `alcance: nível 1 — só pastas padrão · 7 ferramentas`.
Se aparecer `[local]` e `eco`, o arquivo não foi lido.

**3. Digite na barra de baixo (ou fale), um por vez, e confira:**

| Digite | O que deve acontecer |
|---|---|
| `o que tem na minha pasta Documentos?` | "Deixa eu ver…" e a lista, em voz. **Não** pede confirmação (é leitura). |
| `lê o arquivo ~/Documentos/<um .txt seu>` | resume o que o arquivo diz. Binário ou maior que 64 KiB: ele diz que não leu tudo. |
| `procura um arquivo com "orçamento" no nome` | os caminhos achados, nas raízes do modo. |
| `lê ~/.ssh/id_rsa` | **negado**, e ele diz isso. Nada do arquivo chega ao modelo. |
| `anota: comprar café e pão` | aparece a faixa **CONFIRMAR** acima da barra, com o nome do rascunho e "responda em 30 s". **Permitir** grava; **não**, ou 30 s sem resposta, não grava — e ele diz qual dos dois. |
| `marca dentista dia 20 às 14h30` | a faixa pede confirmação; permitido, grava um `.ics` (sem convite, nada sai da máquina). |
| `abre o Dolphin` | abre (está em `apps_autorizados`). `abre o Firefox`, se não estiver na lista: **negado**, com os parecidos que estão. |
| `abre a Wikipédia sobre Marte` | abre no seu navegador padrão sem perguntar (domínio liberado). Outro site: faixa de confirmação. `javascript:`/`file:`: negado. |
| durante qualquer um: **Esc** ou **interromper** | para a fala e a geração; com a faixa aberta, é "não". |

**Onde ficam as coisas:** rascunhos em `~/.local/state/jarvis/voz/area/rascunhos/` (eventos em
`…/rascunhos/agenda/`); cada decisão da política e cada resultado, encadeados por hash, em
`~/.local/state/jarvis/voz/auditoria.sqlite`.

**O que ainda não foi verificado aqui** (é o seu teste que fecha):

- o `claude -p` **de verdade** propondo ferramenta pelo protocolo de texto (`<<ferramenta>>
  {json}`): toda a suíte usa um motor roteirizado e uma CLI falsa. Se ele responder em voz o
  JSON em vez de propor, me mande a linha da conversa;
- abrir app e site **de verdade**: o teste não abre nada (lançador e portal são falsos). O site
  abre pelo portal `OpenURI` do KDE; o app, pelo `Exec` do `.desktop`, sem shell;
- Windows: listar/ler/rascunho são o mesmo código, mas não rodaram lá; abrir app no Windows
  ainda não foi implementado (ele diz isso).

### 0.2 A conversa continua depois de fechar (2026-10-18)

Pedido do dono: a conversa não persistia ao reiniciar. Agora persiste — o histórico cifrado já
existia (livro-razão, ADR-0026) e a janela o liga.

**Como conferir:**

1. `uv run jarvis`, **começar**, escreva duas ou três mensagens e espere as respostas.
2. Feche a janela e abra de novo. As últimas falas voltam à tela (a que você interrompeu vem
   marcada com `…(interrompido)`), **e** o Jarvis sabe o que foi dito: pergunte "o que eu acabei
   de te perguntar?" (com `s2 = "claude"`; o `eco` só repete).
3. **Nova conversa** (botão na barra de baixo, só aparece quando há conversa): a tela limpa e o
   cérebro esquece. Feche e reabra logo depois: continua vazia. O que foi dito antes ainda está
   no histórico (a busca `memoria.buscar_historico` o acha); só deixa de voltar sozinho.

**O que volta:** os últimos 30 turnos na tela e os últimos 12 no contexto do cérebro. Do Jarvis,
só o que você **ouviu** (P4). O modelo lê o texto *redigido* (sem segredo nem dado pessoal); a
tela mostra o original.

**Onde fica:** `~/.local/state/jarvis/voz/memoria/` (`livro.sqlite`; `conversa-atual.json` guarda
o id da conversa corrente). O texto original vai **cifrado** com a chave do chaveiro do sistema.
**Limite honesto (ADR-0026, pergunta aberta 1):** o texto redigido que alimenta a busca léxica
ainda fica em claro no mesmo arquivo — só o bruto é cifrado.

**Sem chaveiro** (sem Secret Service/KWallet), o Jarvis diz na conversa "sem histórico em disco" e
segue funcionando, só que a conversa vale até fechar.

**Não verificado:** o chaveiro real do seu KDE (a suíte usa um cofre de teste); o índice vetorial
(LanceDB + e5) só entra se o modelo já estiver baixado em `~/.cache/jarvis/modelos/` — sem ele a
busca cai no léxico.

---

## 1. O terminal (`jarvis-voz`)

**O que é isto:** um aplicativo de **teste**, no terminal, para você falar com o Jarvis e
julgar de ouvido a voz, a latência e a interrupção.

**O que já funciona aqui e o que só funciona aí:** tudo o que não depende de placa de som foi
exercitado nesta máquina (síntese com a voz do piper, transcrição, epoch, cancelamento,
degradação, configuração). O **microfone e o alto-falante reais nunca foram abertos** — não há
placa de som na máquina onde isto foi escrito, nem o PortAudio instalado. Então o caminho de
dispositivo está **não verificado**, e a primeira vez que ele roda é a sua.

---

### 1.1 Instalar

```bash
cd /home/sodre/GranaFacil/J.A.R.V.I.S

# o básico + a janela + os extras do caminho local de voz
uv sync --frozen --group dev --group gui --group voz --group asr --group dispositivo --group memoria

# a biblioteca de áudio do SISTEMA (o sounddevice não a traz no Linux)
sudo dnf install portaudio        # Nobara/Fedora
```

Extras opcionais, só se for testar esses caminhos:

```bash
uv sync --group edge     # TTS do Edge (LGPL, e barrado por padrão — ver §6)
sudo dnf install ffmpeg  # só o Edge precisa, porque o serviço dele só devolve MP3
```

A voz do piper (63,2 MB) fica em `~/.cache/jarvis/vozes/pt_BR-faber-medium/`. Se não estiver
aí, baixe com `uv run jarvis-voz --baixar-voz` (ou pelo botão na aba de diagnóstico da
janela): o tamanho é dito antes e o sha256 é conferido depois. Dá para testar o resto sem ela,
com `--tts tts-parametrico`.

### 1.2 As duas chaves (só se for usar nuvem)

O jeito simples é guardar pela janela (Configuração → Chaves de API): vai para o chaveiro do
sistema e vale também para o `jarvis-voz` no terminal. Se preferir o shell:

```bash
export JARVIS_GROQ_API_KEY=...
export JARVIS_ELEVENLABS_API_KEY=...
```

Ponha isso no seu `~/.bashrc` se quiser que valha sempre.

**As chaves nunca entram no repositório, na configuração nem na linha de comando.** O
aplicativo *se recusa a subir* se achar o valor de uma delas em `argv`, e a tela de
configuração mostra apenas "definida" ou "AUSENTE" — ela não lê o valor. Sem nuvem ligada,
você não precisa de chave nenhuma: o caminho local funciona sozinho.

### 1.3 Ver o que está pronto antes de falar

```bash
uv run jarvis-voz --diagnostico
```

Ele lista os motores registrados (e quais são de nuvem e se estão ligados), se cada chave está
definida, os dispositivos de áudio do sistema, os extras instalados e **o que falta** para cada
motor rodar — com o motivo escrito.

### 1.4 Falar

```bash
uv run jarvis-voz            # o laço de voz (microfone e alto-falante)
uv run jarvis-voz --texto    # o mesmo laço, digitando — funciona sem placa de som
```

No laço de voz:

- **a barra de espaço interrompe o Jarvis** no meio da fala (é o barge-in: o epoch morre, a
  fila de playback esvazia e nada do resto é tocado);
- **`q` sai**;
- o turno fecha sozinho depois de ~0,7 s de silêncio.

**Limite honesto do terminal:** terminal não avisa quando você *solta* uma tecla. O PTT de
verdade (segurar para falar) é da interface gráfica, no `audio-io`. Aqui a barra **alterna**.

### 1.5 Escolher provedores (a tela de configuração)

```bash
uv run jarvis-voz config
```

Você escolhe: quem ouve (ASR local ou Groq — e, na Groq, o modelo: `whisper-large-v3-turbo`
ou `whisper-large-v3`, com o preço ao lado), quem fala (piper+epitran, ElevenLabs ou Edge), a
voz local, a voz e o modelo da ElevenLabs (`10` e `11`; em `10`, `l` lista as vozes da sua
conta), o modelo do ASR local, quem responde (eco ou a CLI do Claude), microfone, alto-falante
e PTT × VAD. Grava em `~/.config/jarvis/jarvis-voz.toml`. Na janela é o mesmo: em
**provedores**, clicar no provedor abre os modelos dele, o aviso e o botão de ligar.

**Escolher um motor de nuvem não o liga.** A tela mostra, antes, o que sai da sua máquina,
para onde, qual a retenção declarada pelo serviço e quem é o dono do áudio — e pede um "sim"
digitado por extenso. Enquanto você não confirmar, o motor fica escolhido e **desligado**.

### 1.6 O que você precisa saber sobre cada motor de nuvem

| motor | o que sai daqui | o que o serviço declara (lido na origem em 2026-10-15) |
|---|---|---|
| Groq (`whisper-large-v3-turbo`) | **o seu áudio** | não retém por padrão para inferência, mas os endpoints de áudio ficam sob monitoração de abuso por **até 30 dias**; não treina com a entrada (§4.2); a saída é sua (§8.1). US$ 0,04/h, **mínimo de 10 s por requisição** — um turno de 2 s é cobrado como 10 s, e o diagnóstico conta quantas vezes isso aconteceu |
| ElevenLabs | **o texto que o Jarvis vai falar** | **retém por padrão** ("history preservation enabled"); o modo sem retenção é só Enterprise; a saída é sua (§4); o plano gratuito é **só para uso não comercial** |
| Edge (read-aloud) | **o texto que o Jarvis vai falar** | **não há termos publicados para este uso.** Por isso ele é barrado: o portão só o libera se você aceitar explicitamente, duas vezes, na tela. Não é local — o dono achava que fosse |

### 1.7 O que esperar

- **primeira fala:** o aplicativo aquece a voz local ao subir, então o primeiro turno não paga
  o carregamento do modelo (sem o aquecimento, era ~1,8 s nesta máquina; com ele, ~70 ms até o
  primeiro pedaço de áudio). Esse número é **observação de uma execução**, não medição: a
  medição com hardware, n e três execuções é o cartão F1-16, na sua máquina;
- **sem rede:** o Jarvis avisa em uma frase, cai para o botão de falar e **não refaz** o pedido
  que caiu;
- **sem microfone:** ele diz o que falta (inclusive o comando para instalar o PortAudio) e
  oferece o `--texto`;
- **chave errada:** você lê "o serviço recusou o pedido (401) … confira a chave", não "estou
  sem internet".

## 2. Instalar o aplicativo (AppImage, `.deb`, `.rpm`)

Os três saem do **mesmo** AppDir (ADR-0020), e nada é escrito no repositório — tudo vai para
`/tmp/jarvis-dist/`:

```bash
uv run --frozen python tools/empacotar.py tudo        # AppDir + AppImage + .deb + .rpm
uv run --frozen python tools/empacotar.py verificar   # roda os três em contêiner
```

Cada artefato leva junto: o Python 3.12 relocável, as rodas da trava (`uv.lock`), os dados do
produto (`licenses/`, `schemas/`, `tabelas/`, `catalogo/`), os textos das licenças obrigatórias
e o `.desktop` com o ícone. **O peso dos modelos não vai junto**: a voz do piper (63,2 MB) e o
modelo de ASR são baixados no primeiro uso, com o tamanho dito antes e o sha256 conferido
depois.

### 2.1 AppImage — um arquivo, qualquer distro

```bash
chmod +x /tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage
/tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage
```

Sem FUSE instalado (ou dentro de um contêiner), extraia e rode:

```bash
/tmp/jarvis-dist/Jarvis-0.0.0-x86_64.AppImage --appimage-extract
./squashfs-root/AppRun
```

**Requisito da máquina:** o AppImage traz o Python e o Qt, mas **não** traz as bibliotecas
gráficas do sistema — trazê-las desta máquina subiria o piso de glibc e quebraria a promessa
de rodar em distro antiga. Se o Qt reclamar de `libxcb-cursor` ou parecido:

```bash
# Fedora/Nobara
sudo dnf install glib2 krb5-libs mesa-libGL mesa-libEGL libxkbcommon libxkbcommon-x11 \
    xcb-util-cursor xcb-util-wm xcb-util-keysyms fontconfig freetype dbus-libs
# Debian/Ubuntu
sudo apt install libglib2.0-0t64 libgssapi-krb5-2 libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libfontconfig1 libfreetype6 \
    libdbus-1-3
```

### 2.2 `.deb` — Debian e Ubuntu

```bash
sudo apt install /tmp/jarvis-dist/jarvis_0.0.0_amd64.deb
jarvis            # ou pelo menu de aplicativos
sudo apt remove jarvis
```

As bibliotecas do Qt entram como **dependência declarada**: o `apt` resolve sozinho.

### 2.3 `.rpm` — Fedora e Nobara

```bash
sudo dnf install /tmp/jarvis-dist/jarvis-0.0.0-1.x86_64.rpm
jarvis
sudo dnf remove jarvis
```

### 2.4 Onde cada coisa é instalada

| caminho | o que é |
|---|---|
| `/usr/lib/jarvis/python/` | o Python relocável e as dependências (o Qt fica em `.so` separados, substituíveis — obrigação da LGPL) |
| `/usr/bin/jarvis` | o lançador |
| `/usr/share/jarvis/` | os dados do produto (`licenses/`, `schemas/`, `tabelas/`, `catalogo/`) |
| `/usr/share/licenses/jarvis/` | LGPL-3.0, GPL-3.0, BSD-3 do SecretStorage, Apache-2.0 e o `NOTICE` |
| `/usr/share/applications/` e `/usr/share/icons/hicolor/` | o `.desktop` e os ícones |
| `~/.cache/jarvis/vozes/` | os modelos baixados no primeiro uso (não vêm no pacote) |
| `~/.config/jarvis/jarvis-voz.toml` | a sua configuração |

---

## 3. O que ainda **não** foi verificado (e só você pode verificar)

1. **microfone e alto-falante reais.** Nenhum dispositivo foi aberto por este código; o
   PortAudio nem está instalado aqui;
2. **barge-in perceptível ao ouvido.** A nossa fila esvazia no mesmo tique, mas a fila do
   *driver* não é nossa: `limpar` aborta o fluxo sem conseguir dizer quantas amostras o
   sistema ainda tinha para tocar. Isso é o aceite do F1-16;
3. **qualidade da voz com `epitran`.** A fonemização passou a marcar tônica por regra (antes
   não marcava nenhuma) e cobre todo o inventário da voz — mas se **soa bem** é o seu ouvido
   que diz;
4. **WER do ASR em pt-BR**, local ou na Groq: nenhum model card publica, e ninguém mediu aqui;
5. **ferramentas com o `claude -p` de verdade, e abrir site de verdade** (ver o fim da seção
   0.1; abrir **app** de verdade foi feito com o KCalc, seção 0.0d);
6. **chamada real à nuvem.** Toda a suíte fala com um servidor falso em porta efêmera; sob
   `CI=1` o código **recusa** falar com serviço de verdade. Uma chamada real à Groq (ASR, turbo)
   foi feita em 2026-10-17 com áudio sintético e funcionou; **ElevenLabs e Edge** e o
   `whisper-large-v3` ainda não foram exercitados ao vivo por este código, nem a Groq com a sua
   voz no microfone.

## 4. Como reportar

Rode e me mande, nesta ordem:

```bash
uv run jarvis-voz --diagnostico > /tmp/jarvis-diagnostico.txt 2>&1
uv run jarvis-voz --texto                    # se o áudio não subir
uv run jarvis-voz                            # o laço de voz
```

O que ajuda no relato: **o que você ouviu** (robótico? atropelado? tônica no lugar errado?), a
linha `[ouvi … · asr … · resposta … · 1º pedaço … · fala …]` que aparece depois de cada turno,
e o `/tmp/jarvis-diagnostico.txt`. Se travar, `Ctrl+C` e me diga em que parte da frase estava.

Áudio só se você quiser: nada é gravado por padrão.
