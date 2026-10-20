# Handoff — TTS contínuo com síntese antecipada

## Decisão do dono

A fala não pode esperar um bloco terminar para começar a sintetizar o seguinte. Enquanto N toca,
N+1 e N+2 devem estar em síntese, mas a reprodução continua rigorosamente sequencial. Lote normal
tem no mínimo 14 palavras; somente o residual do fim pode ser menor. Token é atômico por espaço:
hífen pertence à palavra e tamanho excepcional não autoriza corte por caractere.

## Implementação

```text
deltas do modelo → fatiador 14..18 → janela de síntese (máx. 3) → ordem de entrada → playback
                         fim → residual <14                 epoch ────────┴→ descarte
```

- `jarvis.fatiador` espera 14 palavras, prefere pontuação entre 14 e 18 e usa 18 como teto. O
  fechamento do stream libera o residual. A tokenização só observa espaço, sem limite destrutivo
  de caracteres.
- `SintetizadorEmStreaming` é o agendador provider-agnóstico. Um produtor consome texto sem bloquear
  a linha do player e uma janela de três futures permite a síntese atual mais duas antecipadas. A
  fila e um semáforo impõem backpressure; conclusão fora de ordem fica retida até chegar sua vez.
- `Aplicativo._tocar` continua sendo o dono da reprodução sequencial. A fila de `ResponseChunk`
  entre o cérebro e o TTS **não tem teto** (correção de 2026-10-20): com teto de 3, o cérebro
  parava de ler o motor enquanto o alto-falante falava — a tela voltava ao ritmo da fala e o prazo
  total do motor (30 s no `claude -p`, conferido a cada `next()`) cortava resposta longa. Quem
  limita o trabalho é a janela de síntese acima; o texto é pequeno.
- O primeiro `False` de `FilaDePlayback.enfileirar` encerra o pipeline. Todos os iteradores são
  fechados explicitamente pelo produtor; future ainda não iniciada é cancelada e resultado tardio
  não atravessa para a fila nem para outro epoch. A vaga é obtida **antes** de ler outro trecho:
  enquanto N toca, há no máximo três sínteses futuras, inclusive resultados já prontos.
- O teclado é consultado na linha do player também durante a espera por texto/síntese. Avanço do
  epoch esvazia o playback inclusive antes do primeiro áudio; recusa por epoch marca o turno como
  interrompido. Um `put` bloqueado na fila do cérebro acorda no cancelamento. O encerramento do
  consumidor também cancela a geração: uma recusa ou erro de síntese não deixa o cérebro preso
  tentando publicar, mesmo se o epoch local ainda não mudou.
- Cada aviso tem seu próprio fatiador, fechado no fim da frase completa. Esse residual pode ter
  menos de 14 palavras: ele é o fim daquele aviso, não um lote normal da resposta. Identidade,
  ordem antes da resposta, entrega apenas quando tocou inteiro e retorno do aviso cortado à fila
  continuam com a mesma semântica.
- As interfaces `MotorDeTts.sintetizar`, `falar_para`, `falar_stream_para`, `pedacos` e
  `pedacos_do_stream` foram preservadas. Não houve alteração em provider, configuração, tools, PDP,
  navegador ou empacotamento.

## Evidência e testes

A documentação oficial da ElevenLabs recomenda streaming para reduzir o tempo até o primeiro áudio
e explica o compromisso inevitável: pouco texto reduz latência mas piora contexto/prosódia; buffer
maior melhora naturalidade mas espera mais. O WebSocket usa `chunk_length_schedule` justamente para
administrar esse equilíbrio e `flush` apenas no fim do turno:

- [Latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)
- [Generate audio in real-time](https://elevenlabs.io/docs/eleven-api/guides/how-to/websockets/realtime-tts)
- [Understanding audio streaming](https://elevenlabs.io/docs/eleven-api/concepts/audio-streaming)

Os testes determinísticos cobrem:

- equivalência entre texto inteiro e deltas, mínimo 14, residual final, pontuação, hífen e token
  excepcionalmente longo;
- N+1 e N+2 iniciados antes de o player falso terminar N, conclusão fora de ordem e reprodução em
  ordem;
- janela limitada/backpressure;
- avanço de epoch com sínteses em voo, sem pedaço tardio na fila;
- fechamento explícito com a entrada ainda referenciada; fonte bloqueada não inicia síntese ao
  retornar depois do cancelamento; erros de entrada/ordem e timeout do provider chegam ao consumidor;
- cancelamento antes do primeiro áudio pela tecla na linha do player, com fila pendente esvaziada;
- geração bloqueada em fila cheia acordando no epoch e recusa da fila marcando o turno interrompido;
- avisos curtos/longos separados por identidade, sem mistura com o aviso seguinte ou a resposta;
- vinte pontos de barge-in no caminho integrado, metade durante geração e metade no playback;
- mapa texto/amostras e tela ainda acompanhando a geração, não o ritmo do alto-falante.

## Diagnóstico da regressão dos avisos

Os três testes originais de `tests/unit/s2/test_avisos.py` falhavam porque `_falar_avisos` usava
o mesmo fatiador para todos os avisos e para a resposta. Antes, o ponto encerrava imediatamente
uma frase curta. Com o novo piso de 14 palavras, o aviso curto ficava no buffer, saía junto com
outro aviso e recebia o `notif_id` errado — ou saía na resposta sem identificador. A correção
fecha cada aviso completo separadamente, sem diminuir o piso dos lotes normais nem mudar a
contabilidade baseada no que tocou. Os três testes foram mantidos, com regressões adicionais
para aviso longo seguido de curto e cancelamento após um aviso curto.

## Verificação nesta entrega (2026-10-19)

Comandos reproduzíveis, sem áudio ou navegador reais:

```bash
uv run --frozen pytest tests/unit/agentd/test_pipeline_tts.py tests/unit/agentd/test_fala_em_stream.py tests/unit/agentd/test_tts.py tests/unit/test_fatiador.py tests/unit/s2/test_avisos.py tests/unit/voz/test_app.py tests/unit/voz/test_app_pipeline_tts.py tests/unit/voz/test_app_pedacos_na_tela.py tests/integration/test_cancelamento_stream.py -ra
uv run --frozen pytest tests/unit/agentd tests/unit/s2 tests/unit/test_fatiador.py tests/unit/voz tests/integration/test_cancelamento.py tests/integration/test_cancelamento_stream.py -ra
```

Format/lint/typecheck limitados aos 13 arquivos Python desta tarefa; mypy com cache isolado em
`/tmp/jarvis-tts-continuo-mypy`. Nenhum portão global de formatação foi executado. O commit anterior
`0cfd83e` (reconexão) e os arquivos do orquestrador ficaram fora das alterações desta entrega.

- Suíte focada acima: **104 passed**, em 36,71 s.
- Após o ajuste final de encerramento da geração: os três testes de
  `tests/unit/voz/test_app_pipeline_tts.py` passaram novamente (**3 passed**, em 0,18 s).
- Regressão ampla final acima: **825 passed, 2 skipped**, em 160,91 s. Os dois skips são os
  casos existentes de `tests/unit/agentd/test_historico.py:48` em que a resposta tocou inteira
  e não restou sufixo para conferir. A ampla inclui todos os testes da suíte focada.
- `ruff format --check`: **13 files already formatted**.
- `ruff check`: **All checks passed**.
- `mypy`: **Success: no issues found in 13 source files**.

## Limites honestos

- Nenhum microfone, alto-falante, piper, ElevenLabs ou Edge real foi usado nesta correção.
- Síntese local já iniciada é atômica: não é interrompida por dentro, mas seu resultado é descartado.
  Os providers remotos continuam consultando cancelamento durante o corpo da resposta.
- Uma fonte externa que bloqueie dentro de `next()` não pode ser fechada à força por outra thread.
  O consumidor cancela sem esperar; o produtor fecha essa fonte quando ela retorna, descartando o
  trecho sem iniciar nova síntese. O caminho do aplicativo usa espera curta e consulta o epoch.
- O tamanho 14..18 e a janela três são decisões iniciais do dono, provadas estruturalmente, mas a
  naturalidade, ausência de lacunas, consumo de CPU, concorrência da conta de nuvem e latência
  ponta a ponta ainda precisam ser medidas no hardware/rede reais.
