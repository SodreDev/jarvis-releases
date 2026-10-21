# Handoff — OmniVoice, motor de TTS opcional de uso pessoal (ADR-0039)

Pedido do dono (2026-10-21): integrar o OmniVoice (k2-fsa) como motor TTS **opcional e só de uso
pessoal** — pesos CC-BY-NC —, sem nunca virar padrão, dependência ou parte do pacote.

## O que existe

| peça | onde | o que faz |
|---|---|---|
| registro | `licenses/modelos.toml`, `licenses/motores.toml` | estado `uso_pessoal`: `k2-fsa/OmniVoice` (CC-BY-NC) e `…:audio_tokenizer` (Boson), revisão `c5fdb5ccb189`, 11 sha256; motor `tts-omnivoice` local, `ligado = false` |
| porta de licença | `tools/license_gate.py` (`conferir_uso_pessoal`, código 6) | falha se o OmniVoice ou o PyTorch entrarem no caminho do produto (pyproject, trava, ambiente, `src/`, download do produto, padrão, NOTICE) |
| empacotador | `tools/empacotar.py` (`FORA_DO_PACOTE`) | recusa montar com `omnivoice`/`torch`/`torchaudio` na trava exportada ou no AppDir |
| instalador | `tools/instalar_omnivoice.py` | aviso → aceite explícito → dispositivo → venv isolado → pacotes fixos → pesos com sha256 → `--verificar` → `aceite.json`; `--estado`, `--remover`, `--cadastrar-voz`, `--vozes`, `--remover-voz` |
| trabalhador | `tools/omnivoice_trabalhador.py` (copiado para a pasta do motor) | o único processo que importa `omnivoice`/`torch`; protocolo tamanho + JSON + float32 24 kHz |
| motor | `src/jarvis/voz/omnivoice.py` | `MotorTtsOmniVoice` (cliente), `MotorComReserva` (cai no padrão), guardas de voz, diagnóstico |
| configuração | `jarvis-voz.toml` | `tts = "tts-omnivoice"` + `omnivoice_uso_pessoal = true` + `voz_omnivoice = "<voz>"` |
| política | `src/jarvis/politica/modos.py` | lista de negação fecha `~/.local/share/jarvis/vozes` e `…/omnivoice` às ferramentas de arquivo |

Comandos do dono (no repositório):

```bash
uv run --frozen python -m tools.instalar_omnivoice                       # aviso + "aceito uso pessoal"
uv run --frozen python -m tools.instalar_omnivoice --cadastrar-voz minha \
    --audio ~/Gravações/eu.wav --texto "o que eu falei" --declaro minha
# e em ~/.config/jarvis/jarvis-voz.toml:  tts = "tts-omnivoice" · omnivoice_uso_pessoal = true · voz_omnivoice = "minha"
uv run jarvis-voz --diagnostico                                           # seção "OmniVoice"
```

## Decisões que não são óbvias

- **Instalador em `tools/`, não `jarvis-voz --instalar-omnivoice`:** o que está em `src/` vai no
  AppImage/`.deb`/`.rpm`; o caminho para baixar pesos não comerciais não pode ir junto.
- **venv isolado, não grupo do `pyproject`:** a roda CUDA do PyTorch depende do driver; no grupo,
  a trava fixaria GBs de PyTorch para todos e a porta teria de tolerar `omnivoice` na trava.
- **processo à parte, com ambiente fechado:** o Jarvis não importa `torch`; o filho recebe uma lista
  fechada de variáveis (nenhuma chave de API) e o Hugging Face offline.
- **ordem de chegada:** o `SintetizadorEmStreaming` põe três lotes ao mesmo tempo; o trabalhador faz
  um por vez — a trava por senha (`_Vez`) garante que o N+2 não passa na frente do N.
- **reserva definitiva para a sessão:** caiu (sem GPU, OOM, processo morto, prazo), fala o
  `tts-piper-epitran` até o fim; tentar de novo a cada lote trocaria a voz no meio da frase e
  recarregaria 3 GB.
- **a transcrição da referência é do dono:** o Whisper automático do OmniVoice nunca roda (baixaria
  outro modelo e facilitaria clonar áudio qualquer).
- **a declaração é do dono:** o código não verifica identidade; exige a declaração, prende-a ao
  sha256 do áudio e recusa áudio de URL ou das pastas onde o Jarvis grava/baixa sozinho.

## Provado e não provado (2026-10-21)

Provado com testes (fakes, sem `pip` nem peso reais): a porta falha em cada porta de entrada do
produto; o instalador não faz nada sem aceite, registra o aceite, é idempotente, reverte só a pasta
marcada e, sob `CI=1`, não consegue baixar os pesos reais; o motor fala com o trabalhador **real**
contra um `torch`/`omnivoice` de mentira (16 kHz, ordem, cancelamento, sem GPU, carga quebrada,
erro, processo morto, prazo, protocolo); a reserva e as guardas de voz.

Provado de verdade **num contêiner podman só com CPU** (imagem `python:3.12-slim-bookworm`, nunca
nesta máquina): o instalador real criou o venv, instalou `torch 2.8.0+cpu`, `torchaudio 2.8.0+cpu`,
`omnivoice 0.2.1` e `transformers 5.20.2`, baixou os 11 arquivos e **todos os sha256 do registro
conferiram**, `--verificar` passou, `--estado` disse "pronto", e a reexecução não reinstalou nem
rebaixou nada. A síntese real pelo motor do Jarvis também rodou lá: **na CPU, um lote de 16 a 17
palavras levou 114 s e 180 s** (n = 2, fator de tempo real 15–19×; noutra rodada, com o prazo padrão, esse mesmo primeiro lote
passou dos 120 s e o motor encerrou o trabalhador — exatamente o caminho da reserva). Detalhes em
[`docs/medicoes/omnivoice-cpu-conteiner.md`](../medicoes/omnivoice-cpu-conteiner.md). A medição
foi interrompida no terceiro lote a pedido do dono (a máquina era dele naquela hora).

**Não provado:** o OmniVoice na GPU do dono (RTX 4060), a qualidade em pt-BR e da clonagem (a
referência da medição é um sinal sintético, não uma voz), a latência na máquina do dono, o som no
alto-falante, macOS/MPS e Windows.

## Se mudar

- **o trabalhador** (`tools/omnivoice_trabalhador.py`): suba `PROTOCOLO` nos dois lados se a forma
  das mensagens mudar; o dono reinstala (até lá o hash não confere e fala o padrão);
- **a revisão dos pesos:** registre os novos sha256 nos dois registros; o aceite antigo deixa de
  valer e o instalador pergunta de novo;
- **as versões fixas** (`VERSOES` do instalador): teste a instalação real em contêiner antes.
