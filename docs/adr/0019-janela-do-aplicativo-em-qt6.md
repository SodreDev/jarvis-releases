# ADR-0019 — A janela do Jarvis: Qt 6 por PySide6, e só apresentação

**Data:** 2026-10-16 · **Estado:** aceita; emendada em 2026-10-16 (ver a emenda no fim) · **Decide:** dono
**Pedido:** o dono testou o `jarvis-voz` no terminal e quer **abrir o Jarvis como aplicativo
de verdade** — janela, ícone, menu de aplicativos — no Linux (Nobara/Fedora, KDE Plasma) e
instalável em Debian/Ubuntu.
**Alcance:** a janela do aplicativo de hoje (o laço da ADR-0017/0018). Ela **não** é o
processo `ui` da SPEC §2, que nasce na F2 com confirmação de risco, editor de memória e log de
ações; é a casca que já usa o laço de voz existente, e o que ela aprender vai para lá.

## Contexto

Hoje só existe `jarvis-voz`, no terminal. Isso basta para julgar voz de ouvido e não basta
para três coisas que o dono pediu e que o terminal **não tem como** dar:

1. **PTT de verdade.** Terminal não entrega evento de *tecla solta* — está escrito em
   `jarvis.voz.teclado` e no `docs/COMO-TESTAR.md`. No terminal a barra **alterna**; segurar
   para falar só existe com janela.
2. **Um estado visível.** "Ouvindo", "pensando", "falando", "parado" num canto de tela é o que
   deixa o dono saber de quem é a vez sem ler linha de log.
3. **A chave de API sem terminal.** Hoje a chave vem de `export` no `~/.bashrc`. Abrir pelo
   menu de aplicativos não passa pelo shell do dono, e aí a chave não existe para o processo.

A SPEC §2 reserva à `ui` "confirmação de alto risco, indicador de microfone, PTT, editor de
memória, log de ações, kill switch", com a proibição de confirmar risco alto só por voz. Esta
ADR não antecipa esse processo: ela abre a janela do aplicativo de teste, com a fronteira
desenhada para que o que nascer aqui caiba lá sem reescrita.

## Decisão

**A janela é Qt 6 por PySide6 (`PySide6-Essentials`), em `jarvis.gui`, e é só apresentação.**

A fronteira, que é a parte que importa:

- **a janela não fala com ASR, TTS, dispositivo ou nuvem.** Quem fala é `jarvis.voz.app`, o
  mesmo núcleo do `jarvis-voz` — mesmo laço, mesmo dono do epoch, mesma configuração, mesmo
  registro de motores. A `gui` não tem `import` de `jarvis.agentd`, de `jarvis.audio_io` nem
  de `jarvis.voz.groq/elevenlabs/edge`, e **há teste que cobra isso** por AST;
- **o laço ganhou três portas, e nada mais** (`jarvis.voz.app`): `ao_mudar_estado` (o laço
  **diz** o que está fazendo), `pressionado` (o PTT de verdade, que o terminal não tem) e
  `texto_digitado` (uma linha digitada é um turno como outro qualquer, no mesmo laço e no
  mesmo epoch). Sem essas portas a janela teria de reimplementar o laço — e a primeira coisa
  que uma segunda implementação perde é o cancelamento;
- **o indicador de microfone continua sendo o do F1-13**: a janela lê
  `microfone-estado.json`, escrito por quem está com a fonte na mão. Ela não tem campo
  booleano "ouvindo" para alguém acender por engano;
- **o trabalho pesado não mora na thread da interface.** O laço roda numa thread de trabalho e
  conversa com a janela por sinais do Qt; o teste mede que a thread da interface não bloqueia.

Três abas, em português do Brasil: **Conversa** (orbe de estado, transcrição rolável, segurar
para falar com botão e com a barra de espaço, parar/interromper, campo de texto, indicador de
microfone), **Configuração** (motores, voz, dispositivos, PTT × VAD, S2 provisório, chaves) e
**Diagnóstico** (o que o `--diagnostico` mostra, mais teste de microfone com nível e teste de
voz com frase).

> **As três abas foram substituídas pela emenda de 2026-10-16** (workspace com três modos). O
> conteúdo delas continua existindo: conversa e estado no modo assistente, provedores e
> diagnóstico como **módulos** do workspace.

`uv run jarvis` abre a janela. `uv run jarvis-voz` continua existindo, no terminal, igual.

## Licença, verificada na origem em 2026-10-16

| o quê | licença | onde foi lida |
|---|---|---|
| `PySide6-Essentials` 6.9.3 e `shiboken6` 6.9.3 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only` | metadados da distribuição publicada no PyPI (`License-Expression`), lidos nesta máquina |
| obrigações do LGPL segundo o detentor | ligação dinâmica, direito de **re-ligar**, texto da licença e aviso visível, fonte correspondente completa das bibliotecas Qt | <https://www.qt.io/licensing/open-source-lgpl-obligations> |
| `keyring` | MIT | metadados da distribuição |
| `SecretStorage` (back-end do Secret Service) | BSD-3-Clause | metadados da distribuição |
| `jeepney` (D-Bus puro, sem libdbus) | MIT | metadados da distribuição |

**Escolhemos o LGPL-3.0** dos três da expressão, e é isso que o produto cumpre:

1. **só ligação dinâmica.** Usamos as rodas oficiais, que trazem o Qt em `.so` separados;
   nada é ligado estaticamente e **o Qt não é alterado** — sem patch, sem recompilação;
2. **o dono pode re-ligar.** Nos três pacotes (ADR-0020) as bibliotecas do Qt ficam em
   arquivos próprios, substituíveis, numa pasta documentada; o AppImage se extrai com
   `--appimage-extract` e volta a empacotar;
3. **texto e aviso.** A roda oficial **não traz** o texto da licença — conferido nesta
   máquina em 2026-10-16: só a expressão nos metadados, nenhum `LICENSE*` no pacote. Então os
   textos do LGPL-3.0 **e** do GPL-3.0 (que a LGPLv3 incorpora) vêm do detentor, ficam
   versionados em `licenses/texto/` e são copiados para `usr/share/licenses/jarvis/` em cada
   artefato; o `NOTICE` diz que o Qt é LGPL-3.0 e não foi modificado, e a janela mostra isso
   na aba de diagnóstico;
4. **fonte correspondente.** O código do Qt é o publicado pelo projeto Qt na versão que a roda
   declara; o `NOTICE` registra a oferta escrita e o endereço.

Isto fica **registrado no portão**, não só nesta prosa: `licenses/bibliotecas-distribuidas.toml`
guarda licença, fonte, data e as obrigações de cada biblioteca que o produto **distribui**, e
`tools/license_gate.py` falha se uma obrigação ficar sem o arquivo que a cumpre. A régua é a
da ADR-0011 e da ADR-0012: licença que ninguém verificou não entra por otimismo.

**Versão fixada em 6.9.x, e o motivo é alcance.** A partir da 6.10 a roda de Linux é
`manylinux_2_34`; a 6.9.3 é `manylinux_2_28` (97,5 MB contra 84,3 MB, tamanhos lidos na API do
PyPI em 2026-10-16). Fixar na 6.9.3 mantém o piso de glibc em 2.28 — Debian 10+, Ubuntu 18.10+,
RHEL/Alma 8+, Fedora 29+ —, enquanto a 6.10+ subiria o piso para glibc 2.34 (Debian 12+,
Ubuntu 22.04+, RHEL 9+). Subir de versão é decisão de quem o pacote deixa de atender.

## Alternativas descartadas

- **PyQt6:** GPL-3.0 ou licença comercial da Riverbank. GPL no caminho do produto obrigaria a
  abrir o produto — a porta de licença trata copyleft forte **em uso** como bloqueio, e abrir
  o produto não é decisão que uma dependência toma por nós (ADR-0011).
- **GTK 4 por PyGObject:** licença boa (LGPL-2.1+), mas o desktop do dono é KDE Plasma: o
  aplicativo nasceria estrangeiro no tema, nos diálogos e no decorador de janela. E o caminho
  Windows (P11) é pior do que o do Qt, que é o que a SPEC pede manter aberto.
- **Tkinter:** vem com o Python e não custa licença, mas não tem como desenhar o orbe, o
  indicador e o tema sem virar um segundo kit de widgets escrito à mão, e o teste de tela
  (captura offscreen) fica muito mais pobre.
- **Interface web em `webview`/Electron:** foi o caminho do Jarvis antigo e trouxe o que o
  relatório registrou — motor de navegador inteiro no pacote, `--no-sandbox` em distro
  conhecida, e uma fronteira de processo a mais entre o dono e o microfone. Para uma janela
  com três abas é peso sem contrapartida.
- **Slint, Kivy, wxPython:** Slint é GPL/comercial (mesma objeção do PyQt6) na versão
  gratuita para uso fechado; Kivy não se parece com um aplicativo do desktop; wxPython ficaria
  bem, mas o ecossistema Qt é o que o resto do projeto (e a futura `ui` da §2) já pressupõe.

## Consequências

- **Mais fácil:** o dono abre pelo menu, segura para falar, lê a transcrição e cola a chave
  sem terminal; e o teste de tela passa a ser captura de imagem em `QT_QPA_PLATFORM=offscreen`,
  que roda em CI sem placa de vídeo.
- **Mais caro:** 97,5 MB de roda e um piso de glibc; uma thread a mais para cuidar (a
  interface não pode bloquear); e a obrigação do LGPL passa a ser conferida a cada pacote.
- **Passa a ser obrigatório testar:** que a `gui` não importa motor nenhum; que a thread da
  interface não faz trabalho pesado; que cada aba desenha sem tela de verdade; e que as
  bibliotecas distribuídas cumprem as obrigações registradas.

## Como invalidar esta decisão

- O dono preferir o aplicativo dentro de outro ambiente (uma extensão do Plasma, um aplicativo
  web): a `gui` sai inteira e o laço fica onde está — é justamente por isso que a fronteira é
  de três funções, e não de herança.
- A Qt Company mudar o licenciamento do PySide6 para algo que a ADR-0011 barre: o portão passa
  a bloquear e a janela precisa de outro kit.
- O piso de glibc 2.28 deixar de importar (todas as distros-alvo em 2.34+): a fixação em 6.9.x
  cai, e a decisão de subir é registrada aqui.


---

## Emenda de 2026-10-16 — a tela é um workspace conduzido pela IA, em Qt Quick

**Quem decide:** dono (como diretor), depois de ver a primeira versão em abas.
**O que muda:** só a camada visual e o jeito de a tela ser montada. A decisão de **Qt 6 por
PySide6 sob LGPL-3.0** continua inteira, e com ela todo o registro de licença acima.

### Por que mudou

A primeira versão era um aplicativo de abas: conversa, configuração, diagnóstico. Funciona, e
é exatamente o que o dono não quer — "abas genéricas de formulário, cartões SaaS" é a cara de
interface montada por conveniência, não de um assistente. O que ele pediu, e a referência que
aprovou (`docs/design/referencia-ui.png`), é outra coisa: **um espaço de trabalho que a IA
organiza**, fundo quase preto, linhas técnicas finas, ciano discreto, um HUD circular no meio
e módulos flutuantes que aparecem conforme a tarefa.

### A pilha: QML por cima, Python por baixo

A camada visual passa a ser **Qt Quick/QML** (`src/jarvis/gui/qml/JarvisUI/`), com a lógica em
Python atrás de uma ponte fina (`jarvis.gui.ponte`). O motivo é concreto, não estético: estado,
transição e animação são declarativos em QML (`Behavior`, `states`, `Shape`), e desenhar anéis
concêntricos com marcadores e movimento radial em QtWidgets seria reimplementar um motor de
cena à mão. **Não há impedimento técnico:** QML desenha e é capturado em
`QT_QPA_PLATFORM=offscreen` com o renderizador de software — testado aqui antes de escrever
uma linha de tela, e é como as capturas do aceite são feitas.

A obrigação do LGPL continua idêntica: `PySide6-Essentials` traz QtQml e QtQuick nas mesmas
rodas, nada é modificado e nada é ligado estaticamente.

### As cinco camadas, e onde cada uma mora

| camada | onde | o que faz | testável sem janela |
|---|---|---|---|
| AI Controller | `jarvis.gui.controlador` | **propõe** ações estruturadas (hoje, um roteiro de demonstração; amanhã, o `s2` da F2) | sim |
| Workspace Manager | `jarvis.gui.workspace` | **valida**, resolve colisão, troca de modo, guarda e restaura layout, segura o que precisa de confirmação | sim |
| Component Registry | `jarvis.gui.componentes` | diz **o que pode existir** na tela e que dados cada componente aceita | sim |
| Animation System | QML (`Behavior`, 200–500 ms, curvas naturais) | move e redimensiona **preservando identidade** — o modelo emite `dataChanged`, não refaz a lista | pela captura |
| Desktop Integrations | nada ligado | navegador, terminal, arquivos e captura de tela são **sensíveis**: viram pendência e esperam o sim do dono (SPEC §5.4, P12) | sim |

O vocabulário é fechado em oito ações (`createWidget`, `removeWidget`, `moveWidget`,
`resizeWidget`, `focusWidget`, `minimizeWidget`, `setWorkspaceMode`, `restoreLayout`) e **campo
desconhecido é recusa**: um `html`, um `script` ou um `comando` não passam despercebidos. É
assim que "nunca HTML ou JS arbitrário da IA" vira propriedade da estrutura, e não promessa.

### As regras do dono que o gerente impõe

1. módulo **fixado** pelo dono não é movido, minimizado nem fechado pela IA;
2. em colisão, quem se muda é o **novo** — o que ele já estava lendo não sai do lugar; sem
   espaço, a ação é **recusada com motivo**, nunca empurrando nada;
3. componente que encosta na máquina dele **espera confirmação**, com o motivo que a IA deu;
4. **fechar não é apagar**: o módulo volta inteiro, com os dados que tinha;
5. **trocar de modo não destrói**: quem não cabe na composição nova é realocado ou minimizado.

### Os três modos

- **assistente**: núcleo grande no centro, poucos indicadores (relógio, tarefas, estado da
  máquina medido de `/proc`), conversa compacta embaixo, muito espaço livre;
- **pesquisa**: o núcleo encolhe para o canto, a faixa da consulta aparece e o conteúdo manda —
  fontes, resultados com mídia e análise, organizados por importância;
- **execução**: várias visões ao mesmo tempo (tarefas, código, console, artefatos, recursos),
  com maximizar e restaurar, e a distinção **visto × em execução × resultado** em cada item.

### O que é demonstração, e como não mentir sobre isso

Não há busca na web, navegador nem terminal ligados. O que preenche os modos 2 e 3 é um
**roteiro** (`RoteiroDeDemonstracao`) com conteúdo deste repositório, passando pelo mesmo
caminho que a IA vai passar — mesma leitura, mesma validação, mesma recusa. Todo módulo criado
a partir de componente de demonstração mostra o selo **DEMONSTRAÇÃO** na moldura. O que é real
e está ligado: o estado do laço de voz no núcleo, a transcrição, o PTT, o parar, o indicador de
microfone (F1-13), a configuração de provedores, o chaveiro e o diagnóstico.

### Consequências

- **Mais fácil:** a tela deixa de ser um formulário e passa a mostrar o que o Jarvis está
  fazendo; e trocar o roteiro pelo `s2` da F2 não muda uma linha da tela nem do gerente.
- **Mais caro:** QtQuick e QtQml entram no pacote (já vinham na roda), e a tela passa a ter um
  contrato a mais para manter — o vocabulário de ações.
- **Passa a ser obrigatório testar:** proposta malformada, componente fora do catálogo, campo
  que a tela executaria, colisão, módulo fixado, confirmação de componente sensível, fechar e
  recuperar, trocar de modo e restaurar o layout. Tudo sem janela; e a janela, por captura
  offscreen dos três modos e dos dois painéis.

### Como invalidar esta emenda

- O dono achar que o workspace atrapalha mais do que ajuda: o vocabulário continua valendo
  para uma tela fixa, porque quem decide layout é o gerente, não o QML.
- O QML custar caro demais no empacotamento (tamanho, tempo de carga): a medida está na
  ADR-0020, e trocar a camada visual não mexe nas quatro camadas de baixo.
