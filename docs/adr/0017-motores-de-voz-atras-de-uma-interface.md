# ADR-0017 — Motores de voz (ASR e TTS) atrás de uma interface, local por padrão

**Data:** 2026-10-15 · **Estado:** proposta · **Decide:** dono
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

- **Frase** (uma só, com os sons que costumam quebrar G2P pt-BR): *"Jarvis, anota aí: a
  reunião de terça às quinze e trinta mudou para o São João, não esqueça o relatório."*
- **Onde:** pasta temporária criada por `tempfile.mkdtemp`, um arquivo por motor
  (`amostra-<motor>.wav`), 16 kHz PCM16 — nada no repositório e nada na sessão do dono.
- **Motores da amostra:** (a) `piper` + `pt_BR-faber-medium` com `espeak-ng` (linha de base, é
  o que o F1-09 mediu); (b) o **mesmo** piper com `epitran` (a opção B da ADR-0016 — a amostra
  é o que mostra se o mapeamento de fonema degrada a voz); (c) `Kokoro-82M` com `pf_dora`;
  (d) `Chatterbox` pt-BR; (e) `parler-tts-mini-multilingual-v1.1`.
- **Regra de download:** **nada baixa sem o tamanho na tela e o "sim" do dono.** O tamanho do
  piper pt-BR é conhecido (~63 MB por voz, ADR-0016); os outros quatro estão em "não
  verificado" abaixo e o plano é imprimir o tamanho que o repositório declarar **antes** de
  buscar. Motor que exigir GPU é anotado como "não roda aqui" em vez de baixado.
- **O que a amostra NÃO decide:** SLO-5 (a fila do dispositivo não está na conta — o veredito é
  do F1-16) nem licença (quem barra é o portão).
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

## Como invalidar esta proposta

- O dono decidir que nuvem **não entra no v0**: a seção de política encolhe para "local, ponto",
  e a interface fica só como fronteira de troca de motor local.
- A amostra mostrar que o `epitran` degrada a voz: a opção B da ADR-0016 cai e a conversa volta
  para distribuir espeak-ng (opção A) ou para um motor sem fonemizador (Parler-TTS, Chatterbox).
- Qualquer motor de nuvem passar a exigir retenção de áudio: o registro barra, porque campo de
  retenção vazio ou pior que o declarado aqui não liga nuvem.
