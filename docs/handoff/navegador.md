# Handoff — navegador controlado pelo Jarvis

## Objetivo

Entregar a decisão aceita na ADR-0027: extensão WebExtension própria distribuída com o produto,
ponte local por Native Messaging em `stdio` (sem porta de rede), ferramentas tipadas atrás do
PDP e, numa etapa posterior, entrada virtual para desktop. Todo texto, título, link, data e DOM
vindo de página é **DADO de terceiro** e contamina o turno; nunca é instrução nem autorização.

## Fatias feitas

### Fatia 1 — decisão da ADR

- Commit local `1ebed7d` — `docs: aceitar ADR de navegador controlável`.
- `docs/adr/0027-navegador-controlavel-por-extensao.md` está com estado **aceita em 2026-10-18**
  e o histórico registra a decisão do dono: extensão própria, Native Messaging por `stdio`, sem
  porta de rede, Firefox e Chromium no v1, e mouse/teclado virtuais onde DOM não for adequado.

### Fatia 2 — extensão MV3 e contratos estáticos

- Commit local `c3644b8` — `feat: adicionar extensão controlada do navegador`.
- `extensao/manifest.json`: MV3, Chrome/Chromium e Firefox, permissões mínimas
  `activeTab`, `tabs`, `nativeMessaging`; somente `http(s)`, sem `debugger`, sem acesso a
  `file:`, `about:` ou páginas internas.
- `extensao/background.js`: ponte somente por `runtime.connectNative`, lista/aba ativa,
  abrir/reutilizar/navegar e encaminhamento dos comandos DOM tipados. Não há `fetch`, servidor,
  WebSocket ou porta TCP.
- `extensao/content.js`: lê URL/título/texto visível/links e datas em `<time datetime>`; clica,
  digita, rola e inspeciona alvo. Rejeita senha, OTP e cartão como defesa adicional.
- `extensao/host/*.json`: templates de host para Chromium e Firefox, com IDs da extensão pinados
  e `type: stdio`.
- `extensao/README.md`: protocolo e caminhos Linux de instalação dos manifests de host.
- `tests/unit/navegador/test_extensao.py`: testes puramente estáticos; não iniciam navegador,
  host, rede nem dispositivo. A fatia de robustez abaixo acrescenta um teste comportamental isolado.

### Commits anteriores próximos na base

`45422ed` e anteriores já existiam antes deste trabalho; não são parte das duas fatias acima.
Não houve push, coautoria ou alteração fora dos arquivos dos dois commits.

### Fatia 3 — lado Jarvis (feita; commit logo abaixo no `git log`)

- `src/jarvis/navegador/`: `quadro.py` (quadro do Native Messaging, ordem nativa), `protocolo.py`
  (vocabulário fechado de 8 métodos, sem seletor CSS), `host.py` (host nativo: stdio de um lado,
  **socket Unix** `$XDG_RUNTIME_DIR/jarvis/navegador/<navegador>-<pid>.sock` do outro, pasta 0700,
  socket 0600, `SO_PEERCRED`; confere a origem da extensão), `cliente.py` (`ClienteDoNavegador` sobre
  `Transporte` injetável; `TransporteUnix` real), `risco.py` (regras de risco dinâmico),
  `ferramentas.py` (`CorposDoNavegador`: o corpo das tools).
- Fluxo real: o **navegador** lança o host (não o Jarvis); por isso o host é quem escuta e o Jarvis
  é o cliente, um pedido por conexão. O README da extensão foi corrigido (dizia o contrário).
- Catálogo: `browser.tabs`, `browser.read`, `browser.inspecionar`, `browser.tela` (livre, contaminam o
  turno; o mapa com `ref` e a tela como anexo, só com motor que `aceita_imagem`, ADR-0032);
  `page.readUrl` (sem tool própria) é a busca do `web.buscar` sem chave: aba de fundo, lida e fechada
  (`jarvis.navegador.busca`, ADR-0033), na janela própria do Jarvis (`janelaDoJarvis`, ADR-0036), que
  `browser.navigate` com `segundo_plano` também usa; `windows.focused` mostra o foco do dono; `browser.click`, `.type` (por `alvo` ou `ref`), `.acionar` (ADR-0032),
  `.scroll`, `.navigate` (moderado; o `aviso_falado` fica só na auditoria, `aviso_silencioso`,
  ADR-0031); `browser.acao_sensivel` (**perigoso**, só o
  código a consulta no PDP — fica fora de `_ligada`, o modelo nunca a vê). Stubs gerados.
- Risco dinâmico: antes de clicar/digitar o corpo chama `page.inspect` na MESMA aba (id resolvido por
  `tabs.current`) e aplica `risco.py`: enviar formulário (exceto busca GET), palavras de envio/
  pagamento/apagar/login, e qualquer clique ou texto em banco/mensageiro/e-mail/senha/pagamento →
  `exigir` (segundo pedido ao PDP, tier perigoso, janela de confirmação, auditado). Senha, código
  e cartão (campo sensível, rótulo, Luhn) → **recusa sem pergunta** (handoff ao dono).
  Turno contaminado: digitar, link para outro site e navegar para site não liberado pedem o sim.
  Ler banco/senha/pagamento também pede o sim (ADR-0027 regra 2); ler mensageiro/e-mail é livre.
- Extensão ajustada na fatia 3 (era bug da fatia 2): `page.type` usava `texto` tanto como alvo quanto
  como conteúdo; agora o alvo é `alvo` (texto/rótulo visível, aria-label, placeholder, `<label>`,
  `title`); o seletor CSS foi removido; `page.inspect` devolve método/busca/formulário sensível/
  destino do link; novo `tabs.current`.
- Compartilhados tocados (diffs estreitos): `executor/ferramentas.py` (import, `FONTES_DE_TERCEIROS`
  +2, campo `navegador`, `_ligada`, `_rodar` ganha `confirmar`, `_navegador`),
  `tests/unit/politica/test_tiers.py` (7 tools nos dois dicionários), `catalogo/` (7 YAMLs) e
  `capacidades/` (7 stubs). Nada em `politica/`.
- A **ligação** do `CorposDoNavegador` ao executor real (quem instancia `ClienteDoNavegador(
  TransporteUnix())` e passa em `ExecutorDeFerramentas(navegador=...)`) ainda não existe: depende de
  `voz/app.py`/`s2` (fora do meu escopo). Sem isso as `browser.*` não aparecem para o modelo.
- Limites conhecidos: o `inspect` e o efeito são duas chamadas (a página pode mudar no meio); alvo só
  por texto visível (elemento sem texto/rótulo não é alcançável); com dois navegadores abertos o
  cliente usa o socket mais recente (`ClienteDoNavegador.navegador` fixa `firefox`/`chromium`).

## Fatia 4 — mouse e teclado virtuais (feita)

- `src/jarvis/entrada/`: `teclas.py` (tabelas fechadas), `porta.py` (`BackendDeEntrada`),
  `portal_remoto.py` (portal `RemoteDesktop`, jeepney), `uinput.py` (reserva, stdlib), `escolha.py`
  (Wayland: portal → uinput; X11: uinput → portal), `foco.py` (kdotool/xprop + classificação),
  `limite.py` (taxa 40/min e `Interruptor`), `controle.py` (a ordem das travas).
- Catálogo: `input.mouse.move`, `input.mouse.click`, `input.key.type`, `input.key.press` (moderado)
  e `input.acao_sensivel` (perigoso, só o código consulta). Fontes, licenças e regras na emenda da
  ADR-0027 (2026-10-18). Config nova do dono: `entrada_virtual` e `entrada_uinput` (padrão: desligadas).
- Compartilhados tocados: `executor/ferramentas.py` (campo `entrada`, `_ligada`, despacho,
  `_exigir_do_dono` — o fecho da confirmação que o navegador já usava virou método comum),
  `executor/comandos.py` (+`kdotool`, +`xprop` na lista de programas), `voz/app.py` e `voz/config.py`
  (flags, `interruptor_de_entrada`, controle guardado entre remontagens), `test_tiers.py`.
- **Decisão a revisar com o dono:** foco desconhecido é *recusa*, não pergunta (ver emenda). Em
  KDE/Wayland sem `kdotool` a entrada virtual fica inerte e a frase diz o que instalar.
- **Pendente (fora do meu escopo):** botão «parar entrada virtual» na janela (`Aplicativo.
  interruptor_de_entrada.parar()` / `.liberar()` já existem) e a tela de configuração das duas
  flags; atalho global de parada.

## Fatia 5 — release e manual (retomada em 2026-10-18)

### Estado recebido da sessão anterior

- Escopo: levar `extensao/` e o executável `jarvis-native-host` aos três formatos de release;
  instalar manifests Linux de Native Messaging com `path` absoluto para Chromium/Chrome e
  Firefox; documentar ativação, instalação, consentimento do portal e PARADA; provar tudo apenas
  com testes e artefatos em diretório temporário, sem instalar nada no sistema.
- Commits anteriores já concluídos e preservados: `c3644b8` (extensão), `f6d6bec` (lado Jarvis),
  `218e4c0` (ligação configurável) e `1fc6450` (mouse/teclado virtual). A decisão da ADR veio antes,
  em `1ebed7d`.
- Alterações sem commit recebidas e ainda sob auditoria: `docs/COMO-TESTAR.md`,
  `src/jarvis/navegador/host.py`, `tools/empacotar.py`; novos
  `src/jarvis/navegador/instalar.py`, `tests/unit/navegador/test_empacotar_host.py` e
  `tests/unit/navegador/test_instalar.py`. Este próprio handoff passa a integrar a fatia.
- Direção já implementada no diff parcial: `extensao/` entrou em `DADOS`; há lançador isolado do
  host e modo `--native-host` no AppRun; `.deb`/`.rpm` ganham manifests de sistema gerados a partir
  dos modelos; AppImage ganha instalação por usuário com stub de caminho estável; o manual já tem
  um roteiro de página local e declara limites de verificação real.
- Validações ainda pendentes neste ponto: revisar integralmente os diffs e os caminhos de cada
  formato; executar os testes novos e os relevantes do navegador; `ruff`, `mypy`, `node --check` e
  `git diff --check`; gerar AppImage, `.deb` e `.rpm` somente sob diretório temporário e inspecionar
  conteúdo, manifests e bits executáveis sem instalar.
- Limite de verificação: navegador real, portal `RemoteDesktop` real e `/dev/uinput` real **não**
  serão usados; instalação real dos pacotes e `tools/empacotar.py verificar` (que instala em
  contêiner) também ficam fora. Só são autorizadas provas unitárias, estáticas e inspeção dos
  artefatos gerados em diretório temporário.

### Resultado concluído

- `tools/empacotar.py` monta `extensao/` no AppDir, cria o executável isolado
  `usr/bin/jarvis-native-host`, oferece `AppRun --native-host` no AppImage e gera manifests com
  `path: /usr/bin/jarvis-native-host` para Chrome, Chromium e Firefox. O `.rpm` leva as duas
  alternativas oficiais do Firefox (`/usr/lib/mozilla` e `/usr/lib64/mozilla`); o `.deb` leva
  `/usr/lib/mozilla`.
- `jarvis.navegador.instalar` valida os modelos, recusa caminho relativo, instala/remove somente o
  manifesto do Jarvis nos diretórios por usuário e, no AppImage, cria um stub estável e copia a
  extensão para `~/.local/share/jarvis/`. `host.main()` encaminha apenas `--instalar`/`--remover`;
  argumentos normais do navegador continuam no protocolo do host.
- `docs/COMO-TESTAR.md` explica as flags desligadas por padrão, host/extensão nos três formatos,
  carregamento manual em Chromium/Chrome e Firefox, prova numa página local, consentimento do
  portal, PARADA e liberação, reserva `uinput` e remoção.
- Artefatos gerados somente em `/tmp/jarvis-fatia5.92NJgx`: AppImage 360,1 MB, `.deb` 407,6 MB e
  `.rpm` 420,4 MB. O AppImage foi extraído; `.deb` e `.rpm` foram listados/lidos sem instalação.
  Foram conferidos extensão, host executável, caminhos e conteúdo dos manifests. O host dentro do
  AppImage devolveu 2 para origem inválida e 0 para a origem Chromium autorizada com `stdin` já
  fechado, usando apenas runtime/socket temporários.
- Verificações verdes: testes focados de instalador/empacotador/host; suíte de navegador, entrada,
  executor, tiers e ligação ao app; `ruff format --check`, `ruff check`, `mypy`, `node --check` e
  verificações de diff. Nenhum pacote foi instalado.
- Limites finais explícitos: navegador real, portal `RemoteDesktop` real e `/dev/uinput` real
  **NÃO foram verificados ao vivo**; pacotes também não foram instalados e a verificação em
  contêiner não foi rodada. O commit local único desta fatia usa o assunto
  `Navegador controlável: empacotar extensão e host nativo (fatia 5)`; não houve push.

### Regras que permanecem

- Manter a chave privada de assinatura da extensão fora do repositório e do artefato. A chave
  pública em `extensao/manifest.json` apenas fixa o ID Chromium.
- Não usar navegador real nos testes automatizados nem perfil/tela do dono.
- Preservar `browser.*` desligadas por padrão, confirmações de ação sensível e bloqueio absoluto
  de senha/cartão.

## Decisões e armadilhas

- A ordem de atuação da SPEC §5.4 é obrigatória: API > protocolo > acessibilidade > DOM isolado
  > tela/coordenadas. DOM não é `eval`; não criar `browser.eval`, CDP exposto, seletor livre sem
  limite ou comando genérico.
- A extensão deliberadamente não usa `chrome.debugger`: nesta decisão, ação de DOM equivale a
  clicar o elemento. Quando o site proibir isso, a solução é a entrada virtual da fatia 4.
- O protocolo da extensão já oferece `page.inspect` para o Jarvis decidir risco antes do efeito.
  Não remova esse comando interno; ele é necessário para detectar submit/campo sensível.
- O ID Chromium é `eainnehpangdlhmjenljnbfkjjeckoli`; o ID Firefox é
  `jarvis-browser@granafacil.local`. Os manifests de host aceitam somente esses IDs.
- A chave em `manifest.json` é pública. A chave privada usada para derivá-la não foi adicionada
  ao repositório nem deve ser recuperada de `/tmp`; a distribuição assinada precisará de material
  de assinatura gerenciado pelo dono. Para desenvolvimento, o carregamento descompactado usa a
  chave pública para manter o ID estável.
- O serviço worker MV3 pode dormir. Estado de pedido, cancelamento e política devem morar no
  Jarvis/host, não na extensão.
- A árvore está suja por trabalho externo. Nesta retomada, não tocar nem incluir no commit
  `.claude/orchestrator-rules.md` nem `.orchestrator/`. `docs/COMO-TESTAR.md` agora pertence
  explicitamente à fatia 5; qualquer outro arquivo fora da lista de alterações recebidas acima
  continua fora do escopo.
- Arquivos compartilhados que este trabalho tocou: ver a fatia 3 acima. As próximas podem tocar `catalogo/`, `capacidades/`, `executor/` e talvez `politica/`;
  faça diffs estreitos, avise no ping e nunca use `git add -A`.

## Correção de robustez — reconexão do host nativo (2026-10-19)

- Decisão final do dono: a arquitetura da fatia 3 permanece. A extensão chama `connectNative`, o
  navegador lança o host e esse host possui o socket Unix mesmo com o Jarvis fechado. O Jarvis
  apenas entra como cliente ao abrir; ele nunca lança nem possui o host/socket.
- `extensao/background.js` agora reage a `onDisconnect` com uma única tentativa pendente por vez.
  O backoff tem base de 250 ms, dobra com jitter de 15% e para de crescer em 30 s. Há no máximo uma
  porta e um timer; não foram adicionados alarm, heartbeat ou mensagem para manter o service worker
  vivo. Tráfego recebido ou uma conexão de 60 s reinicia o atraso.
- A mensagem real de `runtime.lastError` é capturada dentro de `onDisconnect` e registrada com o
  número da tentativa e o atraso. Respostas assíncronas ficam presas à porta que recebeu o pedido,
  portanto uma resposta atrasada nunca é enviada por uma porta nova.
- A validação de origem continua no host, o vocabulário/protocolo da extensão não mudou e todas as
  confirmações, contaminação por terceiros e decisões do PDP permanecem no Jarvis.
- `background_reconexao.test.mjs` carrega o service worker real em uma VM com `Port`, relógio e
  timers falsos. Ele cobre exclusividade de porta/timer, falha síncrona, motivo de desconexão,
  backoff, jitter, teto e recuperação. `test_extensao.py` o integra à suíte quando Node.js existe.
- Referência: documentação oficial do Chrome sobre
  [`connectNative`](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
  e [ciclo do service worker](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).
- Não houve ensaio em navegador real nem geração de artefato nesta correção. O próximo teste do dono
  precisa de um AppImage novo, gerado em diretório novo; não reutilizar o artefato anterior.

## Ponte de ponta a ponta — por que o Jarvis negava a extensão (2026-10-19)

Sintoma do dono (`uv run jarvis`): perguntado sobre a extensão, o Jarvis dizia não ter `browser.*`.
Cinco causas, todas reproduzidas (as duas da extensão num Chromium 155 e num Firefox 158 reais):

1. `navegador_controlado = false` no `jarvis-voz.toml` do dono → `_corpos_do_navegador` devolve
   `None` → `_ligada` tira as `browser.*` do catálogo C0 → o prompt não as lista → o modelo nega.
   Não havia chave na janela. Agora: Acesso → Navegadores → «deixar o Jarvis controlar as abas»
   (`PonteDeAcesso.definirNavegadorControlado`, grava e chama `atualizar_acesso`), e a tool livre
   `browser.estado` existe **sempre** (`jarvis.navegador.estado`): desligado / sem_conexao /
   conectado, e o que fazer, sem falar com a extensão (conecta no socket e solta).
2. O principal do dono é o Brave (rpm). O instalador gravava só Firefox, Chrome e Chromium; nos
   derivados do Chromium o manifesto do usuário mora em `<pasta de dados>/NativeMessagingHosts`
   (conferido: o headless usa `~/.config/chromium-headless/scoped_dir*`). Agora: Brave, Edge e
   Vivaldi também. Firefox e Chromium do dono são Flatpak: não há Native Messaging lá.
3. Repositório sem release não tinha comando: `jarvis-native-host` não era script do projeto.
   Agora `uv run jarvis-native-host --instalar` faz o mesmo que o AppImage, com o stub chamando
   `.venv/bin/python -I -m jarvis.navegador.host`. A extensão carregada no Brave do dono era a cópia
   do AppImage de 18/10 (antes da reconexão): o `--instalar` refaz a cópia; o dono clica «Recarregar».
4. `background.js` repassava a resposta do conteúdo sem desembrulhar: o host recebia
   `{ok, result: {ok, result}}`. `browser.read` via texto vazio, `browser.type` dizia «não é campo»
   sempre, e o risco do clique ficava cego (sem `enviaFormulario`): **botão de envio era clicado
   sem pedir o sim**. Teste: `background_respostas.test.mjs` (4 de 5 falham no `background.js`
   antigo).
5. `manifest.json` só tinha `background.service_worker`: o Firefox recusa instalar. Agora também
   `background.scripts` (o Chromium ≥ 121 o ignora).

Também: o transporte das `browser.*` passou a usar o `XDG_RUNTIME_DIR` do `ambiente` do app (antes
o `os.environ` real — um teste falaria com o navegador do dono); `atualizar_acesso` mantém memória,
tarefas, agenda, desfazer e contaminação (antes sumiam até reiniciar); e a pergunta por ação
(`Confirmacao.por_acao`) não é mais respondida pelo «sim» de uso único do portão.

Prova em navegador real: `uv run --frozen python -m tools.harness_navegador` (podman,
`--network none`, `--userns=keep-id`, repositório e Python do uv só leitura). Armadilhas do roteiro:
o Chromium ≥ 137 ignora `--load-extension` sem
`--disable-features=DisableLoadExtensionCommandLineSwitch`; o `--user-data-dir` tem de ir
explícito; o Firefox instala extensão temporária pelo Marionette (`Addon:Install`); e a URL da
linha de comando do Chromium às vezes carrega antes do conteúdo da extensão (o roteiro navega de
novo com `browser.navigate` antes de ler — é o mesmo caso da aba aberta antes da extensão).

## Auditoria da integração — o caso «abra um vídeo no YouTube» (2026-10-21)

Sintoma do dono: pediu «abra um vídeo no YouTube»; o Jarvis usou a extensão, o navegador dele
«continuou igual» e a resposta parou depois do primeiro comando. Evidência: a trilha dele (só
metadados, `~/.local/state/jarvis/voz/diagnostico/turnos.jsonl`, turno das 01:33 de 21/10) tem
método `navegador`/`cita_site`, uma `browser.navigate` só com `url`, `ok` em 25,7 ms, e o turno
`concluido` com a fala cortada; a sonda em contêiner mostrou o resto. Achados, causa → onde (HEAD
9a4198a) → conserto:

1. **Navegar dizia ok sem conferir nada.** `tabs.navigate` devolvia o `tabs.update`, que responde na
   hora com a URL e o título **de antes** (Chromium 155 e Firefox 158); sem rede, a aba virava a
   página de erro e a ferramenta seguia `ok` — `extensao/background.js:327-335` e
   `src/jarvis/navegador/ferramentas.py:379-386`. Conserto: `navegarEConferir`/`criarEConferir` no
   fundo (a aba sai do lugar, termina, e o conteúdo responde `estado` na página nova) e `_conferido`
   nas `browser.*`: erro `aba_nao_mudou` / `pagina_nao_abriu` com frase de gente, URL da página
   nova.
2. **Nada punha o resultado à vista.** Desde a ADR-0036 navegar não traz a aba para a frente, e com
   o dono falando com o app do Jarvis o navegador fica atrás: a aba mudava e ele não via. Conserto:
   `quer_ver` (fala do dono, `politica/metodo.py`) + `tabs.show`: pedido de ver termina com a aba
   ativa e a janela em foco; o resultado diz `visivel` (e não finge se o sistema negar o foco).
3. **Trabalho de leitura trocava a página da aba do dono, e ler depois de abrir no fundo lia a aba
   errada.** `ferramentas.py:369` navegava a aba atual do dono; `_aba(args)` sem `tab_id` era sempre
   a aba do dono à frente. Conserto: sem pedido de ver, a navegação vai à janela do Jarvis; a **aba
   de trabalho** do objetivo (`Trabalho`, por objetivo do turno ou da tarefa) é o alvo das
   `browser.*` sem `tab_id`.
4. **A "aba atual" podia ser de popup, app, DevTools ou da janela do Jarvis.** `abaAtiva()`
   (`background.js:70-85`) usava `currentWindow` (no service worker, a última janela em foco, de
   qualquer tipo) e só sabia qual era a janela do Jarvis pela memória do worker — que dorme e
   reinicia; a janela `about:blank` não se reconhecia e uma segunda era criada. Conserto:
   `janelaDoDono()` só com janelas `normal`; a janela do Jarvis segura `janela.html` e
   `idDaJanelaDoJarvis()` a reconhece depois de reiniciar.
5. **Aba nova do dono nascia na "janela atual" do navegador** (podia ser a do Jarvis), e o ramo
   `reutilizar` de `tabs.open` era código morto (o protocolo nunca o manda) —
   `background.js:294-309`. Conserto: `abrirAba` cria na janela do dono pelo id; o reuso de abas é a
   parte 2.
6. **Roteador:** «toca um vídeo no YouTube» / «põe uma música no youtube» caíam em `pedido_misto`
   pelas palavras de mídia (`metodo.py:58-62`), sem método nem critério. Conserto: com site citado,
   a mídia sozinha não faz pedido misto. «abra um vídeo no YouTube» já ia certo (`navegador`).
7. **«Parou depois do primeiro comando»:** é o laço do cérebro (o modelo chamou uma ferramenta e
   respondeu); está com outra frente (conferir antes de dizer «abri»). Daqui: a ferramenta não
   devolve mais um `ok` falso, e o resultado diz onde a página ficou e se está à vista.
8. **Commits recentes (eed7e35, f6fd1b1, 53d4abb, 9a4198a, Lotes B e C):** o roteiro em contêiner
   deu 25/25 no Chromium 155 e no Firefox 158 no HEAD 9a4198a (instalar no modo repositório,
   manifesto, host lançado pelo navegador, reconexão depois de SIGTERM, 40 s ocioso, chave
   `navegador_controlado` → as `browser.*` no prompt). Nada quebrado na ponte.

O que o dono faz (não rodamos nada na máquina dele): `uv run jarvis-native-host --instalar` no
repositório (copia a extensão nova, com `janela.html`), **Recarregar** a extensão em
`brave://extensions`, F5 nas abas que já estavam abertas e reiniciar o `uv run jarvis`.

Testes: `background_navegacao.test.mjs` (navegador falso com janelas, abas e eventos; 11 dos testes
novos falham no `background.js` do HEAD), `test_ferramentas_browser.py` (6 novos, todos falham no
HEAD), `test_metodo.py` e o roteiro em contêiner (4 conferências novas).

## Indicador «no controle», PARAR e reuso de abas (2026-10-21, ADR-0027 regra 4)

Pedido do dono: o item 4 da ADR-0027 (que estava registrado como "não foi feito") e o reuso de
abas. Onde mora cada peça:

- **Concessão por objetivo** — `src/jarvis/navegador/controle.py` (`ControleDoNavegador`): cada
  objetivo (turno ou tarefa, o mesmo `Objetivo` da ADR-0030 C2/ADR-0038) ganha um id aleatório que
  vai em todo pedido que lê ou mexe numa aba (`ClienteDoNavegador.sob(concessao)`, por linha — nada
  de atributo disputado entre o turno e as tarefas). Uma **vigia** (linha que só vive enquanto há
  concessão) solta quando o objetivo chega à fase de concluir, solta o que ficou 45 s parado, renova
  com `controle.manter` a cada 10 s, assina os eventos do host e, no fim de um pedido de ver que
  terminou fora da vista (janela do Jarvis, aba de trás), põe a página à vista (`tabs.show`).
- **Extensão** — `extensao/background.js` (registro das abas no controle, selo, `controle.*`,
  revogação, evento `parar` ao host, botão da barra), `extensao/indicador.js` (a faixa, shadow DOM
  fechado, `document_start`, re-anexa até 20 vezes se a página a arrancar, clique só com
  `isTrusted`; confere com o fundo a cada 4 s e some se a extensão foi recarregada),
  `extensao/content.js` (só responde mensagem com `comando`). Sem permissão nova; o manifesto ganhou
  `action` (sem popup) e o segundo script de conteúdo.
- **Host** — `src/jarvis/navegador/host.py`: quadro da extensão com `evento` é validado
  (`protocolo.validar_evento`: só `parar`, concessões no formato, origem `faixa`|`barra`) e escrito
  em quem assinou (`eventos.assinar`, atendido pelo próprio host, até 4 assinantes); o navegador
  que fecha acorda quem espera. `cliente.AssinaturaUnix` lê os quadros à mão com `select` (tempo
  esgotado no meio de um quadro bufferizado embaralharia o fluxo).
- **App e janela** — `voz/app.py`: `_ligar_o_controle` (o navegador do executor e o de outra
  família, para `sites.open`), `_parar_pelo_navegador` (cancela as tarefas daquele objetivo; turno
  no ar → `interromper`, o epoch de sempre), `parar_navegador` (o botão da janela),
  `ao_mudar_navegador` (só depois que a extensão aceitou um pedido da concessão:
  `ControleDoNavegador.confirmar`); `gui/nucleo.py` (`parar_navegador` numa linha à parte),
  `gui/ponte.py` (`navegadorNoControle`, `pararNavegador`), `BarraDeConversa.qml` (botão «parar o
  navegador», só com aba no controle).
- **Reuso** — `navegador/ferramentas.py` (`_aba_para_ver`, `_ja_aberta`, `abrir_site`): pedido de
  ver sem `tab_id` → a aba já na URL só é ativada; a do mesmo site (host sem `www.`, com a porta) é
  navegada; senão a atual. Banco/senha/pagamento/mensageiro/e-mail: a aba do dono não tem a página
  trocada. `browser.tabs` diz janela (1, 2…) e estado. `sites.open` vai por `abrir_site` (o app
  delega em `_na_aba_atual`): conferido, à vista, e `NavegadorIndisponivel` ainda cai para abrir o
  navegador com a URL.

**Armadilha medida no roteiro:** IP e `localhost` não têm domínio registrável, então nunca entram
no objetivo; num turno que já leu a página, navegar para outro endereço do site de teste pede o sim
(ADR-0030, conservador para endereço local). O roteiro diz sim nesse passo; em site público isso
não acontece (o domínio entra em "alcançados").

**Provas:** `tests/unit/navegador/background_controle.test.mjs` (11), `indicador.test.mjs` (6, DOM
falso), `test_controle.py` (9), `test_host.py` (+5), `test_quadro_e_protocolo.py` (+2),
`test_ferramentas_browser.py` (+10), `test_ligacao_ao_app.py` (+3),
`tests/unit/gui/test_parar_navegador_na_janela.py` e o roteiro em contêiner (5 conferências
novas: a faixa em toda página da aba controlada, medida pela própria página; PARAR com clique de
verdade — `Input` do CDP no Chromium, ações do Marionette no Firefox —; 3 casos de reuso).

O que o dono faz: `uv run jarvis-native-host --instalar` no repositório (copia `indicador.js`),
**Recarregar** a extensão em `brave://extensions`, F5 nas abas que já estavam abertas (a faixa só
aparece em página carregada depois da extensão nova) e reiniciar o `uv run jarvis`.

## Uma instância só (2026-10-21, ADR-0036 emenda (2))

Relato do dono depois de testar o `8cc7bf6`: o Jarvis começou no Brave dele, depois **abriu outra
instância** (a janela própria do Jarvis) e o vídeo abriu **nela**. Regras novas: só abrir navegador
sem um ativo; havendo, guia nova na janela dele (ou o reuso de sempre); trabalho de fundo em aba de
segundo plano da janela dele; janela própria só num modo `automacao_social`, desligado. Causa, pela
trilha dele (21/10 15:30–15:32, só metadados): o `web.buscar` sem chave (`page.readUrl`) criou a
janela do Jarvis; depois o modelo mandou um `tab_id` velho, ouviu "falha" crua e caiu num
`sites.open` com `nova_aba`, que **pulava a extensão** e executava `/usr/bin/brave-browser-stable
<url>` (o principal dele é o `brave-browser.desktop`) — o Brave aberto pôs a URL na última janela
ativa dele, a do Jarvis (no Wayland do KDE o navegador não pega o foco de volta).

Onde mora cada peça:

- **Extensão** — `extensao/background.js`: `MODO_AUTOMACAO_SOCIAL`; `abrirAba` (`fundo` → aba na
  janela do dono com `active: false`; `modo` → janela do Jarvis), `lerEmSegundoPlano` (a busca numa
  aba de fundo da janela do dono; a janela própria só no modo), `abaDoPedido` (aba que não existe
  mais → `sem_aba`, dito), `focoAtual` (`janelas`). `janela.html` diz que a janela é da automação
  social e que pode fechar.
- **Protocolo e cliente** — `navegador/protocolo.py`: `tabs.open` aceita `fundo` e `modo`,
  `page.readUrl` aceita `modo`, `MODOS = {"automacao_social"}`; o parâmetro `janela` saiu.
  `navegador/cliente.py`: `ClienteDoNavegador.automacao_social` (o gancho, desligado, copiado no
  `sob`) — sem ele `abrir(segundo_plano=True)` manda `fundo` e nada manda `modo`.
- **Corpos** — `navegador/ferramentas.py`: `Trabalho.abertas` (as abas que o pedido abriu);
  `_navegar` (fundo também com `nova_aba`; o passo de fundo de um pedido de ver só vem à frente no
  fim, pelo `_mostrar_no_fim`); `_aba_para_ver` (mesma URL → só ativa; mesmo site → navega; a guia
  do próprio pedido ou a «nova aba» vazia → navega; senão `None` → **guia nova**); `_aba_de_fundo`
  (só a aba que o pedido abriu e que continua em segundo plano); `mostrar_o_navegador` (sem
  concessão, sem faixa); o resultado diz `segundo_plano`.
- **Abrir navegador** — `executor/navegadores.py`: `ReutilizarAba(url, familia, nova_aba)` devolve
  o resultado da extensão ou `None`; `abrir` vai pela extensão sempre que ela atende (também com
  `nova_aba`); `ja_aberto(familia)` (mostra pela extensão; sem ela, processo rodando em
  `/proc/<pid>/exe` conta; aberto sem janela → `None`, lança) e `abrir_sozinho` →
  `NavegadorAberto`; `navegador_em_execucao`, `EXECUTAVEIS_DA_FAMILIA`, `familia_de_navegador`.
  `executor/ferramentas.py`: `browser.launch` devolve `ja_aberto`/`visivel`, e o `apps.launch` de um
  app que é navegador (configurado ou só liberado) traz a janela se ele já está aberto — fechado,
  abre como qualquer app, com o foco acompanhado. `voz/app.py`: `_controle_da_familia`,
  `_na_aba_atual(..., nova_aba)`, `_mostrar_o_navegador` e `em_execucao=navegador_em_execucao` no
  abridor. `politica/metodo.py`: só a nota do `abre_o_navegador` (o `apps.launch` fica — o
  `cc119e8` o tirava e o ajuste desfez: o Brave liberado só como app não teria como abrir).
  Catálogo: `browser.navigate`, `sites.open`, `browser.launch` (texto e pós-condição) e os stubs.

Armadilhas medidas:

- Para contar instâncias em `/proc`, a linha de comando dos filhos não serve: o Chromium (e parte
  dos do Firefox) a reescreve sem os separadores NUL. O processo principal é o do navegador cujo
  pai não é do navegador (medido no contêiner: uma raiz só, nos dois).
- A tela (`page.capture`) de uma aba de fundo é `aba_escondida` no Chromium (a captura dele é da
  aba à vista); o Firefox captura qualquer uma. Leitura e mapa valem nas duas.
- Extensão e host vão juntos: o host de antes recusa `fundo`/`modo` («parâmetro fora do contrato»)
  e a extensão de antes ignora `fundo`. Recarregar a extensão reinicia o host.
- O app liga a leitura de `/proc` (`em_execucao=navegador_em_execucao`): teste que monta o app
  inteiro e pede «abre o brave» vê o navegador de verdade da máquina do dono — o
  `test_janela_abrir_apps.py` troca o `navegador_em_execucao` do `voz.app` por um que não acha
  nada; os do executor injetam `em_execucao`.

O que o dono faz (nada rodou na máquina dele): `uv run jarvis-native-host --instalar` no
repositório, **Recarregar** em `brave://extensions`, fechar a janela de trabalho do Jarvis que ficou
aberta (a da `janela.html`), F5 nas abas abertas e reiniciar o `uv run jarvis`.

Provas: `background_navegacao.test.mjs` (a busca e a aba de fundo na janela do dono sem `active`,
nenhum pedido cria janela sem o modo, `sem_aba`, o modo social), `test_extensao.py` (um
`windows.create` só, alcançável só pelo modo), `test_ferramentas_browser.py`,
`test_quadro_e_protocolo.py`, `test_ligacao_ao_app.py` (o app inteiro com o host de verdade: guia
nova pela extensão, `browser.launch` sem lançar), `tests/unit/executor/test_navegadores.py` e
`test_ferramentas.py` (o caso do `nova_aba`, o processo em `/proc`, «sem navegador ativo abre um»,
o `apps.launch`), `test_metodo.py`; os novos falham no código de antes. E o roteiro em contêiner,
41/41 no Chromium 155 e no Firefox 158 — com uma prévia em que o próprio Jarvis abre o navegador de
verdade quando não há um. O mesmo roteiro no código de antes (`src/`, `extensao/` e `catalogo/` do
`6ed4134` montados por cima, só leitura, num contêiner) reproduz o bug: 2 janelas depois da busca
(com a do Jarvis e a `janela.html`), o `sites.open` com `nova_aba` executando
`/usr/bin/chromium-browser <url>` / `/usr/bin/firefox <url>`, e o `browser.launch` lançando de novo
com o navegador aberto (Chromium 32/41, Firefox 33/41).

**Não provado:** o Brave e o KWin/Wayland de verdade; o YouTube de verdade; a janela do Jarvis que
ficou aberta no Brave do dono (não é fechada sozinha: pode ter uma aba dele). **Não feito:** a
automação social com digitação humanizada (só o gancho), um grupo de abas «Jarvis».

## Verificações já verdes

Os comandos abaixo passaram para a fatia 2, sem navegador ou dispositivo real:

```bash
node --check extensao/background.js
node --check extensao/content.js
uv run --frozen pytest tests/unit/navegador/test_extensao.py -q
uv run --frozen ruff format --check tests/unit/navegador/test_extensao.py
uv run --frozen ruff check tests/unit/navegador/test_extensao.py
MYPY_CACHE_DIR=/tmp/mypy-navegador uv run --frozen mypy tests/unit/navegador/test_extensao.py
```

O sandbox desta sessão pode recusar a criação do cache em `~/.cache/uv`; quando isso acontecer,
peça a permissão pontual para o `uv`, não altere o comando nem desative `--frozen`.

Antes de cada novo commit: `git diff --check`, `git add -- <somente arquivos próprios>`,
`git diff --cached --stat`, `git diff --cached --check`, `git commit -m ...`; sem `stash`,
`checkout`, `restore`, `reset`, `rebase`, coautoria ou push. Ao terminar cada fatia, chamar
`cli_ping` com commit, compartilhados tocados e verificações não executadas.

## Continua em `velocidade-e-foco.md` (2026-10-21)

A busca sem chave **não** usa mais a aba de fundo (`jarvis.navegador.busca` saiu): busca genérica
vai direto pelo DuckDuckGo; pedido de site começa no navegador do dono pelo caminho rápido (a busca
do próprio site). `browser.navigate` com id de aba que não existe mais vai para a URL. O Brave aberto
vem para a frente pelo KWin quando a extensão não consegue. Detalhes, commits e armadilhas lá.
