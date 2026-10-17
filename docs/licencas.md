# Licenças dos modelos — tabela licença × modelo × fonte

Gerado por `tools/license_gate.py --escrever-tabela` a partir de `licenses/modelos.toml`.
**Não edite à mão**: o CI compara este arquivo com o registro e falha se divergirem
(aceite (b) do cartão F0-09).

Fonte válida é o model card oficial do repositório do modelo (API do Hugging Face) ou o
arquivo de licença do repositório de origem (API do GitHub) — nunca agregador de terceiro.
Refazer a verificação na origem: `tools/license_gate.py --online`.

| papel | modelo | licença | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|---|
| asr | `nvidia/parakeet-tdt-0.6b-v2` | CC-BY-4.0 | atribuicao | candidato | <https://huggingface.co/api/models/nvidia/parakeet-tdt-0.6b-v2> | 2026-10-15 |
| asr | `nvidia/parakeet-tdt-0.6b-v3` | CC-BY-4.0 | atribuicao | candidato | <https://huggingface.co/api/models/nvidia/parakeet-tdt-0.6b-v3> | 2026-10-15 |
| asr | `openai/whisper-large-v3` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/openai/whisper-large-v3> | 2026-10-15 |
| asr | `openai/whisper-small` | Apache-2.0 | permissiva | em_uso | <https://huggingface.co/api/models/openai/whisper-small> | 2026-10-15 |
| embedding | `BAAI/bge-m3` | MIT | permissiva | candidato | <https://huggingface.co/api/models/BAAI/bge-m3> | 2026-10-15 |
| embedding | `intfloat/multilingual-e5-base` | MIT | permissiva | candidato | <https://huggingface.co/api/models/intfloat/multilingual-e5-base> | 2026-10-15 |
| embedding | `intfloat/multilingual-e5-small` | MIT | permissiva | em_uso | <https://huggingface.co/api/models/intfloat/multilingual-e5-small> | 2026-10-16 |
| embedding | `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/Qwen/Qwen3-Embedding-0.6B> | 2026-10-15 |
| reranker | `BAAI/bge-reranker-v2-m3` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/BAAI/bge-reranker-v2-m3> | 2026-10-15 |
| reranker | `jinaai/jina-reranker-v2-base-multilingual` | CC-BY-NC-4.0 | nao_comercial | barrado | <https://huggingface.co/api/models/jinaai/jina-reranker-v2-base-multilingual> | 2026-10-15 |
| reranker | `mixedbread-ai/mxbai-rerank-large-v2` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/mixedbread-ai/mxbai-rerank-large-v2> | 2026-10-15 |
| reranker | `Qwen/Qwen3-Reranker-0.6B` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/Qwen/Qwen3-Reranker-0.6B> | 2026-10-15 |
| tts | `coqui/XTTS-v2` | coqui-public-model-license | nao_comercial | barrado | <https://huggingface.co/api/models/coqui/XTTS-v2> | 2026-10-15 |
| tts | `facebook/mms-tts-por` | CC-BY-NC-4.0 | nao_comercial | barrado | <https://huggingface.co/api/models/facebook/mms-tts-por> | 2026-10-15 |
| tts | `hexgrad/Kokoro-82M` | Apache-2.0 | permissiva | barrado | <https://huggingface.co/api/models/hexgrad/Kokoro-82M> | 2026-10-15 |
| tts | `OuteAI/OuteTTS-0.3-500M` | CC-BY-SA-4.0 | atribuicao | barrado | <https://huggingface.co/api/models/OuteAI/OuteTTS-0.3-500M> | 2026-10-15 |
| tts | `parler-tts/parler-tts-mini-multilingual-v1.1` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/parler-tts/parler-tts-mini-multilingual-v1.1> | 2026-10-15 |
| tts | `rhasspy/piper-voices` | MIT | permissiva | candidato | <https://huggingface.co/api/models/rhasspy/piper-voices> | 2026-10-15 |
| tts | `rhasspy/piper-voices:pt_BR-faber-medium` | MIT | permissiva | em_uso | <https://huggingface.co/api/models/rhasspy/piper-voices> | 2026-10-15 |
| vad | `snakers4/silero-vad` | MIT | permissiva | candidato | <https://api.github.com/repos/snakers4/silero-vad/license> | 2026-10-15 |

**Barrados** (verificados e recusados pela ADR-0011): `jinaai/jina-reranker-v2-base-multilingual` (CC-BY-NC-4.0), `coqui/XTTS-v2` (coqui-public-model-license), `facebook/mms-tts-por` (CC-BY-NC-4.0), `hexgrad/Kokoro-82M` (Apache-2.0), `OuteAI/OuteTTS-0.3-500M` (CC-BY-SA-4.0).

## Ferramentas externas

Programas do sistema usados pelo repositório, de `licenses/ferramentas-externas.toml`. Estado
`fora_do_produto` significa que a ferramenta roda só na geração de dado, em processo separado;
copyleft forte com estado `em_uso` **bloqueia** a porta.

| ferramenta | licença | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|
| `espeak-ng 1.52.0` | GPL-3.0 | copyleft_forte | fora_do_produto | <https://api.github.com/repos/espeak-ng/espeak-ng/license> | 2026-10-15 |
| `ffmpeg (a do sistema do dono)` | LGPL-2.1-or-later | permissiva | extra_opcional | <https://www.ffmpeg.org/legal.html> | 2026-10-15 |

## Bibliotecas distribuídas dentro do pacote

De `licenses/bibliotecas-distribuidas.toml` (ADR-0019, ADR-0020). São as bibliotecas de
terceiros que **saem desta máquina** dentro do AppImage, do `.deb` e do `.rpm` — por isso a
coluna que importa não é só a licença, é a obrigação que ela impõe a quem redistribui. A
licença mostrada é a **escolhida** dentro da expressão publicada pela origem; a conferência
das obrigações (ligação dinâmica, direito de re-ligar, texto junto, aviso no NOTICE) roda em
`tools/license_gate.py`.

| biblioteca | licença escolhida | categoria | ligação | modificada | estado | fonte | acesso |
|---|---|---|---|---|---|---|---|
| `jeepney 0.9.0` | MIT | permissiva | python | não | em_uso | <https://pypi.org/pypi/jeepney/0.9.0/json> | 2026-10-16 |
| `keyring 25.7.0` | MIT | permissiva | python | não | em_uso | <https://pypi.org/pypi/keyring/25.7.0/json> | 2026-10-16 |
| `PySide6-Essentials 6.9.3` | LGPL-3.0-only | permissiva | dinamica | não | em_uso | <https://pypi.org/pypi/PySide6-Essentials/6.9.3/json> | 2026-10-16 |
| `SecretStorage 3.5.0` | BSD-3-Clause | permissiva | python | não | em_uso | <https://pypi.org/pypi/SecretStorage/3.5.0/json> | 2026-10-16 |
| `shiboken6 6.9.3` | LGPL-3.0-only | permissiva | dinamica | não | em_uso | <https://pypi.org/pypi/shiboken6/6.9.3/json> | 2026-10-16 |

## Motores de voz

Motores de ASR e TTS de `licenses/motores.toml` (ADR-0017). A licença da coluna é a do
**cliente** (a biblioteca que faz a chamada), não a do peso do modelo — o peso está na tabela
de modelos. `onde = nuvem` significa que áudio ou texto **sai da máquina do dono**: esses
nascem desligados, e campo de termo vazio barra o motor em tempo de execução
(`jarvis.voz.registro`).

| papel | motor | onde | ligado | licença do cliente | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|---|---|---|
| asr | `asr-groq-whisper-large-v3` | nuvem | não | Apache-2.0 | permissiva | em_uso | <https://console.groq.com/docs/legal/services-agreement> | 2026-10-15 |
| asr | `asr-groq-whisper-large-v3-turbo` | nuvem | não | Apache-2.0 | permissiva | em_uso | <https://console.groq.com/docs/legal/services-agreement> | 2026-10-15 |
| asr | `asr-oraculo` | local | sim | Apache-2.0 | permissiva | em_uso | <https://github.com/SodreDev/jarvis> | 2026-10-15 |
| asr | `asr-whisper-local` | local | sim | MIT | permissiva | em_uso | <https://pypi.org/pypi/faster-whisper/json> | 2026-10-15 |
| tts | `tts-edge` | nuvem | não | LGPL-3.0 | permissiva | extra_opcional | <https://pypi.org/pypi/edge-tts/json> | 2026-10-15 |
| tts | `tts-elevenlabs` | nuvem | não | Apache-2.0 | permissiva | em_uso | <https://elevenlabs.io/terms-of-use> | 2026-10-15 |
| tts | `tts-parametrico` | local | sim | Apache-2.0 | permissiva | em_uso | <https://github.com/SodreDev/jarvis> | 2026-10-15 |
| tts | `tts-piper-epitran` | local | sim | MIT | permissiva | em_uso | <https://pypi.org/pypi/epitran/json> | 2026-10-15 |
| tts | `tts-piper-espeak` | local | não | GPL-3.0 | copyleft_forte | fora_do_produto | <https://api.github.com/repos/espeak-ng/espeak-ng/license> | 2026-10-15 |
