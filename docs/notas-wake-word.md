# Handoff — Tarefa 1 (b)(c)(d): modos de ativação, palavra de ativação e ADR-0021

**Quem escreveu:** executor (Opus 5), em 2026-10-16, ao ser interrompido pela ordem do dono de
reduzir para duas CLIs. **Para quem:** a CLI que continuar (b), (c) e (d).
**Estado honesto:** entregue **um** arquivo, sem teste, sem ligação com o resto e sem medição.
Nada do laço de voz, da janela ou do vocabulário de ações foi tocado. O resto é desenho e
leitura — está tudo aqui para não precisar ser refeito.

## 1. O que existe no repositório

| o quê | onde | estado |
|---|---|---|
| detector de palavra de ativação por casamento fonético | `src/jarvis/voz/palavra.py` | **comitado**, `ruff format`/`ruff check`/`mypy` verdes nele; **sem teste**, sem chamador |

Nada mais foi escrito. Os arquivos que a tarefa vai precisar tocar continuam intactos:
`src/jarvis/voz/config.py`, `src/jarvis/voz/app.py`, `src/jarvis/gui/nucleo.py`,
`src/jarvis/gui/acoes.py`, `src/jarvis/gui/workspace.py`, `src/jarvis/gui/ponte.py`,
`src/jarvis/gui/qml/JarvisUI/VistaConfiguracao.qml`, `src/jarvis/ui/atalhos.py`.

**Atenção à concorrência:** enquanto isto era escrito, outra CLI (a "modelos", item (a) da
mesma tarefa) estava com `config.py`, `app.py`, `registro.py`, `nuvem.py`, `elevenlabs.py`,
`ponte.py`, `VistaConfiguracao.qml` e `licenses/motores.toml` **modificados e sem commit**.
Quem continuar precisa reler esses arquivos antes de editar e **não** usar `git add -A`: o
`config.py` dela já ganhou `voz_elevenlabs` e `modelo_elevenlabs`, e o `escuta` de (b) entra no
mesmo dataclass.

## 2. O que `palavra.py` faz (e por que assim)

- **Sem modelo pré-treinado de wake word.** openWakeWord e parentes têm termos próprios, e
  termo não verificado não entra (ADR-0011/0012). O caminho é o que o dono pediu: ASR local
  transcreve o trecho que o VAD abriu, e a chamada é decidida por **comparação fonética** —
  nenhuma dependência nova, nenhum peso para baixar, nenhum portão novo a atravessar.
- **`fonetica_simples(texto)`**: redução pt-BR em classes de som, escrita à mão (sem
  dependência, roda no CI, que não tem o grupo `voz`). `j`/`ge`/`gi`/`dj` → `J`; `c`/`qu`/`k`
  → `k`; `x`/`ch` → `S`; `h` some; vogal átona final fecha (`e`→`i`, `o`→`u`); repetição
  colapsa.
- **`FonemizadorEpitran` (já no produto, MIT) é o outro caminho**, injetável em
  `DetectorDePalavra(fonetica=...)`: dá IPA de verdade para quem tem o grupo `voz`. Não é o
  padrão **de propósito** — o padrão tem de funcionar onde o `epitran` não está.
- **`similaridade`** = 1 − distância de Levenshtein ÷ tamanho maior. `distancia` é 15 linhas
  no próprio arquivo.
- **`DetectorDePalavra.achar(texto)`** varre janelas de **uma e duas** palavras (o ASR escreve
  nome próprio partido: "jar vis") e devolve `Achado` com `ouvido`, `similaridade`, `antes`,
  `depois`. `Achado.comando` é `depois or antes` — "jarvis, que horas são" e "que horas são,
  jarvis" dão o mesmo pedido. `Achado.so_o_nome` é o caso de armar a escuta e esperar o
  trecho seguinte.
- **`exigir_palavra` / `exigir_limiar`** recusam o que não serve (vazio, pontuação, duas
  palavras, menos de três letras, limiar fora de 0,50–1,0), com frase dizendo o porquê — é a
  validação que a tela de Configuração vai cobrar quando o dono escolher a palavra dele.

### Números de mão (não são medição)

Com `fonetica_simples`, rodado nesta máquina em 2026-10-16 (AMD Ryzen 5 5600G, Python 3.12):

| entrada | parecença com "jarvis" |
|---|---:|
| `jarvis`, `járvis`, `djarvis`, `jarves` | 1,000 |
| `jarvas`, `javis`, `jarvi` | 0,833 |
| `jarbas`, `charles`, `marvin` | 0,667 |
| `carlos` | 0,500 |

`achar` acerta "jarvis abre a pasta de fotos" → comando "abre a pasta de fotos"; "que horas
são, jarvis" → "que horas são"; e **não** dispara em "duplica o documento do aluguel" nem em
"o jarbas ligou". `LIMIAR_PADRAO = 0.82` saiu **desta tabela, não de corpus** — está marcado
como provisório no próprio arquivo.

## 3. O que falta (na ordem que eu faria)

1. **Teste de `palavra.py`** (`tests/unit/voz/test_palavra.py`): variantes que casam, nomes
   próximos que não casam, janela de duas palavras, `comando` antes e depois, recusas de
   `exigir_palavra`/`exigir_limiar`, e um caso com `FonemizadorEpitran` marcado para pular
   quando o `epitran` não estiver instalado.
2. **Harness de medição** (`tools/harness_palavra.py`) — é o que fecha o pedido do dono
   ("taxa de falso positivo medida no corpus sintético"):
   - **negativos**: os campos `texto` e `texto_antes` de `corpus/turnos/rotulos.jsonl` (≈500
     itens, pt-BR, já comitados) — nenhum tem a palavra, então **qualquer** disparo ali é
     falso positivo;
   - **positivos**: a lista de variantes acima, sozinhas e dentro de frase;
   - varredura de limiar de 0,60 a 0,95, para os **dois** fonemizadores, saída em
     `docs/medicoes/palavra-de-ativacao.csv` + tabela para a ADR;
   - o limiar padrão passa a ser o escolhido pela curva, e a frase do `LIMIAR_PADRAO` troca.
3. **`src/jarvis/voz/escuta.py`** — o modo vivo, desenhado e não escrito:
   - `ModoDeEscuta(StrEnum)`: `ATALHO = "ptt"`, `PALAVRA = "palavra"`, `CONTINUA = "vad"`.
     **Manter os valores "ptt" e "vad"** é o que não quebra o `jarvis-voz.toml` que o dono já
     tem nem o `Modo` do indicador de microfone (`jarvis.microfone`);
   - um objeto `Escuta` (modo + palavra + limiar + `armado`) que o laço lê **a cada tique** e
     a janela troca de outra thread — é isso que dá "trocável em tempo de execução" sem
     reiniciar a sessão de voz. Atribuição de atributo em CPython basta; documentar isso;
   - a política de (c) mora aqui, não na tela: `confirmacao_necessaria(alvo, *, asr_na_nuvem)`
     devolve o motivo (ou vazio).
4. **Laço (`jarvis/voz/app.py`)** — três pontos, e só:
   - `_quer_falar`: no modo `ATALHO` manda o dedo (`pressionado`), nos outros dois manda o
     VAD;
   - o fecho do turno hoje é `fechou = self.pressionado is not None or silencio >= 700 ms`;
     tem de virar dependente do modo, senão o turno fecha no primeiro quadro de silêncio
     quando a janela liga `pressionado` em modo contínuo;
   - `_turno_de_audio`: no modo `PALAVRA`, passar a transcrição pelo detector antes de
     responder; sem chamada, **descartar o trecho** (nada de resposta, nada de histórico);
     com chamada e `so_o_nome`, armar por alguns segundos (usar `self.relogio`, que é
     injetável) e dizer na tela que está armado.
   - `_publicar_estado` já deriva o `Modo` do indicador de `configuracao.escuta`: passa a
     derivar do modo vivo (`PTT` só no `ATALHO`; `ESCUTA` nos outros dois).
5. **`SessaoDeVoz._ligar`** (`jarvis/gui/nucleo.py`) liga `pressionado` **só** quando
   `escuta == "ptt"`; com modo trocável em tempo de execução ele tem de ligar sempre e deixar
   o laço decidir pelo modo.
6. **Atalho configurável + global (b.1)** — a parte com mais chão:
   - `src/jarvis/ui/atalhos.py` já tem a fronteira pronta (`BackendDeAtalho`, `AtalhoFalso`,
     `AtalhoDeSistema` declarado-e-não-implementado, `JARVIS_HOTKEYS_BACKEND`). O que falta é
     um `AtalhoPortal` de verdade;
   - **o portal existe nesta máquina** (lido com `busctl` em 2026-10-16, leitura apenas, sem
     abrir sessão): `org.freedesktop.portal.GlobalShortcuts` **version 2**, com
     `xdg-desktop-portal 1.22.1` e `xdg-desktop-portal-kde 6.7.5` (Nobara/Fedora 44, Plasma,
     Wayland). Métodos `CreateSession`, `BindShortcuts`, `ListShortcuts`, `ConfigureShortcuts`
     (esta é da v2) e sinais `Activated`, `Deactivated`, `ShortcutsChanged`;
   - **`Activated`/`Deactivated` são exatamente apertar e soltar** — é o que faz "segurar para
     falar" global ser possível sem `ydotool` e sem ler teclado do sistema;
   - **cliente D-Bus: `jeepney` (MIT), que já vem no produto** por baixo do `keyring`/
     `SecretStorage` (grupo `gui`) e já está na tabela de licenças da ADR-0019. Usando ele não
     há biblioteca nova nem obrigação nova de distribuição — só declarar a dependência direta
     no grupo `gui` do `pyproject.toml`;
   - sintaxe do gatilho (spec freedesktop de atalhos): modificadores `CTRL`, `ALT`, `SHIFT`,
     `NUM`, `LOGO`, juntados por `+`, e a tecla no fim com o nome do keysym sem o prefixo
     `XKB_KEY_` — `CTRL+SHIFT+a`, `CTRL+ALT+Return`, `LOGO+space`. É o que vai em
     `preferred_trigger`;
   - **não dá para exercitar isso na sessão real do dono**: `BindShortcuts` abre diálogo na
     tela dele. O caminho de teste é portal falso em barramento privado
     (`dbus-run-session`), e o que não der para provar entra como "não verificado";
   - **fallback honesto, que o dono pediu por escrito:** sem portal, o atalho vale **só com a
     janela focada** (`Shortcut` do QML / `Keys`), e a tela tem de **dizer isso** em vez de
     prometer atalho global;
   - captura da combinação na janela: `QKeySequence(modificadores | tecla).toString()` no lado
     Python, convertido para a grafia da spec acima antes de ir para o portal.
7. **(c) ação do vocabulário fechado** — `jarvis/gui/acoes.py` hoje tem **oito** tipos e diz
   que acrescentar é emenda de ADR (é o que a 0021 faz). Desenho proposto:
   - tipo novo `setListeningMode` (a grafia do vocabulário é camelCase em inglês, como os
     outros oito; o dono escreveu `definirModoDeEscuta` como **exemplo** — vale confirmar com
     ele qual grafia quer);
   - campo `modo` já existe no `Acao`, mas é do `Modo` de **workspace**: ou se acrescenta um
     campo próprio (`escuta`) ou se reusa `dados` validado. Campo desconhecido continua sendo
     recusa;
   - quem decide é o `Workspace` (é lá que a pendência de confirmação já existe, com o truque
     do `widget="confirmado:<pendencia>"` usado em `_criar`): `ATALHO`↔`PALAVRA` passam
     direto; `CONTINUA` **sempre** vira pendência; e, com ASR de nuvem escolhido, qualquer
     modo que abra o microfone sozinho (`PALAVRA`, `CONTINUA`) também vira pendência — porque
     aí cada trecho que o VAD abrir **sai da máquina**, que é o "ligar nuvem" que o dono quer
     confirmar;
   - **nenhuma ação do vocabulário pode ligar nuvem** (`nuvem_ligada` não tem ação): vale um
     teste que cobre isso explicitamente, além do teste de política pedido;
   - `para_dict()` dos pendentes usa `acao.titulo or acao.componente` para o título — com uma
     ação de escuta os dois são vazios, então a pendência apareceria sem nome na tela.
8. **Tela** (`VistaConfiguracao.qml`, caixa "escuta"): hoje são dois botões ("segurar para
   falar" / "escuta contínua") ligados em `ponte.definirCampo("escuta", ...)`. Viram três, mais
   o campo da palavra, o limiar, a combinação de teclas e **a frase honesta** sobre o alcance
   do atalho. O indicador de modo ativo + "ouvindo agora" é o que o dono cobrou na tela.
9. **(d) ADR-0021** com os números medidos, e `docs/notas-executor-F1.md` ganhando a seção do
   lote. Lembrar do portão: `tools/adr.py conferir` cobra data, estado (primeira palavra depois
   de `**Estado:**`), quem decide, e CSV citado para número com unidade de tempo.

## 4. Armadilhas já pagas (não repita)

1. **`uv run --frozen` travou** (>120 s, sem saída) enquanto outra CLI mexia no ambiente.
   `.venv/bin/python`, `.venv/bin/ruff` e `.venv/bin/mypy` direto resolvem e são instantâneos.
2. **`fonetica_simples` preserva o espaço**: `parecenca("jar vis")` dá 0,857 porque o espaço
   conta como símbolo. Em `achar` isso não acontece (as janelas são juntadas sem espaço), mas
   quem chamar `parecenca` com duas palavras tem de juntar antes.
3. **O corpus sintético serve como negativo, não como positivo**: ele não tem a palavra de
   ativação em frase nenhuma. Positivo tem de ser construído (variantes), e o relatório precisa
   dizer isso, senão vira número que parece medido e não é.
4. **`epitran` está instalado nesta máquina** (grupo `voz`), mas **não no CI** — teste que o
   importe sem `skip` quebra o portão.
5. **Não abrir o portal na sessão do dono.** Introspecção (`busctl --user introspect`) é leitura
   e é segura; `CreateSession` + `BindShortcuts` abrem diálogo na tela dele.

## 5. Perguntas que são do dono (não decidir por ele)

1. **Grafia da ação nova**: `setListeningMode` (consistente com os outros oito) ou
   `definirModoDeEscuta` (como ele escreveu no pedido)?
2. **Palavra de ativação com ASR de nuvem**: bloquear, ou deixar com aviso de que cada trecho
   que o VAD abrir é uma requisição paga que sai da máquina?
3. **Combinação padrão do atalho** quando ele não escolher nenhuma (hoje o módulo propõe
   `Super+Espaço`, que no Plasma pode já estar tomada).
