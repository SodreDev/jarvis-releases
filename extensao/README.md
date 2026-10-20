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

- `tabs.list`, `tabs.current` (`tabId` opcional), `tabs.navigate` (`url`, `tabId`);
- `page.read`, `page.inspect`, `page.click`, `page.type`, `page.scroll`.

`tabs.active` e `tabs.open` continuam na extensão, mas o host não os repassa. O alvo de
`page.inspect`, `page.click` e `page.type` é `alvo`: o **texto ou rótulo visível** do elemento
(não existe seletor CSS). `page.type` leva `texto` (o que digitar) e `limpar`.

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
