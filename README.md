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

`tools/verificar.py` roda, na ordem, o que o CI roda: formatador, linter, tipos, testes e a
porta de licença. É o mesmo comando em qualquer sistema — é isso que o P11 exige.

Para ver o esqueleto dos sete processos funcionando, ou refazer a medição da memória:

```bash
uv run --frozen python tools/rodar_esqueleto.py     # evento sintético atravessa os 7 processos
uv run --frozen python tools/harness_memoria.py     # mede SLO-11 e SLO-12 (docs/medicoes/)

# Harness de captura (cartão F0-04). Precisa do grupo `medicao`, que NÃO entra no CI nem no
# produto, e do peso do silero-vad, que não é versionado aqui:
uv sync --group medicao
uv run --frozen --group medicao python tools/harness_captura.py --modelo /caminho/silero_vad.onnx
```

Para rodar um pedaço só:

```bash
uv run ruff format --check .   # formatação
uv run ruff check .            # linter (barra shell irrestrito, SPEC §4)
uv run mypy                    # tipos (strict)
uv run pytest                  # testes
uv run python tools/corpus.py verificar        # corpus confere com o manifesto de hashes
uv run python tools/manifesto.py validar       # manifestos de capacidade (§4)
uv run python tools/manifesto.py lint          # regras de catálogo (§4, ADR-0010)
uv run python tools/license_gate.py --tabela   # porta de licença (ADR-0011)
```

## Estado

Fase **F0** — esqueleto, medição e portas de qualidade. Nenhuma capacidade real, nenhum
código de produto de voz: cada cartão entrega esqueleto, teste e número.

| Cartão | Estado |
|---|---|
| F0-01 repositório, licença, linter, CI nos dois SOs | feito |
| F0-02 barramento tipado com log encadeado por hash | feito |
| F0-09 porta de licença no CI | feito |
| F0-03 os sete processos e o evento que atravessa tudo | feito |
| F0-06 política: raízes, canonicalização, suíte de TOCTOU | feito |
| F0-05 harness da memória em grafo (SLO-11, SLO-12) | feito |
| F0-04 latência de captura e a proposta de D1 | feito |
| F0-07 ferramental de manifesto de capacidade | feito |
| F0-08 estrutura do corpus e exportador de C1 | feito |
| F0-10 ADRs com os números medidos | feito |

## Linguagem do núcleo

**D1 está decidida**: [ADR-0014](docs/adr/0014-d1-linguagem-e-ipc-do-nucleo.md), aceita em
2026-10-15 — **Python 3.12 nos sete processos no v0**, porque todo o nosso caminho de
captura→evento soma 0,575 ms p95 (0,72% do orçamento de 80 ms do SLO-1) e a diferença para
Rust é 0,14% do orçamento.

A fronteira continua trocável de propósito: o contrato do barramento vive em arquivos de dados
(`schemas/events.v1.json`, `schemas/event_log.sql`, `schemas/manifesto.v1.json`), então trocar
a linguagem de `audio-io` ou `agentd` não reescreve contrato. O **gatilho de reabertura** está
escrito na ADR: se a medição da F1, com AEC, ASR e TTS reais, passar de 80 ms p95 em
captura→evento, D1 reabre e esses dois processos voltam a ser candidatos a Rust.

## Licença

Apache-2.0 (uso comercial permitido, concessão de patente explícita) — ver [`LICENSE`](LICENSE) e
[ADR-0011](docs/adr/0011-reranker-licenca-comercial.md). Nenhuma dependência ou modelo com
cláusula não comercial entra no produto — dependências, pacote, download do produto e padrões; o
CI verifica isso em todo commit. A única exceção registrada é o motor de **uso pessoal** abaixo,
que fica fora de tudo isso e que a porta de licença confere que continua fora.

## Voz: o padrão e o OmniVoice (só uso pessoal)

**O uso padrão do Jarvis é o motor local `tts-piper-epitran`** (voz `pt_BR-faber-medium` do
`rhasspy/piper-voices`, repositório MIT e *dataset* CC0, lida pelo onnxruntime; fonemização pelo
`epitran`, MIT): roda na sua máquina e permite uso comercial.

**Se você usar o OmniVoice, é uso pessoal e não comercial.** O
[OmniVoice](https://github.com/k2-fsa/OmniVoice) (k2-fsa) clona uma voz a partir de 3–10 s de
referência; o código é Apache-2.0, mas os [pesos](https://huggingface.co/k2-fsa/OmniVoice) são
**CC-BY-NC** e o tokenizador de áudio que vem com eles segue a Boson Higgs Audio 2 Community
License (atribuições no [`NOTICE`](NOTICE)). Ele não é dependência, não vai no AppImage, no
`.deb` nem no `.rpm` e nunca é o padrão: você o instala para si, a partir do repositório, num
Python isolado, e liga declarando o uso pessoal na configuração —
[ADR-0039](docs/adr/0039-omnivoice-motor-opcional-de-uso-pessoal.md) e
[COMO-TESTAR §1.8](docs/COMO-TESTAR.md).

```bash
uv run --frozen python -m tools.instalar_omnivoice                 # mostra o aviso e pede o aceite
uv run --frozen python -m tools.instalar_omnivoice --cadastrar-voz minha \
    --audio ~/Gravações/eu.wav --texto "o que eu falei no áudio" --declaro minha
```

**Clonagem de voz, com ética:** só a sua voz, ou a de quem lhe deu permissão — o model card
proíbe clonagem sem autorização, imitação de pessoa, fraude e golpe. O Jarvis só usa voz que você
cadastrou com essa declaração; não há ferramenta do assistente que clone voz por pedido falado.
O [VoiceStudio](https://github.com/debpalash/VoiceStudio) (AGPL-3.0) é outro programa que usa o
OmniVoice: citado aqui como referência, nenhum código dele está no Jarvis.

## Atribuições

Componentes de terceiros com **atribuição obrigatória** (CC-BY), que aparecem também na tela
"sobre" da interface e em `NOTICE`:

- **nvidia/parakeet-tdt-0.6b-v2** — © NVIDIA Corporation, CC-BY-4.0.
- **nvidia/parakeet-tdt-0.6b-v3** — © NVIDIA Corporation, CC-BY-4.0.

Do motor opcional de **uso pessoal** (não distribuído; ver acima e o `NOTICE`):
**k2-fsa/OmniVoice** (Han Zhu et al., k2-fsa, 2026 — pesos CC-BY-NC) e
**k2-fsa/OmniVoice:audio_tokenizer** ("Built with Higgs Materials licensed from Boson AI USA,
Inc. … and Meta Llama 3 licensed under the Meta Llama 3 Community License").

A lista completa de licenças (modelos, dependências e ferramentas externas) está em
`docs/licencas.md`, gerada por `tools/license_gate.py`. A verificação é parte do CI:
`tools/license_gate.py --verificar-atribuicao` falha se a atribuição sair de qualquer um dos
três lugares.
