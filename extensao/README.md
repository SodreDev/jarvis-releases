# Extensão de navegador do Jarvis

Esta é uma WebExtension MV3 sem dependências de terceiros. Ela não abre servidor, porta TCP,
WebSocket ou HTTP próprio. A única ponte é Native Messaging: o navegador lança o host local
registrado e troca mensagens JSON enquadradas por `stdin`/`stdout`.

O host só aceita a extensão identificada no manifesto correspondente. No Chromium, a chave
pública em `manifest.json` fixa o identificador em
`eainnehpangdlhmjenljnbfkjjeckoli`; a chave privada **não** está no repositório nem no release.
No Firefox, o ID é `jarvis-browser@granafacil.local`.

## Protocolo da ponte

O navegador lança o host (`jarvis-native-host`) quando a extensão chama `connectNative`; os dois
trocam quadros do Native Messaging (tamanho de 32 bits na ordem nativa + JSON UTF-8) por
`stdin`/`stdout`. O host envia `{ "id", "method", "params" }`; a extensão responde
`{ "id", "ok", "result" }` ou `{ "id", "ok": false, "error" }`. O host é quem escuta o Jarvis, num
**socket Unix** (`$XDG_RUNTIME_DIR/jarvis/navegador/<navegador>-<pid>.sock`, pasta 0700, socket
0600, par conferido por `SO_PEERCRED`) — não há porta de rede. Os métodos que o Jarvis usa são:

- `tabs.list`, `tabs.current` (`tabId` opcional), `tabs.navigate` (`url`, `tabId`), `tabs.open`
  (`url`; `fundo`: em segundo plano; `modo`), `tabs.show` (`tabId`), `windows.focused`;
- `page.read`, `page.inspect`, `page.click`, `page.type`, `page.scroll`, `page.map`, `page.act`,
  `page.capture`, `page.readUrl` (`url`, `modo`).

**Uma instância só (2026-10-21, ADR-0036 emendada):** a aba nova e a de fundo nascem **na janela
do dono** — com `fundo` (e no `page.readUrl`, a busca), sem `active`: a aba que ele está vendo
continua a mesma e o foco não muda. A extensão **nunca cria janela**, a não ser com
`modo: "automacao_social"`, o gancho da automação de redes sociais, e-mail e agenda, que ainda não
existe e fica desligado no Jarvis — é o único caminho para a janela própria do Jarvis.

`tabs.navigate` e `tabs.open` só respondem depois de **conferir** (2026-10-21): a aba saiu do lugar
(`comecou`), terminou de carregar (`carregou`) e o conteúdo da extensão respondeu na página nova
(`pagina`: `{url, titulo}`, ou nulo na página de erro do navegador); dizem também em que janela ela
está (`janela`: `dono` | `jarvis`) e se ficou à vista (`visivel`: a aba ativa da janela que está na
frente). `tabs.show` põe a aba à vista do dono (a da janela do Jarvis vai para a janela dele). A
"aba atual" é a ativa da última janela **normal** do dono — nunca popup, app, DevTools ou a janela
do Jarvis (só da automação social), que se segura com `janela.html` e é reconhecida por ela depois
que o fundo reinicia. Aba pedida que não existe mais volta `sem_aba`, dito. `windows.focused` conta
também as janelas abertas (`janelas`): é como a prova confere que nada abriu outra.

`tabs.active` continua na extensão, mas o host não o repassa.

### O controle: a faixa, o selo e o PARAR (ADR-0027, regra 4)

Todo pedido que lê ou mexe numa aba leva a **concessão** do objetivo do Jarvis que o fez
(`controle`, 8 a 32 letras e dígitos). Enquanto ela vale, a aba mostra a faixa «Jarvis no controle
desta aba» (`indicador.js`, que nasce com o documento e pergunta ao fundo se a aba está no
controle; shadow DOM fechado, só o botão recebe clique) e o botão da extensão fica com o selo «IA».
O Jarvis solta com `controle.soltar` quando o objetivo acaba e renova com `controle.manter`; sem
renovação, a extensão solta sozinha em 30 s. `controle.estado` diz o que está no controle (para o
diagnóstico e a prova); `controle.parar` é o PARAR da janela do Jarvis.

O PARAR do dono — o botão da faixa ou o botão da extensão na barra — solta tudo na hora, **revoga**
as concessões (o que vier delas depois é recusado com `parado_pelo_dono`) e manda ao host, sem
pedido nenhum, o evento `{ "evento": "parar", "concessoes": [...], "origem": "faixa" | "barra" }`. O
host o entrega a quem assinou `eventos.assinar` (a conexão que o Jarvis deixa aberta enquanto
controla alguma aba): é por ele que o turno e a tarefa param. Clique sintético da página não conta.
O alvo de `page.inspect`, `page.click` e `page.type` é `alvo`: o **texto ou rótulo visível** do
elemento (não existe seletor CSS). `page.type` leva `texto` (o que digitar) e `limpar`.

`page.read` devolve URL, título, texto visível, links (`texto`, `href`, `data` de `<time datetime>`)
e as datas visíveis. O DOM é sempre conteúdo de terceiro; o host do Jarvis o encaminha como
`DADO`, nunca como instrução. `page.inspect` é interno: devolve tag, texto, se é campo, se é sensível, se envia formulário
(`metodoDoFormulario`, `formularioDeBusca`, `formularioSensivel`) e o destino de um link, para o
Jarvis classificar o risco antes de efetivar `click` ou `type`.

O conteúdo rejeita automaticamente campos de senha, cartão e OTP. A política completa, inclusive
as confirmações por ação, fica no Jarvis; a extensão nunca recebe uma autorização da página.

## Instalação Linux para desenvolvimento

No repositório clonado, um comando registra o host **deste código** e copia a extensão:

```bash
uv run jarvis-native-host --instalar      # --remover desfaz
```

Ele grava o stub `~/.local/share/jarvis/bin/jarvis-native-host` (chama o `.venv` com
`python -I -m jarvis.navegador.host`), o manifesto do host em cada pasta onde um navegador do
usuário procura — Firefox (`~/.mozilla/native-messaging-hosts`), Chrome, Chromium, Brave
(`~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts`), Edge e Vivaldi: nos derivados do
Chromium a pasta é `<pasta de dados do navegador>/NativeMessagingHosts` — e copia esta pasta para
`~/.local/share/jarvis/extensao`, que é a que se carrega:

1. Chromium, Chrome ou Brave: `chrome://extensions` (no Brave, `brave://extensions`), ligue o modo de
   desenvolvedor e escolha **Carregar sem compactação** apontando para
   `~/.local/share/jarvis/extensao`. Se ela já estava carregada, clique em **Recarregar**: o
   navegador só procura o host quando a extensão reinicia.
2. Firefox: `about:debugging#/runtime/this-firefox` → **Carregar extensão temporária** →
   `~/.local/share/jarvis/extensao/manifest.json`. O fundo roda por `background.scripts` (o Firefox
   não tem service worker de extensão); o Chromium usa o `service_worker` e ignora `scripts`.
3. Abas abertas antes de carregar a extensão não têm o conteúdo dela: recarregue a aba.
   `about:`, `file:`, páginas de extensão e páginas internas do navegador nunca são lidas ou
   controladas.

O host só atende o Jarvis do mesmo usuário; sem o Jarvis, a extensão fica ociosa. Navegador em
Flatpak não lança o host (o Native Messaging não sai da caixa de areia). A prova de ponta a ponta
num Chromium e num Firefox de verdade, em contêiner, é `uv run --frozen python -m
tools.harness_navegador`.

Não carregue uma extensão de origem diferente: o manifesto do host fixa os IDs acima. Não há
necessidade, nem caminho suportado, para expor uma porta local.
