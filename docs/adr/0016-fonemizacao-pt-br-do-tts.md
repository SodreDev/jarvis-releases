# ADR-0016 — Fonemização pt-BR do TTS: as três saídas e o que cada uma custa

**Data:** 2026-10-15 · **Estado:** proposta · **Decide:** dono

## Contexto

O cartão F1-09 entregou TTS em streaming cancelável e mediu o caminho de voz
(`docs/medicoes/f1-09-tts.md`, commit `bced9bf`): primeiro pedaço em 116 ms p50 com a voz
`pt_BR-faber-medium`, RTF de 0,113× — folga de 5× no SLO-5. O caminho funciona. O problema é de
**licença**, e ele só aparece no produto: a fonemização.

Os fatos abaixo foram verificados **na origem** em 2026-10-15, cada um com a fonte.

### Fato 1 — o fonemizador das vozes do piper é GPL-3.0, sem exceção de linkagem

As quatro vozes pt-BR de `rhasspy/piper-voices` (`faber`, `cadu`, `jeff`, `edresson`) declaram
`phoneme_type: espeak` — a `edresson` não declara o campo e usa o mesmo inventário IPA, o que
confere no `phoneme_id_map` dela. O `espeak-ng` declara, no próprio repositório: *"eSpeak NG
Text-to-Speech is released under the GPL version 3 or later license"* (`README.md`), e o
`COPYING` é a GPL-3 integral, **sem** exceção de linkagem (a única ressalva do README é o
`getopt.c` de terceiros, licença BSD).

### Fato 2 — a FSF dá o critério, e ele é favorável a processo separado; o que pesa é a distribuição

Na *GPL FAQ* oficial (gnu.org/licenses/gpl-faq.html), em **"What is the difference between an
'aggregate' and other kinds of 'modified versions'?"**:

> *"We believe that a proper criterion depends both on the mechanism of communication (exec,
> pipes, rpc, function calls within a shared address space, etc.) and the semantics of the
> communication (what kinds of information are interchanged). […] By contrast, pipes, sockets
> and command-line arguments are communication mechanisms normally used between two separate
> programs. So when they are used for communication, the modules normally are separate
> programs."*

E em **"I'd like to incorporate GPL-covered software in my proprietary system"**:

> *"However, in many cases you can distribute the GPL-covered software alongside your
> proprietary system. To do this validly, you must make sure that the free and nonfree programs
> communicate at arms length, that they are not combined in a way that would make them
> effectively a single program."*

Como chamamos o `espeak-ng` por `argv` e stdin/stdout, trocando **texto e IPA** (nada de
estrutura interna), o critério da própria FSF põe isso do lado de "programas separados". O que
**não** desaparece é a obrigação de quem **distribui**: entregar o `espeak-ng` junto com o
produto é distribuir um programa GPL, com as obrigações de fonte da GPL §6, e dizer claramente
ao dono do computador que aquela parte é GPL. Isso é decisão de **licenciamento do produto**,
não de engenharia — e é por isso que esta ADR não decide.

### Fato 3 — dois candidatos que pareciam saída não são

- `hexgrad/Kokoro-82M`: Apache-2.0, mas o *model card* declara **um** idioma, `en`. **Não é
  candidato de pt-BR.** (Corrige o que as notas do F1-09 diziam: lá eu escrevi que ele
  "também depende de fonemizador externo para pt-BR"; o fato mais forte é que ele não declara
  pt-BR nenhum.)
- `facebook/mms-tts-por`: **CC-BY-NC-4.0**. Barrado pela ADR-0011 — não comercial não entra.
- `OuteAI/OuteTTS-0.3-500M`: **CC-BY-SA-4.0**. *ShareAlike* numa voz contamina o áudio que o
  produto distribui, e o carregador do F1-09 já recusa licença não permissiva.

### Fato 4 — existe G2P de pt-BR com licença permissiva

`epitran` 1.35.3 declara licença **MIT** (classificador `MIT-Modern-Variant` no PyPI), suporta
`por-Latn` na tabela de idiomas do README e diz, no mesmo README: *"For use with most languages,
Epitran requires no special installation steps"* — o **Flite** só é exigido para **inglês**. As
dependências declaradas são `regex`, `panphon`, `marisa-trie`, `requests` e `jamo`.

### Fato 5 — existe TTS pt-BR sem fonemizador e com licença comercial

`parler-tts/parler-tts-mini-multilingual-v1.1`: **Apache-2.0**, e o *model card* declara
`['en', 'fr', 'es', 'pt', 'pl', 'de', 'nl', 'it']` — **pt incluído**. O README oficial do
Parler-TTS passa **texto cru** ao tokenizador (`tokenizer(prompt, return_tensors="pt")`): não há
fonemizador no caminho. Em troca, é modelo **autoregressivo de 880M parâmetros**, contra os
~63 MB de um VITS do piper, que é *feed-forward*.

## Decisão

**Nenhuma ainda: esta ADR é proposta e o que ela decide é a ordem de investigação.** A
recomendação é **tentar primeiro a opção B (voz do piper + `epitran`)**, porque ela mantém o
número já medido do F1-09 e tira a GPL do produto; manter a **opção C (Parler-TTS)** registrada
como candidata a medir quando houver GPU; e tratar a **opção A (distribuir o `espeak-ng`)** como
saída apenas se o dono aceitar distribuir binário GPL ao lado do produto.

## Alternativas descartadas

| opção | o que é | custo | o que a derruba |
|---|---|---|---|
| **A. `espeak-ng` em processo separado, distribuído com o produto** | o que o F1-02 e o F1-09 já usam, movido para o pacote do produto | engenharia **zero** (funciona e está medido); custo de **licenciamento**: obrigações de fonte da GPL §6, aviso ao dono de que aquela parte é GPL, e a comunicação tem de continuar "at arms length" (sem memória compartilhada, sem estrutura interna) | o dono decidir que não quer binário GPL no pacote |
| **B. voz do piper + `epitran` (MIT)** | troca só o fonemizador; a voz (MIT/CC0) e o `onnxruntime` (MIT) ficam | engenharia **média**: o IPA do `epitran` tem de ser mapeado para o `phoneme_id_map` da voz, que foi treinada com o inventário do espeak. Fonema fora do mapa hoje **levanta erro** (F1-09), então divergência aparece como falha, não como voz torta — mas a **qualidade** precisa de julgamento de ouvido, que é do dono | o mapeamento não cobrir o inventário, ou a voz sair ruim ao ouvido do dono |
| **C. Parler-TTS multilingual (Apache-2.0)** | TTS sem fonemizador, pt declarado no card | engenharia **média** (outra família de inferência, `transformers` + `torch`), e custo de **execução** alto: 880M parâmetros autoregressivos contra VITS *feed-forward*. **[SUPOSIÇÃO:** em CPU isto não fecha o SLO-5 e precisa de GPU — a confirmar medindo com o harness do F1-09, que já publica primeiro pedaço e RTF por motor**]** | medir e descobrir que roda em CPU dentro do SLO-5; ou o dono ter GPU no desktop |
| D. `Kokoro-82M` | — | — | não é candidato: o card declara só `en` |
| E. `facebook/mms-tts-por` | — | — | CC-BY-NC: barrado pela ADR-0011 |
| F. `OuteTTS-0.3-500M` | — | — | CC-BY-SA: o carregador do F1-09 recusa licença não permissiva |

## Consequências

- **Fica mais fácil:** decidir com fato, não com impressão. As três saídas estão nomeadas, com
  custo e com o que derruba cada uma.
- **Fica mais caro:** qualquer caminho exige trabalho novo — mapeamento de fonema (B), outra
  família de inferência (C) ou obrigações de distribuição (A).
- **Passa a ser obrigatório testar:** se a opção B for escolhida, o mapeamento
  `epitran` → `phoneme_id_map` precisa de teste que cubra o inventário inteiro da voz, porque o
  carregador do F1-09 **levanta erro** em fonema desconhecido: sem o teste, o produto quebra na
  frase errada em vez de na revisão.
- **Fica registrado:** os três modelos recusados entram em `licenses/modelos.toml` com o motivo,
  para ninguém tentar de novo (é a mesma regra que barrou o `coqui/XTTS-v2` na ADR-0011). Dois
  deles mexeram na porta de licença, e vale dizer por quê:
  - o `Kokoro-82M` é o primeiro `barrado` **cuja licença é permissiva** — ele ficou fora por
    idioma. A porta imprimia "ATRIBUIÇÃO OBRIGATÓRIA" para qualquer item de categoria
    `ATRIBUICAO`, inclusive barrado: cobrar aviso no produto por um modelo que o registro
    existe para manter **fora** do produto é ruído que ensina a ignorar a porta. Agora barrado
    não cobra atribuição;
  - o `OuteTTS` é o primeiro **ShareAlike** do registro, e `cc-by-sa-4.0` estava na mesma lista
    do `cc-by-4.0`. Numa voz de TTS o "derivado" é o **áudio que o produto distribui**, então
    ShareAlike obriga muito mais do que atribuir. A categoria continua `ATRIBUICAO` (uso
    comercial é permitido), mas a porta passa a imprimir um aviso próprio — `compartilha_igual()`
    — para o próximo candidato SA não passar como se fosse CC-BY.

## Como invalidar esta decisão

- Medir o Parler-TTS multilingual em CPU e ele **fechar** o SLO-5 com RTF < 1: aí a opção C
  passa a ser a melhor, porque não tem fonemizador nenhum para mapear.
- O mapeamento do `epitran` cobrir o inventário da voz **e** o dono aprovar a voz de ouvido: a
  opção B deixa de ser recomendação e vira decisão.
- O dono aceitar distribuir o `espeak-ng` com as obrigações da GPL: a opção A fecha o assunto
  sem trabalho novo, e as outras duas viram otimização.
