# J.A.R.V.I.S

Assistente pessoal de desktop com voz bidirecional, **Linux (Wayland e X11) e Windows desde a F0**.
Reescrita do zero; o código antigo é referência histórica fora deste repositório.

A especificação é a fonte de verdade: [`docs/SPEC-v0.md`](docs/SPEC-v0.md), decisões em
[`docs/adr/`](docs/adr/), cartões de tarefa da fase atual em [`docs/F0-tarefas.md`](docs/F0-tarefas.md).

## Como rodar tudo (uma linha por sistema)

Pré-requisito único: [uv](https://docs.astral.sh/uv/) (ele baixa o Python 3.12 do projeto).

```bash
# Linux / macOS
uv run --frozen python tools/verificar.py
```

```powershell
# Windows (PowerShell)
uv run --frozen python tools/verificar.py
```

`tools/verificar.py` roda, na ordem, o que o CI roda: formatador, linter, tipos e testes. É o mesmo comando em qualquer sistema — é isso que o P11 exige.

Para rodar um pedaço só:

```bash
uv run ruff format --check .   # formatação
uv run ruff check .            # linter (barra shell irrestrito, SPEC §4)
uv run mypy                    # tipos (strict)
uv run pytest                  # testes
```

## Estado

Fase **F0** — esqueleto, medição e portas de qualidade. Nenhuma capacidade real, nenhum
código de produto de voz: cada cartão entrega esqueleto, teste e número.

| Cartão | Estado |
|---|---|
| F0-01 repositório, licença, linter, CI nos dois SOs | feito |
| F0-02 barramento tipado com log encadeado por hash | aberto |
| F0-09 porta de licença no CI | aberto |
| F0-03 a F0-08, F0-10 | abertos |

## Linguagem do núcleo

A linguagem definitiva dos processos de áudio é a **decisão D1**, que se fecha por medição no
cartão F0-04 (p95 de captura→evento em Rust e em Python+ONNX). Até lá o esqueleto é Python 3.12
e o contrato do barramento vive em arquivos de dados — `schemas/events.v1.json`
e `schemas/event_log.sql` — para que trocar a linguagem de um processo não reescreva o
contrato. Ver [`docs/notas-executor-F0.md`](docs/notas-executor-F0.md).

## Licença

Apache-2.0 (uso comercial permitido, concessão de patente explícita) — ver [`LICENSE`](LICENSE) e
[ADR-0011](docs/adr/0011-reranker-licenca-comercial.md). Nenhuma dependência ou modelo com
cláusula não comercial entra no repositório; o CI verifica isso em todo commit.
