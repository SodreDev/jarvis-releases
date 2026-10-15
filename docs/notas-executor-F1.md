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
