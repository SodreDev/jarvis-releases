# ADR-0021 — Modos de ativação: atalho de teclas, palavra de ativação e escuta contínua, trocáveis com a sessão aberta

**Data:** 2026-10-16 · **Estado:** proposta · **Decide:** dono
**Pedido:** no modo de fala por ativação o dono escolhe entre (1) um **atalho de teclas** que
ele configura e (2) uma **palavra de ativação** que ele escolhe (padrão "jarvis"), reconhecida
**localmente** e tolerante a pronúncias parecidas; (3) a escuta contínua já existia; e o
**próprio Jarvis** pode alternar o modo para ele.
**Mede:** o detector de palavra sobre texto — `tools/harness_palavra.py`, commit `fc82249`,
publicado em `docs/medicoes/palavra-de-ativacao.{csv,md}`. Nenhum áudio foi medido.
**Commits da implementação:** `47835a2` (testes do detector e conserto de laço infinito),
`fc82249` (medição), `b153374` (modos e política), `35af651` (laço e configuração),
`bdc1ac6` (portal), `5a359d7` (ação do vocabulário), `9c8a2ff` (janela).

## Contexto

1. **O laço tinha dois modos, e o arquivo do dono já os grava.** `escuta = "ptt"` (o dedo
   decide) ou `"vad"` (o VAD decide), e o indicador de microfone do F1-13
   (`jarvis.microfone.Modo`) usa os mesmos textos. Um terceiro modo não pode quebrar o
   `jarvis-voz.toml` que existe.
2. **Modelo pré-treinado de palavra de ativação não entra sem o portão.** openWakeWord,
   Porcupine e parentes vêm com pesos e termos próprios; a régua da ADR-0011/0012 é que termo
   não verificado não entra. O que já está no produto e roda local é o ASR (`faster-whisper`,
   F1-06), que o laço só chama quando o VAD abre um trecho.
3. **O ASR escreve o nome de vários jeitos.** "járvis", "djarvis", "jarves", e partido em
   duas palavras ("jar vis"). Igualdade de texto erraria em todos; "contém" dispararia em
   qualquer coisa parecida.
4. **No Wayland, atalho global é do compositor.** O caminho padronizado é o portal
   `org.freedesktop.portal.GlobalShortcuts`. Nesta máquina ele existe na **versão 2**
   (xdg-desktop-portal 1.22.1 + xdg-desktop-portal-kde 6.7.5, Plasma, lido por introspecção
   com `busctl` em 2026-10-16), com `Activated`/`Deactivated` — apertar e soltar — e o
   `org.freedesktop.host.portal.Registry` (`Register(sa{sv})`) para um aplicativo de fora de
   sandbox dizer o seu id. Assinaturas conferidas também na documentação do projeto
   (<https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html>,
   lida em 2026-10-16). A memória do projeto já registrava que o `kglobalacceld` direto sai
   em silêncio sob `XDG_SESSION_TYPE=wayland` (F2-01): falar com o KGlobalAccel por fora do
   portal não é caminho.
5. **`BindShortcuts` abre um diálogo na tela do dono.** O compositor pergunta se ele aceita a
   combinação. Isso não pode acontecer por teste nem por iniciativa do programa.

## Decisão

**Três modos num estado vivo, a palavra decidida por comparação fonética sobre a transcrição
local, o atalho global só pelo portal, e o modelo propondo troca de modo pelo vocabulário
fechado — com confirmação quando a troca amplia o que o Jarvis escuta.**

1. **Os modos** (`jarvis.voz.escuta.ModoDeEscuta`): `ATALHO = "ptt"`, `PALAVRA = "palavra"`,
   `CONTINUA = "vad"`. Os dois textos antigos ficam; arquivo sem os campos novos continua
   valendo (teste em `tests/unit/voz/test_escuta.py`).
2. **Trocável com a sessão aberta.** `Escuta` é um objeto só, compartilhado pela janela, pelo
   gerente de workspace e pelo laço; o laço o lê a cada tique. Cada troca é uma atribuição de
   atributo — atômica em CPython —, então o laço vê o modo antigo ou o novo, nunca meio. A
   sessão liga a porta do dedo **sempre**; quem decide se o dedo manda é o modo vivo. No
   atalho o turno fecha ao soltar; nos outros dois, por 700 ms de silêncio.
3. **A palavra de ativação** (`jarvis.voz.palavra`): o VAD abre o trecho, o ASR **local**
   transcreve, e o detector compara a forma sonora das janelas de uma e duas palavras com a
   palavra escolhida (distância de edição normalizada). Dois fonemizadores: uma redução pt-BR
   sem dependência (`fonetica_simples`, o padrão, roda no CI) e o `epitran` já do produto
   (MIT, grupo `voz`), injetável. No modo `palavra`:
   - "jarvis, que horas são" e "que horas são, jarvis" pedem a mesma coisa (só o pedido vira
     turno, sem o nome);
   - "Jarvis?" sozinho **arma** a escuta por 8 s, e o trecho seguinte é o pedido;
   - trecho sem a chamada é **descartado sem deixar o texto em lugar nenhum** — nem tela, nem
     histórico; só um contador sobe;
   - o ASR só roda quando o VAD abre um trecho: silêncio não vira transcrição (teste
     `test_o_asr_so_roda_quando_o_vad_abre_um_trecho`).
4. **O limiar é do dono** (de 0,50 a 1,0), com padrão **0,75**, escolhido pela medição abaixo.
5. **O atalho**: a combinação fica na grafia do Qt (`Ctrl+Space`), capturada na janela
   apertando as teclas, ou digitada no `jarvis-voz config`; exige um modificador (exceto
   F1–F24), porque uma letra solta como atalho global tomaria a letra de todo programa.
   - **global** só pelo portal (`jarvis.ui.portal.AtalhoPortal`, cliente `jeepney`, MIT, que
     já vinha no produto por baixo do `keyring` e agora é dependência direta do grupo `gui`):
     registra o id `dev.sodredev.Jarvis`, cria a sessão, pede a combinação como
     **preferência** (`CTRL+space`, a grafia da spec) e segue `Activated`/`Deactivated`.
     Só roda no clique do dono em "usar como atalho global", nunca sozinho;
   - **sem portal**, a tela diz por escrito que o atalho vale **só com a janela em foco**.
6. **O próprio Jarvis troca o modo** pela ação `definirModoDeEscuta` — nona do vocabulário
   fechado da ADR-0019 (emenda desta ADR). O modelo propõe, o `Workspace` decide pela política
   de `confirmacao_necessaria`:
   - escutar **menos ou igual** passa direto (contínua → palavra → atalho, e atalho ↔ palavra
     com ASR local);
   - **ligar a escuta contínua** vira pendência na tela, com o motivo da IA;
   - **ligar a palavra com ASR de nuvem** também — cada trecho que o VAD abrir sairia da
     máquina, e isso é "ligar nuvem" por outro nome;
   - a ação **não leva dados**: palavra, limiar, atalho e o interruptor da nuvem ficam fora do
     alcance do modelo, e nenhum tipo nem campo do vocabulário liga nuvem (teste
     `test_nenhuma_acao_do_vocabulario_liga_nuvem`).
7. **O indicador diz o modo e quando escuta.** Ao lado do estado da fonte (que continua vindo
   do arquivo do F1-13), a barra de conversa mostra o modo vivo ("microfone fechado · palavra
   de ativação") e acende em âmbar quando a palavra armou a escuta; a caixa de escuta diz a
   frase inteira ("só responde quando ouvir “jarvis”", "só ouve enquanto você segura Ctrl+Space
   (com a janela em foco)").

### Um furo antigo, consertado junto

O gerente marcava a confirmação de componente sensível com `widget="confirmado:<pendência>"`.
A própria IA podia escrever esse prefixo numa proposta e pular a confirmação — o oposto do
P12. O sim do dono passou a ser um sinal interno de `Workspace.confirmar()`; nenhum campo da
proposta diz "já confirmado" (teste `test_a_ia_nao_escreve_o_proprio_sim`).

## Medição — sobre texto, não sobre voz

Hardware: AMD Ryzen 5 5600G, 12 fios, 31 GiB de RAM, Linux 7.2.9 (Nobara/Fedora 44), Python
3.12.14. Dados em `docs/medicoes/palavra-de-ativacao.{csv,md}`.

- **negativos do corpus**: `n` = 340 frases distintas de `corpus/turnos/rotulos.jsonl`
  (`texto` ∪ `texto_antes`). Nenhuma tem a palavra, então qualquer disparo é falso positivo;
- **vizinhos** (escolhidos à mão): 18 nomes e palavras que soam perto (`jarbas`, `marvin`,
  `davis`, `jardim`, "já vi"…) × 4 moldes de frase = 72 frases;
- **positivos** (construídos à mão — o corpus não tem a palavra): 12 grafias de ASR × (sozinha
  + antes e depois de 20 pedidos do corpus) = 492 frases.

| fonemizador | limiar sugerido | FP no corpus | FP nos vizinhos | FN |
|---|---:|---:|---:|---:|
| `simples` | 0,75 | 0 / 340 | 0 / 72 | 0 / 492 |
| `epitran` | 0,75 | 0 / 340 | 0 / 72 | 0 / 492 |

Por que 0,75: com `jarvis` as grafias de ASR dão 0,833 ou mais e os vizinhos 0,667 ou menos,
nos dois fonemizadores; nenhuma frase do corpus passa de 0,50. A curva anda em degraus porque o
alvo tem seis símbolos e cada edição custa 1/6 — **entre 0,67 e 0,83 todo limiar é o mesmo
corte, "no máximo uma edição"**, e 0,75 é o meio dele. Abaixo de 0,67 disparam 32 das 72
frases de vizinhos (`simples`; 16 no `epitran`); a partir de 0,84 perdem-se 246 dos 492
positivos (`simples`; 369 no `epitran`).

Custo por trecho (um `achar` sobre cada uma das 340 frases negativas, `perf_counter_ns`):

| fonemizador | tempo por trecho p50 | tempo por trecho p95 |
|---|---:|---:|
| `simples` | 204,5 µs | 263,5 µs |
| `epitran` | 598,7 µs | 764,4 µs |

Ao lado do ASR (centenas de milissegundos por trecho no F1-06), os dois são desprezíveis;
o padrão continua sendo o `simples` porque roda onde o `epitran` não está.

## O que ficou não verificado

- **Áudio real nunca testado.** Nenhuma voz do dono, nenhum ruído da casa, nenhum ASR de
  verdade transcrevendo "jarvis". A taxa de acerto em uso é **desconhecida**; os números acima
  valem para as listas escritas à mão e para o corpus de pedidos, não para conversa livre,
  TV ou música ao fundo. É o F1-16, na máquina do dono.
- **O portal de verdade nunca foi exercitado.** O cliente foi provado contra um portal falso
  num barramento D-Bus privado (`tests/unit/ui/test_portal.py`). Não se sabe: como o diálogo
  do Plasma se comporta; se o `Register` do id é aceito rodando da árvore (sem o `.desktop`
  instalado — o código segue com id vazio se for recusado); se `Ctrl+Space` já está tomada na
  sessão do dono; se `Deactivated` chega ao soltar quando o modificador é solto antes da tecla.
- **O registro do atalho global não sobrevive ao fechar o aplicativo.** A cada abertura o
  dono clica de novo em "usar como atalho global"; se o Plasma lembra a escolha e deixa de
  mostrar o diálogo, não foi verificado.
- **Nenhum modelo emite `definirModoDeEscuta` hoje.** O caminho existe e está testado
  (gerente, política, pendência na janela); quem propõe de verdade é o `s2` da F2 — o S2
  provisório da ADR-0018 só devolve texto.
- **Barge-in por voz continua ligado no modo palavra.** Fala por cima (inclusive de TV)
  interrompe o Jarvis enquanto ele fala, como na contínua. Se isso incomodar, é decisão do dono
  exigir a palavra também para interromper. **Corrigido pela ADR-0040 (2026-10-21):** o laço do
  `jarvis-voz` não lia o microfone durante a fala, então nada interrompia pela voz; agora, no
  modo palavra, só a palavra de ativação dita por cima corta (a TV não), e na contínua ele pausa,
  confere e corta com a palavra, uma ordem de parar ou o detector de endereçamento.
- **Palavra escolhida pelo dono muda o degrau.** O limiar foi medido para `jarvis`; para outra
  palavra o harness roda de novo com ela trocada no código.

### Um incidente durante o teste do portal

A primeira versão de `test_portal.py` subiu o `dbus-daemon` privado com a configuração padrão
de sessão, que **ativa serviços sob demanda**: o teste sem portal falso fez o barramento
privado subir o xdg-desktop-portal e o xdg-desktop-portal-kde **reais**, herdando a sessão
gráfica. A primeira rodada travou 120 s — o `BindShortcuts` pode ter aberto o diálogo de
atalho na tela do dono. Um xdg-desktop-portal-kde órfão ficou vivo; foi identificado pelo
endereço de barramento em `/proc/<pid>/environ` (o privado, não o do dono) e encerrado por
esse PID. Nada foi gravado em `~/.config/kglobalshortcutsrc`. O teste agora usa uma
configuração própria, **sem diretório de serviço**, e o daemon roda sem `DISPLAY` nem
`WAYLAND_DISPLAY`.

## Perguntas do dono — pendentes

1. **Grafia da ação:** ficou `definirModoDeEscuta`, como no pedido; os outros oito tipos são
   camelCase em inglês (`setWorkspaceMode`…). Manter, ou trocar para `setListeningMode`?
2. **Palavra de ativação com ASR de nuvem:** hoje é permitida com aviso na tela, e pedida pelo
   modelo vira pendência. Bloquear de vez?
3. **Combinação padrão do atalho:** sem escolha do dono, é a barra de espaço com a janela em
   foco, e o pedido ao portal usa `Ctrl+Space`. O módulo antigo propunha `Super+Espaço`, que no
   Plasma pode estar tomada. Qual ele quer?

## Alternativas descartadas

- **openWakeWord, Porcupine e outros modelos pré-treinados:** pesos e termos próprios, fora
  do portão da ADR-0011/0012; e um segundo modelo ouvindo o tempo todo, ao lado do ASR que já
  existe. Volta à mesa se a medição em áudio real (F1-16) mostrar que o ASR local erra o nome
  demais — e aí passando pelo portão de licença.
- **Comparar texto cru ou "contém":** erra nas grafias de ASR para um lado e dispara em
  qualquer palavra parecida para o outro.
- **Ler o teclado do sistema (`evdev`, `ydotool`):** exige grupo `input` ou root, lê tudo o que
  o dono digita em qualquer programa, e é exatamente o que o Wayland fecha de propósito.
- **KGlobalAccel por fora do portal:** preso ao Plasma, e o `kglobalacceld` direto sai em
  silêncio sob Wayland (memória do projeto, F2-01).
- **`Shortcut` do QML para o atalho em foco:** só dá "ativou", sem "soltou"; segurar para falar
  precisa dos dois, então a janela compara a combinação no `Keys.onPressed`/`onReleased`.

## Consequências

- **Mais fácil:** o dono escolhe e troca o modo sem reiniciar nada; a palavra é dele e o
  limiar também; o atalho global, onde o sistema oferece, não depende de a janela estar em
  foco; o modelo pode pedir para escutar menos sem atrapalhar ninguém.
- **Mais caro:** no modo palavra, todo trecho que o VAD abre passa pelo ASR — inclusive fala
  que não era para o Jarvis. Com ASR local é custo de CPU; com ASR de nuvem é requisição paga
  e fala saindo da máquina, e por isso a tela avisa e o modelo precisa de confirmação.
- **Passa a ser obrigatório testar:** os três modos no laço (com troca no meio da sessão), a
  política de confirmação nas nove trocas com e sem nuvem, que nenhuma ação liga nuvem, que a
  IA não confirma a si mesma, o portal contra o falso **sem ativação de serviço**, e o limiar
  padrão igual ao que o harness sugere.

## Como invalidar esta decisão

- A medição em áudio real (F1-16) mostrar que o ASR local escreve o nome fora de uma edição
  com frequência, ou que fala comum perto do nome dispara: o limiar muda, ou o caminho passa a
  ser um modelo de palavra de ativação pelo portão de licença.
- O portal do Plasma não entregar `Deactivated` de forma confiável: segurar para falar global
  vira "apertar para alternar", e a tela diz isso.
- O dono responder às perguntas pendentes de forma diferente do que está implementado.
