# A palavra de ativação por cima de uma fala do Jarvis (ADR-0040, emenda de 2026-10-29)

**Gerado por** `tools/harness_interrupcao.py` (`--so-portao` e `--enxuto --turnos-antes 1 --variantes N`, uma variante por processo). **Data:** 2026-10-29. Ryzen 5 5600G, CPU, whisper `small` int8.

> **Tudo sintético.** A resposta do Jarvis e o dono são a voz piper `pt_BR-faber-medium`; o eco é o caminho direto atrasado e atenuado **mais a reverberação** (resposta ao impulso sintética: ruído com decaimento exponencial até o RT60); o dono chega perto do microfone com pouca sala. O eco é calculado do que o alto-falante **tocou**: quando a vigia pausa, ele cala e só a cauda segue. Nenhum microfone, alto-falante ou voz do dono; o ASR é o whisper local com a latência de 600 ms simulada, não a Groq.

## O que a máquina do dono mostrava

A trilha dele (29/10, só metadados): toda fala por cima foi `pausar/suspeita` e, 2,5 s depois, `retomar/prazo_da_pausa` — nenhuma leitura do ASR voltou com o nome. E `degradacao.json` tinha `asr-groq-7, 11, 15, 41…47` descartados.

## As três causas

1. **O `call_id` da Groq colidia entre sessões.** `asr-groq-{n}` com `n` recomeçando em 1 a cada sessão, e a lista de descartados da regra 5 fica no disco: em **toda** sessão a 7ª, 11ª, 15ª e 41ª–47ª transcrição voltavam vazias sem ir à rede. A vigia transcreve muito e chegava nelas em minutos. Mesmo defeito na ElevenLabs e no Edge. Conserto: `jarvis.rede.id_da_instancia()` como prefixo.
2. **O portão de eco aprendia uma perda inflada.** A perda observada era o pico da referência em 300 ms contra o nível do quadro **de agora**; nos vales entre as sílabas o microfone fica muito abaixo do pico, e a perda subia muito acima da real — o limiar caía e o próprio eco passava (tabela 1). Com o eco passando, o trecho nunca fechava.
3. **O teto de 3 s da leitura não valia.** A releitura vinha antes dele: o trecho crescia sem fim (11 s no rastro), relido a cada 400 ms, e o «Jarvis, para» do dono, dito aos 2,5 s, ia ao ASR afogado em segundos de eco — o whisper transcrevia o eco e perdia o nome.

Consertado o portão (pico contra pico), ele fica honesto — e **surdo** ao dono que chega ao microfone no mesmo nível do eco: detector de fala dupla por energia não separa duas vozes do mesmo tamanho (tabela 1, «pico a pico»; tabela 2, 1/32). Por isso a vigia ganhou o cancelador de eco do F1-04 (PBFDAF, referência do nosso playback) **só no caminho dela**: o resíduo vai ao portão, ao ASR do trecho e ao turno do corte. Ele não toca o playback nem o turno normal.

## Tabela 1 — o portão, sem ASR (`--so-portao`)

Três respostas de ~10 s; "eco que passa" é quadro do próprio Jarvis aceito como fala do dono; "dono" é quantos quadros falados do «Jarvis, para.» passam (a suspeita pede 8, 160 ms).

| portão | sala | eco que passa (3 respostas) | perda aprendida | dono −6 dB | dono −12 dB |
|---|---|---|---|---|---|
| antes (perda contra o quadro) | seca, caixa perto | 1164/1821 (64%) | 25.8 dB (direto: 6 dB) | 18/20 | 15/19 |
| antes (perda contra o quadro) | sala, caixa perto | 346/1821 (19%) | 12.3 dB (direto: 6 dB) | 5/20 | 0/19 |
| antes (perda contra o quadro) | sala, notebook | 342/1821 (19%) | 18.3 dB (direto: 12 dB) | 9/20 | 5/19 |
| antes (perda contra o quadro) | sala viva, notebook | 62/1821 (3%) | 13.7 dB (direto: 12 dB) | 2/20 | 0/19 |
| antes (perda contra o quadro) | sala, volume baixo | 334/1821 (18%) | 26.3 dB (direto: 20 dB) | 15/20 | 10/19 |
| antes (perda contra o quadro) | notebook, saída atrasada 150 ms | 380/1821 (21%) | 14.1 dB (direto: 12 dB) | 9/20 | 7/19 |
| pico a pico | seca, caixa perto | 0/1821 (0%) | 5.3 dB (direto: 6 dB) | 0/20 | 0/19 |
| pico a pico | sala, caixa perto | 0/1821 (0%) | 1.6 dB (direto: 6 dB) | 0/20 | 0/19 |
| pico a pico | sala, notebook | 0/1821 (0%) | 7.4 dB (direto: 12 dB) | 0/20 | 0/19 |
| pico a pico | sala viva, notebook | 0/1821 (0%) | 5.6 dB (direto: 12 dB) | 0/20 | 0/19 |
| pico a pico | sala, volume baixo | 0/1821 (0%) | 15.4 dB (direto: 20 dB) | 7/20 | 0/19 |
| pico a pico | notebook, saída atrasada 150 ms | 10/1821 (1%) | 6.5 dB (direto: 12 dB) | 0/20 | 0/19 |
| pico a pico + AEC | seca, caixa perto | 19/1821 (1%) | 32.1 dB (direto: 6 dB) | 20/20 | 18/19 |
| pico a pico + AEC | sala, caixa perto | 20/1821 (1%) | 28.1 dB (direto: 6 dB) | 19/20 | 17/19 |
| pico a pico + AEC | sala, notebook | 18/1821 (1%) | 34.1 dB (direto: 12 dB) | 20/20 | 18/19 |
| pico a pico + AEC | sala viva, notebook | 7/1821 (0%) | 28.4 dB (direto: 12 dB) | 19/20 | 18/19 |
| pico a pico + AEC | sala, volume baixo | 5/1821 (0%) | 41.7 dB (direto: 20 dB) | 20/20 | 19/19 |
| pico a pico + AEC | notebook, saída atrasada 150 ms | 17/1821 (1%) | 31.6 dB (direto: 12 dB) | 20/20 | 18/19 |

## Tabela 2 — a vigia inteira, com o whisper (32 casos com o nome + 8 só de eco por variante)

Salas: seca com a caixa perto (6 dB), notebook (12 dB, RT60 500 ms), sala viva (12 dB, RT60 900 ms, cauda +3 dB), notebook com a saída atrasada 150 ms; dono a −6 e −12 dB do pico do Jarvis; «Jarvis, para.» e «Jarvis, que horas são?»; modos palavra e contínua (`vad`); uma resposta inteira antes de cada caso (o portão aprendendo, com o dono comentando por cima sem o nome).

| variante | corte com o nome | falso corte pelo eco | pausa à toa |
|---|---|---|---|
| antes (portão de 25/10, sem AEC) — só a caixa perto, palavra (a rodada inteira levaria horas: cada trecho sem fim vai ao ASR) | **0/4** (`sem_chamada`: o nome sumiu na transcrição longa) | 0/1 | 0/1 |
| portão pico a pico, sem AEC | **1/32** | **0/8** | 0/8 |
| agora (portão pico a pico + AEC) | **31/32** | **0/8** | 2/8 |
| agora, sem o filtro da ADR-0043 | **32/32** | **0/8** | 2/8 |

Por sala, a de agora:

| variante | sala | modo | corte com o nome | falso corte (só eco) | pausa à toa (só eco) | ms do corte (mediana) | perda aprendida |
|---|---|---|---|---|---|---|---|
| agora (portão pico a pico + AEC) | seca, caixa perto | palavra | 4/4 | 0/1 | 0/1 | 1420 | 30.6 dB |
| agora (portão pico a pico + AEC) | sala, notebook | palavra | 4/4 | 0/1 | 0/1 | 1420 | 32.1 dB |
| agora (portão pico a pico + AEC) | sala viva, notebook | palavra | 4/4 | 0/1 | 0/1 | 1420 | 28.2 dB |
| agora (portão pico a pico + AEC) | notebook, saída atrasada 150 ms | palavra | 4/4 | 0/1 | 0/1 | 1420 | 31.2 dB |
| agora (portão pico a pico + AEC) | seca, caixa perto | vad | 3/4 | 0/1 | 0/1 | 1520 | 30.2 dB |
| agora (portão pico a pico + AEC) | sala, notebook | vad | 4/4 | 0/1 | 1/1 | 1500 | 31.7 dB |
| agora (portão pico a pico + AEC) | sala viva, notebook | vad | 4/4 | 0/1 | 0/1 | 1560 | 28.2 dB |
| agora (portão pico a pico + AEC) | notebook, saída atrasada 150 ms | vad | 4/4 | 0/1 | 1/1 | 1600 | 27.2 dB |

## O que se lê

- **Agora (portão pico a pico + AEC): corte 31/32, falso corte pelo eco 0/8.** O único que não cortou (caixa perto, contínua) leu vazio (`sem_fala`).
- **O filtro da ADR-0043 custa ~600 ms no corte** (mediana 1 420 ms × 800 ms sem ele): a primeira leitura, curta, traz só «Jarvis.» com sinais fracos e é descartada como eco da dica; o corte vem na leitura seguinte. Fica ligado — é ele que segura o «Jarvis» que o ASR inventa numa respiração —; afrouxá-lo na vigia é uma decisão a medir com a voz do dono.
- **Pausa à toa 2/8 na contínua**: o resíduo do eco abriu uma suspeita e o Jarvis pausou e retomou uma vez numa resposta de 10 s. Nenhum corte.

## O que não foi provado

O microfone, o alto-falante, a sala e a voz do dono; o cancelador com o atraso real do PipeWire (aqui 30 e 150 ms; ele cobre 400 ms) e com a distorção não linear de alto-falante de notebook; a Groq turbo no lugar do whisper small (latência e sinais); o efeito na CPU de rodar o cancelador a cada quadro com a síntese e o cérebro disputando (0,087 ms por quadro de 20 ms aqui, sem disputa).
