# ADR-0017 — Motores de voz (ASR e TTS) atrás de uma interface, local por padrão

**Data:** 2026-10-15 · **Estado:** aceita quanto à fronteira e à política (o dono mandou
implementar em 2026-10-15); **qual** motor o v1 usa continua aberto e é do F1-16 · **Decide:** dono
**Implementada em:** 2026-10-16, commits `4552446`..`c72d236` — ver "Emenda da implementação"
**Pedido:** o dono aceitou o caminho local do TTS (piper + `epitran`, ADR-0016) e quer
**comparar motores** antes de fechar. Esta ADR levanta os candidatos com licença e termos
verificados **na origem** e propõe a fronteira; **nenhum produto foi implementado**.
**Método:** cada fato abaixo tem URL e a data em que foi lido. O que não deu para conferir na
origem está na seção "O que ficou não verificado" — e não vale como fato.

## Contexto

A F1 mediu o caminho de voz com um motor de cada lado: ASR `faster-whisper` (cartão F1-06) e
TTS `piper-onnx` + voz `pt_BR-faber-medium` (cartão F1-09, primeiro pedaço em 116,3 ms p50 e
RTF 0,113× — commit `bced9bf`). Os dois números fecham com folga, e **nenhum dos dois é
decisão de motor**: a escolha do v1 é do cartão F1-16, na máquina do dono, com voz real.

O que esta ADR resolve é a pergunta anterior a essa: **de que forma um motor entra no
produto**. Hoje o `MotorPiperOnnx` recebe o fonemizador por injeção (F1-09) e o carregador
recusa licença não permissiva (ADR-0011), mas não existe fronteira comum entre ASR e TTS, nem
regra para motor de **nuvem** — e nuvem muda a natureza do produto: o áudio do dono sai da
máquina dele.

## ASR

| motor | onde roda | licença / termos | o que a origem diz |
|---|---|---|---|
| `openai/whisper-large-v3` | local | **apache-2.0** (metadado do card) | 1 550 M parâmetros na tabela do card (a seção Safetensors diz "2B params"); etiqueta de **99 idiomas**; o card **não** nomeia desempenho em português. https://huggingface.co/openai/whisper-large-v3 — lido 2026-10-15 |
| `whisper-large-v3` na Groq | nuvem | Services Agreement, "Last Modified: June 22, 2026" | **US$ 0,111 por hora** de áudio; mínimo de 10 s por requisição ("If you submit a request less than this, you will still be billed for 10 seconds"); arquivo até 25 MB no *free tier* e 100 MB no *dev tier*. https://console.groq.com/docs/speech-to-text — lido 2026-10-15 |
| `whisper-large-v3-turbo` na Groq | nuvem | idem | **US$ 0,04 por hora**; o card do modelo repete o preço e diz "over 99 languages", sem publicar WER. https://console.groq.com/docs/model/whisper-large-v3-turbo — lido 2026-10-15 |
| `nvidia/parakeet-tdt-0.6b-v3` | local | **CC-BY-4.0** ("GOVERNING TERMS: Use of this model is governed by the CC-BY-4.0 license"), "ready for commercial/non-commercial use" | 0,6 B parâmetros, FastConformer-TDT, **25 idiomas europeus com português incluído** — e o card avisa que o treino usa **português europeu** enquanto a maioria dos *benchmarks* usa pt-BR. https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3 — lido 2026-10-15 |

**O que a Groq diz sobre o áudio que sai daqui** (https://console.groq.com/docs/your-data e
https://console.groq.com/docs/legal/services-agreement, lidos 2026-10-15):

- *"By default, Groq does not retain customer data for inference requests"*;
- os três *endpoints* de áudio (`/openai/v1/audio/transcriptions`, `/translations`, `/speech`)
  aparecem na tabela sob **"System reliability and abuse monitoring"**, com retenção de **até
  30 dias** e marcados **"ZDR Eligible: Yes"** — ou seja, a retenção zero existe, mas é
  configuração para cliente elegível, não o padrão de quem só pega uma chave;
- §8.1: *"Customer retains all Intellectual Property Rights in Customer Data (including in
  Inputs and Outputs)"*;
- §4.2: *"Groq is not permitted to use Inputs or Outputs for training or fine-tuning any AI
  Model Services or other models"*;
- §11.5: depois do fim do contrato, exclusão dos dados **em até 30 dias**;
- §6.3 proíbe revender o serviço e §3.1 permite embuti-lo em aplicação própria — não há
  proibição geral de uso comercial, e o acordo diz que o serviço **"not for consumer use"**.

**Leitura:** para o v0, ASR local é o padrão óbvio — `whisper-large-v3` (apache-2.0) ou
`parakeet-tdt-0.6b-v3` (CC-BY-4.0, com a atribuição que a porta de licença já cobra desde o
F1-06). A Groq entra como **aceleração opcional** e não como dependência: a diferença de
preço entre os dois modelos dela (2,8×) importa menos que o fato de o áudio sair da máquina.

## TTS

| motor | licença | pt-BR | fonemizador | o que a origem diz |
|---|---|---|---|---|
| `piper` + voz `pt_BR-*` + `epitran` | voz MIT/CC0, `epitran` **MIT** | **4 vozes** | `epitran` (MIT) no lugar do espeak | é o caminho aceito em parte na ADR-0016; mantém o número do F1-09 e tira a GPL do produto. Custo: mapear o IPA do `epitran` no `phoneme_id_map` da voz |
| `hexgrad/Kokoro-82M` | **apache-2.0** | **3 vozes**: `pf_dora`, `pm_alex`, `pm_santa` (`lang_code='p'`) | **espeak-ng (GPL-3.0)** | o `VOICES.md` lista as três vozes pt-BR, e `kokoro/pipeline.py` manda `'p'` para o ramo genérico: `self.g2p = espeak.EspeakG2P(language=language)` com `LANG_CODES['p'] == 'pt-br'`. O `misaki` em si é **apache-2.0** (PyPI 0.9.4), e o `espeak` aparece só no extra `[en]` — mas é o pipeline do Kokoro que escolhe o espeak para pt-BR. https://huggingface.co/hexgrad/Kokoro-82M , https://huggingface.co/hexgrad/Kokoro-82M/raw/main/VOICES.md , https://raw.githubusercontent.com/hexgrad/kokoro/main/kokoro/pipeline.py , https://pypi.org/pypi/misaki/json — lidos 2026-10-15 |
| `ResembleAI/chatterbox` | **MIT** | **sim**, 23 idiomas com português, e há *finetune* pt-BR no "Single Language Pack" | o card não cita fonemizador | 0,5 B parâmetros; **marca d'água PerTh em todo áudio gerado** ("Every audio file generated by Chatterbox includes" o watermarker). O `resemble-perth` 1.0.1 declara classificador **MIT**. https://huggingface.co/ResembleAI/chatterbox , https://pypi.org/pypi/resemble-perth/json — lidos 2026-10-15 |
| `parler-tts/parler-tts-mini-multilingual-v1.1` | **apache-2.0** | `pt` declarado no card | **nenhum** (texto cru no tokenizador) | já verificado na ADR-0016 (Fato 5); 880 M autoregressivo, custo de execução a medir |
| `Zyphra/Zonos-v0.1-transformer` | apache-2.0 | **não** ("supports English, Japanese, Chinese, French, and German") | espeak-ng | fora por idioma, e ainda exige GPU NVIDIA 6 GB+. https://huggingface.co/Zyphra/Zonos-v0.1-transformer — lido 2026-10-15 |
| `edge-tts` (Edge *read-aloud*) | pacote com classificador **LGPL-3.0** (PyPI 7.3.1, resumo "Microsoft Edge's TTS") | sim (vozes pt-BR da Microsoft) | — | o README **não** declara vínculo com a Microsoft, **não** exige chave, e registra que a Microsoft bloqueia SSML que o próprio Edge não geraria. https://pypi.org/pypi/edge-tts/json , https://raw.githubusercontent.com/rany2/edge-tts/master/README.md — lidos 2026-10-15 |
| Azure Speech (caminho oficial da Microsoft) | contrato comercial da Azure | sim | — | camada gratuita F0: **0,5 milhão de caracteres por mês** (neural TTS) e **5 horas de áudio por mês** (transcrição em tempo real). https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ — lido 2026-10-15 |
| ElevenLabs | termos "Last Updated: 09 October 2026" | sim | — | §1(c): no plano gratuito *"you may only use the Services for non-commercial purposes"* (e exige e-mail pessoal); em plano pago *"you may use the Services for commercial purposes"*. §4: *"you retain all rights in and to your Output"*, com *download* disponível em **alguns** serviços. https://elevenlabs.io/terms-of-use — lido 2026-10-15 |

### Dois achados que mudam o que a ADR-0016 dizia

1. **O Kokoro TEM pt-BR** — a ADR-0016 (Fato 3) dizia que o *model card* declara só `en`, e
   isso está certo **no metadado**; mas o `VOICES.md` da v1.0 lista `pf_dora`, `pm_alex` e
   `pm_santa` sob `lang_code='p'`, e o `LANG_CODES` do pipeline mapeia `'p'` para `pt-br`. A
   conclusão da ADR-0016 continua de pé por **outro motivo**, que é mais forte: o pt-BR do
   Kokoro chama `EspeakG2P(language='pt-br')`, isto é, cai **no mesmo espeak-ng GPL-3.0** que a
   ADR-0016 quer tirar do produto. Trocar piper por Kokoro não resolveria licença nenhuma.
2. **`edge-tts` tem duas barreiras, não uma.** Além do *endpoint* sem contrato, o pacote
   declara **LGPL-3.0** — então mesmo a biblioteca cliente entra na conversa de licença do
   produto, e o caminho oficial (Azure Speech) é o único que tem termos para ler.

## Interface única e política

Proposta de fronteira — **desenho, não implementação**:

```text
jarvis.voz.MotorDeAsr   (Protocol)        jarvis.voz.MotorDeTts   (Protocol)
  transcrever_parcial(quadros) -> Hipotese   sintetizar(texto, epoch) -> Iterator[Pedaco]
  transcrever_final(quadros)   -> Texto      cancelar()
  idioma: str                                voz: str
  onde: Onde.LOCAL | Onde.NUVEM              onde: Onde.LOCAL | Onde.NUVEM
```

1. **Local por padrão.** O registro de motores (`licenses/motores.toml`, no mesmo formato de
   `licenses/modelos.toml`) nasce com os motores locais ligados e **todo motor de nuvem
   desligado**. Sem interruptor do dono, o produto nunca abre socket para transcrever.
2. **Nuvem só liga pela UI, com o dono presente** — a mesma regra de elevação da §5.5/P12, e
   pelo mesmo motivo: mandar áudio para fora é ampliar alcance, não ajustar preferência.
3. **O aviso é uma frase, e é obrigatório.** Ligar nuvem mostra, na UI, o que sai da máquina,
   para onde, qual a retenção declarada e quem é o dono do áudio — os quatro campos vêm do
   registro, não de prosa. Para a Groq, hoje: *"até 30 dias, monitoração de abuso; ZDR é
   configuração de cliente elegível"*.
4. **Portão de licença e de termos por motor.** O `license_gate` já recusa licença não
   permissiva de modelo; o registro de motores acrescenta, por motor de nuvem,
   `uso_comercial`, `retencao_declarada`, `treina_com_entrada`, `dono_da_saida` e a URL com a
   data da leitura. Campo vazio **barra** o motor: no v0, "não verificado" não liga nuvem.
5. **Marca d'água é fato do produto, não detalhe.** Um motor que marca o áudio (Chatterbox,
   PerTh) tem de declarar isso no registro, porque o dono precisa saber que o áudio que o
   assistente fala sai marcado.
6. **A interface não decide qualidade.** Quem decide é o F1-16, de ouvido, com voz real.

## Plano de amostra para o dono ouvir

Objetivo: **a mesma frase pt-BR em cada motor local viável**, para o dono comparar de ouvido.

### Amostra gerada em 2026-10-15 — o que mediu

Quatro arquivos para ouvir, em **`/tmp/jarvis-amostras/`** (fora do repositório; áudio **não é
comitado**), todos com a mesma frase, uma afirmativa e uma pergunta:

> *"Jarvis, anotei a reunião de terça às quinze e trinta. Quer que eu avise o João agora?"*

Máquina: AMD Ryzen 5 5600G (12 fios), 31 GiB de RAM, Linux 7.2.9 (Nobara 44), Python 3.12.14,
onnxruntime 1.31.0, CPU. `n` = 3 execuções por motor, valor publicado = **mediana**; p95 com
`n` = 3 não significa nada, e a medição de verdade continua sendo o harness do F1-09 (commit
`bced9bf`). Áudio 16 kHz PCM16 mono. RTF = tempo ÷ duração do áudio.

| motor | voz | licença do caminho | fonemização | síntese | áudio | RTF | arquivo |
|---|---|---|---:|---:|---:|---:|---|
| piper + espeak (linha de base) | `pt_BR-faber-medium` | voz MIT + **espeak-ng GPL-3.0** (fora do produto) | 19 ms | 654 ms | 4,31 s | **0,156×** | `piper-espeak-pt_BR-faber-medium.wav` |
| piper + `epitran` (opção B) | `pt_BR-faber-medium` | voz MIT + **epitran MIT** (pode entrar no produto) | 1 ms | 495 ms | 3,55 s | **0,140×** | `piper-epitran-pt_BR-faber-medium.wav` |
| `Kokoro-82M` (ONNX) | `pf_dora` | modelo apache-2.0, **mas pt-BR via espeak-ng GPL-3.0** | — | 1 872 ms | 4,90 s | **0,382×** | `kokoro-pf_dora.wav` |
| `Kokoro-82M` (ONNX) | `pm_alex` | idem | — | 1 933 ms | 5,12 s | **0,377×** | `kokoro-pm_alex.wav` |

Nenhum dos quatro saiu silencioso (pico entre 0,41 e 0,55; RMS entre 0,054 e 0,092), e os
quatro sintetizam **mais rápido do que tocam** nesta máquina.

**O que a amostra achou sobre a opção B (piper + `epitran`), que era a pergunta do dono:**

1. **O IPA do `epitran` é mais fiel ao pt-BR** do que o do espeak nesta frase — `ʒɐɾvis`,
   `ɐnotɛj`, `tɛɾsɐ` contra `ʒaɾəvˈis`, `ˌænotˈeɪ`, `tˈeɾəs` —, e **71 dos 74** símbolos que
   ele produz já estão no `phoneme_id_map` da voz.
2. **Falta tônica.** O espeak marcou **14** acentos (`ˈ`/`ˌ`) na frase; o `epitran`, **zero** —
   ele não atribui tonicidade em `por-Latn`. A voz foi treinada com o inventário do espeak,
   **tônica incluída**, então o que a amostra entrega é a prosódia achatada (e o áudio 0,76 s
   mais curto). É o item concreto que falta para a opção B: **um atribuidor de tônica pt-BR**
   antes do mapeamento.
3. **Falta mapear `ʷ`** (labialização, em `kʷinzɛ`): é o único símbolo do `epitran` fora do mapa
   da voz, e aparece 3 vezes na frase.
4. **E aqui a ADR-0016 estava errada sobre o código:** ela diz que "fonema fora do mapa hoje
   levanta erro (F1-09), então divergência aparece como falha, não como voz torta". Não levanta:
   `MotorPiperOnnx.sintetizar` faz `if simbolo in mapa` e **descarta em silêncio** o que não
   conhece. Foi o que aconteceu com o `ʷ` nesta amostra. Isso muda o custo da opção B — sem
   teste de cobertura do inventário, um fonema novo vira **voz torta**, não erro —, e a emenda
   da ADR-0016 é decisão do dono.

**Não gerados**, com o tamanho que os derrubou (lido na API do Hugging Face antes de baixar
qualquer coisa, regra do teto de ~2 GB):

- **Chatterbox** (MIT, pt-BR): `t3_mtl23ls_v2.safetensors` 2 144,0 MB + `s3gen.safetensors`
  1 056,5 MB + `ve.safetensors` 5,7 MB ≈ **3,2 GB** de pesos, sem contar o `torch`;
- **parler-tts-mini-multilingual-v1.1** (Apache-2.0, pt): `model.safetensors` **3 751,3 MB**,
  também sem contar o `torch`.

Os dois seguem candidatos; ouvi-los depende de o dono liberar ~3 GB e ~4 GB mais o `torch`.
Baixado para esta amostra, dentro do teto e avisado antes: `kokoro-v1.0.onnx` 325,5 MB +
`voices-v1.0.bin` 28,2 MB + ~10 MB de pip (`espeakng-loader`, que **empacota o espeak-ng
GPL-3.0** — é a prova prática de que o pt-BR do Kokoro carrega a GPL junto). A voz do piper
(63,2 MB) já estava em cache desde o F1-02.

- **O que a amostra NÃO decide:** inteligibilidade e naturalidade (julgamento de ouvido, do
  dono), SLO-5 (a fila do dispositivo não está na conta — o veredito é do F1-16) e licença
  (quem barra é o portão).
- **Fica para o F1-16:** escolher voz e ASR de ouvido na máquina do dono, medir o SLO-5 com
  fila de dispositivo real, e decidir se nuvem entra como aceleração opcional.

## O que ficou não verificado

- **Preço por unidade do Azure Speech** (por 1 M de caracteres e por hora): a página oficial
  entrega os valores por *script* e o texto capturado traz `$-`. Só as cotas gratuitas foram
  lidas.
- **Termos da Microsoft para o *endpoint* de *read-aloud* do Edge**, que é o que o `edge-tts`
  usa: não há página de termos pública para esse uso. É exatamente o motivo de a proposta
  tratá-lo como "sem contrato" e apontar o Azure Speech como caminho oficial.
- **Atribuição no plano gratuito do ElevenLabs:** os termos lidos não mencionam atribuição.
- **Limites de taxa da Groq** (requisições por minuto, horas de áudio por dia): o card remete a
  uma página própria de *rate limits* que não foi aberta.
- **WER em pt-BR de qualquer um dos quatro ASR:** nenhum dos *cards* publica. O do parakeet
  chega a avisar que treinou com português **europeu**; comparar pt-BR é medição do F1-16.
- **Fonemizador do Chatterbox:** o card não cita nenhum; se a implementação usar espeak, ele cai
  no mesmo problema do Kokoro.
- **Tamanho de download** de Kokoro-82M, Chatterbox, Parler-TTS e dos pesos de ASR: não foram
  lidos, e por isso o plano de amostra imprime o tamanho antes de baixar.
- **Qualidade das vozes pt-BR do Kokoro:** o `VOICES.md` não dá nota para elas, e avisa que
  idioma fora do inglês pode estar "thin due to weak G2P and/or lack of training data".

## Emenda da implementação (2026-10-16)

O dono mandou implementar. Quatro coisas mudaram em relação ao que esta ADR propôs, e cada
uma mudou porque a implementação mostrou algo que a proposta não sabia.

### 1. A interface ficou mais estreita do que a proposta

A proposta era:

```text
transcrever_parcial(quadros) -> Hipotese        sintetizar(texto, epoch) -> Iterator[Pedaco]
transcrever_final(quadros)   -> Texto           cancelar()
```

Implementar assim obrigaria **cada** motor — quatro de cada lado, dois deles de nuvem — a
reimplementar o acordo de prefixo do F1-06, o fatiamento e o descarte de pedaço em voo do
F1-09 e as vinte interrupções do F1-11. Trocar de motor passaria a poder afrouxar o
cancelamento, que é justamente o que não pode acontecer. O que ficou:

```text
jarvis.voz.MotorDeAsr (Protocol)           jarvis.voz.MotorDeTts (Protocol)
  transcrever(amostras) -> Hipotese          sintetizar(texto) -> bytes
  nome, modelo, licenca, idioma, onde        nome, voz, licenca, onde
```

O motor traduz **um bloco** e declara **de onde ele é**; quem é incremental, fatia, cancela e
conhece epoch continua sendo a camada compartilhada que já é regressão. O cancelamento chega
ao motor como **uma pergunta** (`Cancelado = Callable[[], bool]`, montada por
`cancelado_por_epoch`): o motor não recebe o `DonoDoEpoch` e por isso não tem como mexer no
epoch. `Hipotese` é `NamedTuple` para o `TranscritorIncremental` do F1-06 continuar
desempacotando `texto, confianca` sem reescrita.

Para motor de **nuvem** o contrato ganhou uma segunda chance de parar, que o local não
precisa: o cancelamento é consultado **antes de abrir o socket** (epoch morto não paga
requisição) e **entre pedaços do corpo da resposta**, caso em que o que chegou é descartado.
O limite do descarte é o pedaço lido: uma leitura já bloqueada só termina pelo prazo, e é por
isso que o prazo é obrigatório.

### 2. O `edge-tts`: decidido, e o custo é maior do que esta ADR tinha achado

A ADR tinha achado duas barreiras (biblioteca LGPL e endpoint sem contrato). São **três**:

3. o serviço só devolve **MP3**, e o pacote não deixa escolher formato (`MP3_BITRATE_BPS` é
   constante do módulo, não parâmetro). O caminho de áudio deste produto é PCM16 16 kHz, então
   o motor precisa de um decodificador externo. O FFmpeg do projeto é LGPL-2.1+, **mas o build
   desta máquina é GPL** (`--enable-gpl --enable-version3`, lido no `-version` local em
   2026-10-16) — e o registro não tem como saber qual build o dono instalou.

**Decisão:** usar o pacote `edge-tts` como **extra opcional isolado**, e não falar o protocolo
à mão. Escrever o WebSocket tiraria a LGPL e deixaria as outras duas barreiras de pé (sem
contrato, MP3 para decodificar), trocando-as por manutenção de um protocolo não documentado
que a Microsoft muda quando quer. O decodificador publica a licença do build local em tempo de
execução (`jarvis.voz.edge.licenca_do_ffmpeg`), em vez de o registro afirmar o que não sabe.

### 3. "Não verificado não liga nuvem" ganhou uma saída explícita — e ela é do dono

A política 4, aplicada ao pé da letra, deixa o `tts-edge` permanentemente fora: não existe
página de termos para esse uso, e campo vazio barra. Isso tornaria o motor impossível de
testar, que não é o que o dono pediu. A saída é **por motor e explícita**, na configuração do
dono: `nuvem_sem_termos = ["tts-edge"]`. Com ela:

- o aviso **abre** com "ATENÇÃO: este serviço não publica termos para este uso";
- cada campo vazio aparece como "**não verificado**", nunca em branco — branco num aviso
  lê-se como "tudo bem aqui";
- **procedência (fonte e data) continua não dispensável**, com ou sem aceite: sem ela não dá
  nem para saber o que se está aceitando.

O padrão não mudou: sem a linha na configuração, o portão recusa.

### 4. A opção B da ADR-0016 está inteira, e as duas lacunas que a amostra mediu foram fechadas

- **tônica:** a amostra tinha medido 14 acentos do espeak contra zero do `epitran` na mesma
  frase. `jarvis.voz.tonica` repõe por **ortografia** (acento gráfico manda; sem acento, a
  terminação manda; lista fechada de 40 átonas de gramática não recebe marca), com a regra de
  ataque do português para o acento cair antes das consoantes que abrem a sílaba (`ˈtɾintɐ`,
  mas `ʒɐɾˈviʃ`). A frase da amostra sai com 13 tônicas em vez de zero;
- **`ʷ`:** substituição declarada para vazio, porque em pt-BR o `u` do `qu` não soa (`quinze`
  é /ˈkĩzi/); mapear para `w` daria "cuinze".

E a conferência de cobertura (`conferir_cobertura`), que a ADR pedia como ideia, achou um
defeito que ninguém veria de ouvido sem suspeitar: o `epitran` devolve vogal nasal ora
pré-composta (`ĩ`), ora com til combinante (`ɐ̃`), e o inventário da voz só conhece a segunda
— `jardim` perdia a nasalidade **em silêncio**. A saída passou a ser normalizada em NFD, e
sobre as seis frases de teste a cobertura do inventário é completa.

Sobre o achado 4 desta ADR (o descarte silencioso de fonema fora do mapa): o código **conta**
agora (`fonemas_descartados`, `simbolos_descartados`) e a cobertura mede antes de sintetizar.
Trocar descarte por erro continua sendo emenda da ADR-0016 e **decisão do dono**.

### O que a implementação não mudou

Local por padrão, nuvem desligada no registro, aviso obrigatório derivado dos campos, portão
de licença por motor e marca d'água declarada: tudo como a proposta dizia. O registro
`licenses/motores.toml` tem nove motores, nenhum de nuvem ligado, e um teste cobra isso do
arquivo comitado em vez da intenção de quem leu.

## Como invalidar esta proposta

- O dono decidir que nuvem **não entra no v0**: a seção de política encolhe para "local, ponto",
  e a interface fica só como fronteira de troca de motor local.
- A amostra mostrar que o `epitran` degrada a voz: a opção B da ADR-0016 cai e a conversa volta
  para distribuir espeak-ng (opção A) ou para um motor sem fonemizador (Parler-TTS, Chatterbox).
- Qualquer motor de nuvem passar a exigir retenção de áudio: o registro barra, porque campo de
  retenção vazio ou pior que o declarado aqui não liga nuvem.

## Escolha de modelo (emenda de 2026-10-16)

**Problema.** O dono configurou as chaves da Groq e da ElevenLabs e não conseguiu escolher o
modelo na janela. Três causas, todas na tela e na configuração, nenhuma no portão: (1) a
janela listava ids de motor (`asr-groq-whisper-large-v3-turbo`) sem dizer que eram modelos;
(2) não havia botão de ligar nuvem na janela — o slot `ligarNuvem` existia e nenhum QML o
chamava, então o motor escolhido ficava desligado; (3) o `voice_id` da ElevenLabs dividia o
campo `voz` com a voz do piper — o arquivo do dono tinha `tts = "tts-elevenlabs"` com
`voz = "pt_BR-faber-medium"`, que iria como `voice_id` para o serviço.

**Decisão.**

- **Provedor e modelo são duas escolhas.** `jarvis.voz.provedores` agrupa o registro por
  serviço (Groq, ElevenLabs, Microsoft) e devolve, por provedor, as opções de modelo com o
  campo e o valor que cada clique escreve. A janela e o `jarvis-voz config` escrevem os mesmos
  campos.
- **Groq: um motor por modelo, como já era.** O preço é por modelo e o aviso leva o preço,
  então o interruptor continua por motor: trocar de turbo para v3 **não** herda o "ligado".
  Lista conferida em 2026-10-16 em <https://console.groq.com/docs/speech-to-text> e
  <https://console.groq.com/docs/models>: ASR são só `whisper-large-v3` (US$ 0,111/h, WER
  10,3%) e `whisper-large-v3-turbo` (US$ 0,04/h, WER 12%), nenhum em prévia; o
  `distil-whisper-large-v3-en` foi desligado em 2025-08-23
  (<https://console.groq.com/docs/deprecations>). Nenhum motor novo entrou.
- **ElevenLabs: um motor com lista de modelos.** Mesmo serviço e mesmos termos para todos,
  então o interruptor é um só. O registro ganhou `modelos`, `fonte_dos_modelos` e
  `data_dos_modelos`; lista com `modelos` e sem procedência **barra o motor** no portão
  (`CAMPOS_DOS_MODELOS`), e modelo fora da lista recusa na leitura do TOML e na abertura do
  motor (`exigir_modelo`). Entraram, de <https://elevenlabs.io/docs/models> em 2026-10-16, só
  os que a página dá com português **e** pelo endpoint de Text to Speech que este motor usa:
  `eleven_multilingual_v2` (padrão), `eleven_flash_v2_5` e `eleven_v3`. Ficaram fora, com o
  motivo no registro: `eleven_v4`/`eleven_v4_turbo` e `eleven_v3_conversational` (a página os
  dá pela Text to Dialogue API/WebSocket), `eleven_turbo_v2_5`/`eleven_turbo_v2` (deprecated),
  `eleven_flash_v2` (só inglês).
- **Voz da ElevenLabs em campo próprio** (`voz_elevenlabs`), validado com a forma de um id
  (`[A-Za-z0-9_-]{1,64}`), porque ele vai no caminho da URL. Arquivo antigo com um id em `voz`
  migra na leitura; voz com forma de voz do piper fica onde está.
- **Vozes da conta pela API, não por lista estática.** A página de vozes diz *"All our Default
  voices will expire on December 31, 2026"*: uma lista fixa de vozes padrão envelheceria em
  dois meses. O dono pede a lista (botão na janela; `10` → `l` no terminal), que vem de
  `GET /v2/voices` com a chave no cabeçalho `xi-api-key` — pelo mesmo caminho do motor
  (ambiente + chaveiro, em memória) — paginada por `has_more`/`next_page_token`, com teto de
  5 páginas de 100. Nenhum texto do dono sai nessa consulta, por isso ela não depende do
  interruptor; o id escrito à mão continua valendo. A janela não importa o motor (ADR-0019):
  a consulta passa por `provedores.vozes_da_elevenlabs`.
- **A janela** abre o provedor escolhido: modelos como fichas (com preço na Groq), o aviso
  inteiro montado do registro e só então "li o aviso — ligar"; o painel ocupa a altura toda e
  rola; "salvar" foi para o alto da coluna da direita.

**Verificado.** 28 testes em `tests/unit/voz/test_escolha_de_modelo.py` e 4 em
`tests/unit/gui/test_escolha_na_janela.py`, sem rede (servidor falso em porta efêmera, `CI=1`):
registro, portão, persistência e releitura, migração, recusa de id malformado, o modelo e a
voz chegando ao pedido, paginação e chave só no cabeçalho, terminal e janela gravando o
arquivo. Captura offscreen em `/tmp/jarvis-telas/teste/jarvis-configuracao-modelos.png`.

**Não verificado.** Nenhuma chamada real à Groq nem à ElevenLabs (o dono faz a primeira):
que `eleven_v3` aceite `output_format=pcm_16000` neste endpoint, que a conta do dono devolva
`verified_languages`/`labels.language` como a documentação descreve, e qualquer diferença de
qualidade entre os modelos.

## Emenda de 2026-10-21 — o motor de ASR declara os sinais do que ouviu; a pronúncia é da camada compartilhada (ADR-0043, ADR-0044)

1. **Sinais do ASR.** A interface ganha `Sinais` (o maior `no_speech_prob`, a média do
   `avg_logprob` e a maior `compression_ratio` dos segmentos) e `Transcricao`; o motor que mede
   oferece `transcrever_com_sinais`, e `jarvis.voz.interface.transcrever_com_sinais(motor, …)`
   devolve sinais vazios para o que não mede (o oráculo, os falsos). O whisper local tira dos
   segmentos do `faster-whisper`; a Groq, do `verbose_json` que já pedia. O que não veio é `None`,
   nunca zero. `transcrever` não muda: o F1-06 segue desempacotando `texto, confianca`.
2. **A dica.** Os dois motores recebem a mesma dica curta (`jarvis.voz.dica`): `initial_prompt` no
   local (sem `hotwords`), `prompt` na Groq. Saiu a lista dos apps instalados (medido: ela fazia o
   ruído virar nome de app).
3. **A pronúncia do dono** (`SintetizadorEmStreaming.pronunciar`) troca a grafia só no texto que o
   motor de TTS recebe, para todos os motores, sem tocar em nenhum — como o cancelamento, é da
   camada compartilhada, não do motor.
