# Notas de implementação da F1 (executor)

Decisões de implementação, divergências e **limites do que foi verificado** durante os cartões
da F1. O que muda contrato está marcado como **emenda proposta** — a SPEC só muda por ADR.

Regra desta fase, do próprio mapa de cartões: na ausência do dono, o cartão publica o **piso de
software**, com essa etiqueta, e segue. Número de hardware real não se estima.

**Autor:** executor · **Início:** 2026-10-15

---

## F1-01 — banco de teste de áudio sem microfone

### O tempo entra pela porta, não pelo `time.monotonic_ns()`

`src/jarvis/relogio.py` tem `Relogio` (protocolo), `RelogioDoSistema` e `RelogioFalso`. Quem
olha o tempo no caminho de áudio recebe um relógio; nada chama o relógio global direto. As duas
fontes de teste também **ritmam** a entrega por ele (`dormir(20 ms)` antes de cada quadro):

- com `RelogioDoSistema`, um WAV de 1,7 s leva 1,7 s para atravessar a cascata;
- com `RelogioFalso`, atravessa instantaneamente e **com os mesmos carimbos** em toda execução.

É isso que faz a asserção de latência ser exata em vez de "± o que o CI estava fazendo":
`tests/unit/audio_io/test_replay.py` afirma `instantes_ms == [20, 220, 820, 1120, 1520]` e que
todo instante é múltiplo de 20 ms, sem nenhum `sleep` real.

### Três implementações atrás da mesma interface

`FonteDeAudio` e `SumidouroDeAudio` são protocolos (`fontes.py`, `sumidouros.py`), com
implementação de `arquivo` (WAV PCM16 mono 16 kHz), `sintetico` (gerador por semente) e
`dispositivo` (real). A escolha vem de `JARVIS_AUDIO_BACKEND`; **valor desconhecido é erro**, não
silêncio com padrão, e o padrão de quem não disse nada é `sintetico` — ninguém abre a placa de
som do dono por omissão.

O WAV fora do formato do caminho de captura (8 kHz, estéreo, 8 bits) é **recusado na abertura**
com a lista do que estava errado, em vez de ser reamostrado por engano: reamostragem silenciosa
mudaria o número que a F0-04 mediu.

### A proibição do CI mora no código, não só na fixture

`proibir_dispositivo_em_ci` recusa com `CI` ligado (`1|true|yes|on|sim`), e a fixture *autouse*
de `tests/conftest.py` liga `CI=1` na suíte inteira. São duas camadas de propósito: a fixture
protege os testes que ainda nem foram escritos; a função protege o produto. Os dois caminhos
têm teste, inclusive o de fora do CI — onde a recusa **muda de motivo** (sem backend real
instalado, declarado no próprio erro).

### O detector desta cascata não é o VAD

Para a trilha ter uma decisão a registrar, existe `DetectorDeEnergia` (limiar em dBFS, sem
histerese). **Não é o VAD do projeto**: o `silero-vad` com histerese e janela de 512 amostras é
o cartão F1-05. Todo relatório que usar este detector diz o nome dele.

Armadilha que custou iteração: com o envelope silábico indo a zero entre sílabas, o detector sem
histerese oscilava a cada sílaba e a trilha virava 13 eventos de ida e volta. O remédio certo foi
**o gerador parecer com voz** (piso de 0,3 no envelope) e não dar histerese ao detector antes do
cartão dele — fala humana não cai para o silêncio digital entre sílabas. A trilha passou a ter
exatamente os 5 eventos do roteiro.

### A trilha guarda decisão, não ruído

`EventoDeTrilha` carrega `type`, `epoch`, `ts_mono_ns` e as chaves essenciais do payload; ficam
de fora `event_id` (uuid v7) e `ts_wall`, que mudam a cada execução sem significar nada. Float
vai arredondado a 3 casas, para formatação não virar divergência. `comparar` devolve a
**primeira** divergência com índice, chave e os dois valores — e trilha mais curta é divergência,
não empate.

### Determinismo é entre execuções na mesma máquina

O gerador é `random.Random(semente)` (Mersenne Twister, igual em toda plataforma) **mais**
`math.sin` (libm do sistema). Então o aceite comparado é "duas execuções na mesma máquina dão a
mesma trilha", que é o que o cartão pede; hash fixo entre sistemas operacionais **não** é
afirmado em nenhum teste, de propósito — seria um teste que quebra no Windows por motivo que não
é o nosso.

### Armadilha achada de fora do cartão: a suíte reescrevia medição publicada

`tests/unit/test_harness_captura.py` rodava o harness da F0-04 em amostra pequena e ele
publicava em `docs/medicoes/` — então **todo `pytest` substituía o CSV e o relatório de
n = 10 000 por um de n = 200**, e o repositório ficava sujo depois de qualquer execução. Como
este cartão é justamente o banco de teste, o conserto entrou aqui: `tools/harness_captura.py`
ganhou `--saida` (padrão `docs/medicoes`) e o teste de fumaça escreve em pasta temporária.
Medição publicada é dado comitado; teste não a reescreve.

### A medição da F0-04 foi refeita, porque a publicada era a de fumaça

Depois do conserto, ficou claro que o dano já estava **comitado**: `docs/medicoes/f0-04-captura.*`
no repositório trazia `n = 200`, **1 execução** e três braços, enquanto a ADR-0014 cita
`n = 10 000`, **3 execuções** e quatro braços. A medição de verdade tinha sido substituída por
uma execução de fumaça em algum `pytest` da F0, e o CSV publicado deixou de sustentar a decisão
D1.

O harness foi executado de novo, com os quatro braços (baixei o `silero_vad.onnx` — MIT, já
verificado na porta de licença, fora do repositório). Os números da ADR se sustentam:

| braço | ADR-0014 (p95) | reexecução (p95) |
|---|---:|---:|
| `rust-std` | 0,0003 ms | 0,0003 ms |
| `python-numpy` | 0,0105 ms | 0,0103 ms |
| `python-onnx` (silero) | 0,110 ms | 0,1129 ms |
| `evento-no-barramento` | 0,384 ms | 0,3842 ms |

Ou seja: a conclusão de D1 (0,575 ms p95 = 0,72% do SLO-1) continua válida; o que estava
perdido era a **procedência** publicada, e ela voltou.

### Não verificado (exige hardware real)

- **Jitter de captura, *xruns*, latência e período do driver (PipeWire/WASAPI) e deriva de
  relógio do dispositivo: nada disso foi medido.** Nenhum dispositivo de áudio real foi aberto
  por este código — `FonteDeDispositivo` e `SumidouroDeDispositivo` existem como adaptadores que
  **recusam com motivo** em vez de devolver silêncio e fingir captura. O backend real entra com o
  microfone do dono (F1-13/F1-16).
- A suíte roda em Linux. O job `windows-latest` do CI continua **nunca executado** (sem remoto;
  ver notas da F0): o que roda nos dois sistemas é afirmação de código (só `wave`, `array`,
  `math`, `pathlib` da biblioteca padrão), não de execução.

---

## F1-02 — corpus sintético de turno (500 pausas)

### A licença mudou a escolha de engenharia

O cartão dizia "áudio por TTS de licença permissiva (`rhasspy/piper-voices`, MIT)". A porta de
licença no caminho óbvio **barrou** o caminho óbvio:

- **`piper-tts` do PyPI é GPL-3.0-or-later** (1.8.0). A reescrita `piper1-gpl` liga o espeak-ng,
  e por isso o pacote inteiro é copyleft forte. Colocar isso no caminho de um produto Apache-2.0
  que o dono quer poder licenciar comercialmente é contaminação — e não é decisão de uma
  dependência, é decisão do dono.
- O que **não** é copyleft: a voz (repositório MIT, dataset CC0) e o `onnxruntime` (MIT). A voz
  do piper é um **VITS em ONNX**: dá para sintetizar lendo o `.onnx` direto, sem o pacote GPL.
- Sobrou um pedaço GPL inevitável: o **fonemizador**. O `espeak-ng` (GPL-3.0, binário do
  sistema) roda **só** na geração do corpus, em processo separado, e nunca é ligado ao produto.

Então a porta de licença ganhou um registro novo, `licenses/ferramentas-externas.toml`, e a
regra que o faz valer: **copyleft forte com estado `em_uso` bloqueia; `fora_do_produto` avisa**;
não comercial bloqueia em qualquer estado (dado gerado por ferramenta não comercial é dado
contaminado). Há teste para as três situações. `--online` confere os dois registros novos na
origem: voz `mit`, espeak-ng `GPL-3.0`.

**Voz verificada voz por voz** (ADR-0012), nos MODEL_CARD de origem: `faber`, `cadu` e `jeff`
têm dataset **CC0**; `edresson` é **CC BY 4.0** (atribuição obrigatória) e por isso **não** foi
escolhida, apesar de ser a única nativa em 16 kHz. Escolhida: `pt_BR-faber-medium`.

### Determinismo: o ruído do VITS tinha de sair

`onnxruntime.set_seed` só vale **na criação da sessão**. Com uma sessão compartilhada (que é o
que torna 500 sínteses viáveis — 500 itens em ~3 min), a mesma frase saía diferente a cada
chamada, e o aceite (c) do cartão cairia. Medido: com `set_seed` por item e sessão
compartilhada, dois hashes diferentes; com `noise_scale = 0` e `noise_w = 0`, **hash idêntico
entre processos**, com ou sem semente.

A síntese do corpus roda então sem ruído, e a variação de prosódia que sobra é o **ritmo**
(`length_scale` sorteado por item), que é entrada do modelo e não RNG. Custo declarado no
README do corpus: voz menos expressiva do que o piper padrão, o que **favorece** um detector
semântico — mais uma razão para nenhum número de SLO-4 ou SLO-9 sair deste material.

### O áudio é derivado; o rótulo é o dado

47 MB de WAV não entram no repositório (o `.gitignore` já proibia `corpus/turnos/audio/`). O que
é versionado é `rotulos.jsonl` (500 linhas, 294 KB) com o `sha256` de cada arquivo. Isso exigiu
duas conferências diferentes, e a diferença entre elas está em teste:

- `tools/corpus.py verificar` pega **arquivo alterado** (manifesto + sha256 do rótulo, quando o
  `.wav` existe na máquina);
- `tools/corpus_sintetico.py --verificar` pega **gerador que mudou**: regenera a partir do
  rótulo (semente, texto antes e depois da pausa, duração da pausa) e compara o sha256.

Para a regeneração ser possível a partir do rótulo, o formato ganhou `texto_antes` e
`texto_depois` — e com eles uma invariante dura, em teste: pausa de fim de turno **não tem**
continuação; pausa no meio da frase **tem**. Se o dono continuou falando, não era fim de turno.

### `split` que não dá para escolher depois

Regra 5 do corpus: o 70/30 é decidido na criação. No sintético isso virou **verificável**: o
split sai de `sha256(semente:id)` ordenado e cortado em 70%, então um split trocado a dedo na
hora de medir não bate e o verificador recusa, dizendo qual era o da criação. 350/150 no corpus
comitado.

### O prefixo é ambíguo de propósito

Dos 90 enunciados completos, 87 também aparecem como **prefixo** de um enunciado maior, com a
pausa no meio. E as faixas de pausa se sobrepõem (300–900 ms no fim de turno, 200–1200 ms na
hesitação). Sem essas duas coisas, um limiar fixo de silêncio acertaria quase tudo e a
comparação do F1-07 não mediria nada.

### Não verificado

- **Nada de voz humana.** Este corpus é voz de máquina: não fecha SLO-4 nem SLO-9 (as três
  razões estão em `docs/F1-tarefas.md` e no README do corpus), e **nenhum** item tem `termo` —
  por construção e com teste.
- **WER e detector semântico não foram medidos** aqui: é F1-06 e F1-07.
- **O corpus comitado foi gerado com a voz piper nesta máquina.** O CI não tem o `.onnx` nem o
  espeak-ng, então o que o CI exercita é a voz **paramétrica** (sem modelo), que prova
  determinismo, rótulos e split. A regeneração bit a bit do material piper só é reproduzível
  onde existem a voz e o espeak-ng — e, como a inferência é CPU, só é afirmada **nesta
  máquina**; em outro CPU/BLAS o hash pode mudar.
- O job `windows-latest` continua nunca executado (sem remoto).

---

## F1-03 — `audio-io`: quadros de 20 ms, playback cancelável e `played_ms` real

### O bug que o aceite (a) pegou: byte não é amostra

`amostras_enfileiradas` somava `n_amostras` (amostras) com `_consumido_do_pedaco` (bytes). Com
800 ms enfileirados e 200 ms tocados ela dizia 600 ms de sobra onde havia 600 ms… de uma conta
errada que só coincide quando o número é par de propósito. O teste do aceite (a) — "o resto
nunca aparece em nenhum evento" — foi o que derrubou. Conserto no código, com o comentário
dizendo qual teste pegou.

### `played_ms` é o que o sumidouro consumiu, não o que oferecemos

O `tick` avança pelo **retorno** de `escrever`, não pelo tamanho da fatia. A diferença só
aparece com dispositivo saturado (aceita menos de um quadro), e é justo aí que `played_ms`
mentiria para o histórico (§3.3 regra 4). Há um sumidouro de teste que aceita **metade** do
quadro, e o teste prova que o progresso acompanha o que saiu: 10 ticks = 100 ms, não 200 ms.
O harness mede esse erro: **0,0000 ms** em 1 000 cancelamentos.

### `PlaybackProgress` é fato, não hipótese

No barramento (F0-02) `PlaybackProgress` **não** entra no coalescing: perder um muda o
histórico. Então ele sai nos dois momentos que mudam o histórico — fim de pedaço e
cancelamento — e não a cada 20 ms. Progresso periódico para interface existe
(`intervalo_de_progresso_ms`) e está **desligado por padrão**: 50 fatos por segundo seria
ruído, não informação.

### Quem emite `Cancel` não é o `audio-io`

A §3.2 fixa a origem canônica: `Cancel` é do `agentd`. O `audio-io` **reage** — esvazia a fila
no mesmo tick e publica o `played_ms` do pedaço truncado. Isso virou teste de integração com
processos de verdade: `audio-io --capturar --enfileirar-ms 2000` + `agentd`; a captura vê
`speech_started` aos 220 ms do roteiro, o `agentd` emite `Cancel`, e no log aparece **um** só
`PlaybackProgress` depois do `Cancel`, com ≤ 200 ms tocados dos 2 s enfileirados.

### O laço do processo lê o barramento sem bloquear

O esqueleto do F0-03 era "recebe evento → reage". Isso não serve para quem fica perto do
dispositivo: um `Cancel` que chega enquanto esperamos evento não pode esperar o próximo quadro
para esvaziar a fila. O laço do `audio-io` é captura → playback → barramento **com
`timeout=0`**, e o ritmo de 20 ms vem da fonte, que dorme no relógio injetado.

A captura de verdade fica atrás de `--capturar` (padrão desligado) para não mudar a cadeia que
o aceite do F0-03 afirma. No v0, quem liga a captura é quem sobe a sessão; PTT e indicador de
microfone são o cartão F1-13.

### Privacidade corta na fonte

Com privacidade ligada, o laço **não puxa quadro**: o teste conta as amostras que saíram da
fonte (um embrulho que conta) e elas param de crescer. Ao ligar no meio da fala sai **um**
`AudioActivity(speech=false)` com energia no piso — para ninguém no barramento continuar
achando que o dono está falando — e depois nada. A proibição não é filtro de interface.

### Piso publicado (aceite (e))

`docs/medicoes/f1-03-audio-io.{csv,md}`, 10 000 quadros por execução, 3 execuções, etiqueta
**piso de software, sem dispositivo**:

| caminho | p50 | p95 |
|---|---:|---:|
| `captura→AudioActivity` | 0,2610 ms | 0,2826 ms |
| `quadro→decisão (sem evento)` | 0,0155 ms | 0,0158 ms |
| `Cancel→fila vazia` | 0,5413 ms | 0,5660 ms |

O achado da F0-04 se repete: o custo é a **fronteira**, não a aritmética. Decidir sobre o
quadro custa 0,016 ms; transformar a decisão em evento validado custa 0,26 ms — 17× mais. E
esvaziar a fila custa 0,57 ms porque o caro é o `PlaybackProgress` (envelope + validação), não
o `clear()` da fila.

### Não verificado (exige hardware real)

- **SLO-1 de verdade**: este é o piso do nosso código sobre arquivo. Do microfone ao evento
  faltam AEC (F1-04), VAD (F1-05) e o hardware.
- **Latência do caminho de saída e cancelamento perceptível ao ouvido**: a fila do driver não é
  a nossa fila. Esvaziar a nossa em 0,57 ms não garante que o alto-falante parou (F1-10 piso,
  F1-16 aceite).
- **Jitter de captura, xruns, período do driver**: nenhum dispositivo foi aberto.
- Windows: o código é só biblioteca padrão, mas rodou só em Linux.

---

## F1-04 — AEC / NR / AGC com referência de loopback

### A biblioteca do cartão não existe (verificado, não suposto)

O cartão sugeria `webrtc-audio-processing` (BSD-3) ou `speexdsp` (BSD). Os dois foram
verificados no PyPI e **nenhum passa**:

| candidato | o que tem no PyPI | por que não serve |
|---|---|---|
| `webrtc-audio-processing` | 0.1.3 (2018): `sdist` + rodas cp27/cp36 armv7 | sem roda para CPython 3.12 e sem Windows → P11 |
| `speexdsp` | 0.1.1, só `sdist` (precisa de Cython e dos cabeçalhos) | não compila sem dependência de sistema; e é NR, não AEC |
| `speexdsp-ns` | rodas cp312, **só** manylinux | sem Windows → P11; e faz NR, não AEC |

Então a cadeia é **nossa**, em `numpy` (BSD-3, com roda para Linux e Windows em CPython 3.12),
e `numpy` virou dependência do produto. O custo está declarado: é um AEC honesto de filtro
adaptativo por blocos no domínio da frequência (PBFDAF), não o WebRTC — sem processamento não
linear, sem detector de duplo-falar de nível de produto, sem *comfort noise*.

### Dois bugs que a medição pegou, não a leitura do código

1. **Congelamento eterno do filtro.** A proteção de duplo-falar comparava a energia do resíduo
   com a do **eco estimado**. No primeiro bloco o eco estimado é zero (pesos zerados), então a
   comparação dizia "duplo-falar" para sempre e o filtro nunca adaptava: **ERLE 0,0 dB nas nove
   condições**. A comparação certa é com a **referência** (o eco não pode ter mais energia do
   que o que saiu no alto-falante).
2. **Normalização escalar.** O NLMS normalizava pela potência **total** da referência vezes o
   número de partições, e o passo efetivo ficava centenas de vezes menor do que precisa. A
   normalização é **por bin**.

### O AGC desfazia o trabalho da AEC

Com AEC ligada, o resíduo fica em -67 dBFS. O AGC, com limiar de silêncio de -60 dBFS,
**perseguia o alvo em cima do resíduo**: empurrava para -49 dBFS e o detector disparava em 20 a
30 quadros de 250 na condição de eco mais forte. Ou seja: a AEC cancelava e o AGC trazia de
volta. O limiar de silêncio do AGC passou a ser **o mesmo do detector** (-45 dBFS), com teste
que prova que os dois números são um só. Depois disso: **zero disparos nas nove condições**.

### Números publicados (`docs/medicoes/f1-04-aec.md`)

8 s de áudio por condição (400 quadros), 3 execuções, nove condições:

| | ERLE total | ERLE convergido | converge em | fala SEM AEC | fala COM AEC |
|---|---:|---:|---:|---:|---:|
| melhor caso (240 ms, -20 dB) | 27,5 dB | 38,9 dB | 340 ms | 178/250 | **0/250** |
| pior caso (60 ms, -6 dB) | 23,5 dB | 33,9 dB | 200 ms | 250/250 | **0/250** |

Deriva de ±100 ppm (aceite (d)): saída finita, amplitude limitada, ERLE ainda 21,8 e 22,7 dB —
degrada, não trava nem estoura.

### `aec_ok` é fato; `Cancel` é decisão, e é do `agentd`

A §3.2 fixa a origem canônica: `Cancel` é do `agentd`. Então o `audio-io` **relata**
`aec_ok=false` com motivo (`dispositivo_trocado`, `taxa_diferente`, `referencia_ausente`,
`referencia_atrasada`) e o `agentd` transforma isso em `Cancel(reason: aec_fail)` — uma vez, não
a cada quadro. Não foi preciso emenda à SPEC.

Duas consequências implementadas: a captura publica `AudioActivity` **quando `aec_ok` muda**,
mesmo sem transição de fala (senão o `agentd` nunca saberia); e o `audio-io` **pausa** o playback
enquanto `aec_ok` é falso, sem descartar a fila — continuar falando sem referência é o caminho
curto para o assistente se interromper sozinho.

### Não verificado (exige o ambiente do dono)

- **Eco real de alto-falante aberto, no volume de uso.** O eco sintético é **linear**: é limite
  **inferior** de dificuldade. Alto-falante barato em volume alto distorce, e distorção não
  linear nenhum filtro linear cancela.
- **Duplo-falar real** (os dois falando junto, com voz humana). O que foi medido é fala
  sintética somada ao eco, e o congelamento do passo é proteção simples, não o detector do
  WebRTC.
- **Headset vs alto-falante, e cauda longa da sala.**
- **O caminho de `aec_fail` com processos de verdade** foi provado em peças (cadeia, captura,
  `Percepcao` do `agentd`, pausa da fila); forçar a troca de dispositivo dentro do processo
  exigiria uma opção de linha de comando só para teste, e isso não entra no produto.
- Windows: `numpy` tem roda para os dois sistemas, mas tudo rodou só em Linux.

---

## F1-05 — VAD barato, `speech_started` e a regra 1 do epoch

### O silero v5 precisa de 64 amostras de contexto, e isso não está no formato

A entrada do ONNX é dinâmica (`[None, None]`), então nada no arquivo diz o tamanho certo. O
wrapper oficial do `silero-vad` prepende **64 amostras do bloco anterior** à janela de 512 (a
entrada real tem 576) e guarda a cauda como contexto do bloco seguinte. Sem isso o modelo
responde `0,001` para fala de verdade — ou seja, **o VAD nunca dispara** — e a primeira
medição deste cartão saiu com o VAD mudo em áudio de voz.

Dois efeitos práticos ficam registrados: o quadro de 20 ms **não** alinha com a janela de
32 ms, então uma decisão pode atrasar até uma janela; e o atraso medido do silero (p50 61 ms,
p95 80 ms sobre o início verdadeiro) já contém esse desalinhamento.

### A verdade de referência tem de vir do gerador, não do áudio

Medir "recall de início de fala" exige saber **quando** a fala começa. Estimar isso do próprio
áudio por energia seria medir um detector contra outro detector. Então o rótulo do corpus
ganhou dois marcos — `inicio_fala_ms` e `inicio_pausa_ms` —, que o gerador conhece porque foi
ele que colocou o silêncio e sintetizou o prefixo. O corpus foi **regenerado** (mesma semente,
mesmos 500 itens) e o validador passou a exigir os marcos, com a invariante de que a pausa vem
depois da fala. É o mesmo dado que o SLO-4 do F1-07 vai usar.

### Histerese assimétrica, e por quê

Ligar custa **1 quadro** (20 ms): atrasar `speech_started` é atrasar o barge-in, que é o SLO-2.
Desligar custa 10 quadros **mais** 200 ms de *hangover*: pausa entre palavras não é fim de
fala. A política está em `Histerese` (dado), não espalhada em `if`.

### Números medidos (`docs/medicoes/f1-05-vad.md`), 100 itens do corpus, 3 execuções

| | recall início | precisão início | atraso p50 | atraso p95 | recall/quadro | precisão/quadro |
|---|---:|---:|---:|---:|---:|---:|
| `silero-vad@v5` | 1,000 | 1,000 | 61 ms | 80 ms | 0,966 | **1,000** |
| `energia@1` | 1,000 | 1,000 | 31 ms | 51 ms | 0,985 | 0,999 |

Piso de SLO-1 com a cadeia **real** (AEC → NR → AGC → VAD → envelope validado):

| caminho | p50 | p95 |
|---|---:|---:|
| cadeia + silero, **com** evento | 0,7652 ms | 0,8508 ms |
| cadeia + silero, sem evento | 0,3091 ms | 0,3721 ms |
| cadeia + energia, com evento | 0,5327 ms | 0,6208 ms |

**Gatilho da ADR-0014 (aceite (e)): não abre.** Pior p95 = 0,85 ms contra 80 ms de orçamento
(1,1%). A F0-04 havia medido VAD 0,1129 ms + evento 0,3842 ms em braços separados; a cadeia
junta dá 0,85 ms p95, e a diferença é a AEC/NR/AGC que a F0-04 não tinha — **reconfirmado, com
o custo novo nomeado** (aceite (d)).

### Achado que o F1-07 vai precisar: o hangover do silero é maior que a pausa de fim de turno

O `silero-vad` só declara silêncio **575 ms** (p50) depois do início da pausa, e em 51 dos 100
itens o arquivo acabou antes de ele desligar. A pausa de fim de turno do corpus está entre 300
e 900 ms. Conclusão que vale escrever antes de o F1-07 começar: **detector de turno não pode
esperar o "fala terminou" do VAD** — quando esse evento chega, a janela de decisão já passou.
O detector tem de olhar a pausa em curso, não o desligamento do VAD.

### Não verificado

- **SLO-1 com microfone**: é o aceite (a) da F1 e sai no F1-16. Jitter, período do driver e
  ruído de entrada são do hardware; aqui tudo veio de arquivo.
- **VAD em ruído real da casa do dono**: o corpus tem ruído rosa sintético em ~30% dos itens.
  Televisão, conversa ao fundo e sala são outra coisa.
- **Fim de turno**: o VAD não decide turno (§2). O hangover desta tabela é política de fala.
- O peso do silero **não** é versionado: sem ele, `vad_do_ambiente()` cai no VAD de energia (com
  o nome dele no relatório) e os testes do silero são pulados. O CI pula, e isso está dito.
- Windows: o código é portável, a medição foi só em Linux.
