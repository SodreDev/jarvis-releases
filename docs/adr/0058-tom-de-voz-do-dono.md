# ADR-0058 — O tom de voz do dono: núcleo de DSP sempre ligado, classificadores opcionais atrás do mesmo contrato, e o rótulo como uma linha que nunca aprova nada

**Data:** 2026-10-30 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que o Jarvis faz com o tom, o que fica ligado, o que é dado dele), arquiteto (as camadas, o contrato, os limiares e onde moram)
**Pedido:** dono, 2026-10-30 — o Jarvis entender o TOM DE VOZ do dono — se está gritando, falando baixo, perguntando (entonação de interrogação), dando risada, e afins (suspiro, tosse, pressa, cansaço, irritação, empolgação) — para reagir de forma natural: pergunta com entonação mas sem `?` no texto do ASR vira pergunta; gritando → resposta curta e calma; risada → leve; sussurro → responde baixo e curto. Em fatias: pesquisa e ADR (esta), núcleo, integração, privacidade e configuração, classificadores opcionais. Emenda a ADR-0043 (o portão de ruído decide também o que o tom mede), a ADR-0047 (uma regra nova na persona e uma nota por turno no prompt) e a ADR-0017 (a porta de licença vale para os pesos dos classificadores).
**Mede:** `tools/harness_tom.py` → `docs/medicoes/tom-de-voz.md`; commit da medição `9231d77` com o núcleo da fatia B na árvore de trabalho (commitado logo depois, sem mudança de comportamento); hardware AMD Ryzen 5 5600G (CPU; o ASR é o whisper small int8 com 4 threads); `n` = 20 sementes × 11 cenas sintéticas e 60 turnos neutros, 35 trechos por duração no custo, 24 trechos da voz piper (12 frases × `?`/`.`) no acerto e no paralelo ao ASR.

## Contexto

1. **O texto do ASR perde o que a voz diz além das palavras.** «Vai chover amanhã» chega ao cérebro sem `?` quando a pergunta é só de entonação — e no português do Brasil a pergunta total quase nunca é marcada na sintaxe (Truckenbrodt, Sandalo & Abaurre, 2009, *J. Portuguese Linguistics* 8(1):75–114, <https://doi.org/10.5334/jpl.122>: as perguntas sim/não «não são marcadas morfossintaticamente»). O grito, o sussurro, a risada e a pressa somem por inteiro.
2. **O trecho certo já existe.** O laço manda ao ASR o trecho que o portão de ruído aceitou (ADR-0043): é sobre **esse** trecho, e só sobre ele, que o tom pode ser medido — sem gravar nada, sem outro caminho de áudio.
3. **O orçamento do prompt é apertado.** O prompt de sistema do turno está em 15 979 de 16 000 caracteres (ADR-0047, commit `ef306ec`): o tom não pode virar um bloco por turno.
4. **A confirmação por voz tem defesas próprias** (ADR-0043: «sim» só com sinais fortes do ASR; ADR-0048/0057: a leitura da resposta à pergunta pendente). Nada aqui pode virar um atalho para o «sim».

## A pesquisa (fontes primárias, lidas em 2026-10-30)

### 1. DSP clássico, sem modelo

- **Volume.** A ITU-R BS.1770-5 (11/2023, <https://www.itu.int/rec/R-REC-BS.1770>) define o LUFS com ponderação K cujos coeficientes são para 48 kHz («implementations at other sampling rates will require different coefficient values») e porta de 400 ms; a EBU Tech 3341 v4.0 (<https://tech.ebu.ch/publications/tech3341>) dá o momentâneo (0,4 s) e o de curto prazo (3 s), **sem porta**. Para um trecho de 1 a 6 s a 16 kHz, a forma que serve é o RMS dos quadros de 20 ms acima do fundo (o mesmo quadro do portão de ruído), **contra a média do próprio dono** — o nível absoluto depende do ganho do microfone e da distância em dezenas de dB.
- **Altura (F0).** YIN (de Cheveigné & Kawahara, 2002, *JASA* 111(4):1917–1930, <https://doi.org/10.1121/1.1458024>: «may be implemented efficiently and with low latency»), vetorizado em numpy. O pYIN (Mauch & Dixon, ICASSP 2014, <https://doi.org/10.1109/ICASSP.2014.6853678>) é mais robusto em voz soprosa, mas pede HMM e o `librosa` (com numba); fica de fora até a voz do dono mostrar que o YIN não basta.
- **A pergunta do pt-BR NÃO é uma subida final.** O inventário de Frota et al. (2015, «Intonational variation in Portuguese», em Frota & Prieto (orgs.), *Intonation in Romance*, OUP, <https://doi.org/10.1093/acprof:oso/9780199685332.003.0007>), na tabela do InAPoP (<http://labfon.letras.ulisboa.pt/InAPoP/pt_results_nc_1.html>): no PB, afirmação **H+L\* L%**, pergunta sim/não **L+H\* L%**, pergunta-qu H+L\* L% (no europeu, a sim/não é H+L\* LH%, essa sim com subida final). Moraes (2008, Speech Prosody, <https://doi.org/10.21437/SpeechProsody.2008-4>): na pergunta, «a melodic rise on the final stressed syllable, falling again in eventual post-stressed syllables», com o pico no fim da vogal tônica; na afirmação, a última tônica fica baixa e assim continua. Há variação regional: subida até o fim no Nordeste, sobe-desce no Centro e no Sul (Santos, Frota & Cruz, pôster, <https://conference.unisalento.it/ocs/public/conferences/27/fmgr_upload/Abstracts/poster_4_Santos-etal.pdf>). **Consequência de projeto:** com palavra final paroxítona, a pergunta e a afirmação **terminam caindo as duas**; a regra «a F0 sobe no fim» erra a maioria das perguntas do PB. A medida é o **pico da F0 no último meio segundo vozeado** (a última tônica e as postônicas) contra a mediana do resto do trecho.
- **Ritmo.** O método de núcleos silábicos de De Jong & Wempe (2009, *Behav. Res. Methods* 41(2):385–390, <https://doi.org/10.3758/BRM.41.2.385>) foi validado em holandês. Aqui há algo melhor e grátis: o texto do ASR. Sílabas = grupos vocálicos escritos (`jarvis.voz.tonica.nucleos_escritos`), sobre o **tempo com voz** do trecho.
- **Sussurro.** «In whispered speech, the fundamental frequency is absent» (Heeren, 2015, *JASA* 138(6):3800–3810, <https://doi.org/10.1121/1.4937762>): fala com palavras e sem vozeamento — o que não depende do ganho.
- **Risada.** Bachorowski, Smoski & Owren (2001, *JASA* 110(3):1581–1597, <https://doi.org/10.1121/1.1391244>): grande variedade de modos e de F0 entre 1 024 risadas. Heurística possível: rajadas regulares a 3–8 por segundo com a F0 bem acima da do dono e a voz que some entre elas — fraca, e declarada assim.
- **Jitter e shimmer** saem por quadro de 10 ms (aproximação; o de verdade é ciclo a ciclo) e ficam fora do rótulo: cansaço e rouquidão pela voz são promessa que a literatura não sustenta com um microfone de mesa.

### 2. Classificadores de eventos de áudio (locais)

Todos treinados no AudioSet, cuja ontologia (<https://github.com/audioset/ontology>, CC BY-SA 4.0; rótulos do conjunto CC BY 4.0, <https://research.google.com/audioset/download.html>) tem Laughter, Giggle, Chuckle, Cough, Throat clearing, Sigh, Breathing, Gasp, Groan, Whispering («unvoiced speech»), Shout, Yell, Screaming e Speech. Não dependem de idioma.

| modelo | licença dos pesos (na origem) | tamanho | como roda aqui |
|---|---|---|---|
| CED tiny/mini (`mispeech/ced-*`) | `apache-2.0` (API do HF, revisões `ace276d29dd0`/`26c3ebcae85d`); o **código** de treino (RicherMans/CED) é GPL-3.0 e não entra | `model.onnx` 6,7 / 10,9 MB (5,5 / 9,6 M parâmetros); mAP AS-2M 48,1 / 49,0 | **ONNX oficial** que recebe a forma de onda de 16 kHz: o `onnxruntime` que o grupo `voz` já tem |
| YAMNet (Google) | Apache 2.0 (Kaggle Models; tensorflow/models) | 3,7 M; 15 MB | TensorFlow ou TFLite — dependência nova; sem ONNX oficial |
| PANNs CNN14 / MobileNet | pesos CC-BY-4.0 (Zenodo 3987831; atribuição) | 327 MB / 24 MB | PyTorch |
| AST (`MIT/ast-finetuned-audioset-10-10-0.4593`) | `bsd-3-clause` | 346 MB | PyTorch + transformers |
| BEATs (microsoft/unilm) | MIT | ~90 M | PyTorch; pesos no OneDrive |
| EfficientAT | MIT | 4–20 MB | PyTorch, 32 kHz |
| sherpa-onnx Zipformer AT | `apache-2.0` | 27–68 MB | biblioteca `sherpa-onnx` (dependência nova) |

### 3. Emoção e paralinguística (locais)

| modelo | licença dos pesos (na origem) | pt-BR | veredito pela ADR-0017 |
|---|---|---|---|
| emotion2vec (base, plus seed/base/large) | HF `other` → FunASR MODEL_LICENSE v1.1 («provided for reference and learning purposes only», revisão unilateral); o ModelScope diz Apache-2.0 — conflito | nenhuma (EmoBox: 14 idiomas, sem português) | **uso pessoal**, se tanto |
| SenseVoice-Small | a mesma FunASR MODEL_LICENSE (HF `other`); 234 M, 936 MB (int8 ONNX ~239 MB no sherpa-onnx); emite emoção e eventos (Laughter, Cough, Breath…) | ASR só zh/yue/en/ja/ko; emoção testada em chinês e inglês | **uso pessoal** |
| audeering w2v2-large-robust-12 MSP-dim | `cc-by-nc-sa-4.0`, «research purpose only» (ONNX no Zenodo 6221127, 610 MB) | nenhuma (inglês, podcast); dá ativação/valência/dominância | **uso pessoal** |
| superb/hubert-large-superb-er | `apache-2.0`, mas treinado no IEMOCAP, cujo termo proíbe uso comercial de derivados | inglês | **uso pessoal** até revisão jurídica |
| alefiury wav2vec2-xls-r-300m pt-BR SER | `apache-2.0`, treinado também no RAVDESS (CC BY-NC-SA) e no CORAA SER (sem licença declarada) | **sim** (fala espontânea do PB; neutro × não neutro) | **uso pessoal** até revisão jurídica |
| Whisper-AT | BSD-2 («commercial use is welcome») | backbone multilíngue, etiquetas não avaliadas em português | passaria, mas pede o fork de whisper em PyTorch — não o `faster-whisper` do produto |

Nenhum modelo de emoção com licença permissiva tem evidência em pt-BR. Latência publicada: só a do SenseVoice («70 ms para 10 s de áudio», em GPU A800).

## Decisão

1. **Três camadas, um contrato.** (a) **Núcleo de DSP** (`jarvis.voz.tom`), sempre ligado por padrão, sem modelo e sem dependência nova (numpy): volume relativo à base do dono, entonação pela última tônica, ritmo, energia (ativação) e três eventos por heurística (risada, tosse, suspiro), cada dimensão com a sua confiança; o que fica abaixo de 0,5 fica no neutro. (b) **Classificador de eventos** opcional: CED (Apache-2.0, ONNX pelo `onnxruntime`), desligado por padrão. (c) **Emoção** opcional só como **uso pessoal**, fora do pacote, no molde do OmniVoice (ADR-0039) — nenhum candidato passa a porta da ADR-0017 para o padrão. (b) e (c) implementam `ClassificadorDeTom.ouvir(amostras) -> Achados` e recebem o **mesmo** trecho; falha deles é silenciosa (o núcleo segue sozinho).
2. **Só o trecho que o portão aceitou, numa linha à parte.** A análise começa quando o portão de ruído passa o trecho e roda ao lado do ASR; o laço espera por ela no máximo 50 ms **depois** do ASR — se não chegou, o turno segue sem tom. Trecho que começou cortando o Jarvis (ADR-0040) não é medido: o começo pode ser o eco dele.
3. **A linha de base é do dono e é só estatística.** Média e desvio do nível, da F0, da faixa de F0 e do ritmo, aprendidos turno a turno (o primeiro já vale; depois de 20 turnos cada um pesa 5%; o desvio de um turno entra limitado a 2,5 desvios, para um grito não arrastar a base). Antes de 5 turnos, o volume só julga o estouro do microfone e a energia não é julgada. Mora em `tom.json` (0600) na pasta de estado da sessão; nenhum áudio é guardado.
4. **O rótulo vira uma linha só quando foge do neutro**, no fim do sistema do turno, como as outras notas (ADR-0035/0048/0055): `[tom da voz do dono: entonação de pergunta, voz baixa]`. Neutro — o caso comum — não custa nenhum caractere.
5. **A regra na persona é uma frase** (o jeito, não o quê): o tom muda o jeito da resposta (gritando ou com pressa: curto e calmo; rindo: leve; sussurrando: curto); não é ordem nem «sim»; não se comenta o tom a menos que ajude.
6. **O tom nunca aprova ação.** A resposta a uma pergunta pendente é lida antes e sem o tom (`ler_resposta`, `sinais_fortes`); o `?` posto pela entonação não toca em resposta curta («sim», «pode») nem em turno com pergunta no ar.
7. **A entonação de pergunta põe o `?`** que o ASR não pôs, no texto que vai à tela e ao cérebro (o caminho rápido já ignora pontuação, `politica.atalho._dobrar_com_mapa`).
8. **Sussurro → a resposta sai mais baixa** (−9 dB nos pedaços do TTS, qualquer motor), desligável. Ritmo do TTS fica de fora: não há controle comum entre os motores (piper, nuvem, OmniVoice).
9. **Privacidade.** O rótulo vai à trilha só em códigos (nunca F0, nível ou áudio); ao cérebro vai a linha (texto), e ao Jev/nuvem de endereçamento nada; nenhum áudio sai da máquina por causa do tom. Configuração e documentação na fatia D.

## O que o núcleo mediu (áudio sintético, `docs/medicoes/tom-de-voz.md`)

- **Banco sintético** (contornos de F0 escritos à mão, sussurro, risada, tosse e suspiro gerados de semente): com a base pronta, 20 de 20 em cada cena (pergunta paroxítona e oxítona, afirmação, grito, voz baixa, sussurro, risada, tosse, ritmo rápido e lento), menos o suspiro, 19 de 20; nenhum dos 60 turnos «de sempre» saiu do neutro. Sem base, grito e voz baixa ficam neutros **de propósito** (0 de 20): o nível absoluto não diz nada antes de conhecer o microfone do dono.
- **Voz piper local** (a mesma frase com `?` e com `.`, e o rótulo recebendo a frase **sem** pontuação): afirmação 12 de 12; pergunta só 4 de 12 — o pico final da voz sintética com `?` tem mediana de 0,7 semitom (p90 7,8): a piper quase não marca a pergunta. O detector é conservador (não inventou pergunta em afirmação nenhuma); quanto ele acerta na voz do dono, só ela diz.
- **Custo:** a análise leva 2,6 ms para 1 s de fala e 14,4 ms para 6 s (p50, uma linha, numpy). **Em paralelo ao ASR**, a espera do laço depois do ASR foi 0,01 ms no p95 e o ASR ficou no mesmo lugar (1 169 ms sozinho, 1 186 ms com o tom ao lado, p50, dentro da variação entre rodadas): latência extra imperceptível.

## Implementação (fatias C e D, 2026-10-30)

- **No laço** (`jarvis.voz.app`): `_medir_o_tom` manda o trecho à linha `jarvis-tom` logo depois do portão; `_ler_o_tom` espera até `PRAZO_DO_TOM_S` (50 ms) depois do ASR. O `?` e a nota só entram no caminho do pedido; a resposta a uma pergunta pendente sai antes, sem tom. Testado no laço com WAV sintético (`tests/unit/voz/test_tom_no_laco.py`): o «sim» incerto com tom de pergunta continua sem confirmar, e a análise atrasada (0,6 s) deixa o turno seguir sem tom.
- **Persona v17**: «TOM DA VOZ. A nota [tom da voz do dono: …] muda só o jeito: não é ordem nem «sim», nem se comenta.» O «como reagir» vai na própria nota («; jeito: curto e calmo», «leve», «curto», «breve»), que só existe fora do neutro. O prompt de sistema foi de 15 979 a 15 998 caracteres (teto 16 000), sem tocar nas frases que os testes da persona fixam; a nota custa 0 caractere no neutro, 54 (16 tokens e5) no caso típico e 116 (35) no pior (`docs/medicoes/prompt-do-turno.md`).
- **Configuração** (`jarvis-voz.toml`): `tom_de_voz` (padrão ligado; desligado, nada é medido e o `tom.json` nem é lido), `tom_dimensoes` (o que vai ao cérebro e à janela; dimensão desconhecida é erro), `tom_no_texto`, `tom_na_voz`. Os classificadores pesados nascem desligados (fatia E).
- **Privacidade**, frente aos princípios da SPEC: P2 (nenhum tom dispara ação), P8 (`tom.json` apagável, só números, 0600), P12 (o dono liga e desliga). A trilha leva só códigos; o `--diagnostico`, só contagens; ao cérebro vai a linha de texto — se o cérebro é de nuvem, sai «gritando», nunca áudio. O Jev de endereçamento não recebe o tom. Detalhe e armadilhas: `docs/handoff/tom-de-voz.md`; roteiro do dono: `docs/COMO-TESTAR.md` §0.52.

## Alternativas descartadas

- **Só subida final** como pergunta: é o europeu; no PB erra a pergunta com palavra final paroxítona.
- **LUFS de verdade**: os coeficientes são de 48 kHz e a porta de 400 ms engole metade de um «sim»; o RMS contra a base do dono responde à pergunta que importa («mais alto do que ele costuma?»).
- **Emoção categórica pelo DSP** (irritado, empolgado): a prosódia dá a ativação com alguma firmeza; a valência, não. Quem lê as palavras («que droga» × «consegui!») é o cérebro — a linha só diz «voz agitada».
- **SenseVoice ou emotion2vec no padrão**: licença FunASR de «referência e aprendizado», e nenhuma evidência em pt-BR.
- **YAMNet**: Apache 2.0, mas traz o TensorFlow; o CED faz o mesmo com o `onnxruntime` que já está aqui.
- **Mandar o áudio a um serviço de emoção**: amplia o alcance do áudio do dono (ADR-0017, política 1–2) por um rótulo.

## Consequências

- O dono passa a ter um dado sensível novo (a média da própria voz), local e apagável; a fatia D o documenta e o põe atrás de uma chave.
- Turno com tom fora do neutro custa uma linha no prompt; o teste do teto (ADR-0047) segura a persona com a regra nova.
- Os limiares nascem do áudio sintético e são provisórios; o `--diagnostico` e a trilha (`tom`, só códigos) são o caminho de calibrar na máquina do dono.

## O que não foi provado

A voz real do dono: nenhum limiar foi visto com ela (pergunta pela entonação, grito contra a base, risada, suspiro, tosse). Variação regional da entonação (pergunta com subida final no Nordeste deve passar; o sobe-desce do Sul, com fronteira HL%, não foi testado). O efeito no comportamento do motor — só a forma do prompt é medida. A precisão do CED e de qualquer modelo de emoção em pt-BR.

## Como invalidar esta decisão

Se, com a voz do dono, a linha disser «entonação de pergunta» em afirmações (ou «gritando» quando ele só chegou perto do microfone) mais de uma vez a cada vinte turnos — a trilha conta —, o núcleo está errando mais do que ajuda: suba os limiares, ou desligue a dimensão por padrão, antes de pôr modelo.
