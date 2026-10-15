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
| embedding | `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/Qwen/Qwen3-Embedding-0.6B> | 2026-10-15 |
| reranker | `BAAI/bge-reranker-v2-m3` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/BAAI/bge-reranker-v2-m3> | 2026-10-15 |
| reranker | `jinaai/jina-reranker-v2-base-multilingual` | CC-BY-NC-4.0 | nao_comercial | barrado | <https://huggingface.co/api/models/jinaai/jina-reranker-v2-base-multilingual> | 2026-10-15 |
| reranker | `mixedbread-ai/mxbai-rerank-large-v2` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/mixedbread-ai/mxbai-rerank-large-v2> | 2026-10-15 |
| reranker | `Qwen/Qwen3-Reranker-0.6B` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/Qwen/Qwen3-Reranker-0.6B> | 2026-10-15 |
| tts | `coqui/XTTS-v2` | coqui-public-model-license | nao_comercial | barrado | <https://huggingface.co/api/models/coqui/XTTS-v2> | 2026-10-15 |
| tts | `hexgrad/Kokoro-82M` | Apache-2.0 | permissiva | candidato | <https://huggingface.co/api/models/hexgrad/Kokoro-82M> | 2026-10-15 |
| tts | `rhasspy/piper-voices` | MIT | permissiva | candidato | <https://huggingface.co/api/models/rhasspy/piper-voices> | 2026-10-15 |
| tts | `rhasspy/piper-voices:pt_BR-faber-medium` | MIT | permissiva | em_uso | <https://huggingface.co/api/models/rhasspy/piper-voices> | 2026-10-15 |
| vad | `snakers4/silero-vad` | MIT | permissiva | candidato | <https://api.github.com/repos/snakers4/silero-vad/license> | 2026-10-15 |

**Barrados** (verificados e recusados pela ADR-0011): `jinaai/jina-reranker-v2-base-multilingual` (CC-BY-NC-4.0), `coqui/XTTS-v2` (coqui-public-model-license).

## Ferramentas externas

Programas do sistema usados pelo repositório, de `licenses/ferramentas-externas.toml`. Estado
`fora_do_produto` significa que a ferramenta roda só na geração de dado, em processo separado;
copyleft forte com estado `em_uso` **bloqueia** a porta.

| ferramenta | licença | categoria | estado | fonte | acesso |
|---|---|---|---|---|---|
| `espeak-ng 1.52.0` | GPL-3.0 | copyleft_forte | fora_do_produto | <https://api.github.com/repos/espeak-ng/espeak-ng/license> | 2026-10-15 |
