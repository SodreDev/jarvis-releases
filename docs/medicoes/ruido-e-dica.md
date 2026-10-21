# Ruído e dica do ASR — o que vira texto, com e sem dica, e o que o filtro segura (ADR-0043)

Data: 2026-10-21. Reproduzível com (precisa do grupo `asr`, do whisper small no cache, da voz
piper `pt_BR-faber-medium` e do `espeak-ng`, que só roda em `tools/`):

```bash
nice -n 19 uv run --frozen python -m tools.harness_ruido
```

Dados por transcrição: [ruido-e-dica.csv](ruido-e-dica.csv) (cena, variante de dica, texto que o
whisper devolveu, `no_speech_prob`, `avg_logprob`, `compression_ratio`, o veredito do portão e do
filtro, o tempo). Rodado sobre o commit 86555bc mais a fatia da dica curta (o commit em que este
arquivo entrou) · hardware: AMD Ryzen 5 5600G, CPU, whisper small int8, 2 threads, `nice -n 19`
com a máquina em uso.

## Cenário

Só áudio **sintético** — nenhum microfone, nenhuma voz do dono:

- **8 ruídos**, num trecho de 2 s como o laço manda ao ASR (o evento aos 400 ms): sala quieta
  (−62 dBFS), clique do mouse, teclado (7 teclas/s), respiração (ruído filtrado de 300–2 500 Hz com
  envelope de 0,6 s e de 0,8 s), tosse, ventilador (ruído marrom com zumbido de 120 Hz, −40 dBFS) e
  chiado (−42 dBFS). Mandados **forçados** ao ASR: o silero não abriu trecho para nenhum deles na
  exploração — o que se mede é o que acontece quando o VAD abre (um ruído real que o engane, o VAD
  de energia sem o peso do silero).
- **8 falas** da voz piper com fonemas do espeak-ng, com 400 ms antes e 1,3 s depois: "Sim.",
  "Não.", "Para.", "Jarvis.", "Jarvis, que horas são?", "Abre o Discord.", "Abre o Spotify." e
  "Manda mensagem para o Kauã Ximenes." (nome fictício de grafia difícil).
- **5 dicas**: nenhuma; a antiga (`hotwords` + `initial_prompt` "Abra …" com 31 nomes de apps, ~480
  caracteres — apps comuns, não o catálogo do dono); `hotwords` só com "Jarvis"; a nova só com a
  palavra ("Jarvis."); e a nova com três termos de vocabulário ("Jarvis, Discord, Spotify, Kauã
  Ximenes.").

`n` = 8 ruídos e 8 falas por variante: 80 transcrições.

## Resultado

| dica | ruído que virou texto | e passou no filtro | fala acertada | fala que o filtro derrubaria | ASR p50 (ms) |
|---|---:|---:|---:|---:|---:|
| sem dica | 0/8 | 0/8 | 2/8 | 0/8 | 1578 |
| lista de apps (a antiga) | 3/8 | 0/8 | 2/8 | 0/8 | 1911 |
| `hotwords` "Jarvis" | 3/8 | 0/8 | 3/8 | 0/8 | 1610 |
| nova, só a palavra | 1/8 | 0/8 | 3/8 | 0/8 | 1666 |
| nova, com vocabulário | 2/8 | 0/8 | 5/8 | 0/8 | 1643 |

"Fala acertada" = todas as palavras que importam da frase estão no texto (critério estrito: "Abrir
o Spotify" para "Abre o Spotify" conta como erro). "Fala que o filtro derrubaria" = acertada **e**
descartada pelo filtro — a métrica que não pode subir.

O que os ruídos viraram: com a lista de apps, "Calculadora, Kdenlive, Konsole, Elisa, Firefox,
GIMP…" (sala, tosse, chiado); com `hotwords` "Jarvis", "Jarvis" (sala e chiado) e "Um, dois, três,
fffff" (respiração); com as dicas novas, "Caramba!" (tosse) e "Legendas pela comunidade de
Amara.org" (ventilador e chiado). O `no_speech_prob` desses textos ficou entre 0,53 e 0,95; o das
falas, entre 0,004 e 0,17.

**Portão do trecho** (antes do ASR, igual em todas as variantes): sala, chiado, ventilador e clique
→ `fundo`; teclado → `impulso`; respiração e tosse **passam** (por energia parecem fala — quem as
segura é o filtro da transcrição); as 8 falas passam, inclusive "Sim." com 260 ms seguidos acima do
fundo. Custo: p50 0,4 ms por trecho (máximo 4,9 ms, a primeira chamada).

## O que isso decide

1. A lista de apps sai da dica: é a que mais faz ruído virar texto (e texto de nome de app, que vira
   pedido), não acerta mais fala do que sem dica e é a mais lenta (+250 ms no p50 do ASR, pelos
   ~240 tokens de prompt).
2. A dica vai só como `initial_prompt`: em `hotwords`, até o "Jarvis" sozinho vazou no silêncio.
3. A dica curta com o vocabulário do dono é a que mais acerta (nome próprio, palavra de ativação no
   meio da frase) — por isso o vocabulário entra nela.
4. Nenhuma dica é à prova de ruído: o filtro da transcrição é obrigatório, e nesta rodada segurou
   todos os textos inventados sem derrubar fala reconhecida.

## Limite honesto

- **Whisper small, não a Groq.** O dono usa `whisper-large-v3-turbo` na Groq: os limiares de
  `no_speech_prob` e logprob não foram medidos nela. A trilha (`ruido`, com os sinais) é o que
  calibra na máquina dele.
- **Voz sintética.** A piper com espeak-ng é inteligível para o whisper, mas não é voz humana: o
  "Sim." saiu "Tchau." em todas as variantes (e o filtro o derruba — o texto estava errado de
  qualquer jeito). O quanto a fala curta do dono passa nos limiares não foi medido.
- **Ruído sintético.** Respiração e tosse de verdade têm outro espectro; teclado mecânico e mouse
  reais podem durar mais que os 30 ms do clique daqui. O portão é por energia e duração, não por
  classe de som.
- **Uma rodada.** O whisper volta com temperatura quando o logprob cai: o texto inventado muda de
  rodada para rodada (na exploração, a lista de apps fez 4 de 4 ruídos forçados virarem texto).
