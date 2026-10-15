# F1 — Cartões de tarefa para o executor

**Data:** 2026-10-15 · **Autor:** arquiteto (Opus 5) · **Base:** SPEC-v0.1 §2, §3, §3.3, §3.4, §5.1, §7 (SLOs), §9 (F1); ADR-0002 (epoch/cancelamento), ADR-0007 (processos), ADR-0012 (licenças verificadas), ADR-0014 (D1 = Python 3.12)
**Como usar:** cada cartão é delegável sozinho e fecha em **um commit**. O executor entrega **código, teste e número** — e a frase "não dá para verificar sem o microfone do dono" está escrita em cada cartão, no lugar de um número inventado.

**Regras que valem para todos os cartões:**
- Python 3.12 nos sete processos (ADR-0014). A fronteira é o barramento e o contrato vive em `schemas/`: trocar `audio-io`/`agentd` por Rust depois não pode exigir reescrever contrato.
- Sem tool genérica, sem shell irrestrito, sem `run_command` (SPEC §4). Revisão recusa.
- Tudo roda em Linux e Windows no CI; o que não roda nos dois não fecha a tarefa (P11).
- **Nenhum modelo entra sem passar pela porta de licença** (`licenses/modelos.toml` + `tools/license_gate.py`, F0-09). `coqui/XTTS-v2` está **barrado** (ADR-0012); modelo CC-BY-4.0 (`parakeet`) só entra **com a atribuição no produto**, e isso é teste, não boa vontade.
- Nenhum número inventado: medição vem com hardware, `n`, 3 execuções, mediana e p95, e vai para arquivo no repositório (`docs/medicoes/`).
- **Toda tabela de medição separa `sintetico` de `real`.** Média que mistura os dois não é número, é opinião.
- Toda tarefa termina com `cli_ping` (resumo + estado `pronto|precisa_decisao|falhou`).
- Ordem sugerida: F1-01 → (F1-02 em paralelo) → F1-03 → F1-04 → F1-05 → F1-06 → F1-07 → F1-08 → F1-09 → F1-10 → (F1-11, F1-12, F1-13, F1-14 em paralelo) → **F1-15 (dono)** → **F1-16 (dono presente)**.

## Mapa dos cartões

| Cartão | Entrega | Precisa de hardware/máquina do dono? |
|---|---|---|
| F1-01 | banco de teste de áudio: dispositivos falsos, relógio injetável, replay determinístico | não |
| F1-02 | corpus **sintético** de turno (≥ 500 pausas rotuladas) | não |
| F1-03 | `audio-io`: frames de 20 ms, playback cancelável, `PlaybackProgress` real | não (piso) |
| F1-04 | AEC/NR/AGC com referência de loopback, `aec_ok`, `Cancel(aec_fail)` | parcial (eco real) |
| F1-05 | VAD barato + `speech_started` + regra 1 do epoch | não (piso) |
| F1-06 | ASR incremental (`parakeet` CC-BY-4.0 **com atribuição**) e coalescing | parcial (WER em voz real) |
| F1-07 | detector de turno semântico **vs** silêncio fixo + curva falso corte × atraso | **sim, para o aceite** |
| F1-08 | S1 (`ouvir|backchannel|ceder|falar|cancelar`) | não |
| F1-09 | TTS streaming cancelável, licença comercial | não (piso) |
| F1-10 | barge-in ponta a ponta (SLO-2) | parcial |
| F1-11 | suíte de cancelamento em 20 pontos | não |
| F1-12 | histórico só com `played_ms` real | não |
| F1-13 | PTT + indicador de microfone | parcial (atalho global) |
| F1-14 | queda para PTT sem rede, e dizer isso | não |
| F1-15 | **corpus real** de turno (≥ 500 pausas consentidas) | **sim — é o dono que grava** |
| F1-16 | aceite da F1 na máquina do dono + ADR com os números | **sim** |

Doze dos dezesseis cartões fecham sem microfone. Os quatro que não fecham estão isolados de propósito, para o executor nunca ficar esperando o dono.

---

## F1-01 — Banco de teste de áudio sem microfone

**Objetivo:** todo o resto da F1 ser testável em CI headless; nenhuma suíte depender de dispositivo real.
**Entrega:** interfaces `FonteDeAudio` / `SumidouroDeAudio` em `src/jarvis/audio_io/` com três implementações — `arquivo` (WAV PCM16 mono 16 kHz, entregue em frames de 20 ms), `sintetico` (gerador por semente: fala simulada, silêncio, ruído rosa, eco atrasado) e `dispositivo` (real, só fora do CI); seleção por `JARVIS_AUDIO_BACKEND`; `Relogio` monotônico injetável para que teste de latência não dependa de `sleep`; `tools/replay_audio.py`, que injeta um WAV na cascata e grava a **trilha de eventos** em JSONL (`type`, `epoch`, `ts_mono_ns`, `payload` essencial); comparador de trilhas.
**Aceite:** (a) `pytest` completo passa em Linux e Windows **sem** dispositivo de áudio, e uma fixture proíbe abrir dispositivo real quando `CI=1` (teste prova a proibição); (b) **determinismo**: o mesmo WAV com a mesma semente produz a mesma trilha (sequência de tipos, epochs e decisões idêntica); (c) a trilha carrega o tempo do relógio injetado, de modo que asserção de latência não seja flaky; (d) `tools/replay_audio.py --trilha a.jsonl --comparar b.jsonl` acusa divergência com o primeiro evento que diferiu.
**Não verificar aqui (exige hardware real):** jitter de captura, *xruns*, latência e período do driver (PipeWire/WASAPI), deriva de relógio do dispositivo. O relatório do cartão tem de dizer, em uma linha, que nada disso foi medido.
**Fora do escopo:** AEC, VAD, ASR, TTS.
**Depende de:** F0-03.

## F1-02 — Corpus sintético de turno (≥ 500 pausas rotuladas)

**Objetivo:** ter curva de turno e regressão **antes** de existir uma única pausa real — e deixar impossível confundir uma coisa com a outra.
**Entrega:** `tools/corpus_sintetico.py`, determinístico (semente fixa comitada), que gera **≥ 500 pausas** em pt-BR: texto sintético do uso do v1 (arquivos, mídia, calendário em rascunho — Q3), áudio por TTS de licença permissiva (`rhasspy/piper-voices`, MIT, com a voz pt-BR verificada **voz por voz** conforme ADR-0012; alternativa `hexgrad/Kokoro-82M`, Apache-2.0 — [SUPOSIÇÃO: tem voz pt-BR; confirmar no model card com `tools/license_gate.py --online`]), pausa de duração sorteada em faixa declarada, mistura opcional de ruído e de eco. Rótulos em `corpus/turnos/rotulos.jsonl`, no formato do `corpus/turnos/README.md`, mais os campos novos **`"sintetico": true`**, `"semente"`, `"gerador"`, `"voz"` e `"licenca_voz"`. **`split` 70/30 decidido na criação** (`"calibracao"` / `"retido"`), nunca na hora de medir (regra 5 do `corpus/README.md`). `corpus/turnos/README.md` atualizado com os campos e com a regra de separação; manifesto de hashes regenerado.
**Aceite:** (a) `n` ≥ 500 pausas, com a proporção `fim_de_turno: true|false` **declarada e justificada** no README (o caso `false` — pausa no meio da frase — é o que mais importa); (b) `tools/corpus.py verificar` e `resumo` verdes, com contagem **separada** de sintético e real; (c) rodar o gerador duas vezes com a mesma semente produz os mesmos `sha256`; (d) item sintético **sem** `"sintetico": true` é recusado por teste; (e) item sintético **não** tem `termo` de consentimento (não se inventa termo para voz de máquina), e o teste cobre isso; (f) `split` ausente ou atribuído fora da criação é recusado.
**Não verificar aqui:** nada de latência ou de hardware. E, explicitamente: **este corpus não fecha SLO-4 nem SLO-9** (veja "Por que sintético não fecha o SLO-4", no fim do arquivo).
**Fora do escopo:** gravar pausa real — é o F1-15, e é do dono.
**Depende de:** F0-08.

## F1-03 — `audio-io`: frames de 20 ms, playback cancelável e `PlaybackProgress` real

**Objetivo:** o processo que fica perto do dispositivo cumprir o contrato da §2 — inclusive a parte chata: contar o que **saiu**, não o que foi enfileirado.
**Entrega:** captura em frames de 20 ms sobre as fontes do F1-01, emitindo `AudioActivity` (`device_id`, `energy_db`); playback de pedaços de TTS com `epoch` e fila esvaziável **no mesmo tick** (regra 2 da §3.3); `PlaybackProgress` com `played_ms` derivado das amostras **consumidas pelo sumidouro**; botão de privacidade que corta na fonte, não na interface.
**Aceite:** (a) cancelar no meio de um pedaço deixa `played_ms` na amostra realmente consumida (± 1 frame) e o resto nunca aparece em nenhum evento; (b) fila de 2 s de áudio enfileirado é esvaziada no mesmo tick do `Cancel` (teste); (c) pedaço com `epoch` menor que o atual é descartado e nunca toca; (d) privacidade ligada → zero amostra sai da fonte (teste conta bytes) e `AudioActivity` para; (e) **piso** de captura→`AudioActivity` publicado sobre a fonte `arquivo` (p50/p95/p99, 3 execuções) com a etiqueta "piso de software, sem dispositivo".
**Não verificar aqui (exige hardware real):** SLO-1 de verdade, latência do caminho de saída, cancelamento perceptível ao ouvido (a fila do driver não é a nossa fila).
**Fora do escopo:** AEC (F1-04), VAD (F1-05).
**Depende de:** F1-01.

## F1-04 — AEC / NR / AGC com referência de loopback

**Objetivo:** o assistente não se ouvir falar. Sem isso, o barge-in do F1-10 dispara no próprio TTS e toda a medição de turno mente.
**Entrega:** cadeia AEC → NR → AGC no `audio-io`, com referência do **nosso próprio playback** (o que o F1-03 entrega); biblioteca de licença permissiva inventariada na porta de licença (candidatos: `webrtc-audio-processing`, BSD-3; `speexdsp`, BSD — versão e licença verificadas no CI, F0-09); `aec_ok` no `AudioActivity`; `Cancel(reason: aec_fail)` quando a referência se perde (dispositivo trocado, taxa diferente, deriva de relógio).
**Aceite:** (a) mistura **sintética** fala + eco (nosso TTS atrasado 60/120/240 ms, a −6/−12/−20 dB): ERLE em dB publicado por condição, com `n` e 3 execuções; (b) **o aceite que importa**: sem AEC, o VAD do F1-05 dispara no nosso próprio áudio (teste que prova o problema); com AEC, não dispara — nas três condições; (c) troca de dispositivo no meio emite `aec_fail`, e o assistente não passa a falar sozinho; (d) deriva de relógio simulada (± 100 ppm) não trava nem estoura a cadeia.
**Não verificar aqui (exige hardware real):** eco real de alto-falante aberto na sala do dono, no volume de uso; duplo-falar real (os dois falando junto); diferença entre headset e alto-falante; eco de cauda longa do ambiente dele. Eco sintético é **limite inferior** de dificuldade: dizer isso no relatório.
**Fora do escopo:** supressão de ruído de nível de produto (um NR razoável basta); separação de falantes.
**Depende de:** F1-03.

## F1-05 — VAD barato, `speech_started` e a regra 1 do epoch

**Objetivo:** o evento mais importante do sistema (começou a falar) sair rápido e **sem esperar ninguém**.
**Entrega:** `silero-vad` (MIT, já verificado na F0-09) atrás da interface do F1-01, frames de 20 ms e janela de 512 amostras a 16 kHz (como a F0-04 mediu); histerese configurável (início, fim, *hangover*); `AudioActivity(speech=true)` com `speech_started` em **P0**; a regra 1 da §3.3 implementada no lugar certo: `epoch := epoch + 1` e `Cancel(epoch_anterior)` imediatos, **sem** esperar ASR nem S2.
**Aceite:** (a) sobre o corpus sintético: recall e precisão de início de fala com `n` e matriz de confusão; (b) teste da regra 1: `speech_started` publica `Cancel` P0 **antes** de qualquer `PartialTranscript` (ordem na trilha, não cronômetro); (c) piso de SLO-1 publicado em `docs/medicoes/f1-05-vad.csv|md` (p50/p95/p99 de frame→`AudioActivity`, 3 execuções); (d) o número da F0-04 (0,110 ms de VAD + 0,384 ms de evento) é **reconfirmado ou corrigido** com a cadeia real (AEC incluído); (e) se o piso já passar de 80 ms p95, o cartão termina em `precisa_decisao` e abre o gatilho da ADR-0014 — não se ajusta o SLO.
**Não verificar aqui (exige hardware real):** SLO-1 com microfone (é o aceite (a) da F1, e sai no F1-16); VAD em ruído real da casa do dono.
**Fora do escopo:** decisão de fim de turno — é F1-07. VAD não decide turno (§2).
**Depende de:** F1-04.

## F1-06 — ASR incremental, com a atribuição CC-BY como teste

**Objetivo:** texto parcial utilizável cedo, sem 10 raciocínios por 10 parciais, e com a licença em ordem.
**Entrega:** `agentd` com `TranscritorIncremental` e **duas** implementações registradas na porta de licença: `nvidia/parakeet-tdt-*` (CC-BY-4.0, atribuição obrigatória — ADR-0012) e `openai/whisper-large-v3` (Apache-2.0) como controle; `PartialTranscript` com `text`, `stability`, `t_start_ms`, `t_end_ms`, `lang`; `FinalTranscript` com `confidence`; o coalescing da §3.4 (10 parciais em 200 ms substituem a hipótese e geram **1** revisão); atribuição CC-BY no produto — `NOTICE`, tela "sobre" da `ui` e `README` —, com teste que **falha** se o modelo CC-BY estiver configurado e a atribuição não estiver no pacote.
**Alerta de fato, a resolver dentro deste cartão:** o modelo que está hoje na tabela, `nvidia/parakeet-tdt-0.6b-v2`, é de **inglês**. Para pt-BR é preciso registrar e verificar na origem o multilíngue (`parakeet-tdt-0.6b-v3` — [SUPOSIÇÃO: ~25 idiomas, inclui português, CC-BY-4.0; confirmar no model card com `tools/license_gate.py --online`]) ou ficar com o `whisper`. **Não existe WER de pt-BR deste projeto hoje**: medir é parte da entrega, e a tabela de licenças só muda pelo gerador, nunca à mão.
**Aceite:** (a) WER/CER em pt-BR sobre o corpus sintético (split `calibracao`), por implementação, com `n` — publicado **com a ressalva** de que TTS sintético é material fácil; (b) SLO-3 (primeiro parcial utilizável) medido sobre arquivo, p50/p95, com a definição de "utilizável" escrita antes de medir (`stability` mínima); (c) coalescing provado: 10 parciais em 200 ms → 1 `StateRevision`; (d) teste de atribuição: apagar a linha do `NOTICE` quebra o CI; (e) `docs/licencas.md` atualizado pelo `license_gate`, com data de acesso e fonte oficial.
**Não verificar aqui (exige hardware real):** SLO-3 ao vivo; WER na voz do dono, com o microfone e o ruído dele; comportamento com sotaque, nome próprio e termo do domínio dele.
**Fora do escopo:** diarização; ASR em nuvem.
**Depende de:** F1-05.

## F1-07 — Detector de turno: semântico **vs** silêncio fixo, e a curva falso corte × atraso

**Objetivo:** responder, com número, a pergunta que dá nome à fase: quando calar. A SPEC §7 é explícita — o que se otimiza é a **curva**, não um número único de latência.
**Entrega:** interface `DetectorDeTurno` e **duas** implementações: `silencio_fixo` (limiar em ms, o controle honesto) e `semantico` (`p_eot` a partir do texto parcial + pausa/prosódia; só modelo de licença permissiva registrado na porta de licença, ou classificador nosso treinado **apenas** no corpus do projeto — nada CC-BY-NC entra aqui); `TurnPrediction` com `p_eot`, `detector` e `decision: hold|yield|unknown`; `tools/curva_turno.py`, que faz a varredura de limiares e publica **a curva** falso corte × atraso em `docs/medicoes/f1-07-turno.csv` + `.md`, com A/B **pareado** no mesmo corpus e intervalo de confiança.
**Regra de empate, escrita antes de medir (e não no fim do relatório):** o detector semântico só entra no v1 se, **no mesmo atraso**, reduzir o falso corte, ou, **no mesmo falso corte**, reduzir o atraso. Empate dentro do intervalo de confiança → fica o `silencio_fixo`, que é mais simples e mais explicável.
**Aceite:** (a) curva publicada para os dois detectores no mesmo corpus, limiar escolhido no split `calibracao` e número reportado no split `retido`; (b) SLO-4 (pausa → decisão) p50/p95 do caminho de software, com `n`; (c) `unknown` nunca vira `yield` (teste): sem confiança, não interrompe; (d) a âncora externa fica declarada como âncora, não como meta nossa (Semantic VAD, −53,3% de latência em conjunto interno; Voice-Light, recall de EOT aprendido de 12,53% contra 95,60% do Silero — relatório 01); (e) o cartão diz, com número, se o alvo **[SUPOSIÇÃO]** do SLO-9 (≤ 3% de falso corte) se sustenta, e prepara a ADR do F1-16.
**Não verificar aqui (exige corpus real + máquina do dono):** **o aceite (d) da F1 não fecha neste cartão.** A curva sobre corpus sintético serve para **ordenar candidatos e pegar regressão**; o número publicado de SLO-4 e SLO-9 sai do corpus real (F1-15), medido na máquina do dono (F1-16). Um relatório que apresente a curva sintética como aceite da fase é motivo de recusa na revisão.
**Fora do escopo:** S2S nativo (F5); adaptar o detector por falante.
**Depende de:** F1-06, F1-02.

## F1-08 — S1: a decisão de 20–100 ms

**Objetivo:** a reação rápida existir como tabela auditável, não como efeito colateral do LLM.
**Entrega:** S1 em `agentd` — `ouvir | backchannel | ceder | falar | cancelar` — **determinístico, sem LLM**, a partir de `TurnPrediction`, `AudioActivity`, estado de playback e cenário; tabela de decisão versionada em arquivo de dados (não espalhada em `if`); orçamento de 20–100 ms com guarda: estourou o teto → `ouvir`, nunca `falar`.
**Aceite:** (a) a tabela de decisão tem um teste por linha, inclusive as linhas que levam a `cancelar`; (b) p95 da decisão medido com `n` ≥ 10 000; (c) atraso injetado estoura o orçamento e cai em `ouvir` (teste); (d) S1 não publica fala de epoch morto (§2, proibição do `s2` vale aqui também); (e) replay: a mesma trilha do F1-01 produz a mesma sequência de decisões.
**Não verificar aqui:** nada depende de hardware — **este cartão é 100% testável sem microfone**, e o relatório pode afirmar isso sem ressalva.
**Fora do escopo:** escolher *o que* dizer (é o `s2`, F2).
**Depende de:** F1-07.

## F1-09 — TTS streaming cancelável, com licença comercial

**Objetivo:** primeiro áudio cedo e **interrupção no meio da síntese**, não só no meio da fila.
**Entrega:** TTS em streaming atrás de interface, no caminho `agentd → audio-io`; licença comercial obrigatória: `rhasspy/piper-voices` (MIT, **voz por voz** — algumas vozes são CC-BY-SA, ADR-0012) e `hexgrad/Kokoro-82M` (Apache-2.0) como candidatos; **`coqui/XTTS-v2` está barrado** e qualquer dependência dele reprova a porta de licença; síntese em pedaços com `chunk_id` e `epoch`, primeiro pedaço o mais curto que a prosódia aceite; o processo de síntese é **interrompível**: depois do `Cancel`, não escreve mais nada no sumidouro.
**Aceite:** (a) tempo até o primeiro pedaço (p50/p95) por candidato, sobre texto do corpus, publicado com `n`; (b) `Cancel` no meio da síntese: zero amostra nova chega ao sumidouro depois do tick (teste conta amostras), e nenhum pedaço de epoch velho toca; (c) invariante testada: `played_ms` ≤ amostras sintetizadas, sempre; (d) voz com licença fora da permissiva não carrega — teste injeta uma voz CC-BY-SA e o carregamento falha com mensagem clara; (e) **piso** de SLO-5 (fim de turno aceito → primeiro áudio) ponta a ponta sobre arquivo.
**Não verificar aqui (exige hardware real):** SLO-5 de verdade (a fila do dispositivo entra na conta); qualidade e naturalidade da voz pt-BR no alto-falante dele — isso é julgamento do dono, não teste.
**Fora do escopo:** clonagem de voz; escolha estética da voz (o dono escolhe no F1-16).
**Depende de:** F1-03.

## F1-10 — Barge-in ponta a ponta (SLO-2)

**Objetivo:** fechar o caminho inteiro da regra 1: começou a falar → o assistente cala em ≤ 150 ms p95, **sem esperar transcrição**.
**Entrega:** caminho completo instrumentado — `speech_started → epoch++ → Cancel P0 → fila de playback vazia → síntese interrompida → s2 cancelado` — com um marcador por salto na trilha de eventos; extrator que calcula SLO-2 a partir da trilha; decomposição por salto.
**Aceite:** (a) p50/p95 de `speech_started` → última amostra tocada, sobre fonte `arquivo`, 3 execuções, `n` ≥ 200 interrupções; (b) **nenhum salto espera ASR**: teste que atrasa o ASR em 2 s e mostra SLO-2 intacto; (c) decomposição publicada (quem gasta o quê), para que otimizar depois não seja chute; (d) se o p95 já estourar 150 ms no piso de software, o cartão termina em `precisa_decisao` com o gatilho da ADR-0014 aberto.
**Não verificar aqui (exige hardware real):** SLO-2 com microfone e alto-falante reais — é o aceite (a) da F1 e sai no F1-16. O piso de software ignora a fila do driver, que é justamente onde o áudio velho sobrevive.
**Fora do escopo:** cancelar tool de efeito já executada (não existe no v1 por especulação — §3.3 regra 3).
**Depende de:** F1-09, F1-05.

## F1-11 — Suíte de cancelamento em 20 pontos

**Objetivo:** o aceite (b) da F1, que é o mais duro: interromper em 20 pontos distintos e nada sobrar.
**Entrega:** suíte parametrizada que interrompe **uma mesma resposta** em 20 pontos nomeados e listados no arquivo — antes do primeiro pedaço; durante a síntese do primeiro; entre pedaços; no meio de um pedaço; no último pedaço; com parcial instável na tela; durante recuperação de memória; durante tool de **leitura** em voo; depois do `ToolResult` e antes da fala; durante `StateRevision`; com fila cheia; com dois `Cancel` seguidos; com `speech_started` espúrio (eco, cobre o F1-04); etc. Três invariantes conferidas em **cada** ponto: **0** áudio velho tocando, **0** entrada no histórico de algo não tocado, **0** tool disparada depois do `Cancel`.
**Aceite:** (a) 20 pontos, um caso de teste nomeado cada, passando em Linux e Windows; (b) as **seis** regras da §3.3 têm pelo menos um ponto que as exercita, incluindo a exceção da regra 3 (`ToolResult` de leitura pode chegar, e só entra se o `s2` reavaliar); (c) fuzz com ponto de interrupção aleatório (semente comitada, `n` ≥ 1 000) sem violar as três invariantes; (d) a suíte entra no `tools/verificar.py`, para virar regressão e não evento único.
**Não verificar aqui:** nada depende de hardware. O que **não** se prova aqui é o áudio já entregue ao driver: a invariante é sobre o nosso sumidouro.
**Fora do escopo:** cancelamento de tool de escrita (F4).
**Depende de:** F1-10.

## F1-12 — Histórico com `played_ms` real

**Objetivo:** o aceite (c) da F1 e a regra 4 da §3.3 — o que o modelo lembra é o que o dono **ouviu**.
**Entrega:** histórico de turno construído a partir de `PlaybackProgress`, com o mapeamento texto ↔ amostras do F1-09; retomada ("continua") resolvida **do trecho tocado** (regra 5), sem ressuscitar plano antigo; entrada de histórico carrega `epoch` e `played_ms` e vai para o log encadeado.
**Aceite:** (a) interromper no meio deixa no histórico exatamente o prefixo tocado — comparação caractere a caractere com o mapeamento, em 20 interrupções (reaproveita o F1-11); (b) texto enfileirado e não tocado **não existe** para o modelo (teste busca o sufixo no histórico e exige ausência); (c) "continua" retoma do prefixo tocado, e um teste prova que o plano antigo não volta; (d) o log encadeado mostra `played_ms` e `epoch` de cada entrada, e adulterar quebra a cadeia (reaproveita a F0-02).
**Não verificar aqui:** nada depende de hardware.
**Fora do escopo:** resumo/consolidação de histórico (F3).
**Depende de:** F1-03, F1-09.

## F1-13 — PTT e indicador de microfone que não mente

**Objetivo:** o dono saber, sem interpretar, quando o microfone está aberto — e ter um caminho que funciona mesmo quando a escuta contínua não funciona.
**Entrega:** PTT na `ui` com backend de atalho **injetável** (`JARVIS_HOTKEYS_BACKEND` falso para teste, como o Jarvis anterior fez no Wayland); indicador de microfone derivado do estado **real** da fonte (amostras consumidas), nunca da intenção da UI; *kill switch* que corta captura e playback; estado vazio útil quando não há dispositivo (explica e oferece o modo de arquivo, em vez de tela morta).
**Aceite:** (a) com o backend falso, pressionar e soltar abre e fecha a captura, e o indicador segue a fonte (com o indicador apagado, a contagem de amostras é 0); (b) propriedade testada nas duas direções: nunca "ouvindo" com a fonte fechada, nunca fonte aberta com o indicador apagado; (c) *kill switch*: zero amostra, zero evento, e a UI diz que está desligado; (d) sem dispositivo, a UI explica em uma frase e oferece PTT com áudio de arquivo (modo de teste).
**Não verificar aqui (exige a máquina do dono):** atalho **global** de verdade — portal `GlobalShortcuts`/KGlobalAccel no Wayland e o caminho do Windows —, inclusive se outro aplicativo rouba a combinação; e se o indicador é visível onde ele realmente olha.
**Fora do escopo:** bandeja/tray e autostart (fase de empacotamento).
**Depende de:** F1-03.

## F1-14 — Sem rede: cai para PTT e **diz** isso

**Objetivo:** o aceite (e) da F1. Degradar é obrigatório; degradar em silêncio é defeito.
**Entrega:** detecção de perda de rede/serviço **no adaptador** (injeção, nunca mexendo no firewall da máquina) e degradação declarada: desliga escuta contínua, liga PTT, avisa na UI e **uma vez** por voz, mantém o que é local (VAD, ASR local, TTS local); nenhum pedido pendurado em fila; na volta, confirma e **não** repete pedido velho.
**Aceite:** (a) derrubar a rede no meio de um turno → PTT em ≤ 1 turno, aviso na UI, nenhum travamento e nenhum *timeout* longo herdado; (b) a mensagem diz, em uma frase, o que deixou de funcionar; (c) rede de volta não ressuscita o pedido antigo (regra 5) e não dispara nenhuma tool de efeito; (d) a cascata local inteira roda offline no CI (teste que proíbe socket externo); (e) o aviso por voz não se repete em loop.
**Não verificar aqui:** nada de hardware. O que **não** se testa aqui é a rede real do dono (Wi-Fi caindo devagar, DNS lento) — isso vira observação no F1-16, não número.
**Fora do escopo:** fila de trabalho offline (F4).
**Depende de:** F1-13, F1-06.

## F1-15 — Corpus **real** de turno: ≥ 500 pausas consentidas — **do dono**

**Objetivo:** dar à F1 o único corpus que fecha SLO-4 e SLO-9 (Q4 da SPEC §11: quem grava é o dono, com o orquestrador conduzindo).
**Entrega:** ≥ 500 pausas reais em pt-BR no formato do `corpus/turnos/README.md`, com `"sintetico": false`, `termo` do `CONSENTIMENTO.md` preenchido, e `split` 70/30 decidido na entrada; roteiro de gravação que cobre pedido curto, frase com pausa no meio, enumeração ("abre o… espera… abre o outro"), hesitação, ruído de casa, música ao fundo e dois falantes (com termo); a proporção real de `fim_de_turno: false` **medida**, não suposta.
**Aceite:** (a) `n` ≥ 500 publicado com a distribuição de pausa (ms) e de contexto; (b) `tools/corpus.py verificar` verde e manifesto de hashes cobrindo os áudios; (c) nenhum segredo e nenhuma terceira pessoa sem termo — teste de redação mais conferência do campo `termo`; (d) o relatório diz máquina, microfone e sala: isso faz parte do número.
**Quem faz:** **dono + orquestrador.** O executor não grava nada e não toca no microfone de ninguém; se faltar corpus, o cartão dependente para em `precisa_decisao`, não em estimativa.
**Depende de:** F1-02 (formato e campos já em pé).

## F1-16 — Aceite da F1 na máquina do dono e a ADR com os números

**Objetivo:** fechar a fase com medição real e decisão registrada — e com o gatilho de reabertura de D1 conferido.
**Entrega:** `tools/aceite_f1.py`, roteiro único que, **com microfone e alto-falante reais e o corpus real**, mede SLO-1, SLO-2, SLO-3, SLO-4 e SLO-5 e publica `docs/medicoes/f1-16-aceite.csv|md` com hardware, `n` e 3 execuções, separando `sintetico` de `real` em toda tabela; refaz a curva falso corte × atraso do F1-07 no corpus real, split `retido`; ADR da F1 com a escolha de **detector de turno**, **ASR** e **TTS** decidida pelos números e pela regra de empate do F1-07; conferência explícita do gatilho da ADR-0014.
**Aceite:** (a) os cinco SLOs publicados na máquina do dono, com hardware descrito e `n`; (b) curva final no corpus **real** (split retido) e veredito numérico sobre o SLO-9 (os ≤ 3% se sustentam, ou mudam — com o número e a data); (c) ADR com número, hardware, `n`, data e commit, sem afirmação sem fonte ou sem marca **[SUPOSIÇÃO]** (mesma porta do F0-10); (d) `tools/verificar.py` verde; (e) se SLO-1 > 80 ms p95 ou SLO-2 > 150 ms p95, o cartão termina em `precisa_decisao` com **D1 reaberta** pela ADR-0014 — e não com o SLO reescrito para caber; (f) a SPEC §7 é atualizada se algum SLO mudar, com o commit citado.
**Quem faz:** executor conduz, **dono presente** — o microfone, a sala e a voz são dele.
**Depende de:** F1-15 e todos os cartões anteriores.

---

## O que só o dono pode validar na máquina dele

| Item | Cartão que preparou | Por que não fecha sem ele |
|---|---|---|
| SLO-1 (captura → evento de fala) com microfone real | F1-05 (piso) | jitter, período do driver e ruído de entrada são do hardware, não do nosso código |
| SLO-2 (barge-in) com alto-falante real | F1-10 (piso) | o áudio velho sobrevive na fila do dispositivo, que o sumidouro falso não tem |
| SLO-3 e WER em pt-BR na voz dele | F1-06 (piso sintético) | TTS sintético é material fácil; sotaque, nome próprio e ruído de casa não estão lá |
| **SLO-4 e SLO-9 (curva falso corte × atraso)** | F1-07 (ordenação) | pausa humana real é o fenômeno medido; sintético não reproduz hesitação |
| AEC com eco real e duplo-falar | F1-04 (eco sintético) | sala, volume e caminho acústico são dele |
| SLO-5 (primeiro áudio) e a voz escolhida | F1-09 (piso) | fila de saída real, e a escolha de voz é julgamento, não teste |
| Atalho global de PTT e visibilidade do indicador | F1-13 (backend falso) | conflito com outros aplicativos e ergonomia da tela dele |
| Rede caindo de verdade (Wi-Fi, DNS lento) | F1-14 (injeção) | injeção cobre o contrato, não a rede dele |

Nenhum desses itens autoriza o executor a inventar número: na ausência do dono, o cartão publica o **piso de software**, com essa etiqueta, e segue.

## Por que sintético não fecha o SLO-4

O corpus sintético do F1-02 existe para três coisas: desenvolver sem esperar o dono, pegar regressão no CI e **ordenar** candidatos de detector. Ele não fecha o aceite (a) nem o (d) da F1, por três razões escritas aqui para não serem renegociadas depois:

1. **A pausa sintética é a que nós escolhemos.** A distribuição de duração sai da nossa faixa sorteada; a pausa humana tem hesitação, respiração, retomada e pausa longa que **não** é fim de turno. Medir falso corte contra o nosso próprio gerador mede o gerador.
2. **Voz de TTS não tem o que engana o detector.** Prosódia de fim de frase sintética é mais limpa do que a real, e o detector semântico se beneficia de forma injusta — exatamente no eixo em que ele está sendo comparado com o silêncio fixo.
3. **O SLO-9 já está marcado [SUPOSIÇÃO] na SPEC §7**, para ser recalibrado com o corpus pt-BR da F1. Recalibrar com corpus sintético seria trocar uma suposição por outra, com aparência de medição.

Toda tabela, relatório e ADR da F1 carrega a coluna `sintetico`. Média que mistura os dois é recusada na revisão.

## Fechamento da F1

A F1 só fecha com: SLO-1, SLO-2, SLO-3 e SLO-4 medidos **na máquina do dono** (F1-16); suíte de cancelamento em 20 pontos verde nos dois SOs (F1-11); histórico contendo só `played_ms` real (F1-12); curva falso corte × atraso publicada no **corpus real**, com A/B entre silêncio fixo e detector semântico e a regra de empate aplicada (F1-07 + F1-16); queda para PTT sem rede, declarada ao dono (F1-14); porta de licença verde com a atribuição CC-BY do ASR dentro do produto (F1-06); e `tools/verificar.py` verde.

**O que a F1 não decide:** índice de memória (§8.1), grafo no caminho crítico (§8.2), backend de calendário (D2), nem nada de tool por julgamento — isso é F2/F3/F4. E a F1 **não** adota S2S: a comparação contra a cascata é F5, no mesmo corpus desta fase.

## Pendências do dono que tocam a F1

| # | Pendência | Onde aparece |
|---|---|---|
| — | **Gravar o corpus real** (≥ 500 pausas, com termo) — é o que destrava o aceite da fase | F1-15 |
| — | **Escolher a voz** do TTS entre as de licença permissiva, ouvindo os candidatos | F1-09, F1-16 |
| — | Confirmar se ASR **local** basta no v1, ou se pode haver ASR remoto (muda egress e o F1-14) | F1-06, F1-14 |
| Q1 | D1 fica fechada por ADR-0014, mas **reabre por número** se o F1-05/F1-10 estourarem o SLO | F1-05, F1-10, F1-16 |
