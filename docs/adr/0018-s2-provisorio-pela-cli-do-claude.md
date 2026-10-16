# ADR-0018 — O "S2" do aplicativo de teste é provisório: a CLI do Claude, sem ferramenta

**Data:** 2026-10-16 · **Estado:** proposta · **Decide:** dono
**Pedido:** o dono quer **ouvir e falar com o Jarvis hoje**, no terminal, para julgar voz e
latência de ouvido. O laço precisa de alguém que responda entre o ASR e o TTS, e esse alguém
(o `s2` da SPEC §2) é trabalho da F2.
**Alcance:** vale **só** para o aplicativo de teste `jarvis-voz`. Não entra no `agentd`, não
entra no barramento e não participa de decisão de política.

## Contexto

A SPEC §2 descreve o `s2` como o processo que mantém estado de trabalho, planeja, escolhe
capacidade na *shortlist* autorizada e redige resposta — acordado por evento, nunca em laço
cego. Nada disso existe ainda: a F1 entregou o caminho de **voz** (captura, VAD, ASR
incremental, S1, TTS cancelável, barge-in, histórico com `played_ms` real), e o `s2` de hoje
é um processo que sobe, responde ao barramento e não raciocina.

Para o dono testar voz **hoje**, falta só a peça do meio. Há duas formas de não fazer errado:

1. deixar o laço sem resposta (ecoar a transcrição), que testa áudio mas não testa conversa;
2. pôr um gerador de resposta atrás de uma interface pequena, **declarado provisório**, que
   sai inteiro quando a F2 chegar.

Esta ADR propõe a segunda, com a fronteira escrita para que a saída seja barata.

## Decisão proposta

**`jarvis.voz.s2_provisorio.RespostaPelaCli`**: um `GeradorDeResposta` (interface de um método,
`responder(texto) -> str`) que chama a CLI `claude` em modo não interativo, com um prompt de
sistema curto em pt-BR de assistente conversacional, **sem ferramenta e sem acesso a arquivo**.

Cinco regras, e cada uma existe por um motivo deste projeto:

1. **Sem ferramenta, sem arquivo.** `--disallowed-tools` nomeia as ferramentas de efeito e de
   leitura, `--permission-mode manual` não deixa nada ser aprovado sem gente, e o processo roda
   com `cwd` numa **pasta vazia** — não na raiz do repositório, para não haver `CLAUDE.md`,
   nem arquivo do projeto, nem contexto que ninguém pediu. O P1 continua valendo por
   construção: este gerador não tem como executar nada.
2. **A fala do dono vai por `stdin`, nunca em `argv`.** `argv` é legível por qualquer processo
   do usuário (`/proc/<pid>/cmdline`) e entra em histórico; a transcrição do que o dono falou
   é privada. É a mesma regra que a chave de API já segue (`jarvis.voz.chaves`).
3. **O que volta é `untrusted` (P6).** Texto gerado é dado: não amplia permissão, não vira
   memória durável, não escolhe capacidade. No `jarvis-voz` ele só vira voz.
4. **O prazo é nosso** (regra 1 do F1-14). Sem resposta no prazo, o laço **degrada e diz**, em
   vez de pendurar o turno; e o pedido que caiu não é refeito (regra 5 da §3.3).
5. **Cancelável como o resto.** O gerador consulta o mesmo `Cancelado` dos motores de voz: com
   o epoch morto, o processo é encerrado e a resposta descartada — o dono falou por cima, e
   responder a um turno que ele interrompeu é exatamente o que o F1-11 proíbe.

## Alternativas consideradas

- **Modelo local (llama.cpp, Ollama):** sem rede e sem conta, o que é melhor de princípio. Mas
  escolher modelo, medir memória e caber no orçamento do SLO é trabalho de cartão próprio — e
  o dono quer ouvir voz hoje, não comparar LLM. Continua candidato para a F2.
- **API HTTP direta (Anthropic, OpenAI):** mais uma chave para guardar, mais um contrato para
  verificar na origem e mais um motor de nuvem no registro. A CLI já está instalada e
  autenticada na máquina do dono.
- **Respostas enlatadas:** honesto e inútil — não dá para julgar barge-in sem ter o que
  interromper.
- **Esperar a F2:** adia o único julgamento que só o dono pode dar (voz, naturalidade,
  interrupção) para depois de construir tudo em cima de uma voz que ninguém ouviu.

## Consequências

- **Mais fácil:** o dono testa o laço inteiro hoje, com uma peça que cabe em um arquivo.
- **Mais caro:** há um processo externo no caminho do turno, com a latência dele. O relatório
  do aplicativo mostra o tempo da resposta separado do tempo de ASR e de TTS, para ninguém
  culpar a voz pelo que é do gerador.
- **Dívida declarada:** quando a F2 entregar o `s2` de verdade, este arquivo sai e a interface
  `GeradorDeResposta` passa a ser implementada por ele. Nada mais muda no laço.

## Como invalidar esta proposta

- O dono decidir que o aplicativo de teste não pode falar com a nuvem de forma alguma: aí o
  laço fica com o eco da transcrição (há uma opção para isso) até a F2.
- A F2 começar: esta ADR vira "revogada" no mesmo commit que entregar o `s2` de verdade.
- A CLI mudar as opções de que esta decisão depende (`--print`, `--system-prompt`,
  `--disallowed-tools`): o gerador recusa com mensagem clara em vez de rodar sem a trava.
