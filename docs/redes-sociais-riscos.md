# Redes sociais: como reduzir o risco de banimento

**Ligado a:** [ADR-0060](adr/0060-redes-sociais-monitorar-notificar-e-responder.md) · **Data:** 2026-11-12 · **Pedido:** dono, 2026-11-12

Este documento vale para **todo agente** que mexer em `jarvis.social`, `extensao/social.js`, `extensao/social-seletores.js` ou no envio de mensagens. Leia antes de mudar qualquer coisa. Se uma ideia contradiz algo daqui, ela está errada até o dono decidir o contrário numa ADR nova.

## 0. Honestidade primeiro

- **Risco zero não existe.** WhatsApp, Instagram, Facebook, TikTok e Discord proíbem nos termos de uso automatizar uma conta pessoal ou acessá-la por meio não autorizado. Uma conta pode ser limitada ou banida mesmo com tudo o que está aqui.
- **O dono sabe e aceitou o risco** (2026-11-12). Isso não autoriza aumentar o risco: as regras abaixo existem para manter o uso no volume baixo que ele descreveu (responder colegas quando ele está ausente).
- **Ler é quase seguro. Enviar é o arriscado.** A leitura é a mesma página que o dono já tem aberta, lida em silêncio. O envio é uma ação na conta dele, e é o que as plataformas procuram. Em caso de dúvida, o Jarvis **só notifica** o dono.
- Este documento traz estratégias comuns e sóbrias. Nada de truque de evasão: qualquer coisa que dependa de enganar um detector cai no primeiro patch da plataforma, e o próprio truque vira o sinal.

## 1. Identidade: o navegador e a sessão do dono, nada além

- Use **o navegador do dono, com o perfil dele e a extensão do Jarvis**. O «headless» daqui é uma **aba em segundo plano** na janela que ele já usa (`tabs.create` sem `active`, na janela dele). Assim a sessão, o IP, os cookies e a impressão digital do navegador são os de um uso normal.
- **Nunca** abra outro navegador, outra instância, outro perfil, `--user-data-dir`, modo headless de verdade, Puppeteer, Playwright ou Selenium. Cada um desses é uma identidade digital nova, que pede login novo e parece um robô.
- **Nunca** abra uma segunda aba da mesma conta. Se a aba da rede já está aberta (pelo dono ou pelo Jarvis), ela é **reusada**. O WhatsApp Web, por exemplo, só aceita uma aba ativa: abrir outra derruba a primeira («usar aqui»), e esse vaivém é um sinal.
- **Nenhuma credencial.** O Jarvis nunca lê, guarda nem envia senha, token, cookie, código de verificação ou QR. Nunca cria conta. Se a rede pede login, o estado é «esperando login» e o dono entra sozinho.

## 2. Ler (o modo seguro)

- Leia o **DOM no mundo isolado** do content script (`extensao/social.js`): título da aba, contador de não lidas, nome de quem mandou. Use `MutationObserver` no `<title>` e uma releitura lenta de reserva (15 s), nunca um laço apertado.
- **Não** instale hook em `fetch`, `XMLHttpRequest`, `WebSocket` ou em qualquer função da página. **Não** injete script no mundo principal da página para ler o estado interno dela.
- **Não** altere `navigator`, `navigator.webdriver`, o user agent ou qualquer propriedade do ambiente. **Nada de «stealth»**: é a adulteração que denuncia o robô, não a leitura.
- **Não** recarregue a página em laço, não navegue de conversa em conversa para ler, não role a lista para «carregar mais». O monitor não clica, não digita e não rola: ele só lê o que já está na tela.
- **Não** leia o texto das mensagens por enquanto (mapear o formato fica para depois, por pedido do dono). O monitor lê nome e contagem.
- Uma aba de fundo pode ser congelada ou descartada pelo navegador. Isso é normal: o estado vira «sem notícia» e o dono é avisado. Não «acorde» a aba com truque.

## 3. Seletores que sobrevivem a um patch

- **Não dependa de classe CSS ofuscada** (`_ak8l`, `x1n2onr6`, `name__3b2f1`). Use **papel** (`role`), **`aria-label`**, atributo de dado estável (`data-e2e`, `data-list-id`), texto visível e estrutura.
- Tenha **vários seletores por elemento, em ordem de preferência, com recuo**. O título da aba (`(3) WhatsApp`) é o recuo de toda contagem.
- Os seletores ficam num **arquivo de dados separado e versionado**, `extensao/social-seletores.js` (só um objeto literal, sem lógica). Quando a plataforma mudar, é só esse arquivo que muda, com a versão subindo.
- **Canário por rede**: ao abrir (e a cada leitura), o script confere se os elementos essenciais existem (lista de conversas ou tela de login). Falhou: o estado vira **«formato desconhecido»**, o dono é avisado e a rede passa a **só notificar**. Nunca chute um elemento parecido e nunca envie às cegas.
- Uma queda súbita dos elementos esperados é também um sinal de alerta (seção 6).

## 4. Enviar (só WhatsApp, só sob os guardrails)

### 4.1 Quem pode receber

- Só responde **quem escreveu primeiro** (há mensagem não lida dele). O Jarvis nunca inicia conversa.
- Só **contato salvo e na lista permitida** do dono (nome e telefone). Fora da lista, ou na dúvida, **só notifica**.
- **Grupo, chat ambíguo ou homônimo**: não envia. Dois contatos com o mesmo nome contam como ambíguo.
- Só com o **modo «ausente» ligado pelo dono**. Com o dono presente, o Jarvis propõe e o dono confirma.

### 4.2 Conferir o contato

- Antes de digitar, o código lê o **cabeçalho do chat aberto** (nome e telefone ou identificador) e compara com o contato esperado. Divergiu: recusa, avisa o dono e registra.
- Confere **de novo** logo antes de apertar Enter: se o chat mudou (o dono clicou noutro, chegou outra conversa), não envia.

### 4.3 Como digitar

- Evento sintético de content script (`dispatchEvent`, `element.value = …`, `execCommand`) tem `isTrusted = false` e é detectável. **Não use.**
- Use a **entrada confiável já existente**: o CDP da ADR-0051 (`Input.dispatchKeyEvent` / `Input.insertText` por caractere, pelo `page.gesture` «digitar»). O depurador é **anexado só durante o envio e solto logo em seguida**, nunca permanente. O Chromium mostra ao dono a faixa «um software está depurando este navegador» enquanto está anexado; é esperado.
- Anexe **sem ligar domínio nenhum** do CDP. `Input.*` não precisa de `Runtime.enable`, `Network.enable` nem `Log.enable`, e ligar o `Runtime` tem efeito colateral que a página consegue medir. O envio usa `anexarSoEntrada` (em `extensao/background.js`), nunca o `anexarCdp` das ferramentas de depuração.
- No Firefox não há CDP pela extensão (ADR-0051): **lá o envio não existe**, só a notificação.
- Simule o fluxo de uma pessoa, sem exagero:
  - **Atraso de reação** antes de começar: dezenas de segundos, aleatório (padrão entre 20 e 90 s). Nunca instantâneo.
  - Focar o chat e digitar **por caractere**, com ritmo variável: intervalo log-normal entre teclas, pausas maiores em espaço e pontuação. Errar e corrigir é opcional e raro.
  - O «digitando…» aparece sozinho, porque a digitação é real.
  - **Enter só no fim.** Nunca colar um texto longo de uma vez.
- Texto curto. Resposta longa não é resposta de quem está ausente: o Jarvis resume ou só notifica.

### 4.4 Volume e ritmo

- **Teto baixo**, configurável só para baixo: padrão **≤ 4 envios por hora e ≤ 15 por dia**, com **máximo rígido no código** (8 por hora, 30 por dia) que nenhum arquivo ultrapassa.
- **Intervalo mínimo entre envios** (padrão 3 min), mesmo para contatos diferentes. Nunca em rajada.
- **Madrugada sem envio**: padrão 0h–6h. Mensagem que chega nesse horário só vira notificação.
- **Nunca dois textos idênticos seguidos para contatos diferentes**: o código compara o hash do texto com o do envio anterior e recusa o repetido (a redação tem de variar).
- Nunca envio em massa, convite, link não pedido, mídia ou anexo em lote. Texto puro.
- Conteúdo barrado no código: dinheiro (pedir, oferecer, PIX, transferência), dado sensível (CPF, cartão, senha, código, dados bancários). Recusado antes de chegar à página.

### 4.5 Parar

- Botão «parar envios» na aba «redes sociais» e o comando de voz do dono desligam o ausente e o envio **na hora**, gravado no arquivo, e cancelam o envio em curso.

## 5. Registro

- Cada envio, recusa ou pausa vai a um log 0600 fora do repositório: rede, contato, **hash SHA-256 do texto** (nunca o texto em claro), hora e resultado.
- Nada disso entra em trilha, auditoria, commit, prompt de outro serviço ou memória do projeto.

## 6. Sinais de alerta: parar tudo

Qualquer um destes faz o Jarvis **pausar todo envio daquela rede por 24 h**, notificar o dono e registrar:

- captcha ou desafio de «não sou um robô»;
- pedido de verificação (código, selfie, telefone);
- «conta limitada», «bloqueada», «suspensa», «atividade incomum» ou banner parecido;
- logout inesperado (a sessão caiu);
- queda súbita dos elementos esperados (o canário falhou de repente numa página que funcionava).

**Nunca** tente contornar, resolver o desafio, recarregar para ver se passa ou repetir o envio. A pausa só sai antes das 24 h se o dono a tirar.

## 7. O que é proibido a qualquer agente

Mudar o «headless» para outro navegador ou perfil; usar Puppeteer, Playwright, Selenium ou bibliotecas que falam o protocolo da plataforma (whatsapp-web.js, Baileys); hook de rede da página; adulterar `navigator`; ler cookie ou storage; enviar com evento sintético; subir o teto rígido; enviar de madrugada; enviar para fora da lista; iniciar conversa; responder em grupo; ignorar um sinal de alerta; tirar a pausa de 24 h sem o dono. Qualquer um desses pede uma ADR nova com a decisão do dono.

## Fontes

- Termos de uso e políticas públicas de cada rede (WhatsApp, Meta/Instagram/Facebook, TikTok, Discord), que proíbem acesso automatizado não autorizado. Este documento não cita trecho: as redes mudam o texto, e a regra vale mesmo assim.
- ADR-0027 (a extensão), ADR-0036 emendada (uma instância só), ADR-0051 (CDP: `Input.dispatchKeyEvent`, anexar e soltar), ADR-0060 (esta arquitetura).
