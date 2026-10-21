# ADR-0040 — Interromper o Jarvis pela voz: a palavra de ativação corta; na contínua ele pausa, confere e corta

**Data:** 2026-10-21 · **Estado:** aceita (pedido do dono) · **Decide:** dono (o que corta), arquiteto (o portão de eco, a vigia e onde ela mora no laço)
**Pedido:** dono, 2026-10-21 — "INTERROMPER POR VOZ. Hoje só o botão interrompe. Quando o dono falar com a WAKE WORD (ou falar por cima dele no modo CONVERSA CONTÍNUA), o Jarvis PARA de falar na hora (corta o áudio do TTS, esvazia a fila de lotes, cancela o que ainda não foi falado, mantém o turno novo). Com wake word: o dono pode cortá-lo no meio (barge-in). Conversa contínua: detecção de fala do dono durante a fala do Jarvis, com cuidado para NÃO se auto-interromper pelo próprio áudio (eco/alto-falante: use o que já existe de AEC/VAD/endereçamento do Jev; se não houver, gate por energia + wake word/detector de endereçamento e documente a limitação; e o ruído de TV não deve cortar). Respeite a regra de que fala não confirma ação perigosa sozinha." Emenda a ADR-0021 (o barge-in por voz que ela dava como ligado não existia no laço) e a ADR-0029 (o detector passa a confirmar, na contínua, a fala por cima).

## Contexto

1. **O laço não ouvia enquanto falava.** `Aplicativo._tocar` drenava a fila de playback quadro a quadro olhando **só o teclado**; o microfone só era lido no laço principal, entre um turno e outro. Com o dispositivo real o buffer do PortAudio estourava e a fala do dono se perdia; o ramo de barge-in do laço principal (`if fila.pedacos_na_fila`) nunca disparava, porque quando o laço voltava a fila já tinha tocado tudo. A ADR-0021 dizia "o barge-in por voz continua ligado no modo palavra" — no código do `jarvis-voz`, não estava.
2. **O alto-falante entra no microfone.** O VAD (silero ou energia) chama o eco do Jarvis de fala: cortar pelo VAD, como a ADR-0002 descreve para os processos da SPEC, faz o Jarvis se interromper sozinho num alto-falante sem AEC — e a TV também corta.
3. **O que existe de AEC não está no laço.** A `CadeiaDeAec` (F1-04) foi medida com áudio sintético e o `jarvis-voz` não a monta; com o dispositivo real, a referência que temos é o que **escrevemos** no driver, não o que ele tocou (a latência de saída não é conhecida, `jarvis.audio_io.dispositivo`). Ligar a cadeia sem medir na máquina do dono arriscaria o playback pausado (`aec_ok` falso) ou um filtro que não converge.
4. **O detector de endereçamento (ADR-0029) só roda se o dono o ligou** (nuvem, chave) e leva ~0,6 s por consulta (a medição dela, de 2026-10-17).

## Decisão

**Enquanto o Jarvis fala (ou prepara a fala), o laço lê um quadro do microfone a cada quadro tocado e uma vigia decide: a palavra de ativação corta, nos dois modos que ouvem sozinhos; na contínua, a suspeita de fala do dono pausa na hora, e ele corta com a palavra, uma ordem de parar ou o "é com ele" do detector — senão retoma de onde parou. O corte é o do botão (o epoch morre), e o trecho do dono vira o começo do turno novo.**

1. **Onde.** `_tocar` chama `_enquanto_fala` entre um quadro de playback e o próximo e enquanto espera a síntese (`ao_esperar`): olha o teclado, como antes, e dá um quadro da `Captura` à `VigiaDeInterrupcao` (`jarvis.voz.interrupcao`). Quem dá o ritmo é o dispositivo (as duas leituras bloqueiam 20 ms). No **atalho** (PTT) quem interrompe é o dedo, como antes: a vigia não ouve. O indicador do microfone (F1-13) é renovado a cada meio segundo durante a fala, porque a fonte agora segue sendo lida.
2. **Portão de eco** (`PortaoDeEco`) — energia, não AEC. A fila de playback entrega cada fatia que saiu (`FilaDePlayback.escuta`); o portão guarda a energia dos últimos 300 ms dela e prevê o eco: a maior energia da janela menos a **perda** do caminho alto-falante → microfone, que ele **aprende** nos quadros que não passam (começa em 6 dB, o pior caso, e assenta em ~400 ms; fone de ouvido vai a 50 dB). Passa só o quadro mais alto que o eco previsto + 6 dB, que o ambiente + 9 dB (o percentil 30 dos últimos 5 s com o Jarvis calado: a TV ligada, a rua) e que −50 dBFS. Acima do portão, a perda só diminui, devagar: um eco que cresceu de verdade (o volume subiu) acaba aprendido, e o dono falando quase não a mexe.
3. **Suspeita.** 240 ms de fala (VAD **e** portão). Na **contínua** o Jarvis pausa na hora (`FilaDePlayback.pausado`: o resto do lote fica guardado) — é o que um humano faz quando alguém começa a falar, e o microfone fica só com o dono. Na **palavra** ele segue falando: ali só o nome corta, e a TV não pode fazê-lo gaguejar.
4. **Conteúdo.** O trecho, com os 400 ms de antes, vai ao ASR da sessão numa linha à parte (o áudio não espera; uma trava impede o ASR de rodar duas vezes ao mesmo tempo) e de novo a cada 400 ms de fala nova, até 3 s. Corta quando:
   - o trecho tem a **palavra de ativação** (o detector fonético da ADR-0021) — nos dois modos;
   - na contínua, é uma **ordem de parar** curta no começo do trecho ("para", "chega", "espera aí", "peraí", "silêncio", "cala a boca", "cancela", "esquece"; até 5 palavras; "ok" e "obrigado" ficam de fora: a TV diz isso o tempo todo);
   - na contínua, o **detector de endereçamento** (quando o dono o ligou) diz que a fala é com o Jarvis.
   Não corta: transcrição vazia, o ASR que falhou, ou a fala sem nada disso — na contínua o Jarvis **retoma**; e, pausado por 2,5 s sem decisão, retoma também (na dúvida, não age).
5. **Não se interromper sozinho.** Além do portão, a transcrição é comparada com o que o Jarvis acabou de dizer (as últimas 60 palavras dos lotes que tocaram): 60 % ou mais das palavras ali = **eco**, não corta, e o portão fica 3 dB mais exigente. O nome dito pelo próprio Jarvis ("eu sou o Jarvis") no eco não corta.
6. **A fala contida.** Julgada no meio uma fala que não era com o Jarvis (a TV, alguém na sala), o resto dela — até 400 ms de silêncio — não pausa de novo nem volta ao detector (senão ele gaguejaria a cada 240 ms); a palavra e a ordem de parar continuam valendo.
7. **O corte** é `Aplicativo.interromper("voz")`, o mesmo do botão: o epoch morre, a fila descarta o que não tocou, o sintetizador para de produzir os lotes antecipados, o cérebro fecha o motor, e a conversa guarda só o que o dono ouviu, marcado como interrompido. O trecho do dono volta ao laço como o começo do **turno novo**, que segue até o silêncio de sempre (700 ms). Nele, o que vem **antes** da palavra de ativação é o eco do fim da fala do Jarvis: o pedido é o que vem depois (sem nada depois, ele só chamou — a escuta arma, como na ADR-0021); na contínua sem a palavra, tira-se o começo que repete o que o Jarvis disse. Turno que é só ordem de parar ("Jarvis, para") não vai ao motor: o corte já foi o pedido.
8. **Fala não confirma sozinha.** A vigia nunca responde a uma pergunta: cortar a fala é não ter ouvido a pergunta inteira, e o `interromper` derruba a pergunta de tarefa ainda não ouvida (é não, ADR-0038) e a do fim do turno (`Cerebro.ouvido`). O "sim" dito por cima não autoriza nada; o tier perigoso e o risco por ação continuam como estão.
9. **A fala do dono que já estava no ar** quando o Jarvis acabou sozinho (um trecho com fala de verdade) volta ao laço como o começo do turno dele, em vez de se perder.
10. **Trilha:** o evento `interrupcao` com o modo, o que a vigia fez (`pausar`, `retomar`, `cortar`, `nada`), o motivo (código) e em quantos ms de trecho — nunca o que o dono disse.
11. **Configuração:** `interromper_por_voz` (ligado por padrão). Desligado, só o botão interrompe, como antes.

## Alternativas descartadas

- **Cortar pelo VAD, sem conteúdo:** com alto-falante e sem AEC, o eco e a TV cortam. É o caminho certo **com** AEC medida (ADR-0002, SLO-2); volta quando a cadeia estiver no laço e medida.
- **Ligar a `CadeiaDeAec` já:** não medida no hardware do dono e sem a referência alinhada do driver. O PipeWire tem cancelamento de eco próprio (`module-echo-cancel`, WebRTC): o dono pode escolhê-lo como entrada, e o portão continua por cima — está no COMO-TESTAR.
- **Modelo de palavra de ativação** (openWakeWord, Porcupine): fora do portão de licença (ADR-0021); o ASR local já transcreve o trecho.
- **Pausar também no modo palavra:** a TV faria o Jarvis gaguejar no modo que existe justamente para a TV não chamar.
- **Na contínua sem detector, cortar com qualquer fala que passe no portão:** a TV perto do microfone, ou alguém na sala, cortaria. O dono pediu, para esse caso, o portão de energia com a palavra ou o detector — e a ordem de parar, que é explícita.

## Consequências

- O caso do dono: "Jarvis, para" ou "Jarvis, que horas são" por cima de uma resposta longa a corta, e o pedido novo é atendido; na contínua, "chega" corta, e a fala dele com o detector ligado também.
- **Latência:** na palavra o corte sai depois do ASR do trecho — 240 ms de fala mais o tempo do ASR (centenas de milissegundos no whisper local da CPU, F1-06; nada medido com voz). Na contínua o **áudio** para em 240 ms (a pausa) e o corte vem com a leitura (com o detector, ~0,6 s a mais).
- **Custo:** ASR extra só quando o portão abre (o dono por cima, ou a TV alta durante a fala).
- **Privacidade:** com ASR de nuvem escolhido, o trecho por cima sai da máquina como já sairia um trecho da escuta; com o detector ligado, o texto do trecho vai ao Jev, como na ADR-0029. Nada novo além disso.
- **Limitação aceita:** na contínua **sem** o detector, fala comum por cima (sem a palavra nem ordem de parar) pausa e o Jarvis retoma — e essa fala não vira turno. Com o detector ligado, vira.
- **Limitação aceita:** TV muito alta e perto do microfone passa no portão; na palavra ela não corta (não diz o nome), na contínua pode pausar o Jarvis por um instante (até a leitura dizer que não era com ele) — uma vez por fala, pela regra da fala contida.
- **Risco aceito:** um eco mais alto do que a perda aprendida (o volume subiu de repente) passa no portão até ser reaprendido; a comparação com o que o Jarvis disse segura o corte, e na contínua custa uma pausa curta.
- Testes: `tests/unit/voz/test_interromper_por_voz.py` — o portão (eco, dono por cima, TV), a vigia (palavra, ordem de parar, detector, eco do próprio nome, ASR vazio ou quebrado, prazo da pausa, ASR em segundo plano, fala contida) e o laço inteiro com WAV de entrada (o nome por cima corta a história e o pedido novo é atendido; fala sem o nome não corta; "Jarvis, para" não vira pedido; a contínua pausa e retoma sem perder áudio; o "sim" por cima não confirma).

## O que não foi provado

Tudo com áudio sintético e ASR falso: **nenhum microfone e nenhum alto-falante de verdade**, nenhuma voz do dono, nenhuma sala, nenhuma TV. Não se sabe: a perda do caminho alto-falante → microfone no notebook do dono e se 6 dB de margem bastam; se o whisper local transcreve "Jarvis" falado por cima do próprio Jarvis; quanto tempo o ASR leva com a síntese e o cérebro disputando a CPU; o atraso real entre a fatia escrita e o som no alto-falante (o portão cobre 300 ms); o comportamento com o `module-echo-cancel` do PipeWire. **[SUPOSIÇÃO]** a janela de 300 ms cobre a latência de ida e volta do PipeWire com `latency="low"`; confirma ou derruba: o teste de ouvido do F1-16 na máquina do dono (falar por cima com o volume normal e alto, olhando a trilha `interrupcao`).

## Como invalidar esta decisão

- O teste do dono mostrar o Jarvis se interrompendo sozinho (a trilha com `cortar` sem ninguém falando) ou não cortando com o nome dito por cima: a margem, a perda inicial ou o caminho mudam — ou entra a AEC.
- A AEC (a nossa ou a do PipeWire) medida no hardware do dono: o corte passa a poder sair pelo VAD, em vez de esperar o ASR.

## Emenda de 2026-10-21 — a vigia ouve com o filtro de ruído (ADR-0043)

A transcrição de cada trecho por cima passa pelo mesmo filtro do turno (`jarvis.voz.ruido.julgar_texto`,
com os sinais do ASR e as palavras da dica): o "Jarvis." que o ASR inventa numa respiração ou no
próprio eco não corta a fala — a vigia recebe vazio, que é `sem_fala`. O trecho que cortou o Jarvis
e vira turno (`por_cima`) não passa pelo portão do trecho (a vigia já o julgou com 240 ms de VAD e
portão de eco), mas passa pelo filtro da transcrição.
