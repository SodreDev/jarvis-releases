# Redes sociais: como testar na sua máquina

**Ligado a:** [ADR-0060](adr/0060-redes-sociais-monitorar-notificar-e-responder.md) e [redes-sociais-riscos.md](redes-sociais-riscos.md). Siga a ordem: cada passo só depois de o anterior dar certo.

## 0. Preparar

1. Instale o pacote novo de `dist-teste/` (no Nobara, o `.rpm`), ou rode pelo repositório com `uv run jarvis`.
2. Reinstale o host do navegador: `uv run jarvis-native-host --instalar` (ou o do pacote).
3. No Brave, abra `brave://extensions` e clique em **Recarregar** na extensão do Jarvis. A ponte agora é a versão 4; isso também reinicia o host.
4. Dê F5 na aba do WhatsApp Web, se ela já estava aberta.
5. Abra o Jarvis e vá em **Configuração → redes sociais**. Tudo começa desligado.

## O que o cartão diz quando não conecta

O Jarvis espera até 30 s pelo host da extensão (o navegador partindo, ou o **Recarregar** relançando o host) e tenta de novo sozinho; nesse meio-tempo o cartão diz «procurando o navegador com a extensão do Jarvis…». Depois disso ele diz exatamente o que faltou:

| O cartão diz | O que fazer |
|---|---|
| «o navegador não está aberto» | Abra o Brave. |
| «a extensão do Jarvis não está conectada» | Em `brave://extensions`, confira se o Jarvis está **ativo neste perfil** e clique em **Recarregar**. |
| «a extensão do Jarvis no navegador é de uma versão anterior» | **Recarregar** no card do Jarvis (isso relança o host). |
| «a extensão não respondeu ao abrir a aba» | Nada: o Jarvis tenta de novo em 15 s. Se repetir, rode o diagnóstico abaixo. |

Se continuar falhando, rode `uv run --frozen python tools/diagnostico_navegador.py` e me mande a saída inteira: ela lista os hosts, a versão da ponte e, na seção «redes», cada mudança de estado do monitor (só códigos).

## 1. Só leitura do WhatsApp

1. Em «navegador preferido», deixe **o principal** (ou escolha o Brave).
2. No cartão **WhatsApp**, clique em **monitorar**.
3. O que deve acontecer:
   - Se não houver aba do WhatsApp, abre **uma** aba em segundo plano na sua janela. Não abre janela nova, não pega o foco e nunca abre uma segunda aba da mesma conta.
   - O cartão vai de «abrindo…» para «conectada — nada novo» (ou «faça login…», se o WhatsApp pedir o QR; o Jarvis não lê o QR).
4. Peça a alguém que mande uma mensagem. O cartão mostra «WhatsApp: 1 mensagem nova — Nome (1)». O mesmo aviso aparece no card de avisos com a conversa aberta.
5. Abra a conversa e leia. A contagem cai e não vem aviso novo.

## 2. O canário

1. O cartão deve dizer «conectada» sempre que você está logado. Se ele mostrar «a página mudou e o Jarvis não reconhece o contador», o canário falhou: o WhatsApp mudou o DOM. A rede fica só avisando. Me mande o que o cartão diz.
2. Para ver um alerta de propósito, saia do WhatsApp Web (logout) com o monitor ligado. O cartão deve mostrar «sinal de alerta — a sessão caiu sem você sair», e o envio fica pausado por 24 h (painel «respostas no whatsapp»). Entre de novo e clique em **tirar a pausa**.
3. Repita o passo 1 com Instagram, Facebook, TikTok e Discord se quiser. Essas redes só leem e avisam, nunca enviam.

## 3. Envio, com um contato de teste seu

Só depois de 1 e 2. Use um número **seu** (um segundo chip ou um familiar que saiba do teste), salvo nos contatos com um nome único.

1. Em **memórias fixas**, adicione uma instrução, por exemplo «responda curto e diga que eu retorno à tarde».
2. No painel **respostas no whatsapp**:
   - adicione o contato de teste em «lista permitida» (o nome exatamente como aparece no WhatsApp, e o telefone);
   - baixe o teto para **1 por hora**;
   - clique em **ligar envio automático** e depois em **estou ausente**.
3. Deixe o Jarvis com a conversa aberta (é o motor dela que redige) e fora da madrugada (0h–6h não envia).
4. Do número de teste, mande uma mensagem.
5. O que deve acontecer:
   - de 20 a 90 s depois, o Chromium mostra a faixa «um software está depurando este navegador»;
   - a conversa abre, o «digitando…» aparece e o texto entra letra a letra;
   - o Enter é apertado e a faixa some;
   - o cartão diz «WhatsApp: respondi a Nome (você está ausente)».
6. Confira o log: a pasta de configuração do Jarvis (`~/.config/jarvis/`) tem um `envios.jsonl` com contato, hash e resultado, nunca o texto.
7. Mande uma segunda mensagem antes de ler a primeira. O Jarvis não responde de novo (uma resposta por rodada de não lidas).

**Se algo sair diferente** (conversa errada, texto no lugar errado, nada acontece), o Jarvis deve recusar e avisar «não respondi a Nome — motivo». Se ele enviou para quem não devia, pare na hora e me mande o motivo do log.

## Como parar

- **parar envios agora** (painel «respostas no whatsapp»): desliga o ausente e o envio na hora, grava no arquivo e corta o envio no meio.
- **monitorar** de novo no cartão: desliga a leitura daquela rede. A aba fica aberta e você fecha quando quiser.
- Fechar o Jarvis para tudo, e a extensão solta o depurador sozinha em até 120 s.

## O que ainda não foi provado

Tudo foi testado só com páginas, abas e navegador falsos. Ainda não foi provado na sua máquina:

- o DOM real de cada rede;
- o clique e a digitação por CDP numa aba do WhatsApp **em segundo plano** (se não funcionar, o cabeçalho não confere e o Jarvis só avisa);
- a aba de fundo congelada pelo navegador depois de horas (vira «sem notícia»).
