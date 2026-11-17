# ADR-0074 — A voz do Jarvis dentro da ligação (rascunho)

**Data:** 2026-11-16 · **Estado:** proposta (o dono decidiu parte em 2026-11-17 — abaixo; continua proposta até ele aceitar; as fatias de segurança estão feitas só com fakes — abaixo; o que falta está no §6 de [docs/estudos/voz-na-ligacao.md](../estudos/voz-na-ligacao.md)) · **Decide:** dono
**Pedido:** dono, 2026-11-16 — o Jarvis falar o TTS pelo microfone do dono numa chamada (tipo soundpad), sem o dono trocar de microfone, para avisar quem liga que é um assistente pessoal quando o dono está ausente, ou atender antes de avisá-lo, se configurado; com proteção forte contra jailbreak e contra alguém se passar pelo dono. Usa o laço da ADR-0072 e os eventos da ADR-0070/0073.

## Contexto

O Jarvis ouve o dono pelo microfone real e fala no alto-falante. Numa chamada no PC, quem liga só
ouve o microfone. Para o Jarvis falar com quem liga, a voz dele tem de entrar na **entrada** que o
app de chamada usa — e o que vem de quem liga é texto de terceiros, com risco de injeção e de
engenharia social. O estudo mapeia o áudio (PipeWire), que chamadas passam pelo PC, as ameaças e o
legal.

## Decisões do dono (2026-11-17)

- **Celular fora por ora** (as opções ficam no §7 do estudo: no iPhone nenhum app de loja atende
  ou fala numa ligação da operadora; o caminho comum é o desvio da operadora para um número VoIP do
  assistente). **Alvo:** atender chamada na versão **web** no PC (WhatsApp Web, Meet, Discord).
- **TOTP** aceito, configurável pelo app (aba «chamadas»); 4 dígitos + palavra só fator fraco.
- **5 min sem encerramento automático**: passado o tempo, o agente é notificado e avisa a pessoa
  ou o dono. **Até 30 turnos; até 5 frases por fala.**
- O Jarvis **lembra do interlocutor** entre chamadas (quem monta um plano continua), mas pede o
  **TOTP a cada chamada** a quem disser ser o dono — instrução no prompt da chamada, não regra de
  código que fale por ele.

## Decisão proposta

1. **Fonte virtual no PipeWire que assume o lugar do microfone, como o Soundpad** (revisto em
   2026-11-17, a pedido do dono): um nó `Audio/Source/Virtual` que soma o microfone real (loopback)
   e o fluxo de TTS da ligação, em três camadas — (a) vira a entrada padrão (`wpctl` e `pactl`,
   conferidos lendo de volta); (b) o Jarvis **move** para ela, em tempo de execução, toda captura
   de app que esteja no microfone físico (exceto ele mesmo e o loopback), e devolve ao desligar;
   (c) opcional, modo instalado: dois arquivos em `~/.config` (sem sudo, desfazíveis) fazem a fonte
   virtual assumir o nome e a descrição do físico, que fica renomeado só para o loopback e o Jarvis.
   **Cobre quase tudo; exceções:** app que abre o ALSA direto (`hw:`) fora do PipeWire, e app que
   reverte o move sozinho (o Jarvis move de novo, com teto). O padrão é o modo sessão (nada no
   disco; se o Jarvis cair, o grafo volta ao físico). O Jarvis continua ouvindo o **microfone
   real**.
2. **O outro lado é o fluxo do app de chamada**, gravado sozinho (não a saída inteira), transcrito
   pelo ASR de sempre. Canal remoto × canal local = diarização mínima.
3. **Só chamada que toca no PC:** WhatsApp Web, Meet, Discord (sem bot), softphone SIP. Ligação do
   celular e WhatsApp do app do celular **não** passam pelo PC (o celular está estudado no §7 do
   estudo e fica para depois, por decisão do dono).
4. **Um subagente da chamada, no laço canônico (`quem="chamada"`), com 5 ferramentas** —
   `chamada.falar`, `chamada.anotar_recado`, `chamada.avisar_dono`, `chamada.verificar_totp`,
   `chamada.lembrar_interlocutor` — e nada mais (sem memória do dono, arquivos, navegador, sistema,
   envio, delegação; ferramenta fora do catálogo volta recusada). A primeira fala declara que traz
   o aviso de que é um assistente com IA e não o dono (o código recusa a 1ª fala sem a declaração e
   devolve o veredito; não escreve a frase). Até 5 frases por fala; 5 min e 30 turnos viram
   **notificação** ao agente, que decide — sem corte automático; o dono atendendo ou falando corta
   a fala na hora. **Memória por interlocutor**: só o que a pessoa disse, entregue à chamada
   seguinte como dado, nunca como autoridade.
5. **A fala de quem liga é dado:** entra entre **marcadores aleatórios de vários tokens sorteados
   por chamada** (≥ 96 bits, nunca falados nem gravados), com os marcadores e os caracteres de
   delimitação removidos do texto e o scanner de injeção (ADR-0065) aplicado. É a segunda linha; a
   primeira é o privilégio mínimo.
6. **Reconhecer o dono não destrava poder.** TOTP RFC 6238 (decisão do dono), janela ±1, uso
   único também entre chamadas, pedido **a cada chamada**, com tentativas limitadas e bloqueio; o código fixo de 4 dígitos + palavra-chave
   é fator fraco (é ouvido e repetível). Reconhecido, o dono só ganha o modo «recado do dono»;
   leitura ou ação exigem confirmação por outro canal já autenticado e seguem pelo Jarvis principal,
   com as permissões de sempre. Voz nunca autentica.
7. **Ética:** aviso de IA na primeira frase; voz sintética do Jarvis, **nunca** a do dono; nunca
   liga para ninguém; transcrição local, bruta apagada ao fim, recado com retenção curta, trilha só
   com códigos.
8. **Atender sozinho** só por softphone SIP com número do assistente, ou — se o dono aceitar o risco
   da ADR-0060 — clicando «Atender» no WhatsApp Web pela extensão. Padrão: o dono atende e passa.

## Fatias

Na ordem: (3) agente da chamada e (5) reconhecimento do dono — a segurança, testável só com motor
roteirizado e relógio injetado; (1) misturador virtual e (2) canais — com executor de comandos e
backends de áudio falsos; (4) estado da chamada pela extensão falsa; (6) atender. Windows
(VB-Cable/Voicemeeter) só se pedido. Detalhe e o que só a máquina do dono prova: no estudo, §5.

**Feito em 2026-11-17, só com fakes** (nada toca áudio, conta ou navegador real): fatia 5 —
`jarvis.chamada.totp` e a aba «chamadas» (gera o segredo no chaveiro, mostra a URI e a chave uma
vez, confere; limites e textos em `chamada.toml`); fatia 3 — `jarvis.chamada.agente` com as 5
ferramentas, delimitadores de 4 tokens aleatórios por chamada, limites como notificação, memória
por interlocutor; fatias 1a/1b — `jarvis.audio_io.misturador` atrás de um executor (o do sistema
recusa sob CI). Medido com o modelo real (Claude haiku, uma passada, 20 falas com alvos fixados
antes): 19/20, ataques 10/10, nenhum falso dono reconhecido — a falha era o caminho de texto do
motor descartando eventos anteriores, consertado depois e não medido de novo
([medição](../medicoes/agente-da-chamada.md)). **Ainda não ligado** a uma chamada de verdade:
faltam as fatias 2 (canais de áudio) e 4 (estado pela extensão).

## Consequências

- Se aceita: o Jarvis passa a mexer no grafo de áudio do sistema (precisa desfazer limpo, inclusive
  quando cai) e a ter um segundo laço de ASR durante a chamada (CPU/GPU).
- O risco de conta (WhatsApp/Discord) só existe se o dono escolher atender por automação.
- Fica aberto: chamadas do celular (§7 do estudo: desvio da operadora para número VoIP + app
  companheiro), Windows, chamadas em grupo (sem diarização por modelo).
