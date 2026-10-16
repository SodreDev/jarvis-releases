# S2 provisório (`claude -p`) em streaming — tempo até o primeiro texto e cancelamento

**Feito por:** planejador, 2026-10-16, à mão (script no apêndice, **não** versionado como
harness). **Para:** ADR-0025. **Não é medição de harness:** `n` pequeno, rede doméstica, sem
repetição em dias diferentes. Serve para dizer de que tamanho é o problema, não para fechar SLO.

## Como foi medido

- hardware: AMD Ryzen 5 5600G (o mesmo da F1-09), Linux 7.2.9 (Nobara/Fedora 44), rede doméstica
  não caracterizada; Claude Code `2.1.302`; repositório em `bdc1ac6` (o código do Jarvis não
  participa: o script chama a CLI direto).
- comando: `claude --print --verbose --output-format stream-json --include-partial-messages
  --system-prompt <o PROMPT_DE_SISTEMA da ADR-0018, sem a última frase> --tools ""
  --permission-mode manual --no-session-persistence --strict-mcp-config
  --disable-slash-commands`, com `cwd` numa pasta vazia, a pergunta por `stdin`.
- **avulso** = um processo por pergunta (o que o `jarvis-voz` faz hoje, mas com stream).
  **contínuo** = um processo só, `--input-format stream-json`, as perguntas como turnos da mesma
  conversa; o relógio começa quando a mensagem é escrita no `stdin`.
- 8 perguntas curtas em pt-BR, repetidas em ciclo. Marcas por turno: **1º texto** (primeiro
  `text_delta`), **1ª fronteira** (o texto acumulado tem 3 palavras ou uma pontuação de corte —
  o que o `fatiar()` do `agentd/tts.py` precisa para sintetizar o primeiro pedaço) e **fim**
  (evento `result`).
- "modelo padrão" = o que a CLI usa nesta conta sem `--model`; o nome não foi registrado.

## Resultado (mediana, mínimo e máximo de cada série, em ms)

| série | n | 1º texto (mediana) | 1ª fronteira (mediana) | 1ª fronteira (mín–máx) | fim (mediana) |
|---|---:|---:|---:|---:|---:|
| avulso, `haiku` | 10 | 1263 | 1388 | 1181–2279 | 1588 |
| contínuo, `haiku` | 10 | 944 | 992 | 860–1822 | 1293 |
| avulso, modelo padrão | 6 | 1899 | 2021 | 1224–2919 | 2409 |
| contínuo, modelo padrão | 6 | 2257 | 2330 | 1082–3727 | 3039 |
| contínuo, `sonnet`, `--effort low` | 6 | 1036 | 1050 | 797–2091 | 1657 |

O primeiro turno do modo contínuo inclui o fim da inicialização do processo (1822 ms no `haiku`);
sem ele, a mediana da 1ª fronteira do `haiku` contínuo fica em 980 ms.

Valores por turno, em segundos (1º texto / 1ª fronteira / fim):

- avulso `haiku`: 1.40/1.43/1.70 · 2.28/2.28/2.63 · 1.40/1.40/1.47 · 1.30/1.30/1.37 ·
  1.23/1.23/1.59 · 1.56/1.81/1.84 · 1.16/1.32/1.55 · 1.21/1.38/1.71 · 1.18/1.18/1.25 ·
  1.23/1.40/1.58
- contínuo `haiku`: 1.80/1.82/2.06 · 0.78/0.97/1.30 · 1.03/1.28/1.29 · 0.94/0.94/1.23 ·
  1.04/1.04/1.41 · 0.98/1.01/1.23 · 0.85/0.86/1.29 · 0.80/1.18/1.21 · 0.86/0.86/1.11 ·
  0.94/0.98/1.36
- avulso padrão: 1.54/1.54/2.26 · 2.10/2.13/3.02 · 1.89/2.53/2.56 · 1.91/1.91/2.22 ·
  2.92/2.92/3.82 · 1.22/1.22/1.85
- contínuo padrão: 1.51/1.51/2.25 · 1.16/1.63/2.33 · 3.01/3.73/3.75 · 3.03/3.03/3.89 ·
  3.41/3.64/4.95 · 1.08/1.08/1.78
- contínuo `sonnet` low: 1.18/1.21/1.71 · 0.76/0.80/1.60 · 1.72/1.75/2.21 · 0.89/0.89/1.44 ·
  2.09/2.09/2.61 · 0.80/0.84/1.32

## Cancelamento no modo contínuo (n = 1, observação)

Pedido longo ("conte de um até cento e cinquenta por extenso"); depois de 6 palavras recebidas,
o script escreveu no `stdin` `{"type":"control_request","request_id":"int-1",
"request":{"subtype":"interrupt"}}`.

- `control_response` com `success` em 2 ms; evento `result` com `subtype:
  error_during_execution` em 8 ms. Chegaram 13 palavras ao todo ("… doze, tre").
- **O processo continuou vivo** e respondeu ao turno seguinte.
- Perguntada qual foi a última resposta, a CLI disse que foi "a contagem que comecei, mas ela
  ficou incompleta e truncada". Ou seja: **a conversa da CLI guarda o texto gerado até o corte, e
  não o texto que tocou no alto-falante.** Com TTS e fila de áudio atrás do texto, o tocado é
  sempre menor que o gerado. É o P4 da SPEC, e é o motivo da regra 3 da ADR-0025.
- **Não verificado:** se o servidor para de gerar e de cobrar no instante do `interrupt` (a CLI
  não mostra tokens gerados depois do corte).

## O que não foi medido

- a mesma coisa pela API HTTP direta (sem o processo da CLI no meio);
- motor local (nenhum instalado para isso nesta máquina);
- carga de contexto realista (histórico de vários turnos, memória recuperada, lista de tools):
  aqui o contexto é o prompt curto mais a conversa do próprio teste;
- dias e horários diferentes; percentis altos (o `n` não sustenta p95).

## Apêndice — o script

Rodado de uma pasta fora do repositório com `python3 -I medir.py <avulso|continuo> <modelo|->
<effort|-> <n>`. O núcleo:

```python
def base(modelo, effort):
    a = ["claude", "--print", "--verbose", "--output-format", "stream-json",
         "--include-partial-messages", "--system-prompt", PROMPT, "--tools", "",
         "--permission-mode", "manual", "--no-session-persistence",
         "--strict-mcp-config", "--disable-slash-commands"]
    return a + (["--model", modelo] if modelo else []) + (["--effort", effort] if effort else [])

def ler_turno(saida, t0):          # lê eventos até o `result`
    ttft = tfrase = None; texto = ""
    for linha in saida:
        ev = json.loads(linha)
        if ev.get("type") == "stream_event":
            e = ev["event"]
            if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                agora = time.monotonic(); texto += e["delta"]["text"]
                ttft = ttft or agora - t0
                if tfrase is None and (len(texto.split()) >= 3
                                       or any(p.endswith(CORTE) for p in texto.split())):
                    tfrase = agora - t0
        elif ev.get("type") == "result":
            return ttft, tfrase, time.monotonic() - t0, texto

# contínuo: + ["--input-format", "stream-json"], e cada turno é
# {"type":"user","message":{"role":"user","content":[{"type":"text","text": pergunta}]}}
```
