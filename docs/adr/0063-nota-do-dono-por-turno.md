# ADR-0063 — O dono dá nota ao turno (👍/👎, botão ou frase) e a trilha guarda, sem treinar nada

**Data:** 2026-11-12 · **Estado:** aceita (implementada e testada com a janela offscreen e motores falsos; o uso real é do dono) · **Decide:** dono (os dois botões, as frases que contam, que nada é treinado); arquiteto (onde grava, como a frase é lida)
**Pedido:** backlog do núcleo, item B4 (`docs/estudos/openjarvis-nucleo.md` §8), autorizado pelo dono em 2026-11-12.

## Contexto

- Sem um sinal de qualidade do dono, não dá para comparar presets por acerto (B5) nem montar casos de teste a partir do uso (B12). A trilha já tem tempo e custo (ADR-0061), mas não diz se a resposta serviu.
- A ideia vem do `feedback` dos traces do OpenJarvis (`OJ/cli/feedback_cmd.py`, `OJ/traces/store.py`, commit 13706f2). Nenhum código foi copiado.

## Decisão

1. **Dois jeitos de dar nota, os dois ao último turno que acabou:**
   - **botão** 👍/👎 ao lado da última resposta do Jarvis na conversa da janela;
   - **frase** no começo da fala seguinte, lida pelo código (`jarvis.s2.nota_do_dono.nota_na_fala`): «ficou ótimo», «mandou bem», «boa, Jarvis» são boa; «ficou ruim», «não era isso», «você errou», «não gostei» são ruim.
2. **A frase não muda o turno.** Ela é anotada e segue para o cérebro como qualquer fala: «não era isso, eu queria a planilha» continua sendo um pedido. O dono não ouve «anotado».
3. **Leitura conservadora.** A frase tem de estar nas 6 primeiras palavras. Fala com as duas notas, ou com a nota negada («não ficou ruim»), não anota. «Valeu» e «isso mesmo» não contam: são agradecimento e confirmação. A frase vale só se o turno anterior acabou há menos de 10 minutos.
4. **Trilha:** o evento `turno.nota` vai com o id do turno avaliado e leva `nota` (`boa`, `ruim`) e `origem` (`botao`, `voz`). Nunca o texto da fala. Vale a última nota de cada turno: o clique corrige a frase.
5. **Nada é treinado.** Nenhum prompt, peso, preset ou memória muda com a nota. O `--diagnostico` mostra a contagem por dia, e é só isso. Usar a nota para sugerir preset é o B5, e lá também só sugere (ADR-0056).

## Alternativas descartadas

- **O Jev ou o motor classificando a fala:** custaria uma chamada por turno para um sinal que o dono dá raramente. E «isso ficou bom?» (pergunta) viraria nota.
- **Responder «anotado» na frase de voz:** mudaria a conversa. O dono pediu o registro, não um diálogo sobre a nota.
- **Nota de 1 a 5:** o dono dá nota de passagem. Dois botões bastam para comparar.

## Consequências

- O botão aparece só na última linha do Jarvis, e só depois de um turno acabar. Uma nota nova no mesmo turno troca a anterior: o botão aceso mostra a que vale.
- A frase de nota no meio de um pedido longo («abre o arquivo e diz se ficou bom») não anota: está longe do começo.
- Testes: `tests/unit/s2/test_nota_do_dono.py`, `tests/unit/voz/test_nota_do_turno.py` e `tests/unit/gui/test_nota_na_janela.py` (offscreen), sem microfone.

## Como invalidar esta decisão

Se a trilha mostrar `turno.nota` de voz em turnos que o dono diz que não avaliou, a frase que disparou sai da lista. Se em um mês houver menos de 20 notas, o botão não está sendo visto: ele muda de lugar antes de o B5 depender dele.
