# Velocidade do pedido, por etapa: antes e depois (ADR-0045)

**Gerado por** `tools/medir_velocidade.py` (não editar à mão). **Data:** 2026-10-21. **Máquina:** AMD Ryzen 5 5600G with Radeon Graphics, 12 fios, 31 GiB de RAM, GPU NVIDIA GeForce RTX 4060, 8188 MiB, 982 MiB; Linux-7.2.9-200.nobara.fc44.x86_64-x86_64-with-glibc2.43, Python 3.12.14.

## 1. Antes — a trilha do dono (turnos de verdade, só metadados)

Turnos com método ou ferramenta desde 2026-10-21: **25**. Motor `claude -p` (o modelo padrão da conta), extensão no Brave, ASR da Groq e voz da ElevenLabs. O ASR e o contexto só aparecem nos turnos gravados depois desta medição (campos novos da trilha).

| etapa | n | p50 | p95 |
|---|---:|---:|---:|
| fala do dono (ms) | 0 | — | — |
| ASR (ms) | 0 | — | — |
| contexto do cérebro (ms) | 0 | — | — |
| 1º token do motor (ms) | 24 | 3328 ms | 9373 ms |
| 1ª ferramenta (ms desde o turno) | 18 | 3709 ms | 6575 ms |
| 1ª fala (ms) | 25 | 3860 ms | 9540 ms |
| 1º áudio (ms) | 25 | 4793 ms | 11910 ms |
| TTS: da 1ª fala ao 1º áudio (ms) | 25 | 634 ms | 2515 ms |
| pedido de site: até a 1ª página aberta (ms) | 8 | 13802 ms | 22397 ms |
| ferramenta apps.launch (ms) | 2 | 110 ms | 216 ms |
| ferramenta browser.click (ms) | 1 | 46 ms | 46 ms |
| ferramenta browser.estado (ms) | 1 | 2 ms | 2 ms |
| ferramenta browser.inspecionar (ms) | 4 | 54 ms | 63 ms |
| ferramenta browser.navigate (ms) | 11 | 26 ms | 1770 ms |
| ferramenta browser.read (ms) | 7 | 9 ms | 14 ms |
| ferramenta browser.tabs (ms) | 7 | 4 ms | 7 ms |
| ferramenta clipboard.text.read (ms) | 1 | 10 ms | 10 ms |
| ferramenta memoria.buscar (ms) | 1 | 21 ms | 21 ms |
| ferramenta sites.open (ms) | 2 | 364 ms | 726 ms |
| ferramenta web.buscar (ms) | 5 | 1312 ms | 1426 ms |
| ferramenta web.canal_videos (ms) | 5 | 1339 ms | 3237 ms |
| ferramenta window.close (ms) | 2 | 10887 ms | 21773 ms |
| ferramenta window.focus_app (ms) | 1 | 183 ms | 183 ms |
| ferramenta window.list (ms) | 1 | 69 ms | 69 ms |

Contagens: navegação com erro (o id velho: «falha»): 5 · web.buscar (a aba escondida, sem chave): 5.

## 2. Depois — o caminho rápido, com o código de verdade e sem LLM

Cérebro, executor, PDP e auditoria em SQLite (numa pasta temporária); o motor que não pode ser chamado (o teste quebra se for). As ferramentas respondem na hora: este é o tempo que é **nosso**. No desktop do dono some-se o tempo da ferramenta (tabela 1: o `apps.launch`, a extensão) e, para a fala, o TTS.

| comando | etapa | n | p50 | p95 |
|---|---|---:|---:|---:|
| «abre o Discord» 1ª ferramenta | 50 | 1 ms | 1 ms |
| «abre o Discord» 1ª fala | 50 | 4 ms | 6 ms |
| «abre o Discord» turno inteiro | 50 | 4 ms | 6 ms |
| «fecha o Discord» 1ª ferramenta | 50 | 1 ms | 1 ms |
| «fecha o Discord» 1ª fala | 50 | 106 ms | 108 ms |
| «fecha o Discord» turno inteiro | 50 | 106 ms | 108 ms |
| «o que está em foco?» 1ª ferramenta | 50 | 1 ms | 1 ms |
| «o que está em foco?» 1ª fala | 50 | 3 ms | 5 ms |
| «o que está em foco?» turno inteiro | 50 | 3 ms | 5 ms |
| «abre o YouTube» 1ª ferramenta | 50 | 1 ms | 1 ms |
| «abre o YouTube» 1ª fala | 50 | 5 ms | 6 ms |
| «abre o YouTube» turno inteiro | 50 | 5 ms | 6 ms |
| «pesquisa vídeos de gatos no YouTube» 1ª ferramenta | 50 | 1 ms | 1 ms |
| «pesquisa vídeos de gatos no YouTube» 1ª fala | 50 | 4 ms | 6 ms |
| «pesquisa vídeos de gatos no YouTube» turno inteiro | 50 | 5 ms | 6 ms |

## 3. Rede — conexão nova × reaproveitada (GET sem autenticação, sem chave)

| serviço | etapa | n | p50 | p95 |
|---|---|---:|---:|---:|
| Groq | conexão nova (antes) | 10 | 221 ms | 238 ms |
| Groq | conexão reaproveitada (depois) | 10 | 196 ms | 211 ms |
| Groq | 1º pedido com aquecer (depois) | 10 | 197 ms | 214 ms |
| ElevenLabs | conexão nova (antes) | 10 | 231 ms | 336 ms |
| ElevenLabs | conexão reaproveitada (depois) | 10 | 158 ms | 165 ms |
| ElevenLabs | 1º pedido com aquecer (depois) | 10 | 154 ms | 228 ms |

## 4. Escala pela máquina — a consulta da memória antes de cada turno

| threads do embedding (e5, ONNX, CPU) | n | p50 | p95 |
|---|---:|---:|---:|
| 2 | 30 | 6 ms | 8 ms |
| 4 | 30 | 5 ms | 6 ms |

Com 12 fios o Jarvis passa a usar 4 (`threads_da_maquina`: piso 2, teto 4, `JARVIS_THREADS_DA_MEMORIA` manda). O Whisper local (`small`, int8) leva ~1,4 s por fala de ~2,2 s na CPU com 4 ou 6 threads (medido em 2026-10-21 com o corpus); na GPU ele não carrega sem a `libcublas.so.12` (as bibliotecas CUDA da NVIDIA, licença própria) — decisão do dono. Até lá, a Groq é o ASR mais rápido aqui.

## 5. O pedido típico, antes e depois (p50)

Depois = o nosso tempo (tabela 2) + a ferramenta + o TTS, os dois da trilha do dono (tabela 1). Composição das etapas medidas, não uma medida de ponta a ponta no desktop dele.

| pedido | antes: 1ª fala | antes: 1º áudio | depois: 1ª fala | depois: 1º áudio |
|---|---:|---:|---:|---:|
| «abre o Discord» | 3860 ms | 4793 ms | 114 ms | 748 ms |
| «abre o YouTube» | 3860 ms | 4793 ms | 864 ms | 1498 ms |
| «pesquisa vídeos de gatos no YouTube» | 3860 ms | 4793 ms | 864 ms | 1498 ms |
| «o que está em foco?» | 3860 ms | 4793 ms | 8 ms | 642 ms |

Pedido de site, até a 1ª página aberta: antes **13802 ms** (p50 da trilha: o motor planejava, buscava numa aba escondida e errava o id da aba); depois, o 1º passo é do código: ~860 ms (a navegação da extensão).

O `window.close` da trilha (10–22 s) inclui a espera pelo «sim» do dono — fechar a janela do navegador pergunta (ADR-0042): não é tempo do código.
