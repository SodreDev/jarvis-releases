# ADR-0074 — A voz do Jarvis dentro da ligação (rascunho)

**Data:** 2026-11-16 · **Estado:** proposta (só estudo e desenho; nada implementado; espera as respostas do dono no fim de [docs/estudos/voz-na-ligacao.md](../estudos/voz-na-ligacao.md)) · **Decide:** dono
**Pedido:** dono, 2026-11-16 — o Jarvis falar o TTS pelo microfone do dono numa chamada (tipo soundpad), sem o dono trocar de microfone, para avisar quem liga que é um assistente pessoal quando o dono está ausente, ou atender antes de avisá-lo, se configurado; com proteção forte contra jailbreak e contra alguém se passar pelo dono. Usa o laço da ADR-0072 e os eventos da ADR-0070/0073.

## Contexto

O Jarvis ouve o dono pelo microfone real e fala no alto-falante. Numa chamada no PC, quem liga só
ouve o microfone. Para o Jarvis falar com quem liga, a voz dele tem de entrar na **entrada** que o
app de chamada usa — e o que vem de quem liga é texto de terceiros, com risco de injeção e de
engenharia social. O estudo mapeia o áudio (PipeWire), que chamadas passam pelo PC, as ameaças e o
legal.

## Decisão proposta

1. **Fonte virtual no PipeWire, criada pelo Jarvis ao abrir:** um nó `Audio/Source/Virtual`
   («Microfone (com Jarvis)») que soma o microfone real (loopback) e o fluxo de TTS da ligação.
   Ela vira a entrada padrão (`wpctl` e `pactl`, conferidos lendo de volta) e o padrão anterior
   volta ao fechar. O Jarvis continua ouvindo o **microfone real**. Limite aceito: app com microfone
   escolhido à mão escolhe a fonte virtual uma vez.
2. **O outro lado é o fluxo do app de chamada**, gravado sozinho (não a saída inteira), transcrito
   pelo ASR de sempre. Canal remoto × canal local = diarização mínima.
3. **Só chamada que toca no PC:** WhatsApp Web, Meet, Discord (sem bot), softphone SIP. Ligação do
   celular e WhatsApp do app do celular **não** passam pelo PC (hipótese Bluetooth HFP fica para
   estudo à parte).
4. **Um subagente da ligação, no laço canônico, com 4 ferramentas** — `ligacao.falar`,
   `ligacao.anotar_recado`, `ligacao.notificar_dono`, `ligacao.encerrar` — e nada mais (sem
   memória, arquivos, navegador, sistema, envio, delegação). A primeira fala tem de conter o aviso de
   que é um assistente com IA e não o dono (o código confere e devolve o veredito; não escreve a
   frase). Resposta curta, teto de duração, turnos e silêncio; o dono atendendo ou falando corta na
   hora.
5. **A fala de quem liga é dado:** entra entre **marcadores aleatórios de vários tokens sorteados
   por chamada** (≥ 96 bits, nunca falados nem gravados), com os marcadores e os caracteres de
   delimitação removidos do texto e o scanner de injeção (ADR-0065) aplicado. É a segunda linha; a
   primeira é o privilégio mínimo.
6. **Reconhecer o dono não destrava poder.** Código de uso único (TOTP RFC 6238, ou
   desafio-resposta) com tentativas limitadas e bloqueio; o código fixo de 4 dígitos + palavra-chave
   é fator fraco (é ouvido e repetível). Reconhecido, o dono só ganha o modo «recado do dono»;
   leitura ou ação exigem confirmação por outro canal já autenticado e seguem pelo Jarvis principal,
   com as permissões de sempre. Voz nunca autentica.
7. **Ética:** aviso de IA na primeira frase; voz sintética do Jarvis, **nunca** a do dono; nunca
   liga para ninguém; transcrição local, bruta apagada ao fim, recado com retenção curta, trilha só
   com códigos.
8. **Atender sozinho** só por softphone SIP com número do assistente, ou — se o dono aceitar o risco
   da ADR-0060 — clicando «Atender» no WhatsApp Web pela extensão. Padrão: o dono atende e passa.

## Fatias

Na ordem: (3) agente da ligação e (5) reconhecimento do dono — a segurança, testável só com motor
roteirizado e relógio injetado; (1) misturador virtual e (2) canais — com executor de comandos e
backends de áudio falsos; (4) estado da chamada pela extensão falsa; (6) atender. Windows
(VB-Cable/Voicemeeter) só se pedido. Detalhe e o que só a máquina do dono prova: no estudo, §5.

## Consequências

- Se aceita: o Jarvis passa a mexer no grafo de áudio do sistema (precisa desfazer limpo, inclusive
  quando cai) e a ter um segundo laço de ASR durante a chamada (CPU/GPU).
- O risco de conta (WhatsApp/Discord) só existe se o dono escolher atender por automação.
- Fica aberto: chamadas do celular (Bluetooth HFP), Windows, chamadas em grupo (sem diarização por
  modelo).
