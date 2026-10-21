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
