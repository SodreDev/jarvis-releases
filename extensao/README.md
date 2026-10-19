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

O empacotamento do release fará esta cópia e substituirá
`__JARVIS_NATIVE_HOST_ABSOLUTO__` pelo executável instalado. Para testar uma árvore de release
sem abrir porta de rede:

1. Instale a extensão descompactada. Em Chromium/Chrome, abra `chrome://extensions`, ligue o
   modo de desenvolvedor e escolha **Carregar sem compactação** apontando para `extensao/`.
   No Firefox, abra `about:debugging#/runtime/this-firefox`, escolha **Carregar extensão temporária**
   e selecione `extensao/manifest.json`.
2. Copie o manifesto de host para o navegador correto e troque o marcador pelo caminho absoluto
   do lançador `jarvis-native-host` que acompanha o release:

   - Firefox: `~/.mozilla/native-messaging-hosts/br.com.granafacil.jarvis.json`
   - Google Chrome: `~/.config/google-chrome/NativeMessagingHosts/br.com.granafacil.jarvis.json`
   - Chromium: `~/.config/chromium/NativeMessagingHosts/br.com.granafacil.jarvis.json`

   O arquivo do host deve ter permissão de leitura para o navegador; o executável indicado em
   `path` deve ser absoluto e executável. Em instalações corporativas, o administrador pode usar
   os diretórios de sistema equivalentes do navegador.
3. Abra uma página `http` ou `https`. O navegador lança o host ao carregar a extensão; o host só
   atende o Jarvis do mesmo usuário, e sem o Jarvis a extensão permanece inerte.
   `about:`, `file:`, páginas de extensão e páginas internas
   do navegador nunca são lidas ou controladas.

Não carregue uma extensão de origem diferente: o manifesto do host fixa os IDs acima. Não há
necessidade, nem caminho suportado, para expor uma porta local.
