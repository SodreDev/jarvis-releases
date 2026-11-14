# ADR-0067 — STT em pt-BR: o modelo certo na placa certa, e a palavra trocada achada pelo som

**Data:** 2026-11-14 · **Estado:** aceita (medida com voz sintética e testada com fakes; a voz do dono é dele medir com `tools/diagnostico_stt.py`) · **Decide:** arquiteto (configuração do ASR, limiares da reconciliação, onde a nota entra); dono (qual modelo roda na máquina dele, e a trilha passar a guardar o texto ouvido quando a reconciliação age)
**Pedido:** dono, 2026-11-14 — «o STT piorou muito em português»: «mãe» sai «ma i», «gp mad» sai «gepe madi», «WhatsApp» sai «note pad». Relaciona: ADR-0017 (motores), ADR-0043 (ruído e dica curta), ADR-0044 (vocabulário), ADR-0047 (teto do prompt), ADR-0058 (linha do tom no turno), ADR-0064 (harness de acerto).

## Contexto (medido, sem o microfone do dono)

- **O que roda hoje.** O `jarvis-voz.toml` do dono tem `asr = "asr-whisper-local"` com `modelo_do_asr = "small"`; a cópia de 16/10 tinha `asr = "asr-groq-whisper-large-v3-turbo"`. O whisper local roda **sempre na CPU em int8** (`device="cpu"` fixo em `MotorWhisper.abrir`), beam 1. A máquina tem uma RTX 4060 que o CTranslate2 enxerga, mas falta a `libcublas.so.12` — a placa não roda nada hoje. A regressão percebida casa com a troca de motor: do large-v3-turbo na Groq para o **small** na CPU.
- **Idioma.** Os dois caminhos já mandam `language="pt"` (local: `MotorWhisper.idioma`; Groq: o campo `language` com `temperature=0`). «note pad» não é auto-detecção caindo no inglês.
- **A dica** (ADR-0043) é a palavra de ativação e até 12 termos do vocabulário, ≤200 caracteres, só como `initial_prompt`/`prompt`. Medida de novo aqui (abaixo): tirar a dica piora (WER 0,38 → 1,10; «WhatsApp» 8/9 → 6/9, e «Jarvis» some); trocar por uma frase em pt-BR com os mesmos termos não ajuda e **tira o «Jarvis» do começo** (3/3 → 0/3). A dica fica como está.
- **VAD/ruído** não come a palavra curta: o laço manda o trecho com 400 ms antes, e o portão do trecho (ADR-0043) só descarta o que não tem 100 ms seguidos de fala; o `vad_filter` do faster-whisper continua desligado. No harness, nenhum «mãe» foi descartado pelo filtro.
- **O teto é o modelo.** No small, «Mãe.» sozinho sai «Naí.»/«Não.» em toda configuração (beam 1 ou 5, com ou sem dica); «Abre o ChatGPT» sai «chat de GPT»; «Fecha o Steam» sai «Fechos de…».

### A medição (`tools/harness_stt.py` → `docs/medicoes/stt-pt-br.md`)

16 frases (as do dono, nomes de apps e IAs, sim/não) × 3 variações de ritmo, altura e fundo, na voz piper com fonemas do espeak-ng (só em `tools/`), + os 8 ruídos forçados do `harness_ruido`. CPU Ryzen 5 5600G, 4 threads, `nice -n 19`, int8.

| configuração | WER | termo-chave | «WhatsApp» | ruído → texto | ASR p50 |
|---|---|---|---|---|---|
| small, CPU, beam 1, dica atual (o de hoje) | 0,381 | 35/48 | 8/9 | 0/8 | 1,9 s |
| small, CPU, beam 1, sem dica | 1,101 | 28/48 | 6/9 | 0/8 | 1,7 s |
| small, CPU, beam 5, dica em frase | 0,396 | 34/48 | 8/9 | 0/8 | 2,5 s |
| large-v3-turbo, CPU, beam 1 | 0,222 | 37/48 | 9/9 | 5/8 | 9,2 s |
| small, placa, beam 1 | 0,339 | 36/48 | 8/9 | 0/8 | 140 ms |
| medium, placa, beam 5 | 0,326 | 36/48 | 9/9 | 0/8 | 246 ms |
| **large-v3-turbo, placa, beam 1** | **0,194** | **38/48** | **9/9** | 3/8 | **265 ms** |
| large-v3-turbo, placa, beam 5 | 0,243 | 37/48 | 8/9 | 4/8 | 460 ms |

A tabela inteira, as colunas e as ressalvas (o piper diz «Mãe.» sozinho de um jeito que todo modelo
ouve «Não.») estão em `docs/medicoes/stt-pt-br.md`. A placa foi medida com a cuBLAS 12 do pacote
`nvidia-cublas-cu12` numa pasta à parte — a máquina não a tem instalada.

## Decisão

1. **O whisper local escolhe a placa sozinho** (`MotorWhisper.dispositivo = "auto"`): com GPU visível ao CTranslate2, tenta `cuda/float16` e faz uma conta de teste de 0,1 s — a falta da cuBLAS só aparece na primeira conta, não ao carregar —; se falhar, volta à `cpu/int8` de sempre, sem erro na tela. Se o pacote `nvidia-cublas-cu12` estiver no Python, a biblioteca dele é aberta antes (o carregador não procura na pasta do pacote). `em_uso` diz o que ficou.
2. **`modelo_do_asr = "auto"` é o padrão novo** (`MODELO_NA_PLACA = "large-v3-turbo"`, `MODELO_NA_CPU = "small"`, beam 1): o turbo na placa leva 265 ms e erra metade do small; na CPU ele leva 9 s, então lá fica o small. Um tamanho escrito à mão vale nos dois. O arquivo do dono passou de `small` para `auto` (cópia em `jarvis-voz.toml.bak-stt`). Para a placa rodar, falta a cuBLAS 12 — `uv pip install nvidia-cublas-cu12` no venv (licença NVIDIA, por isso **não** entra no `uv.lock` nem nos pacotes sem decisão do dono); sem ela, nada muda.
3. **A dica não muda** (lista curta da ADR-0043) e o idioma continua forçado em `pt` nos dois caminhos.
4. **Reconciliação por som** (`jarvis.voz.reconciliar`), no laço de voz depois do `vocabulario.corrigir` e **antes** da palavra de ativação e do caminho rápido:
   - **candidatos do contexto do dono:** o vocabulário (com a `fala` dele), os contatos das memórias fixas, os apps autorizados e um léxico base (família, mensageiros, apps e IAs comuns, cada um com a pronúncia brasileira: «uótsápi», «djêmini», «gê pê tê»);
   - **o som:** classes de som do pt-BR (`jarvis.voz.palavra.fonetica_simples`), sigla soletrada («GPMad» → «gê pê mad»), grafia inglesa lida como o brasileiro lê («wh» → «u», «pad» → «padi») e as átonas e/i, o/u juntas;
   - **a vaga da frase:** depois de «mensagem no» só cabe mensageiro; depois de «minha»/«meu», gente; depois de «abre o», app ou IA;
   - **só com confiança:** som quase igual (≥ 0,86, com 0,08 de margem sobre o segundo) troca; na vaga de conjunto fechado (os mensageiros) som parecido (≥ 0,5) troca como **palpite**, e o cérebro diz o que entendeu; entre 0,65 e a troca, nada muda e a nota leva os candidatos. Fora de vaga, só o nome que o ASR partiu em 2–3 palavras e com som quase igual; substantivo comum («navegador», «grupo», «pasta») e nome já certo nunca mudam.
5. **A nota da voz vai no turno, não na persona.** «Este pedido veio do reconhecimento de voz e pode ter palavra trocada por outra de som parecido (…): entenda pelo som e pelo contexto; se ainda não fizer sentido, pergunte curto» + o que foi trocado («Ouvi «note pad» e entendi «WhatsApp» … diga em poucas palavras o que entendeu»). Vai pelo mesmo canal da linha do tom (ADR-0058), no fim do sistema do turno falado: o prompt-base não cresce (ele já está no teto de 16 mil da ADR-0047), e o turno digitado não a recebe.
6. **A trilha leva o antes e o depois** (pedido do dono): evento `ouvido` com `bruto`, `corrigido`, `trocas`, `duvidas` e `certeza` (`certa`/`palpite`/`duvida`) — **só no turno em que a reconciliação agiu**, redigido (segredo, URL, caminho) e cortado como os motivos (forma `FALA`). É a única forma da trilha com texto do dono.
7. **O harness pt-BR ouve como o laço** (ADR-0064): cada fala dos cenários passa pela reconciliação antes, e a categoria nova `ouvido` tem os exemplos do dono e os que não podem mudar. 66 cenários, 100%; os 54 de antes continuam 100% com a reconciliação ligada.

## Alternativas descartadas

- **Dica em frase pt-BR** («Conversa em português do Brasil com o Jarvis: …»): medida, não melhora o small e perde o «Jarvis».
- **Beam 5 no small**: WER 0,381 → 0,375, termo-chave igual, +350 ms por trecho na CPU. Não paga.
- **Correção pelo modelo de linguagem só (sem código):** o cérebro já recebe a nota e corrige o resto; mas o caminho rápido (ADR-0045) roda **antes** do motor e precisa do nome certo — «fecha o stim» só vira `window.close steam` com a troca feita em código.
- **Palpite em qualquer vaga:** «minha mana» viraria «mamãe». Palpite só onde o conjunto é fechado (mensageiros); gente e app só com som quase igual.

## Consequências

- **O turbo inventa «E aí» no silêncio com confiança alta**: 3/8 ruídos forçados passaram pelo filtro da ADR-0043, que foi calibrado no small. O portão do trecho e o silero vêm antes (não abriram para nenhum ruído sintético), mas os limiares do filtro precisam ser revistos no turbo pela trilha `ruido` quando a placa estiver ligada.

- O dono pode ensinar o que o ASR erra de um jeito que o som não acha («gp mad»): `vocabulario.aprender` ou o `vocabulario.toml` com `escrita = "GPMad"` — a sigla é soletrada sozinha e «gepe madi» passa a virar «GPMad».
- A nota custa ~260 caracteres por turno falado (+ ~120 por troca), fora do prompt-base.
- **Não provado:** a voz do dono, o microfone dele e a Groq (sem chave aqui) — `tools/diagnostico_stt.py` mede na máquina dele, com arquivos que ele mesmo grava, e diz se a placa pode rodar o whisper.
