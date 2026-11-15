# ADR-0069 — O Jarvis formula, não repassa: delegação, navegador e mensagens

**Data:** 2026-11-15 · **Estado:** aceita (testada só com fakes: `claude` falso, página falsa, motor roteirizado; o uso real é do dono) · **Decide:** dono (o comportamento de assistente, não de automação), arquiteto (onde cada regra mora)
**Pedido:** dono, 2026-11-15 (memória `fa335dd0`), depois de 5a09ba9. Emenda: ADR-0066 (execução direta e relato verdadeiro), ADR-0054 (delegar ao Claude Code). Relaciona: ADR-0038 (ciclo do objetivo), ADR-0051 (CDP), ADR-0060 (envio social).

## Contexto

O dono viu o Jarvis agir como automação: repassar a fala dele literal ao subagente, agir na página sem lê-la (e desistir no primeiro erro) e mandar a mensagem com o texto ditado, palavra por palavra. Um assistente pessoal formula o pedido, lê antes de agir e escreve a mensagem com as próprias palavras.

## Decisão

### 1. Delegar é formular

- **`delegar.claude_code` v2:** o contrato exige o pedido formulado — `tarefa` (o objetivo nas palavras do Jarvis), `passos` (1 a 12), `pronto_quando`, `devolver`; `contexto` e `site` opcionais. O subagente recebe o pedido em seções (`OBJETIVO`, `CONTEXTO`, `COMECE POR`, `PASSOS`, `PRONTO QUANDO`, `DEVOLVA`), montado por `jarvis.delegacao.pedido.texto`; o guarda de contexto (ADR-0049) julga esse mesmo texto.
- **A cópia não sai:** `pedido.recusa` compara o objetivo e cada passo com a fala do dono (texto normalizado: igual, `SequenceMatcher` ≥ 0,8, ou a fala recortada). Cópia volta ao motor como `erro` com causa `pedido_nao_formulado` e a instrução de formular — o `claude` nem é chamado. Fala curta (menos de 3 palavras) só conta quando igual.
- **Responder depois do retorno:** a delegação roda na tarefa do pedido (nunca é o 1º passo, `delegar_cedo`), e a resposta ao dono é a rodada seguinte do motor, com o resultado na mão; o relato verdadeiro (ADR-0066 §2) continua cortando o que nada confirmou.
- **Persona v18:** «Ao delegar, formule o pedido … sem copiar o dono; responda com o que voltou» — vale também para `tarefa.iniciar` (só na instrução: a descrição dela é curta demais para a régua da cópia).

### 2. Ler a página antes de agir, e reler depois do erro

- **O código garante a ordem** (`jarvis.s2.leitura_da_pagina`): a ação na página (`browser.click`, `browser.type`, `browser.acionar`, `browser.gesto`) só roda depois de uma leitura que ainda vale (`browser.inspecionar`, `browser.read`, `browser.tela`). A leitura deixa de valer quando a página muda (`browser.navigate`, `sites.open`, `browser.launch`, ou um clique/acionamento/gesto que deu certo — digitar não muda) e quando um passo na página **falha**. Faltando a leitura, o passo vira a inspeção da mesma aba e o motor decide de novo com o mapa na mão (`NOTA_DA_LEITURA`). Vale no turno (`Cerebro`) e na tarefa (`MotorDoObjetivo`), até `LEITURAS_FORCADAS` (6) por pedido; depois, o orçamento da recuperação (ADR-0038) e a guarda de laço (ADR-0062).
- **O roteiro (985ffb1)** manda `browser.inspecionar` antes de cada ação e, quando um passo falha, reler, achar o campo ou botão certo e tentar de novo — até `TENTATIVAS_POR_PASSO` (3) por passo antes de dizer o que falhou.
- **As ferramentas** dizem isso a quem as lê: o `quando` da `browser.inspecionar` («ler a página antes de agir e depois de um erro») e a descrição de `browser.click`/`type`/`acionar`. O subagente do navegador (Claude Code, ADR-0054) recebe a mesma regra nas regras fixas dele.

## Alternativas descartadas

- **Uma chamada extra ao motor só para reescrever o pedido antes de delegar:** mais uma ida ao modelo em cada delegação, e o motor que já está no laço tem o mesmo contexto. O contrato estruturado obriga a formulação na própria proposta, e a régua da cópia pega quem não formulou.
- **Repassar a fala do dono junto «para referência»:** é o que o dono pediu para acabar; o contexto que importa vai em `contexto`, escrito pelo Jarvis.

## Como testar

`tests/unit/delegacao/test_pedido_formulado.py` (a régua da cópia e as seções) e, em `tests/unit/delegacao/test_delegar_claude_code.py`, os testes do fim (a cópia não chega ao `claude` falso; a entrada padrão chega em seções; sem `passos`/`pronto_quando`/`devolver` é fora do contrato). `tests/unit/s2/test_leitura_da_pagina.py` (a regra pura, a inspeção que o turno põe antes da ação sem leitura, o roteiro com ler e depurar) e o `test_relato_verdadeiro` (o envio do WhatsApp falso lê antes de digitar).
