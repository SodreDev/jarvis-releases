# Handoff — ruído não vira pedido, e os nomes do dono ouvidos e falados certo

Pedido do dono de 2026-10-21, em duas tarefas: (1) ruído do microfone (estalo, respiração, teclado,
mouse, ventilador) virando texto e o Jarvis agindo sobre isso; (2) nomes de apps, pessoas e termos
saindo errados no ASR e no TTS. Commits: `9499379` (sinais do ASR), `86555bc` (portão e filtro),
`c8288b0` (dica curta e medição), `8f10fb6` (vocabulário), `118da02` (a tool que aprende), e o
commit destes docs. ADRs: **0043** (ruído) e **0044** (vocabulário); emendas na 0017, 0021 e 0040.
COMO-TESTAR §0.27 e §0.28.

## 1. Ruído não vira pedido (ADR-0043)

**A causa, medida** (`tools/harness_ruido.py` → `docs/medicoes/ruido-e-dica.md`, áudio sintético,
whisper small): o laço mandava ao ASR qualquer trecho que o VAD abrisse (uma janela de 32 ms do
silero basta), com 400 ms antes e ~1,3 s de silêncio; a dica do whisper local era a lista dos apps
instalados (~480 caracteres em `hotwords` **e** `initial_prompt`), que fazia ruído virar nome de app
(3 de 8; na exploração, 4 de 4) e era a mais lenta; e a regra padrão do Whisper deixava passar o
texto inventado (`no_speech_prob` 0,39–0,95 contra ≤ 0,17 da fala). O silero não abriu trecho para
nenhum ruído sintético: o risco real é o ruído de verdade que o engana, o VAD de energia (sem o peso
do silero) e a escuta armada.

**Onde está:**

- `src/jarvis/voz/interface.py` — `Sinais`, `Transcricao`, `transcrever_com_sinais(motor, …)`.
- `src/jarvis/agentd/asr.py` (`MotorWhisper.transcrever_com_sinais`, `dica` só como
  `initial_prompt`) e `src/jarvis/voz/groq.py` (`transcrever_com_sinais`, `_transcricao_de`, `dica`
  → `prompt`).
- `src/jarvis/voz/ruido.py` — `medir_trecho`/`julgar_audio` (o portão: 100 ms seguidos a 6 dB acima
  do fundo, percentil 20 do trecho), `julgar_texto` (o filtro), `sinais_fortes`, `so_cortesia`,
  `PoliticaDeRuido` com os padrões, e as listas (`_SEMPRE`, `_FRACAS`, `_FRACAS_PADROES`).
- `src/jarvis/voz/dica.py` — `dica_do_asr` (palavra de ativação + até 11 termos, ≤ 200 caracteres).
- `src/jarvis/voz/app.py` — `_turno_de_audio` (portão → ASR com sinais → filtro → vocabulário → "sim"
  sem certeza), `_montar_a_vigia` (a vigia com o mesmo filtro), `_pedido_do_trecho` e
  `_pedido_por_cima` ("Jarvis. Obrigado." arma), `_ruido_descartado` (contador e trilha),
  `politica_de_ruido`, `_palavras_da_dica`, `_sim_sem_certeza`, `_dica_do_asr`.
- `src/jarvis/voz/config.py` — `filtro_de_ruido`, `fala_minima_ms`, `margem_de_fala_db`,
  `sem_fala_maximo`, `politica_de_ruido()`. `src/jarvis/voz/escuta.py` — `Escuta.ruidos`.
- `src/jarvis/trilha.py` — evento `ruido` (`etapa`, `motivo`, `modo`, `ms`, `maior_fala_ms`,
  `contraste_db`, `sem_fala`, `logprob`), os códigos e `ruidos_descartados`; `src/jarvis/voz/cli.py`
  — as linhas do filtro no `--diagnostico`.
- Saiu: `dicas_de_apps` (apps instalados na dica) e `_nomes_dos_apps`.

**Decisões que valem lembrar:** motor sem sinais (oráculo, falsos) só sofre as frases que valem
sempre — nada do que já funcionava muda; o trecho `por_cima` não passa pelo portão (a vigia já
julgou), mas passa pelo filtro; "para" e "pra" não são palavras sem peso (o eco da dica não engole
"Jarvis, para"); fim de vídeo que pode ser pedido ("me inscreve no canal", "abre o link na
descrição", "pula até o próximo vídeo") só cai inteiro e sem certeza.

**Armadilhas:** os fixtures do laço usam WAV de nível **constante** (`wav_de`, `wav_longo`) com VAD
falso — o portão os recusa, com razão; `tests/unit/voz/test_app.aplicativo_de`,
`tests/unit/gui/test_nucleo.sessao` e `tests/unit/gui/test_botao_de_falar.CONFIGURACAO` desligam o
filtro, com o porquê. O ventilador sintético fica a ~6 dB do próprio fundo e o clique isolado nem
chega ao percentil 95: saem `fundo` **ou** `impulso` conforme a semente (os dois não chegam ao
ASR). O whisper volta com temperatura quando o logprob cai: o texto inventado muda de rodada para
rodada.

**Testes:** `tests/unit/voz/test_ruido.py`, `test_ruido_no_laco.py`, `test_asr_local.py`,
`test_groq.py`, `test_asr_dicas_de_apps.py`, `tests/unit/test_trilha.py`, `test_cli.py`,
`tests/unit/test_harness_ruido.py`.

## 2. O vocabulário do dono (ADR-0044)

**Onde está:**

- `src/jarvis/voz/vocabulario.py` — `Termo`, `Vocabulario` (`corrigir`, `pronunciar`,
  `termos_da_dica`), `ler_vocabulario` (tolerante), `RepositorioDoVocabulario` (`carregar`,
  `aprender`, `esquecer`; `padrao(ambiente)` é `None` para ambiente explícito sem casa).
- `docs/exemplos/vocabulario.toml` — o exemplo (nomes fictícios e apps comuns).
- `src/jarvis/agentd/tts.py` — `SintetizadorEmStreaming.pronunciar` (só o texto do motor muda).
- `src/jarvis/voz/app.py` — `vocabulario` (o repositório; `None` na suíte), `_ler_o_vocabulario`
  (uma vez por abertura), `recarregar_vocabulario` (vale já: dica do ASR aberto, correção,
  pronúncia), `_pronunciar` (pelo id do motor que fala).
- Produção: `src/jarvis/gui/principal.py` → `Ponte(vocabulario=…)` → `SessaoDeVoz.vocabulario` →
  `Aplicativo`; `src/jarvis/voz/cli.py` (`main` e o `--diagnostico`).
- A tool: `catalogo/vocabulario.aprender.yaml` (moderada, desfaz com `acao.desfazer`), o stub em
  `src/jarvis/capacidades/`, o corpo e o desfazer em `src/jarvis/executor/ferramentas.py`
  (`FERRAMENTA_DE_VOCABULARIO`, tipo de desfazer `vocabulario`), o portão em
  `src/jarvis/politica/vocabulario.py` (chamado pelo `Pdp._decidir`), `FORA_DA_ALLOWLIST` das
  tarefas, e a persona v14 (NOMES DO DONO).

**Decisões que valem lembrar:** o arquivo do dono nunca é reescrito (o aprendido é outro arquivo);
só a `escrita` já serve (entra na dica — "não é disco, é Discord" sem fazer de "disco" apelido); a
fonética só vale para nome composto; a pronúncia mais recente vence; `motores` restringe a voz.

**Testes:** `tests/unit/voz/test_vocabulario.py`, `test_vocabulario_no_laco.py`,
`tests/unit/executor/test_vocabulario_aprender.py`, `tests/unit/politica/test_tiers.py`,
`tests/unit/s2/test_persona.py`.

## O que não foi provado

Nada com microfone, voz do dono ou ruído de verdade: ruídos e fala sintéticos (a piper com o
espeak-ng só em `tools/`), o ASR medido é o whisper **small**, não a Groq turbo do dono — os
limiares de `no_speech_prob` e logprob não foram medidos nela. O `claude -p` real chamando
`vocabulario.aprender`, a pronúncia soando bem em cada voz, e a fonética com os nomes do dono.

## Próximos passos sugeridos

1. Uma semana de uso real e o `jarvis-voz --diagnostico`: a contagem por motivo e os números da
   trilha `ruido` dizem se o portão e o `sem_fala_maximo` precisam de ajuste na Groq turbo.
2. Se uma fala curta do dono sumir: afrouxar `fala_minima_ms` / `margem_de_fala_db` /
   `sem_fala_maximo` no `jarvis-voz.toml`, com o número da trilha na mão.
3. Medir a mesma bateria do harness com a Groq (`whisper-large-v3-turbo`) — exige a chave e
   autorização do dono para mandar o áudio sintético para fora.
