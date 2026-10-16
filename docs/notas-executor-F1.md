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

---

## F1-06 — ASR incremental, com a atribuição CC-BY como teste

### O alerta de fato do cartão: resolvido na origem

O cartão mandava resolver, dentro dele, se o `parakeet` serve para pt-BR. Verificado na origem
(API do Hugging Face, `tools/license_gate.py --online` confere o mesmo campo):

| modelo | licença | idiomas | veredito |
|---|---|---|---|
| `nvidia/parakeet-tdt-0.6b-v2` | CC-BY-4.0 | **1** (`en`) | **não serve** para pt-BR; fica registrado para ninguém escolher por engano |
| `nvidia/parakeet-tdt-0.6b-v3` | CC-BY-4.0 | **25**, com `pt` | a `[SUPOSIÇÃO]` do arquiteto **se sustenta**; é o candidato de pt-BR |
| `openai/whisper-large-v3` | Apache-2.0 | 99, com `pt` | controle, sem obrigação de atribuição |
| `openai/whisper-small` | Apache-2.0 | 99, com `pt` | **o que rodou** nesta medição |

O `parakeet-tdt-0.6b-v3` **não foi executado**: o runtime é o NeMo, pesado e orientado a GPU.
Isso está declarado na tabela de licenças, no relatório e aqui — e a escolha entre ele e o
whisper é do F1-16, com voz real.

### A atribuição virou portão, em três lugares

CC-BY exige atribuição **no produto**. Então ela está em `NOTICE`, no `README.md` e na tela
"sobre" da `ui` (`jarvis.ui.sobre`, que monta o texto a partir de `licenses/modelos.toml` — a
mesma fonte da porta, para a lista não envelhecer à mão). E
`tools/license_gate.py --verificar-atribuicao` **falha** se algum modelo com atribuição
obrigatória não aparecer nos três. Está no `verificar.py` e no CI.

Vale para `em_uso` **e** `candidato`, de propósito: a CC-BY pede atribuição em qualquer uso ou
distribuição de material derivado, e as tabelas de medição que publicamos são material
derivado. Só `barrado` fica de fora — ele existe no registro para ficar fora.

O aceite (d) é um teste que roda o portão como processo, apaga a linha do `NOTICE`, exige
código de saída 4 e restaura o arquivo. Apagar a linha quebra o CI de verdade, não por
convenção.

### Incremental sem modelo streaming: janela crescente + acordo de prefixo

O `whisper` transcreve bloco, não fluxo. A cada 200 ms o transcritor refaz a transcrição do
turno **inteiro até agora** e compara com a hipótese anterior; o prefixo em que as duas
concordam é o que já dá para usar, e `stability` é essa fração. "Utilizável" é
`stability >= 0,6`, **escrito antes de medir** (aceite (b)) — mexer no limiar depois de ver o
resultado seria escolher o número.

O coalescing não é esperteza do transcritor: `PartialTranscript` está em `TIPOS_COALESCIVEIS`
desde a F0-02, o barramento derruba dez hipóteses do mesmo instante a uma, e o `s2` ganhou a
reação que faltava (`PartialTranscript → StateRevision`). O teste publica dez parciais em
200 ms na fila e afirma: **uma** sobrevivente, **uma** revisão de estado.

### Lacuna de contrato encontrada (para o dono decidir)

O diagrama da §2 manda "frames + PlaybackProgress" do `audio-io` para o `agentd`, mas **nenhum
dos onze tipos da §3.2 carrega PCM**. Então hoje o ASR é exercitado sobre arquivo (que é o que
o cartão pede) e **não existe caminho de áudio entre os dois processos**. Isso é decisão de
contrato — emenda à SPEC com um canal fora do barramento (memória compartilhada ou socket
dedicado, com o `epoch` no cabeçalho) — e não cabe em um cartão de ASR. Fica registrado para o
F1-10/F1-16 ou para uma ADR própria.

### Números medidos (`docs/medicoes/f1-06-asr.md`), 24 itens do split `calibracao`

| motor | modelo | WER médio | WER p50 | CER | SLO-3 p50 | SLO-3 p95 | atinge SLO-3? | RTF de parede |
|---|---|---:|---:|---:|---:|---:|:--|---:|
| `incremental+faster-whisper@small` | `openai/whisper-small` | 0,089 | 0,000 | 0,027 | 1007 ms | 1362 ms | **não** | 6,02× |
| `incremental+oráculo-do-rótulo@1` | (nenhum) | 0,000 | 0,000 | 0,000 | 345 ms | 457 ms | **não** | 0,00× |

O alvo da SPEC §7 é p50 ≤ 250 ms e p95 ≤ 450 ms (marcado lá como **hipótese, não
compromisso**). Dois problemas diferentes aparecem no mesmo número:

1. **O modelo não cabe no tempo real desta máquina.** RTF de parede 6,02× (p95 8,17×) e de CPU
   25,48×: a janela crescente re-transcreve o turno inteiro a cada passo, então o custo cresce
   com o quadrado da duração. Com `whisper-small` em CPU, **não dá** para rodar ao vivo.
2. **O passo domina o SLO-3, e isso é independente do modelo.** O estudo em
   `docs/medicoes/f1-06-asr-passo.md` roda só o oráculo (custo zero) variando o passo:

| passo | SLO-3 p50 | SLO-3 p95 | atinge o alvo? |
|---:|---:|---:|:--|
| 100 ms | **162 ms** | **257 ms** | **sim** |
| 200 ms | 345 ms | 457 ms | não |
| 400 ms | 1007 ms | 1439 ms | não |

Ou seja: o acordo de prefixo precisa de **dois passos** para existir, então o piso do SLO-3 é
~2× o passo. Com passo de 100 ms o encanamento cabe no alvo; o que sobra como problema é
exclusivamente o custo do modelo.

**Recomendação com número, para o F1-16:** passo de 100 ms **e** ASR *streaming*. Um transducer
como o `parakeet-tdt` decodifica por quadro e não refaz o passado — é a diferença entre RTF 6×
e RTF < 1 —, e o `parakeet-tdt-0.6b-v3` já está verificado na origem para pt-BR (CC-BY-4.0, com
a atribuição já em portão). Não mexi no alvo do SLO-3: ele está marcado como hipótese na SPEC e
quem o recalibra é o dono, com voz real.

### Não verificado

- **WER na voz do dono**, com o microfone e o ruído dele, sotaque, nome próprio e termo do
  domínio: F1-15 (corpus real) e F1-16 (aceite). O WER de 0,089 é sobre **TTS sintético**, que
  é material fácil — piso otimista, e a ressalva está no relatório.
- **SLO-3 ao vivo**: aqui é tempo de **áudio** sobre arquivo. Ao vivo entram captura, AEC, VAD
  e a fila do driver.
- **`parakeet-tdt-0.6b-v3` não foi executado** (runtime NeMo, orientado a GPU) e
  **`whisper-large-v3` também não** (3 GB). Rodou o `whisper-small`, mesma família e licença.
- **n = 24**: amostra equilibrada entre fim de turno e hesitação, declarada na tabela. Medir os
  350 itens do split com esta estratégia custaria ~2 h de CPU, e o número que importa (voz
  real) é de outro cartão.
- Windows: a medição rodou só em Linux.

### Decisão a medir no F1-16: passo de 100 ms + ASR *streaming* (registrada a pedido do dono)

O SLO-3 não foi atingido neste cartão, e a medição separou a causa em duas partes que pedem
decisões diferentes. Fica aqui como **decisão a medir no F1-16**, não como escolha já tomada:

| o que medir no F1-16 | número que motivou | o que esperar |
|---|---|---|
| **passo de 100 ms** no transcritor incremental (hoje 200 ms) | piso do encanamento: 100 ms → p50 162 ms e p95 257 ms (**cabe** no alvo de 250/450); 200 ms → 345/457; 400 ms → 1007/1439 | o acordo de prefixo precisa de **dois** passos, então o piso do SLO-3 é ~2× o passo. Reduzir o passo é a única mudança que move o piso, e não depende de modelo |
| **ASR *streaming*** (transducer) em vez de janela crescente | `whisper-small` em janela crescente: RTF de **parede 6,02×** (CPU 25,48×) — não roda ao vivo nesta máquina | a janela crescente re-transcreve o turno a cada passo e o custo cresce com o quadrado da duração. Um transducer (`parakeet-tdt-0.6b-v3`, CC-BY-4.0, pt verificado na origem) decodifica por quadro e não refaz o passado |

Duas ressalvas que viajam com a recomendação: o passo menor **aumenta** o número de inferências
por turno (com modelo de janela crescente isso piora o RTF, e é por isso que as duas mudanças
andam juntas); e o `parakeet` exige **atribuição no produto**, que já está em portão desde o
F1-06 — trocar de modelo não é só trocar o peso.

O alvo do SLO-3 **não foi mexido**: a SPEC §7 o marca como hipótese, e quem recalibra é o dono
com voz real.

---

## F1-07 — detector de turno: semântico vs silêncio fixo

### A regra de empate está em código, não em prosa no fim do relatório

`aplicar_regra_de_empate` implementa a regra do cartão: o semântico entra só se **não for
pior** em nenhuma das duas dimensões (dentro do IC) e for **estritamente melhor** em pelo menos
uma (fora do IC). Empate dentro do intervalo → fica o `silencio_fixo`. Há teste para os três
casos: empate, vitória por falso corte, e a tentação de aceitar quem melhora o atraso piorando
o falso corte.

O ponto de operação também tem critério declarado antes: no `calibracao`, o limiar de **menor
atraso p50 entre os que têm falso corte ≤ 3%** (alvo do SLO-9); se nenhum alcança, o de menor
falso corte. O número publicado sai do `retido`, com IC de 95% por *bootstrap* de itens.

### O texto do detector é o do ASR, não o do rótulo

Dar ao detector semântico o texto perfeito do rótulo inflaria justo o eixo em que ele está
sendo comparado. Então `tools/curva_turno.py --preparar-texto` transcreve, com o `whisper-small`
do F1-06, o áudio de **cada item até o início da pausa**, e publica o cache em
`docs/medicoes/f1-07-texto-no-corte.csv` — o que torna a curva reproduzível sem o modelo. O WER
desse prefixo é ~0,125, e é com esse texto imperfeito que o semântico trabalha.

### Duas armadilhas de método que apareceram antes de qualquer número

1. **Métrica vazia parece boa.** Na primeira execução de fumaça, o cache tinha só os 87
   primeiros itens do corpus — que são todos de **fim de turno**, porque o gerador escreve essa
   classe primeiro. Resultado: falso corte 0,000 por **vácuo** (não havia item de meio de frase
   para cortar) e o critério escolheu o limiar mais rápido. Agora é erro explícito: split sem as
   duas classes aborta a medição.
2. **Traço constante leva peso.** `estabilidade` é 1,0 em todo o corpus sintético (o cache
   guarda o prefixo já fechado), e o treino lhe dava peso +2,98 — que é viés disfarçado de
   conhecimento. O treino passou a descartar traço de variância zero, dizendo quais descartou.

### O corpus sintético não deixa o semântico ganhar, e isso é da construção dele

Isto precisa estar escrito antes de qualquer leitura da curva: o corpus do F1-02 foi feito com
**prefixo ambíguo de propósito** (87 dos 90 enunciados completos também aparecem como prefixo
de um maior). No instante do corte, o texto de um item de fim de turno e o de um item de meio de
frase são **o mesmo texto**. Então o sinal de texto que um detector semântico exploraria
simplesmente não existe aqui, e sobra a pausa — que é o que o `silencio_fixo` já usa.

Pior: as faixas de pausa que escolhemos (300–900 ms no fim de turno, 200–1200 ms na hesitação)
**invertem a monotonia natural** da pausa neste corpus: pausa acima de 900 ms só acontece em
meio de frase. Em fala real é o contrário — quanto mais longa a pausa, mais provável que o turno
acabou.

Conclusão de método, não de resultado: **esta curva é conservadora para o semântico**. Ela
serve para pegar regressão e para provar que o encanamento e a regra de empate funcionam; ela
**não** é capaz de mostrar o semântico ganhando, e um resultado "fica o silencio_fixo" aqui
**não** é evidência contra o detector semântico. Quem decide isso é o corpus real (F1-15) na
máquina do dono (F1-16). O F1-15 precisa ser gravado **sem** essa inversão: pausa de fim de
turno e de hesitação têm de vir da fala natural do dono, não de faixas escolhidas por nós.

### Números medidos (`docs/medicoes/f1-07-turno.md`), 500 itens, A/B pareado

Curva no `calibracao` (175 itens de fim de turno, 175 de meio de frase):

| detector | limiar | falso corte | atraso p50 | decidiu |
|---|---:|---:|---:|---:|
| `silencio_fixo` | 300 ms | 91,4% | 300 ms | 175/175 |
| `silencio_fixo` | 500 ms | 71,4% | 500 ms | 114/175 |
| `silencio_fixo` | 700 ms | 52,6% | 700 ms | 60/175 |
| `silencio_fixo` | 900 ms | 32,6% | 900 ms | 1/175 |
| `silencio_fixo` | 1200 ms | 0,0% | — | 0/175 |
| `semantico` | 0,3 | 100,0% | 0 ms | 175/175 |
| `semantico` | ≥ 0,5 | 0,0% | — | 0/175 |

No `retido`: `silencio_fixo` a 500 ms deu falso corte **0,680 [0,573; 0,787]**; `semantico` a
0,3 deu **0,587 [0,480; 0,693]** com atraso 0 ms.

**Veredito: INCONCLUSIVO, e fica o `silencio_fixo`.** Nenhum ponto de operação é utilizável —
os dois interrompem o dono em mais de um turno a cada três, contra um alvo de 3%. Comparar dois
pontos inúteis não ordena candidato nenhum.

### Três armadilhas de medição que esta curva pegou (e que eu produzi)

1. **"Nunca decidir" ganhava a comparação.** Limiar de 1200 ms dá falso corte 0,0% — porque
   decide em **zero** itens. A guarda (candidato tem de decidir em ≥ 50% dos itens de fim de
   turno) entrou **antes** de medir, e o relatório agora imprime "—" em vez de "0 ms" onde
   ninguém decidiu: zero ali parecia o melhor resultado possível, e era o pior.
2. **O classificador aprendeu a inversão do corpus.** Com `pausa_s` livre, o peso saiu
   **−1,622**: "quanto mais longa a pausa, menos provável que o turno acabou" — verdade **neste
   corpus** (fomos nós que escolhemos 200–1200 ms para hesitação e 300–900 ms para fim de
   turno), falso na fala humana. O detector virava um degrau: cedia no instante zero ou nunca.
   Monotonia na pausa passou a ser **restrição do modelo** (gradiente projetado, peso ≥ 0),
   declarada como propriedade do fenômeno e não descoberta nos dados.
3. **"Atinge o SLO-4" sem ponto utilizável não é conquista.** Com a monotonia imposta, o peso
   da pausa foi a zero e o semântico passou a ceder **no instante zero**: atraso p50 = 0 ms, que
   "atinge" o SLO-4 por construção, com 59% de falso corte. A regra de empate premiou isso na
   primeira execução real. Agora existe uma guarda explícita: ponto com falso corte fora do
   alvo do SLO-9 **não é candidato**, e o veredito é `INCONCLUSIVO`. A ressalva anda na mesma
   linha do número, no relatório.

### Resposta do aceite (e), com número: o alvo do SLO-9 não se sustenta neste corpus

O alvo **[SUPOSIÇÃO]** de ≤ 3% de falso corte não é alcançado por **nenhum** limiar que ainda
decida: a 900 ms o falso corte é 32,6% e só 1 dos 175 itens decide; a 1200 ms o falso corte é
0% porque ninguém decide. E a razão é a **construção do corpus**, não o detector: com pausa de
hesitação indo a 1200 ms e pausa de fim de turno parando em 900 ms, qualquer limiar que decida
cedo corta hesitação, e qualquer limiar que não corte hesitação não decide nada.

Isso é exatamente o que a SPEC previa ao marcar o SLO-9 como **[SUPOSIÇÃO] a recalibrar com o
corpus pt-BR da F1**. A recalibração é do F1-15/F1-16, e o F1-15 tem de gravar pausa **natural**
— sem faixas escolhidas por nós, que foi o que produziu a inversão.

### O custo da decisão não é o problema

3,2 µs p50 por decisão (o nosso código). O SLO-4 mede tempo de **áudio** — quanto o dono espera
—, não CPU. Confundir os dois faria o relatório parecer ótimo e o assistente parecer lento.

---

## F1-08 — S1: a decisão de 20–100 ms como tabela auditável

### A tabela é dado, e dado inválido é recusado na carga

`tabelas/s1.v1.json`: 13 linhas, avaliadas de cima para baixo, cada uma com `quando`, `entao` e
**`porque`**. A carga recusa, com erro nomeado: condição que não está em `condicoes_aceitas`
(vocabulário fechado, como no barramento e no rótulo do corpus), ação fora das cinco da §2,
linha sem `porque` — porque linha sem porquê não é auditável — e **tabela sem saída padrão**: a
última linha não pode ter condição, senão um estado não previsto deixaria o S1 sem decisão.

Cada linha tem um teste, e há um teste que **compara o conjunto de ids da tabela com o conjunto
de testes**: linha nova sem teste quebra a suíte, em vez de passar sem ninguém notar.

### As cinco ações, e onde ficou o `ceder`

A §2 lista `ouvir | backchannel | ceder | falar | cancelar`. Quatro apareceram naturalmente; o
`ceder` exigiu uma decisão. Ficou assim, declarado na própria tabela: sobreposição **curta** (até
200 ms) enquanto falamos é `ceder` — pode ser o dono dando um "uhum", não tomando o turno, e a
resposta em voo não precisa ser jogada fora; sobreposição **sustentada** é `cancelar`. O epoch
já subiu antes disso pela regra 1 da §3.3, que não espera o S1 — o que o S1 escolhe aqui é o que
fazer com a resposta em voo. Os 200 ms são valor inicial declarado, a calibrar com voz real.

Só **uma** linha leva a `falar` (e um teste garante que continua sendo uma), e só uma produz som
sem ser nossa vez (`backchannel`, com fala longa e `p_eot` baixo).

### As três guardas duras, cada uma numa linha

- **L01, orçamento**: estourou o teto de 100 ms → `ouvir`, nunca `falar`. Teste injeta o atraso
  e confere que a mesma situação que levava a `falar` passa a levar a `ouvir`.
- **L02, epoch morto**: evento de epoch menor que o atual não produz som. O teste varre **todos**
  os estados da tabela com epoch morto e exige que nenhum produza som.
- **L10, sem confiança**: `unknown` nunca vira `falar` — a mesma regra do F1-07.

### Números medidos (`docs/medicoes/f1-08-s1.md`), n = 10 000 por cenário

| cenário | linha | ação | p50 | p95 |
|---|---|---|---:|---:|
| orçamento estourado | L01 | `ouvir` | 0,94 µs | 0,99 µs |
| barge-in | L04 | `cancelar` | 2,56 µs | 2,63 µs |
| nossa vez | L08 | `falar` | 3,25 µs | 3,33 µs |
| esperando | L11 | `ouvir` | 4,39 µs | 4,49 µs |

90 000 decisões no total; pior p95 = **4,49 µs**, que é 0,0045% do teto de 100 ms. O custo
cresce com a posição da linha (a tabela é varrida de cima para baixo), e as guardas estão no
topo — o que é a ordem certa: o caso em que já não há tempo é o mais barato de decidir.

**O orçamento do S1 não é gasto pela tabela.** Ele é gasto pelo que vem antes dela — captura,
AEC, VAD, ASR, detector de turno —, e é por isso que a guarda de orçamento existe: quando o
tempo acabou, a decisão certa é `ouvir`, não `falar` com informação velha.

### Não verificado: nada

Este é o único cartão da F1 que fecha sem ressalva de hardware. A tabela é dado, o estado é
dado, o replay é determinístico sobre a trilha do F1-01 — e o relatório pode afirmar isso sem
nenhuma lacuna de microfone. O que **não** está aqui, por não ser deste cartão: o custo do que
chega ao S1 (está nos relatórios do F1-03 ao F1-07) e a escolha do **que** dizer, que é do `s2`
(F2). Windows: só biblioteca padrão, mas a medição rodou em Linux.

---

## F1-09 — TTS em streaming cancelável, com licença no carregamento

### A política de licença saiu do CI e entrou no produto

O cartão pede que voz com licença fora da permissiva **não carregue**. Isso é verificação em
tempo de execução, então a classificação de licença saiu de `tools/license_gate.py` e virou
`src/jarvis/licencas.py` — uma lista só, usada pelo CI **e** pelo produto, para os dois nunca
discordarem sobre o que é permissivo. `carregar_voz` recusa em três casos, cada um com teste:

- voz **não registrada** em `licenses/modelos.toml` ("licença que ninguém verificou não entra");
- voz **barrada** no registro (é o caso do `coqui/XTTS-v2`: existe lá para ninguém tentar);
- licença **não permissiva** — e aí está o caso do cartão: **CC-BY-SA não carrega**, porque
  *ShareAlike* numa voz contamina o áudio que o produto distribui.

### Interromper no meio da síntese: o pedaço em voo é descartado

O sintetizador consulta o cancelamento **duas vezes** por pedaço: antes de sintetizar e **antes
de escrever**. Quando o `Cancel` chega durante a síntese, o pedaço que acabou de sair do modelo
é **jogado fora** em vez de enfileirado — é isso que faz valer "zero amostra nova no sumidouro
depois do tick". A síntese de um pedaço é atômica (o modelo não é interrompível por dentro), e é
por isso que o **primeiro** pedaço é o mais curto que a prosódia aceita: ele é o pior caso de
trabalho desperdiçado, e também o que atrasa o SLO-5.

### O mapa texto ↔ amostras corta no texto original, não na junção dos pedaços

Primeira versão juntava os textos dos pedaços e devolvia o prefixo — e perdia o espaço entre
eles ("Achei três arquivos,o ma"). Como o aceite (a) do F1-12 compara **caractere a caractere**,
isso teria virado falha lá. O corte agora é uma **posição no texto original**, e há teste de que
todo prefixo devolvido é prefixo do texto e que o fim devolve o texto inteiro.

### Números medidos (`docs/medicoes/f1-09-tts.md`), 40 turnos do corpus

| motor | licença | 1º pedaço p50 | 1º pedaço p95 | piso SLO-5 p50 | RTF |
|---|---|---:|---:|---:|---:|
| `piper-onnx@1.0.0+pt_BR-faber-medium` | MIT | **116,3 ms** | 145,3 ms | 116,3 ms | 0,113× |
| `parametrico@1` (sem modelo, CI) | Apache-2.0 | 17,3 ms | 24,9 ms | 17,3 ms | 0,026× |

O alvo do SLO-5 é p50 ≤ 600 ms e p95 ≤ 900 ms: o **piso de software** cabe com folga de 5×, e o
RTF de 0,113× mostra que a voz acompanha a própria fala sem engasgar. Diferente do ASR do F1-06,
aqui o modelo **não** é o gargalo.

### Pendência de licença do caminho de produto (achado, para o dono decidir)

Verifiquei **voz por voz** as quatro vozes pt-BR do `rhasspy/piper-voices`: todas usam fonemas
do **espeak-ng** (GPL-3.0). Inclusive a `edresson`, que não declara `phoneme_type` e usa o mesmo
inventário IPA (confirmei no `phoneme_id_map`). O `Kokoro-82M` (Apache-2.0) também depende de
fonemizador externo para pt-BR.

No F1-02 isso não era problema: o espeak rodava **fora** do produto, gerando corpus. Aqui é,
porque o TTS roda **no** produto. A arquitetura deixa a fronteira visível em vez de esconder: o
`MotorPiperOnnx` recebe o fonemizador por **injeção**, então a peça GPL aparece na assinatura e
mora em `tools/`. As opções, para o F1-16:

1. **G2P próprio de pt-BR**, treinável no corpus do projeto (pt-BR é regular; o custo é nosso e
   a licença fica limpa);
2. **voz que aceite grafema** (`phoneme_type: text`): nenhuma pt-BR registrada hoje é assim;
3. **outra família de TTS** com fonemização embutida e licença permissiva — a procurar.

Não escolhi: é decisão de licença do produto, e licença é do dono.

### Não verificado (exige hardware real)

- **SLO-5 de verdade**: a fila do dispositivo entra na conta, e é ela que atrasa o primeiro
  áudio audível. O que está medido é piso de software sobre sumidouro de memória.
- **Qualidade e naturalidade da voz pt-BR**: é julgamento do dono, não teste. Ele escolhe a voz
  no F1-16, ouvindo os candidatos.
- **Kokoro-82M não foi executado** (registrado, Apache-2.0): não resolveria a pendência de
  fonemização, que é o que importa decidir.
- Windows: a medição rodou só em Linux.

---

## F1-10 — barge-in ponta a ponta (SLO-2)

### De onde se conta: do início real da fala, não de quando percebemos

O SLO-2 é do ponto de vista de quem fala. Se o VAD leva 80 ms para ter certeza, esses 80 ms são
do dono — contar do instante em que o nosso VAD percebeu seria medir o nosso código e chamar o
resultado de experiência do dono. O rótulo do corpus sabe onde a fala começa (`inicio_fala_ms`,
criado no F1-05 justamente para isto), e é de lá que a conta sai.

### Dois relógios, e o veredito usa o conservador

O atraso de **áudio** (quadros de 20 ms) é o que o dono sente; o **custo de CPU** dos saltos é o
que gastamos para reagir. Em tempo de áudio, os cinco saltos depois da detecção caem todos no
mesmo tique e apareciam como **0 ms** — o que é verdade e engana. O número do veredito é a soma:
tempo de áudio **mais** custo de CPU.

### Números medidos (`docs/medicoes/f1-10-barge-in.md`), 600 interrupções por VAD

| VAD | n | SLO-2 p50 | SLO-2 p95 | atraso do VAD p50 | custo de código p95 | p50 ≤ 80? | p95 ≤ 150? |
|---|---:|---:|---:|---:|---:|:--|:--|
| `energia` | 600 | 52,6 ms | 73,8 ms | 51,0 ms | 4,0 ms | sim | sim |
| `silero-vad` | 600 | **81,6 ms** | **105,7 ms** | 81,0 ms | 1,0 ms | **não** (1,6 ms acima) | sim |

**O gatilho da ADR-0014 não abre:** ele é definido sobre o **p95 ≤ 150 ms**, e o pior p95 medido
é 105,7 ms. O que não se cumpre é a **meta** de p50 ≤ 80 ms com o `silero`, por 1,6 ms. Separei
os dois vereditos na tabela de propósito: "passou de 80 ms" e "estourou o SLO" são coisas
diferentes, e misturá-las transformaria uma meta em alarme.

**Quem gasta o SLO-2 é o VAD, não o caminho de cancelamento.** Os cinco saltos depois da
detecção custam de 1 a 4 ms somados. O resto é o tempo que o VAD leva para ter certeza — e aí
está uma troca real para o dono decidir no F1-16: o limiar de energia cala **29 ms mais rápido**
(52,6 contra 81,6 ms p50) e o `silero` não produz falso positivo por quadro (F1-05: precisão
1,000 contra 0,999). É escolher entre calar mais rápido e calar por engano.

### Nenhum salto espera o ASR (aceite (b))

Com um transcritor que avança o relógio **2 segundos** dentro da percepção, o SLO-2 medido é
35,7 ms — o mesmo 35,7 ms de antes. Quem garante isso não é a velocidade de ninguém: é a
**ordem** da regra 1, que devolve o `Cancel` como primeiro envelope e só então chama o
transcritor (F1-05).

### Não verificado (exige hardware real)

- **SLO-2 com microfone e alto-falante reais**: é o aceite (a) da F1 e sai no F1-16. O piso de
  software ignora a **fila do driver**, que é exatamente onde o áudio velho sobrevive: o nosso
  `Cancel` esvazia a nossa fila, não a do dispositivo.
- **Cancelar tool de efeito já executada**: não existe no v1 por especulação (§3.3 regra 3),
  então não há o que medir.
- **Voz de verdade no playback**: aqui o TTS é o paramétrico — o que se mede é o caminho de
  cancelamento, e a voz está medida no F1-09.
- Windows: a medição rodou só em Linux.

---

## F1-11 — suíte de cancelamento em 20 pontos

### A lista é arquivo, e cada ponto tem porquê

`jarvis.agentd.turno_completo.PONTOS` tem os vinte pontos nomeados, cada um com o motivo
escrito e as regras da §3.3 que ele exercita. A suíte parametriza por essa lista, então **ponto
novo sem teste é impossível**: o teste nasce do próprio arquivo. E há um teste de que a lista
tem vinte nomes distintos — nome repetido esconderia um ponto não testado.

As três invariantes, conferidas em **todos** os vinte: zero áudio novo no sumidouro depois do
`Cancel` (medido com mais vinte ticks depois de tudo), zero presença do sufixo não tocado no
histórico, zero tool disparada depois do `Cancel`.

### Dois pontos que mediam o vácuo (e o conserto)

1. **`com_fila_cheia` não enchia nada.** A primeira versão enchia a fila de prioridade com
   `PartialTranscript` — que **coalesce** (F0-02): hipótese nova substitui a antiga, e a fila
   nunca passa de um item por banda. O ponto existia e media vácuo. Agora enche com
   `DesktopObservation`, que é **fato** e não coalesce, e o cenário **afirma** que houve recusa
   por fila cheia antes de cancelar.
2. **A exceção da regra 3 passava por motivo errado.** O `ToolResult` era construído com o
   epoch **de agora**, então parecia sempre fresco e "não entrou no estado" nunca era testado de
   verdade. Agora ele carrega o epoch **da chamada** — é isso que o torna `stale` quando o turno
   morreu no meio, e o teste passou a provar o que diz: leitura em voo **pode** terminar, e o
   resultado só entra se o `s2` reavaliar no epoch novo.

### A regra 5 entrou de verdade, não como caixa marcada

Faltava a regra 5 ("'continua' não ressuscita o plano antigo") na cobertura. Em vez de marcar a
regra como coberta, implementei a retomada (`jarvis.agentd.historico.retomar`): ela devolve
**só** o trecho tocado, e a estrutura `Retomada` **não tem campo** para o sufixo não tocado — a
ausência é a garantia. O método `ressuscita()` existe para o teste poder afirmar o negativo.

### Fuzz com semente comitada

1 000 execuções com ponto de interrupção sorteado (semente `20261015`), as três invariantes em
todas. Fuzz que não se reproduz é anedota, não regressão — por isso a semente está no arquivo.
Custo: ~34 s, o que é aceitável para um portão que protege o aceite mais duro da fase.

### Portão próprio no `verificar.py` (aceite (d))

A suíte tem marcador `cancelamento` e roda como etapa **própria** no `tools/verificar.py`, além
de entrar no `pytest` geral. Virou regressão, não evento único.

### Não verificado

- **O áudio já entregue ao driver.** A invariante é sobre o **nosso** sumidouro. A fila do
  dispositivo aceita amostras e as entrega quando quiser: nela o áudio velho sobrevive ao nosso
  `Cancel`, e isso só se mede com alto-falante (F1-16).
- Cancelamento de tool de **escrita** é F4 (fora do escopo do cartão).

---

## F1-12 — histórico com `played_ms` real

### O histórico **é** o log, não uma cópia dele

Cada entrada vem de um `PlaybackProgress`, que já carrega `epoch`, `chunk_id` e `played_ms`, e
é gravada no log encadeado da F0-02. Guardar o histórico num arquivo à parte permitiria editar
o que o modelo "lembra" sem deixar rastro; gravado no log, mexer num `played_ms` depois quebra
a cadeia de hash. O teste prova as duas pontas: reconstrói o histórico **a partir do log** e,
depois, adultera o `played_ms` no banco e exige `CadeiaRompida`.

Detalhe que o teste revelou sobre o log: ele é **append-only por gatilho**, então o `UPDATE` da
adulteração só passa derrubando os gatilhos — e mesmo assim a cadeia acusa. A garantia é melhor
do que a que o cartão pedia.

### Bug que o teste de reconstrução pegou: `played_ms` é por pedaço

`PlaybackProgress.played_ms` conta o que saiu **daquele pedaço** (F1-03), não do turno. A
primeira versão de `do_log` tratava o valor como total do turno e devolvia um histórico **mais
curto do que o dono ouviu** — `'Achei três arquivos,'` onde o correto era
`'Achei três arquivos, o maior é o r'`. O total do turno é a **soma dos pedaços**, com o maior
valor quando o mesmo pedaço aparece mais de uma vez (progresso periódico). Era um erro que
diminuía a memória do assistente de forma silenciosa — do tipo que só aparece comparando com o
mapa.

### Aceite (a) e (b) sobre os vinte pontos

A comparação é **caractere a caractere** com o mapa do F1-09, nos vinte pontos do F1-11: o
histórico tem exatamente `fala.texto_ate(amostras_tocadas)`. E para o sufixo que foi
sintetizado e não saiu, o teste exige **ausência** — em todas as entradas, uma por uma. Ponto
que tocou a resposta inteira é `skip` explícito, não falso verde.

### A retomada não tem onde esconder o plano antigo

`Retomada` carrega `ouvido`, `epoch` e `played_ms` — e **não tem campo** para o sufixo não
tocado. Não é disciplina de quem escreve o código: é a estrutura não permitir. O teste afirma o
negativo (`ressuscita()` é falso) e que o contexto que vai para o `s2` é exatamente o trecho
tocado.

### Não verificado

Nada depende de hardware aqui. O que fica de fora, por não ser deste cartão: resumo e
consolidação de histórico (F3), e o áudio já entregue ao **driver** — o histórico conta o que
saiu do **nosso** sumidouro, e a fila do dispositivo é do F1-16.

## ADR-0015 — canal de áudio entre `audio-io` e `agentd` (achado do F1-10)

### O que foi medido, e por que o número não decidiu sozinho

Três canais, produtor em **outro processo**, ritmo real de 20 ms, `n` = 1500 quadros por
execução, 3 execuções (`docs/medicoes/f1-canal.md`, commit `7272d0c`): anel 47,1 µs p95, socket
50,2 µs, `multiprocessing.Connection` 59,3 µs. Os três ficam ~340× abaixo do período de um
quadro, e os 12 µs entre o melhor e o pior são **0,01% do orçamento de 80 ms do SLO-1**.
Escolher por esse delta seria inventar precisão; quem decidiu foi o **P11**: `AF_UNIX` em
datagrama não existe no Python para Windows, o anel precisa de concorrência escrita à mão nos
dois sistemas, e a `Connection` já é o transporte do barramento (endereço, família e `authkey`
vêm de `jarvis.barramento.ipc`). O anel fica medido e testado no repositório para o dia do
`audio-io` em Rust.

### O erro que repeti e como ele aparece

O primeiro `test_barge_in_com_os_dois_processos_de_verdade` subia o `agentd` com
`--parar-em PlaybackProgress` e o log saía sem `Cancel` nenhum: o **primeiro**
`PlaybackProgress` é de pedaço que terminou (~200 ms), e a fala do dono no áudio sintético
começa aos 220 ms — o `agentd` morria antes do barge-in. É o mesmo erro do F1-03. A condição de
parada tem de ser o **evento que prova o que se quer medir** (`Cancel`), e o `PlaybackProgress`
do corte é o que vem **depois** dele no log.

### Não verificado

- **Windows**: a escolha é portátil por construção (é o transporte do barramento, que o CI roda
  nos dois sistemas), mas os microssegundos publicados são de Linux. E o `ts_mono_ns` só é
  comparável entre processos porque o Linux compartilha o `CLOCK_MONOTONIC`.
- **Máquina sob carga**: a medição rodou com a máquina ociosa; com ASR consumindo CPU o jitter
  piora — é por isso que o canal descarta em vez de bloquear.
- **SLO-2 entre processos como número publicado**: o teste de integração exige que caiba nos
  150 ms, mas é uma execução por rodada de CI, não p50/p95 com três execuções. O número com a
  fila do driver é o F1-16, na máquina do dono.

## F1-13 — PTT e indicador de microfone que não mente

### Por que o controle não é evento do barramento

A §3.2 fecha **onze** tipos de evento, e nenhum é "abra o microfone". Inventar um seria emenda
de SPEC, que é do dono. Então PTT e *kill switch* usam o mecanismo que a pasta de sessão já
tem para `sessao`, `pronto` e `quadros-de-audio`: arquivo pequeno trocado por `Path.replace`
(atômico nos dois sistemas). O barramento continua carregando **decisão**; abrir e fechar
microfone é **controle de dispositivo**, e quem manda nele é o dono.

### O que faz o indicador não poder mentir

Dois arquivos, em direções opostas: `microfone-pedido.json` é o que a `ui` **pediu**, e
`microfone-estado.json` é o que o `audio-io` observou da fonte. O indicador lê **só o segundo**,
e `PainelDoMicrofone.ouvindo` é propriedade **derivada** (`estado.aberta`) — não existe campo
para alguém escrever "ouvindo" por engano, e há teste que exige `AttributeError` ao tentar.

Do outro lado, `Captura.aberta` não é booleano: é `self._quadros is not None`, a existência do
iterador. Fonte fechada não tem de onde puxar amostra — então "indicador apagado" e "zero
amostra" não são duas afirmações que precisam combinar, são **a mesma**.

Três armadilhas que entraram como regra depois de pensar no que o dono veria:

1. **PTT fecha a fonte, não filtra depois de capturar.** Filtrar amostra já capturada deixaria
   o áudio do dono passar pela nossa memória sem ele querer.
2. **Estado velho não acende o indicador.** O `audio-io` republica a cada 250 ms; parado há
   mais de 2 s, o painel mostra apagado e diz que perdeu contato. Indicador aceso porque o
   processo de áudio **morreu** com a fonte aberta é a pior mentira possível, e era a que
   passaria sem ninguém notar.
3. **Pedido ilegível vira `DESLIGADO`.** JSON corrompido não pode virar microfone aberto: na
   falha, o padrão é o mais silencioso, não o mais útil.

### A contagem de amostras é um retrato

`estado.amostras` é republicado a cada 250 ms (ou na hora em que `aberta`/`modo`/`indisponivel`
mudam), não a 50 Hz: escrever o arquivo 50 vezes por segundo seria custo sem leitor. A
consequência honesta está no teste: no tick em que a fonte abre a contagem é 0 **de verdade**, e
quem atrasa é o número, nunca o zero do fechamento — que é o que o aceite (a) cobra.

### O atalho global está declarado e não implementado, de propósito

`JARVIS_HOTKEYS_BACKEND=falso|portal|windows|nenhum`. O `falso` é arquivo (`1`/`0`), e é por
isso que o teste de integração consegue apertar a tecla de **outro processo**. `portal`
(`org.freedesktop.portal.GlobalShortcuts`) e `windows` (`RegisterHotKey`) levantam
`AtalhoIndisponivel` no `abrir`, a `ui` registra o motivo como **aviso** (linha separada da
frase do microfone) e cai no botão da tela. Pôr um cliente D-Bus que o CI não pode exercitar
seria código de produto sem teste no caminho mais sensível da tela.

### Não verificado (exige a máquina do dono — cartão F1-16)

- **atalho global de verdade**: portal/KGlobalAccel no Wayland e `RegisterHotKey` no Windows,
  inclusive a pergunta que só se responde lá — se **outro aplicativo** já tomou a combinação;
- **se o indicador é visível onde o dono realmente olha**: aqui ele é uma frase em arquivo
  (`ui-microfone.txt`), porque a tela é de outra fase;
- **dispositivo real**: a fonte do teste é a sintética; `CI=1` recusa abrir placa de som.

## F1-14 — Sem rede: cai para PTT e diz isso

### A detecção fica no adaptador, e o prazo é nosso

`jarvis.rede.AdaptadorRemoto` passa o **prazo restante** para quem faz a chamada
(`fazer(prazo)`) e **mede** quanto levou: resposta que chegou depois do prazo conta como queda,
pela mesma regra do orçamento do S1 (F1-08) — informação velha não decide nada. É assim que não
existe `timeout` herdado: o prazo não é o padrão de um SDK, é o nosso, e desce como argumento.

A sonda é injetável (`JARVIS_REDE_BACKEND=injetada|socket`), e a de produção **recusa abrir
socket sob `CI=1`**, do mesmo jeito que `proibir_dispositivo_em_ci` recusa abrir a placa de som
(F1-01). O aceite (d) fica estrutural: a suíte não tem como falar com a rede por descuido. O
teste da cascata local ainda assim proíbe `AF_INET`/`AF_INET6` por `monkeypatch`, deixando passar
o socket de domínio do barramento — que é local e é o que a §2 usa.

### Dois defeitos que os aceites pegaram, e valem mais que o código novo

**1. O aviso por voz repetia 50 vezes (aceite (e)).** O arquivo de degradação tem **dois
escritores**: o adaptador (no `s2`) e quem fala o aviso (no `agentd`). Enquanto `_cair` escrevia
a partir da cópia em memória, cada nova queda apagava o `avisado_por_voz` que o `agentd` tinha
acabado de gravar — cinquenta chamadas caindo, cinquenta avisos no ouvido do dono. A correção é
ler o arquivo antes de escrever (`_no_disco`): o arquivo é a verdade, a cópia em memória é cache.
A lição geral: **arquivo com dois escritores não pode ser escrito a partir de cache**.

**2. O microfone ficava surdo depois do primeiro `Cancel` da sessão.** `Captura.epoch` era
gravado na conexão e nunca mais mudava. Depois do primeiro barge-in, todo `AudioActivity` saía
com epoch morto e `DonoDoEpoch.classificar` manda **descartar** (`AudioActivity` não é tipo de
auditoria): o `audio-io` seguia capturando, publicando e sendo ignorado, sem erro e sem log.
Apareceu porque o F1-14 precisa de um **segundo** turno — o dono falando por PTT com a rede fora
— e o segundo turno nunca chegava ao `agentd`. A correção é `seguir_epoch`: o `audio-io` **segue**
o epoch do barramento (ele não é dono dele, §3.2 é o `agentd`), e há teste que mostra o veredito
mudando de `DESCARTAR` para `ACEITAR`.

### Nada pendurado, e a volta não ressuscita

Pedido que cai é **descartado** com o `call_id` registrado, e a lista de descartados **sobrevive
à volta da rede**: `chamar` recusa um `call_id` descartado sem nem consultar a sonda. Pedido
novo funciona normalmente — degradar não pode virar sistema inútil. O `s2` tem batimento de
sondagem (2 s degradado, 5 s saudável) para a queda e a volta serem notadas **sem tráfego**:
sem isso a `ui` ficaria dizendo que está tudo bem enquanto a rede caiu e ninguém falou.

### Quem faz o quê (e por que não é tudo no mesmo lugar)

- **`s2`** detecta: é o processo que, no produto, fala com o serviço remoto;
- **`ui`** degrada e mostra: desliga a escuta contínua, liga o PTT (reusando o contrato do
  F1-13) e põe a frase na tela. O *kill switch* **vence** a degradação: se o dono desligou o
  microfone, cair a rede não o religa em PTT. A volta restaura o modo de antes, não inventa
  escuta contínua que o dono não pediu;
- **`agentd`** fala: é ele que tem o TTS e o epoch.

### Não verificado

- **rede real do dono** (Wi-Fi caindo devagar, DNS lento, captive portal): é observação do
  F1-16, não número. Aqui a rede cai por arquivo, nunca mexendo no firewall da máquina;
- **o aviso por voz chegando ao alto-falante**: ele é sintetizado de verdade (há asserção sobre
  as amostras) e registrado em `aviso-por-voz.jsonl`, mas a ponte de pedaços de TTS do `agentd`
  para o playback do `audio-io` é a mesma lacuna que o F1-11 já declara — o caminho até a placa
  de som é o F1-16;
- **serviço remoto de verdade**: não existe nenhum no v0. O adaptador está no caminho do `s2`
  com a sonda injetada; o `s2` com LLM é a F2.
