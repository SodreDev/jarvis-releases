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
  turno; o mapa com `ref` e a tela como anexo, só com motor que `aceita_imagem`, ADR-0032); `browser.click`, `.type` (por `alvo` ou `ref`), `.acionar` (ADR-0032),
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
