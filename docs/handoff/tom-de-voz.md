# Handoff — o tom de voz do dono (ADR-0058)

**Data:** 2026-10-30 · **Autor:** opus-tom-de-voz · **Commits:** `9231d77` (A, ADR), `4b85c75` (B, núcleo), `bb198d2` (C, laço/cérebro/persona), fatia D (configuração, privacidade, janela) e fatia E (classificadores opcionais) — ver `git log --grep ADR-0058`.

## O que o Jarvis faz agora

No trecho que o portão de ruído aceitou (ADR-0043), o Jarvis mede como o dono falou — volume contra a média da voz dele, entonação de pergunta, ritmo, energia (ativação) e risada/tosse/suspiro — e:

- **fora do neutro**, manda ao cérebro uma linha no fim do sistema do turno: `[tom da voz do dono: gritando; jeito: curto e calmo]` (neutro = nada, zero caractere);
- **pergunta pela entonação** põe o `?` que o ASR não pôs, na tela e no pedido («vai chover amanhã» → «vai chover amanhã?»);
- **sussurro** → a resposta sai 9 dB mais baixa (qualquer motor de TTS);
- **a janela** mostra o tom curto ao lado do estado («· entonação de pergunta · voz baixa»);
- **a trilha** ganha o evento `tom`, só com códigos.

O tom **nunca** aprova nada: a resposta a uma pergunta pendente é lida antes e sem ele.

## Onde mora cada peça

| peça | onde |
|---|---|
| medida (YIN, nível, eventos), rótulo, linha de base, contrato dos opcionais | `src/jarvis/voz/tom.py` (`medir`, `rotular`, `LinhaDeBase`, `AnalisadorDeTom`, `ClassificadorDeTom`, `Achados`) |
| no laço: medir ao lado do ASR, prazo de 50 ms, `?`, ganho, aprender a base | `src/jarvis/voz/app.py` (`_medir_o_tom`, `_ler_o_tom`, `PRAZO_DO_TOM_S`, `_turno_de_audio`, `responder(tom=…)`, `_tocar`) |
| a nota no prompt | `src/jarvis/s2/cerebro.py` (`responder(tom=…)`) |
| a regra na persona (v17) | `src/jarvis/s2/persona.md`, seção «TOM DA VOZ» |
| configuração | `src/jarvis/voz/config.py` (`tom_de_voz`, `tom_dimensoes`, `tom_no_texto`, `tom_na_voz`) |
| diagnóstico | `src/jarvis/voz/cli.py` (`_linhas_do_tom`) |
| janela | `gui/nucleo.py` (`ao_tom`), `gui/ponte.py` (`tomDaVoz`), `qml/JarvisUI/Principal.qml` |
| trilha | `src/jarvis/trilha.py` (evento `tom`: volume, entonacao, som, ritmo, energia, confianca, fonte, base_pronta) |
| áudio sintético e harness | `tools/sinais_de_tom.py`, `tools/harness_tom.py` → `docs/medicoes/tom-de-voz.md` |
| custo no prompt | `tools/medir_prompt.py` → `docs/medicoes/prompt-do-turno.md` |

## Configuração (`~/.config/jarvis/jarvis-voz.toml`)

```toml
tom_de_voz = true                      # false: nada é medido nem lido (nem o tom.json)
tom_dimensoes = ["volume", "entonacao", "evento", "ritmo", "energia"]   # o que vai ao cérebro e à janela
tom_no_texto = true                    # «?» pela entonação
tom_na_voz = true                      # sussurro → resposta mais baixa
```

## Privacidade (é dado sensível do dono)

- **Nenhum áudio é gravado** por causa do tom: a análise lê o trecho em memória e devolve números.
- **A linha de base** (média e desvio do nível, da F0, da faixa de F0 e do ritmo, e quantos turnos) mora em `~/.local/state/jarvis/voz/tom.json`, pasta 0700, arquivo 0600, nunca sai da máquina. Apagar o arquivo zera a calibração (P8: esquecer é função de produto); `tom_de_voz = false` para de ler e de aprender.
- **A trilha** leva só os códigos do rótulo e a confiança — nunca a F0, o nível ou o áudio (allowlist de `jarvis.trilha`).
- **O cérebro** recebe a linha (texto), e o cérebro pode ser de nuvem (o `claude -p`): sai da máquina, no máximo, «gritando» ou «entonação de pergunta», junto do pedido que já ia. O detector de endereçamento (Jev, nuvem) não recebe o tom. Áudio nunca vai a lugar nenhum por causa do tom.
- **O `--diagnostico`** mostra ligado/desligado, as dimensões e quantos turnos a base tem — nunca os valores (a tela pode ser compartilhada).
- Princípios da SPEC: P2 (nenhuma frase — e nenhum tom — dispara ação), P6 (a nota é medida do nosso código; o que vem de fora continua dado), P8 (apagável), P12 (o dono liga e desliga).

## Armadilhas

1. **A pergunta do PB não «sobe no fim»** (L+H\* L%: sobe na última tônica e cai nas postônicas). A medida é o pico do último meio segundo vozeado contra a mediana do resto — não troque por inclinação final.
2. **O filtro de erro de oitava é local** (vizinhança de 9 análises): com a mediana global, a F0 da risada (uma oitava acima da fala) sumia como «erro».
3. **Fala sintética regular parece risada**: as rajadas só viram risada com a F0 delas ≥ 4 semitons acima da voz do dono **e** a voz sumindo entre elas.
4. **Volume sem base não chuta**: antes de 5 turnos, só o estouro do microfone vira «gritando».
5. **O índice git era compartilhado com outra CLI** durante estas fatias: commits por `GIT_INDEX_FILE` privado (HEAD + só os blobs do tom). Ver a memória «Duas CLIs no mesmo repo».
6. `Aplicativo` é dataclass com `slots`: nos testes, `monkeypatch.setattr(Aplicativo, …)` na classe, não na instância.
7. A leitura da resposta (ADR-0048) devolve o «sim» normalizado (`sim`), não o texto do ASR.

## O que não foi provado (só a voz real do dono fecha)

Todos os limiares: pergunta pela entonação (a voz piper só marcou 4 de 12 perguntas — conservador, não inventou pergunta em afirmação), grito contra a base (e o «cheguei perto do microfone»), sussurro com ventilador ligado, risada, tosse e suspiro de verdade, energia (agitada/cansada), variação regional da entonação. O efeito no comportamento do motor (só a forma do prompt foi medida). A janela com o indicador numa sessão real.

**Como calibrar:** use o Jarvis normalmente por alguns dias; o `--diagnostico` diz quantos turnos a base tem; a trilha (`~/.local/state/jarvis/voz/diagnostico/turnos.jsonl`, evento `tom`) conta o que foi rotulado. Se uma dimensão errar mais do que ajuda, tire-a de `tom_dimensoes` (ADR-0058, «Como invalidar»).
