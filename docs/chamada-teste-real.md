# Voz na ligação: como testar na sua máquina

**Ligado a:** [ADR-0074](adr/0074-voz-do-jarvis-na-ligacao.md) e
[estudo](estudos/voz-na-ligacao.md). Tudo começa **desligado** (a chave «chamadas ativas» da aba
«chamadas»). Siga a ordem: cada passo só depois de o anterior dar certo, e me mande a saída de
cada comando. Nada aqui foi provado numa máquina de verdade — os testes rodaram só com peças
falsas.

## 0. Preparar

1. Instale o pacote novo de `dist-teste/` (no Nobara, o `.rpm`), ou rode pelo repositório com
   `uv run jarvis`.
2. No navegador, `brave://extensions` → **Recarregar** na extensão do Jarvis. A ponte agora é a
   **versão 7** (lista de conversas, abrir a linha escolhida, estado da ligação). Sem isso o cartão
   das redes avisa «a extensão do Jarvis no navegador é de uma versão anterior».
3. F5 na aba do WhatsApp Web, se ela já estava aberta.

## 1. A fonte virtual (sem ligação nenhuma)

```bash
pactl info | head -3
```

Tem de mostrar «Server Name: PulseAudio (on PipeWire …)». Sem `pactl`, instale
`pulseaudio-utils`.

```bash
uv run --frozen jarvis --testar-chamada
```

(Do pacote: `jarvis --testar-chamada`.) Seis passos, só «ok/FALHOU» e nomes de dispositivo — nada
é gravado nem tocado. Ele liga a fonte virtual em modo sessão, abre uma captura de teste no seu
microfone, confere que ela foi **movida** para a fonte virtual, abafa e devolve o microfone real,
e desliga conferindo que a entrada padrão voltou. Me mande a saída inteira. Se algo ficar
carregado depois de uma queda:

```bash
pactl list short modules | grep -i jarvis
```

e tire cada um com `pactl unload-module <número>`.

## 2. O chat de destino e a mensagem de teste

1. No WhatsApp Web, veja como o seu chat aparece na lista («Você», «Seu Nome (você)») e **fixe**
   esse chat no topo (a lista é virtual: só as linhas desenhadas são lidas).
2. Na aba **chamadas**: ligue **chamadas ativas**; em «chat de destino», escreva o nome **como
   aparece**. Pode ser o seu chat ou o de um **2º número seu**.
3. Na aba **redes sociais**, deixe o WhatsApp **monitorado** (é a mesma aba de fundo).
4. Com a conversa do Jarvis aberta, aperte **mandar mensagem de teste ao chat de destino**.
5. Me diga: a mensagem chegou no chat certo? **O celular tocou?** Mensagem da própria conta
   enviada pelo WhatsApp Web costuma **não** tocar; se não tocar, troque para o chat de um 2º número.

## 3. Uma ação pedida e a confirmação

Sem ligação de verdade, dá para provar só a confirmação pelo PC: ela aparece em «ações à espera
de você» quando uma chamada pede algo. O caminho completo é o passo 4.

## 4. Uma ligação de verdade (o último passo)

1. De outro telefone, ligue para o seu WhatsApp e **atenda no WhatsApp Web**.
2. A aba «ligação agora» tem de mostrar «em andamento» com o nome de quem ligou (se não mostrar,
   os seletores da ligação não batem com a sua página — me mande o que aparece).
3. Aperte **Jarvis atende**. Do outro telefone, diga «alô, o dono está?» — o Jarvis tem de se
   apresentar como assistente com IA.
4. Do outro telefone, peça uma ação («manda a planilha pro Carlos»). Tem de aparecer em «ações à
   espera» e chegar uma mensagem com o **código** no chat de destino.
5. Responda no chat de destino «sim CÓDIGO». A ação tem de sumir das pendentes e o Jarvis avisar
   que foi confirmada. Do outro telefone, diga «eu confirmo» — não pode mudar nada.
6. Aperte **tirar o Jarvis da ligação** (ou desligue a ligação) e rode de novo:

```bash
pactl list short modules | grep -i jarvis
```

Não pode sobrar nada.

## O que eu preciso de volta

A saída do `--testar-chamada`, se o celular tocou com a mensagem de teste (e com qual chat), e o
que cada passo do item 4 mostrou. Com isso a ADR-0074 sai de «proposta».
