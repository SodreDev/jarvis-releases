# ADR-0060 — Redes sociais: monitorar e notificar pela aba de fundo do navegador do dono, responder só sob guardrails

**Data:** 2026-11-12 · **Estado:** aceita (fatias A–E desta ADR; o uso real é do dono) · **Decide:** dono (o pedido, o navegador próprio, o baixo volume, aceitar o risco de banimento), arquiteto (onde mora cada peça, os guardrails)
**Pedido:** dono, 2026-11-12 — monitorar e notificar WhatsApp Web, Instagram, Facebook, TikTok e Discord (web) e, depois, responder colegas no WhatsApp quando ele estiver ausente, com o Jarvis instruído por «memórias fixas». O dono declarou que aceita o risco de os termos dessas plataformas levarem ao banimento da conta. Acréscimo do dono no mesmo dia: o «headless» é uma aba de fundo do navegador e perfil que ele já usa (mesma sessão, mesmo IP, mesma impressão digital), e antes de implementar vem um documento de risco. Emenda a ADR-0036 (o modo `automacao_social`) e usa a ADR-0027 (a extensão), a ADR-0047 (o orçamento do prompt) e a ADR-0051 (o CDP).

**Leitura obrigatória antes de mexer nesta área:** [redes-sociais-riscos.md](../redes-sociais-riscos.md). Ele explica cada regra abaixo e o que é proibido a qualquer agente.

## Contexto

- A regra «uma instância só» (memória `ca49d028`, emenda da ADR-0036) já fixa que trabalho sem mostrar é **aba em segundo plano na janela do dono**, nunca outra instância ou outro perfil. As redes do dono estão logadas no perfil dele; outro perfil exigiria login de novo e seria «outra instância».
- A extensão (ADR-0027) já tem content script em toda página http(s), Native Messaging e eventos que o host entrega a quem assinou (`eventos.assinar`, hoje só `parar`).
- O prompt de um turno tem teto de 16 mil caracteres (ADR-0047). A memória do turno já tem orçamento próprio (`memoria_do_turno.ORCAMENTO_DE_TOKENS`).
- Nenhuma das cinco redes tem API oficial para conta pessoal ler e responder mensagens. Automatizar a interface web viola os termos de todas [SUPOSIÇÃO: lido nos termos públicos de cada uma; nada aqui testa contra conta real — confirma ou derruba o uso do dono]. O dono aceitou esse risco; os guardrails abaixo existem para que o risco fique no volume baixo que ele descreveu.

## Decisão

Monitorar lendo a página que o dono já tem logada, numa aba de fundo da janela dele; responder só no WhatsApp, só para quem ele permitiu, só com ele ausente, com teto e com parada imediata — e tudo desligado por padrão.

1. **Navegador.** Ajuste novo `navegador_preferido` em `redes.toml` (vazio = o `navegador_principal` do `jarvis-voz.toml`). Cada rede ligada vira **uma aba de fundo** na janela do dono (`social.abrir`: sem `active`, sem tirar o foco). Se a aba da rede já estiver aberta, é reusada: nunca duas abas da mesma conta. Nunca navegador novo, janela nova, instância nova ou perfil novo; o `modo: automacao_social` continua reservado e **não** é usado aqui. Nenhuma credencial é lida, guardada ou enviada.
2. **Ajustes salvam na hora.** Toda troca na janela de configuração (voz, escuta, motores, nuvem, atalho, acesso e a aba nova «redes sociais») grava no arquivo no mesmo clique, só os campos que mudaram, sobre o que está no disco. O botão «salvar configuração» sai. `redes.toml` e as memórias fixas são gravados atomicamente com permissão 0600, na pasta de configuração do usuário (fora do repositório).
3. **Aba «redes sociais» no painel.** Um cartão por rede: chave «monitorar», estado (desligada, sem aba, esperando login, conectada), não lidas e as últimas notificações dessa rede. Sem vídeo nem captura de tela: só estado. As notificações de cada rede são separadas.
4. **Monitor somente leitura (fatias B e E).** Um content script (`extensao/social.js`, só nos hosts das cinco redes, no mundo isolado) observa título, contador de não lidas e quem mandou, com `MutationObserver` no título e releitura lenta de reserva, e manda um **evento** `social` ao host (mesmo caminho do `parar`). Sem hook de rede da página, sem mexer em `navigator`, sem recarregar. Os seletores ficam num arquivo de dados separado e versionado (`extensao/social-seletores.js`), por papel, `aria-label` e atributo estável, nunca classe ofuscada. Um canário por rede confere os elementos essenciais; falhou, o estado é «formato desconhecido» e a rede só notifica. O Python (`jarvis.social.monitor`) guarda o estado por rede e cria uma notificação quando a contagem sobe. O monitor não clica, não digita e não rola. Mapear o formato das mensagens fica para depois.
5. **Memórias fixas (fatia C).** Um arquivo do dono (`memorias-fixas.toml`, 0600) com rede de contatos, prestadores de serviço e instruções de como responder, editável pela janela. Entra no prompt só quando o turno é sobre redes, mensagem ou um contato que está nelas, e com orçamento próprio de caracteres, abaixo do teto da ADR-0047.
6. **Envio (fatia D), só no WhatsApp Web, com estes guardrails, todos no código e não no prompt:**
   - **Desligado por padrão**: sem `envio_automatico = true` em `redes.toml`, a ferramenta de envio não existe para o modelo.
   - **Lista permitida**: só contatos que o dono pôs na lista (nome e telefone), salvos, e só quem **escreveu primeiro**. Fora da lista, grupo, homônimo ou dúvida: o Jarvis **só notifica** o dono.
   - **Modo «ausente»**: o envio automático só acontece com o «ausente» ligado pelo dono (na janela ou por voz dele). Com o dono presente, o Jarvis só propõe e o dono confirma.
   - **Teto e ritmo**: padrão ≤ 4 envios por hora e ≤ 15 por dia, ajustáveis só para baixo de um máximo rígido no código (8 e 30); intervalo mínimo de 3 min entre envios; sem envio de 0h a 6h; nunca o mesmo texto em seguida para contatos diferentes. Passou de qualquer um, só notifica.
   - **Parada imediata**: botão «parar envios» na aba e o comando de voz «para de responder» desligam o ausente e o envio na hora, gravado no arquivo, e cancelam envio em curso.
   - **Contato conferido**: antes de digitar, a extensão lê o cabeçalho do chat aberto (nome e telefone) e o código compara com o contato esperado. Se divergir, o Jarvis recusa e avisa. Ele confere de novo logo antes de apertar enviar, se o chat foi reaberto.
   - **Digitação de verdade**: entrada confiável pelo CDP da ADR-0051 (`Input.dispatchKeyEvent`), com o depurador anexado só durante o envio e solto em seguida; nunca evento sintético de content script (`isTrusted = false`). Atraso de reação aleatório (20 a 90 s), digitação por caractere com ritmo log-normal e pausas, Enter só no fim. No Firefox, sem CDP, não há envio.
   - **Sinais de alerta**: captcha, pedido de verificação, conta limitada ou bloqueada, logout inesperado, aviso de atividade incomum ou queda súbita dos elementos esperados pausam todo envio daquela rede por 24 h, notificam o dono e ficam registrados. Nunca se tenta contornar.
   - **Conteúdo barrado**: texto com dado sensível (CPF, cartão, senha, chave PIX, código, dados bancários) ou pedido/oferta de dinheiro é recusado pelo código antes de chegar à página.
   - **Registro**: cada envio, ou recusa, vai a um log 0600 com rede, contato, hash SHA-256 do texto e hora. O texto em claro não vai ao log.
7. **Testes.** Só páginas falsas (fixtures HTML que imitam o DOM de cada rede), o navegador falso das suítes `.mjs` e contêiner. Nenhum teste abre o navegador, as contas, o microfone ou o áudio reais do dono, e nenhum envia mensagem de verdade.

## Alternativas descartadas

- **Perfil ou instância separada do navegador** (`--user-data-dir`, headless de verdade): exige outro login nas redes e viola a regra de uma instância. Volta se o dono pedir um perfil só para isso.
- **APIs oficiais** (WhatsApp Business Cloud API, Graph API): não servem para conta pessoal e exigem número comercial. Voltam se o dono migrar para conta comercial.
- **Bibliotecas de terceiros que falam o protocolo do WhatsApp** (whatsapp-web.js, Baileys): outro processo com a sessão do dono e uma cadeia de dependências inteira com acesso às mensagens. Ler a página que ele já tem aberta mantém tudo no navegador e no host local.
- **Guardrails no prompt**: o modelo pode ser convencido do contrário. Lista, teto, ausente, parada e filtro de conteúdo ficam no código, antes da extensão.
- **«Stealth»** (mascarar `navigator.webdriver`, falsificar impressão digital, hook de rede): é a adulteração que denuncia, e cai no primeiro patch da plataforma.
- **Eventos sintéticos para digitar**: `isTrusted = false`, detectável pela página.

## Consequências

- `redes.toml`, `memorias-fixas.toml` e o log de envios são dados pessoais do dono (telefones, nomes, instruções): ficam fora do git, com 0600, e nunca entram em trilha, auditoria ou commit.
- A extensão ganha `social.js` e o evento `social`, e a versão da ponte sobe. A extensão antiga, sem recarregar, simplesmente não informa estado: a aba mostra «sem notícia da extensão».
- O DOM das redes muda sem aviso. Os seletores ficam num arquivo só, por rede, e o estado «formato desconhecido» aparece na aba em vez de um número errado.
- Passa a ser obrigatório testar: salvamento na hora de cada ajuste, 0600, o monitor contra fixtures, cada guardrail do envio com um caso que tenta furá-lo.

## O que não foi provado

O DOM real de cada rede (as fixtures imitam o que é público hoje), o comportamento das redes com uma aba de fundo aberta por horas (o Chromium congela abas de fundo: o título e o contador podem atrasar), e se o volume que o dono descreveu fica abaixo do que leva a banimento.

## Como invalidar esta decisão

Se o dono for bloqueado por uma rede com o volume dentro do teto, o envio daquela rede é desligado e o teto padrão cai. Se a trilha mostrar um envio fora da lista, sem «ausente» ou com o contato divergente, o envio é desligado inteiro até a causa ser corrigida.

## Andamento

- **Fatia A** (`f7898dc`): esta ADR, o documento de risco, a aba «redes sociais», `redes.toml` e o salvamento na hora de todo ajuste.
- **Fatia B** (monitor só leitura): `extensao/social.js` e `extensao/social-seletores.js` (seletores como dados, versão 1, com canário e sinais de alerta), `social.abrir`/`social.estado` e o evento `social` no protocolo (ponte versão 3), `jarvis.social.monitor` (estado por rede, aviso quando a contagem sobe, alerta sempre avisado e nunca repetido) e o monitor ligado à janela só pela ponte de verdade (`gui/principal.py`). Provas: `tests/unit/social/social.test.mjs` contra as páginas falsas de `tests/unit/social/paginas/`, `tests/unit/navegador/background_social.test.mjs` com abas falsas, `tests/unit/social/test_monitor.py` e a janela offscreen em `tests/unit/gui/test_redes_na_janela.py`. Para usar: recarregar a extensão do Jarvis no navegador (ela reinicia o host) e ligar a rede na aba.
