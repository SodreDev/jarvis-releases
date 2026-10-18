# Pesquisa — pronúncia aproximada → aplicativo instalado

**Data:** 2026-10-18
**Escopo:** pesquisa; não implementa nem altera o fluxo atual.

## Conclusão

Não manter uma lista inicial de apelidos. O catálogo deve nascer dos aplicativos que já
estão instalados e o resolvedor deve comparar **pronúncias**, não só grafia. A solução
recomendada é local, determinística e em duas fases: (1) gerar e indexar antecipadamente
as formas faladas de cada app; (2) no comando `abrir <alvo>`, fonemizar a transcrição
pt-BR e ranquear poucos candidatos. Correções explícitas do dono são a única fonte de
aliases persistentes.

Isso cobre `discórdi` → Discord, `espótifai` → Spotify, `vi esse côdi` → Visual Studio
Code, `cróme` → Chrome, `brêive` → Brave, `obisídian` → Obsidian e `tim speak` →
TeamSpeak sem cadastrar esses exemplos à mão. Não há garantia de acerto para nomes muito
curtos ou homófonos: nesses casos a resposta correta é perguntar, não abrir por palpite.

## Referências consultadas

| Fonte | Licença visível | O que aproveitamos |
|---|---|---|
| [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry/latest-single/) | especificação | `Name`, `GenericName` e `Keywords` descrevem app lançável; também define precedência/ID de `.desktop`. |
| [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html) | documentação | `flatpak --user --columns=app list` permite descobrir instalações do usuário; os apps também seguem desktop entries. |
| [Whisper](https://github.com/openai/whisper) e [discussão sobre `initial_prompt`](https://github.com/openai/whisper/discussions/1477) | MIT | mostra o viés por contexto de vocabulário; é complemento ao resolvedor, não substituto. |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | o backend em uso expõe `initial_prompt` e `hotwords`; ambos entram no prompt do decodificador. |
| [Vosk API — grammar/keyword recognition](https://github.com/alphacep/vosk-api/blob/master/ruby/README.md) | Apache-2.0 | lista dinâmica de frases e N-best: boa referência de ASR restrito, mas não motivo para trocar o Whisper que já é melhor no texto livre. |
| [Rhasspy — intent recognition](https://rhasspy.readthedocs.io/en/v2.4.20/intent-recognition/) | MIT (Rhasspy) | separa STT de reconhecimento de intenção e usa matching fuzzy/gramática depois da transcrição. |
| [HassIL](https://github.com/OHF-Voice/hassil) | Apache-2.0 | parser de frases/intents com slots; inspira extrair o trecho `<alvo>` só em intenções de abrir app. |
| [OpenVoiceOS](https://github.com/OpenVoiceOS/ovos-core) | Apache-2.0 | assistente modular com pipeline de intent/skills: o resolvedor deve ser um componente trocável, não lógica no ASR. |
| [Willow](https://github.com/HeyWillow/willow) | Apache-2.0 | referência de assistente local e autocontido; confirma que o processamento não precisa sair da máquina. |
| [Talon Community](https://github.com/jorenvo/talon-community) | MIT; motor Talon é proprietário | grande conjunto de comandos por voz, mas baseado em vocabulário escrito/manual; é evidência do problema, não o desenho a copiar. |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) e [Jellyfish](https://github.com/jamesturk/jellyfish) | MIT / MIT | similaridade Levenshtein/Jaro-Winkler rápida e chaves Soundex/Metaphone/NYSIIS para a pré-seleção. |
| [Metaphone / Double Metaphone](https://github.com/oubiwann/metaphone) | BSD-3-Clause | chave fonética aproximada para recuperar candidatos; foi feito para inglês e não deve decidir sozinho em pt-BR. |
| [Epitran](https://github.com/dmort27/epitran) e o [artigo](https://aclanthology.org/L18-1429.pdf) | MIT | G2P/transliteração para IPA; já é uma dependência opcional do Jarvis. Para G2P inglês, requer Flite/`lex_lookup` (BSD-4-Clause). |
| [Gruut](https://github.com/rhasspy/gruut) | MIT; repositório arquivado | léxico + G2P treinado para palavras fora do léxico e idiomas inclusive en/pt; bom protótipo/cache de índice, mas não nova dependência sem avaliar manutenção. |
| [PanPhon](https://github.com/dmort27/panphon) e [estudo sobre embeddings acústicos](https://www.isca-archive.org/interspeech_2021/abdullah21_interspeech.pdf) | MIT (PanPhon); artigo | distância por traços articulatórios de IPA é apropriada ao reranking; o artigo acha correlação só moderada para embeddings acústicos, portanto embeddings não são primeira escolha. |

`phonemizer`/eSpeak-NG também é útil para experimentar G2P, mas depende de eSpeak-NG
GPL-3.0. Uso comercial não é proibido por GPL, porém o repositório já o classifica como
`copyleft_forte` e só fora do produto; não o incluir no resolvedor distribuído.

## Comparação prática

As estimativas de precisão são hipóteses a validar no corpus abaixo, não números já
medidos. Latência é só do **resolvedor**, após o Whisper, em catálogo de até alguns milhares
de formas pré-indexadas.

| Abordagem | Precisão esperada neste caso | p95 < 30 ms/local | Dependências e licença | Esforço | Aprende sozinha? |
|---|---|---|---|---|---|
| Normalizar + igualdade | baixa | sim | só stdlib | muito baixo | não |
| RapidFuzz/Jellyfish no texto | média para `chrome`/erros de letra; baixa em “à brasileira” | sim | MIT | baixo | não |
| Soundex/Double Metaphone | baixa-média; orientado ao inglês, perde vogais | sim, como pré-filtro | Metaphone BSD-3 | baixo | não |
| G2P/IPA + edit distance simples | alta para empréstimos previsíveis | sim, com candidatos pré-calculados | Epitran MIT; G2P EN com Flite BSD-4 | médio | não |
| G2P/IPA + distância ponderada por traços/epêntese | mais alta e mais robusta a sotaque PT-BR | sim se recuperar top-50 antes do rerank | código próprio pequeno; PanPhon MIT é referência/opção | médio | não |
| `initial_prompt`/`hotwords` do Whisper | melhora recall do nome, mas pode enviesar/hallucinar | não acrescenta etapa relevante ao resolvedor | faster-whisper MIT | baixo | só por atualização do catálogo |
| Gramática fechada no Vosk | alta apenas se a frase estiver na lista; piora texto livre e troca o ASR | sim, porém no ASR | Vosk Apache-2.0 + modelo | médio | catálogo dinâmico, não correção |
| Embedding fonético/acústico | incerta; exige modelo e boa calibração | não é aposta segura sob 30 ms | peso/licença a verificar | alto | não sem treino |
| Alias aprendido por confirmação | muito alta para a forma corrigida | sim | SQLite/JSON local | baixo | **sim**, mediante confirmação |

Escolha: G2P/IPA + regras PT-BR + distância ponderada, com RapidFuzz como sinal adicional e
`hotwords`/prompt como viés leve. Não usar embeddings nesta fase; eles acrescentam modelo,
licença e calibração sem resolver a ambiguidade de lançamento.

## Desenho recomendado

### 1. Catálogo automático e seguro

Em início de sessão e quando a configuração mudar, construir um `AppCatalog` com uma chave
estável (desktop-file ID/Flatpak ID) e uma ação de lançamento já validada pela camada de
capacidade. Não derivar um comando de shell da fala.

- Ler `.desktop` em `XDG_DATA_HOME/applications` e `XDG_DATA_DIRS/applications`, respeitando
  a precedência da especificação. Ignorar `Hidden=true`, entradas não `Type=Application` e
  manter `Name[pt_BR]`, `Name`, `GenericName`, `Keywords`, ID e `Exec` parseado — nunca
  concatenado em shell.
- Incluir apps Flatpak de usuário e sistema pelo ID/nome (`flatpak --user` e `--system`) e
  casar com sua desktop entry.
- Acrescentar nomes-base de binários executáveis do `PATH`, mas só como **rótulos** para uma
  capacidade de lançamento previamente autorizada; não transformar qualquer binário dito em
  voz em execução arbitrária. Separar identificadores com ponto, hífen, sublinhado e CamelCase.
- Deduplicar por desktop-file ID/Flatpak ID/ação. `Name` tem prioridade sobre `GenericName`;
  `Keywords` servem à recuperação, não para vencer pelo som um nome explícito.

Para cada rótulo, reter: texto original, texto normalizado (casefold, Unicode NFKD, sem
pontuação), origem/peso e várias pronúncias. É índice renovável: instalar ou remover app não
exige alteração de código nem lista de apelidos.

### 2. Pronúncias candidatas pré-calculadas

Para cada nome do catálogo:

1. Gerar IPA inglês com G2P para o nome e também para tokens de ID/`Exec` que parecem
   ingleses; usar léxico quando existir e G2P para OOV. Cachear o resultado no rebuild do
   catálogo, nunca no caminho crítico.
2. Converter esse IPA para um alfabeto fonêmico interno pequeno e aplicar regras finitas de
   aproximação de falante pt-BR: redução de vogais inglesas, `/θ/→t|s`, `/ð/→d`, `/r/` e
   vogais finais/epêntese em grupos e codas (`Discord` pode gerar uma forma terminada em
   `...dʒi`). Não escolher uma única “pronúncia brasileira”: armazenar as variantes limitadas.
3. Gerar também a leitura pt-BR da grafia/ID. Isso recupera quando o dono soletra ou quando
   o Whisper já aportuguesou o texto. A transcrição recebida passa pelo G2P pt-BR e pela mesma
   normalização fonêmica.
4. Expandir siglas de forma algorítmica (`VS` como letras; `vscode` também separado em
   `vs code`), sem tabela por aplicativo. Limitar, deduplicar e registrar a origem de cada
   forma para não explodir o índice.

Epitran já está previsto no grupo `voz` do projeto. É adequado para IPA pt-BR; para a
fonemização inglesa, Epitran documenta a dependência de Flite. Gruut é alternativa de
protótipo para G2P inglês, mas está arquivado — decidir por medição e pela porta de licença,
não por conveniência.

### 3. Resolução no comando

Ativar o resolvedor apenas depois de identificar uma intenção de desktop, por exemplo
`abrir|iniciar|executar <alvo>`. O texto fora dessa intenção não pode disparar um app pelo
candidato mais próximo.

1. Normalizar e fonemizar `<alvo>` em pt-BR; manter a grafia do Whisper como segundo sinal.
2. Recuperar no índice por n-gramas de texto e por uma chave fonética simplificada; unir e
   limitar a, por exemplo, 50 candidatos. Double Metaphone pode ser uma dessas chaves, nunca
   o veredito.
3. Reranquear pelo máximo entre as variantes: `S_fone` é distância de edição de fonemas com
   substituições próximas mais baratas (traços articulatórios, como em PanPhon), e
   `S_texto` é RapidFuzz. Um início simples e calibrável é
   `S = 0,70·S_fone + 0,25·S_texto + 0,05·S_origem`; alias confirmado substitui a pronúncia
   gerada e recebe sinal explícito, não peso secreto ilimitado.
4. Aceitar somente se `S ≥ T_aceite` **e** `S1 - S2 ≥ M_margem`. Os dois valores vêm do conjunto
   de validação. Abaixo do limiar: “não encontrei um aplicativo parecido”. Sem margem: “você
   quis dizer Discord ou Discord Canary?”.

Esse cálculo é local. Pré-calcular formas e usar recuperação top-50 torna realista a meta de
menos de 30 ms p95; ela deve ser tratada como SLO mensurado, incluindo fonemização, e não
promessa da biblioteca.

### 4. Viés do Whisper, sem lista manual

Montar por sessão um contexto curto a partir do catálogo: nomes canônicos, aliases já
confirmados e apps recentes/frequentes. Passar esse conjunto — truncado pelo orçamento de
tokens do modelo — como `hotwords`; quando a API/modelo não aplicar hotwords, usar
`initial_prompt` numa frase natural, por exemplo “Abra Discord, Spotify e Visual Studio
Code.”. Recalcular quando o catálogo mudar.

Não despejar todos os milhares de nomes no prompt: contexto longo compete com a fala e pode
forçar um nome inexistente. O resolvedor pós-STT continua obrigatório; ele permite que um
novo app instalado funcione mesmo antes de ganhar prioridade no prompt.

### 5. Confirmação e aprendizado

Ao haver empate ou baixa confiança, perguntar mostrando no máximo três candidatos. Só depois
da resposta inequívoca executar. Persistir, por dono/perfil, algo como:

`{fala_normalizada, fala_ipa_ptbr, app_id, data, contagem, origem="confirmacao"}`.

A confirmação vira alias do mesmo `app_id`, sobrevive ao rebuild do catálogo e é retirada se
o app desaparecer. Guardar também exemplos de acerto/negação, versão do resolvedor e score
para reavaliar limiares. Não aprender silenciosamente de um lançamento errado.

## Plano de medição

1. **Corpus.** Em cada máquina de teste, congelar o `AppCatalog` e selecionar todos os nomes
   únicos (ou amostra estratificada por tamanho, idioma, sigla e colisão). Para cada nome,
   gerar áudios sintéticos em TTS inglês e pt-BR, incluindo velocidade/voz distintas; transcrever
   os WAVs com o mesmo Whisper local e as mesmas opções do produto. Acrescentar as falas reais
   corrigidas pelo dono somente com consentimento e sem áudio bruto por padrão.
2. **Rótulo.** A chave-verdade é o `app_id`, não a string do nome. Preservar áudio, texto
   Whisper, voz/idioma TTS, versão de modelo, catálogo e seed como artefatos reproduzíveis.
   Separar treino/calibração/teste por *app_id* e por voz para não medir o mesmo alias nos dois
   lados.
3. **Braços.** Medir: texto exato; RapidFuzz; chave Metaphone; IPA simples; IPA+regras
   PT-BR+distância ponderada; e o último braço com `hotwords`/prompt. Medir também sem aliases
   e depois de aliases confirmados, sem deixar um exemplo corrigido entrar no teste.
4. **Métricas.** Publicar acerto top-1 e top-3, MRR opcional, cobertura (percentual aceito),
   falso-aceite (`app_id` errado entre os aceitos), falso-rejeite, taxa de pergunta e p50/p95
   do resolvedor completo. Quebrar por TTS EN/PT-BR, nome curto (≤4), multi-palavra, sigla e
   app recém-instalado. O objetivo de segurança é reduzir falso-aceite; aumentar perguntas é
   preferível a abrir o programa errado.
5. **Calibração e aceite.** Escolher `T_aceite` e `M_margem` apenas na validação; congelá-los
   antes do teste. Aceitar a camada somente se p95 local ficar abaixo de 30 ms e ela superar
   RapidFuzz em top-1 **sem** elevar falso-aceite. Registrar um conjunto de regressão com os
   casos que o dono corrigiu e rodá-lo a cada mudança de G2P, regras ou modelo Whisper.
