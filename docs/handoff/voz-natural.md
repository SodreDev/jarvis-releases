# Handoff — o Jarvis natural: interromper por voz, falar menos, encerrar, fechar × encerrar app

Pedido do dono de 2026-10-21 ("todos para o Jarvis ficar NATURAL"), em quatro partes, um commit
cada. Este arquivo cresce a cada parte: o que mudou, onde está, como testar e o que **não** foi
provado.

## 1. Interromper por voz (ADR-0040)

**O problema:** o laço do `jarvis-voz` (`jarvis.voz.app.Aplicativo`) não lia o microfone enquanto
o Jarvis falava; só o botão (a barra, o PARAR) interrompia.

**Onde está:**

- `src/jarvis/voz/interrupcao.py` — `PortaoDeEco` (detector de fala dupla por energia: o eco
  previsto pela referência dos últimos 300 ms menos a perda aprendida, o ambiente pelo percentil 30
  dos últimos 5 s com o Jarvis calado, piso de −50 dBFS) e `VigiaDeInterrupcao` (suspeita em 240 ms
  de fala que passou no portão; na contínua pausa na hora; o trecho vai ao ASR numa linha à parte e
  de novo a cada 400 ms de fala nova; corta com a palavra de ativação, a ordem de parar ou o
  detector; descarta eco, vazio, falha; a "fala contida" não pausa de novo).
- `src/jarvis/voz/app.py` — `_enquanto_fala` (teclado + `_ouvir_por_cima`) no lugar do
  `_olhar_o_teclado` dentro de `_tocar` (entre quadros e no `ao_esperar` da síntese);
  `_montar_a_vigia` (ASR com `_trava_do_asr`, `ThreadPoolExecutor` de 1 linha, detector se houver);
  `_fala_por_cima` → `_continuar_o_dono` no laço principal (o trecho vira o começo do turno novo);
  `_turno_de_audio(por_cima=True)` → `_pedido_por_cima` (o que vem depois do nome; sem o nome,
  sem o eco) e "só ordem de parar" não vai ao motor; `fila.escuta = vigia.portao.referencia`.
- `src/jarvis/voz/config.py` — `interromper_por_voz` (padrão `true`).
- `src/jarvis/trilha.py` — evento `interrupcao` (`modo`, `decisao`, `motivo`, `ms`) e os códigos.

**Decisões que valem lembrar:** no atalho (PTT) a vigia não ouve (o dedo decide); na palavra não
há pausa (a TV faria gaguejar); o corte é o `interromper("voz")` de sempre — o epoch morre, e a
pergunta não ouvida cai (fala não confirma ação sozinha); o detector do Jev só **confirma** o
corte na contínua (emenda à ADR-0029).

**Testes:** `tests/unit/voz/test_interromper_por_voz.py` (21). Áudio sintético
(`jarvis.audio_io.sintese`: eco = cópia atrasada e atenuada; TV = fala mais baixa; dono = fala mais
alta) e ASR falso; o laço inteiro roda com `JARVIS_AUDIO_BACKEND=arquivo` (WAV entra como
microfone) e `RelogioFalso`.

**Não provado:** microfone e alto-falante reais, voz do dono, sala, TV real, o whisper
transcrevendo "Jarvis" por cima do próprio Jarvis, o tempo do ASR com a CPU disputada, o
`module-echo-cancel` do PipeWire (o passo a passo está no COMO-TESTAR §0.22). A `CadeiaDeAec`
(F1-04) continua fora do laço: ligá-la é o próximo passo, depois de medida no hardware do dono.

**Próximos passos possíveis:** medir no F1-16 (trilha `interrupcao`); ligar a AEC medida e deixar o
VAD cortar direto; um interruptor na tela de Configuração para `interromper_por_voz`.

## 2. Falar menos (emenda à ADR-0031)

**O problema:** a persona pedia resposta curta, mas nada no código segurava o que ia para o TTS; a
resposta de uma tarefa (ADR-0038) era falada inteira.

**Onde está:**

- `src/jarvis/s2/orcamento_da_fala.py` — `OrcamentoDaFala` (stream: `passar`/`fechar`, a quarta
  frase guardada até saber se vem a quinta, corte na vírgula de frase comprida, `so_na_tela`),
  `orcar` (texto inteiro) e `quer_detalhe` (a fala do dono que tira o teto).
- `src/jarvis/s2/cerebro.py` — `responder` cria o orçamento pela fala do dono; `_rodada.falar` passa
  o texto por ele antes do fatiador (a tela segue recebendo tudo); o fim do turno solta a quarta
  frase ou o fecho; `Resposta.so_na_tela`; `ouvido` põe o que ficou na tela na conversa, marcado.
- `src/jarvis/voz/app.py` — `_resposta_da_tarefa` orça a resposta da tarefa
  (`quer_detalhe(tarefa.descricao)`); `_aviso_da_tarefa(na_tela=…)` guarda o texto inteiro para a
  tela (`_telas_dos_avisos`); `_falar_os_avisos` mostra o inteiro e fala o orçado; a trilha ganha
  `caracteres_so_na_tela`.
- `src/jarvis/s2/persona.md` — v13, parágrafo FALAR POUCO.

**Testes:** `tests/unit/s2/test_falar_menos.py`. Os testes de TTS que pedem "uma história" seguem
falando tudo (história é pedido de detalhe).

**Não provado:** o `claude -p` real seguindo a v13.

