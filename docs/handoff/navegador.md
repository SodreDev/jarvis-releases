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
  host, rede nem dispositivo.

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
- Catálogo: `browser.tabs`, `browser.read` (livre, contaminam o turno); `browser.click`, `.type`,
  `.scroll`, `.navigate` (moderado, com `aviso_falado`); `browser.acao_sensivel` (**perigoso**, só o
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

## Falta na fatia 4 — mouse e teclado virtuais

1. Pesquisar **fontes oficiais** antes de escolher a implementação para Fedora KDE Wayland e X11.
2. Criar `src/jarvis/entrada/` com porta injetável e fakes.
3. Decisão de implementação a verificar e registrar:
   - padrão Wayland: `xdg-desktop-portal` `org.freedesktop.portal.RemoteDesktop`, pois a sessão
     tem consentimento explícito, é revogável e o compositor controla a permissão;
   - fallback: `uinput`/`evdev`, isolado e permitido somente com a configuração/ACL explícita do
     dono; para X11, preferir a via controlada disponível e não elevar privilégio para contornar
     o compositor;
   - justificar a licença de cada biblioteca. Não colocar GPL no caminho distribuído; se algo GPL
     for indispensável, isolá-lo em processo separado e declará-lo.
4. Implementar `input.mouse.move`, `input.mouse.click`, `input.key.type`, `input.key.press`:
   - tier moderado por padrão, limite de taxa e interruptor global de parada;
   - antes do efeito, verificar janela em foco; gerenciador de senhas, terminal e banco tornam a
     ação perigosa e confirmada por ação;
   - testes somente com fakes, nunca `uinput`, portal, tela, mouse ou teclado reais do dono.

## Falta na fatia 5 — release e manual

1. Alterar `tools/empacotar.py` sem quebrar AppImage, `.deb` ou `.rpm`:
   - incluir `extensao/` e os manifests de host na árvore do release;
   - instalar/criar o lançador absoluto `jarvis-native-host` e substituir o marcador de `path`;
   - manter a chave privada de assinatura da extensão fora do repositório e do artefato. A chave
     pública em `extensao/manifest.json` apenas fixa o ID Chromium.
2. Acrescentar a `docs/COMO-TESTAR.md` o procedimento de instalação e prova:
   - carregar extensão no Chromium/Chrome e no Firefox;
   - instalar o manifesto nativo no caminho Linux correto;
   - testar lista/leitura/clique/digitação/rolagem em página local segura;
   - demonstrar que não há porta de rede e que senha/pagamento pedem handoff/confirmação;
   - documentar remoção/revogação do host/extensão.
3. Não usar navegador real nos testes automatizados. Se houver prova headless inevitável, apenas
   em Podman com `--name` e `--timeout`, nunca no perfil ou tela do dono.

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
- A árvore está suja por trabalho alheio. No momento deste handoff, não tocar nem incluir no
  commit mudanças em `.claude/`, `catalogo/sites.open.yaml`, `docs/COMO-TESTAR.md`,
  `src/jarvis/capacidades/sites_open.py`, `src/jarvis/executor/`, `src/jarvis/s2/`,
  `src/jarvis/voz/`, seus testes relacionados e `catalogo/web.canal_videos.yaml`. Especialmente,
  a ordem proíbe tocar `src/jarvis/s2/`, cérebro e tarefas.
- Arquivos compartilhados que este trabalho tocou: ver a fatia 3 acima. As próximas podem tocar `catalogo/`, `capacidades/`, `executor/` e talvez `politica/`;
  faça diffs estreitos, avise no ping e nunca use `git add -A`.

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
