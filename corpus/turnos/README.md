# `turnos/` — pausa de turno em pt-BR

Mede **SLO-4** (pausa → decisão de turno) e **SLO-9** (falso corte). Aqui convivem dois
materiais que **nunca** se somam numa média:

| | o que é | de onde vem | fecha SLO-4/SLO-9? |
|---|---|---|---|
| **sintético** (`"sintetico": true`) | voz de máquina, pausa sorteada por nós | `tools/corpus_sintetico.py` (cartão F1-02) | **não** |
| **real** | voz consentida, pausa humana | o dono grava (cartão F1-15) | sim, é o aceite da F1 |

- áudio em `turnos/audio/<id>.wav` — PCM 16 bits, mono, 16 kHz;
- rótulo em `turnos/rotulos.jsonl`, uma linha por pausa;
- o áudio **não é versionado** (`.gitignore`): o sintético se regenera do rótulo e o real entra
  por pedido do dono. O `sha256` de cada arquivo mora no rótulo, então medição feita hoje
  continua comparável amanhã mesmo sem os bytes no repositório.

## Formato

```jsonc
// real (voz de pessoa): exige `termo`, nunca tem campo de geração
{"id": "t-0001", "arquivo": "audio/t-0001.wav", "sha256": "…",
 "termo": "TERMO-0001", "falante": "dono",
 "pausa_ms": 420, "fim_de_turno": true,        // o dono realmente parou?
 "texto": "liga o rádio",                       // transcrição humana
 "contexto": "pedido curto, sala silenciosa",
 "split": "calibracao"}

// sintético: exige `"sintetico": true`, semente, gerador, voz, licença da voz e a posição
// da pausa no texto; e NUNCA tem `termo` (não se inventa consentimento para voz de máquina)
{"id": "s-0001", "arquivo": "audio/s-0001.wav", "sha256": "…",
 "falante": "sintetico", "sintetico": true,
 "semente": 20261015, "gerador": "piper-onnx@1.0.0+pt_BR-faber-medium",
 "voz": "pt_BR-faber-medium", "licenca_voz": "MIT (repositório) / CC0 (dataset)",
 "pausa_ms": 463, "fim_de_turno": false,
 "texto": "compacta a apresentação do curso antes de eu sair",
 "texto_antes": "compacta a apresentação do curso",   // antes da pausa
 "texto_depois": "antes de eu sair",                   // depois (só se não é fim de turno)
 "contexto": "hesitação no meio da frase; domínio arquivos; ruído rosa a -12 dB",
 "split": "retido"}
```

O vocabulário é **fechado**: chave desconhecida é recusada por `tools/corpus.py verificar`, não
ignorada (`jarvis.corpus.rotulos`). Outras regras que o verificador impõe:

1. item com marca de geração (id `s-…`, `semente`, `gerador` ou `voz`) **tem** de se declarar
   `"sintetico": true` — sintético e real não se misturam por omissão;
2. item sintético **não** tem `termo`; item real **tem** (`corpus/CONSENTIMENTO.md`);
3. pausa de fim de turno não tem `texto_depois`; pausa no meio da frase tem — se o dono
   continuou falando, não era fim de turno;
4. `split` é decidido **na criação** (regra 5 de `corpus/README.md`). No sintético isso é
   verificável: o split sai de `sha256(semente:id)` ordenado e cortado em 70%, então um split
   escolhido depois — ou a dedo, na hora de medir — não bate e é recusado;
5. se o `.wav` existir na máquina, o `sha256` do rótulo tem de bater.

## O corpus sintético que está no repositório

500 pausas, semente `20261015`, voz `pt_BR-faber-medium` (repositório `rhasspy/piper-voices`
**MIT**, dataset do MODEL_CARD **CC0** — verificada voz por voz, ADR-0012), síntese por
`onnxruntime` (MIT). Regerar: `tools/corpus_sintetico.py --verificar --saida corpus/turnos`
(precisa do `.onnx` da voz e do `espeak-ng`; veja a mensagem de erro do comando, que diz de
onde baixar).

| número | valor | por quê |
|---|---|---|
| itens | 500 | mínimo do cartão F1-02 |
| `fim_de_turno: true` | 250 (50%) | proporção **declarada**: a humana de verdade só sai do corpus real (F1-15). Equilibrado, falso corte e atraso se estimam com a mesma precisão, e nenhum detector ganha ponto respondendo sempre a classe majoritária |
| `fim_de_turno: false` | 250 (50%) | é o caso que mais importa: pausa no meio da frase que o assistente **não** pode interromper |
| pausa, fim de turno | 300–900 ms (uniforme) | faixa declarada |
| pausa, meio de frase | 200–1200 ms (uniforme) | **sobrepõe** a de cima de propósito: sem sobreposição, limiar fixo de silêncio acertaria 100% e a comparação do F1-07 não mediria nada |
| `split` | 350 calibração / 150 retido | 70/30 da regra 5, decidido na criação |
| com ruído rosa | ~30% dos itens, a -12 dB | regressão com ruído de sala plausível |
| com eco do nosso TTS | ~10% dos itens, -18 dB e 120 ms | prepara o F1-04 (AEC) |

**Prefixo ambíguo, de propósito:** cada enunciado completo ("abre a pasta de fotos") também
aparece como prefixo de um maior ("abre a pasta de fotos" / pausa / "na área de trabalho"). O
mesmo começo é fim de turno num item e falso corte em outro, então o detector não acerta pela
escolha das palavras.

**Limites deste material** (além dos três motivos escritos em `docs/F1-tarefas.md`): o prefixo é
sintetizado como enunciado próprio, então a prosódia no ponto da pausa é de fim de frase; e a
síntese roda com `noise_scale = 0` para ser determinística, o que deixa a voz menos expressiva
do que o piper padrão. As duas coisas **favorecem** um detector semântico — mais uma razão para
nenhum número de SLO-4 ou SLO-9 sair daqui.

`fim_de_turno: false` é o caso que importa mais. No corpus real, grave os dois na mesma
proporção em que acontecem.
