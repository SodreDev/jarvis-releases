# OpenJarvis: integrações e superfícies — o que reaproveitar no Jarvis

**Data:** 2026-11-12 · **Autor:** opus-estudo-integracoes (estudo somente leitura) · **Par:** [openjarvis-nucleo.md](openjarvis-nucleo.md) (núcleo, outra CLI)
**Fonte:** clone do OpenJarvis (Stanford Hazy Research / Scaling Intelligence Lab), licença Apache-2.0, `Copyright 2025 The OpenJarvis Authors`, commit `13706f2`, em `../referencias/OpenJarvis` (fora deste repositório). Nada foi rodado, instalado nem baixado. Os caminhos abaixo são relativos à raiz do clone; `oj/` = `src/openjarvis/`.

**Como ler.** Cada seção diz o que o OpenJarvis tem, quão maduro é, que risco traz e se o Jarvis já tem algo igual ou melhor. O backlog priorizado está no fim (§11). As marcas **[inferência]** indicam leitura de código sem execução.

---

## 0. Resumo em cinco linhas

1. **Amplitude grande, profundidade desigual.** São 32 canais, 26 conectores, skills, MCP, A2A, voz, servidor FastAPI, SPA React, app Tauri e Docker. Cerca de metade dos canais **só envia**. Workflow, sessões e A2A são protótipos com bugs.
2. **Os conectores são a parte mais sólida e a lacuna real do Jarvis.** Gmail, Calendar, Drive, IMAP, Notion e Obsidian funcionam, com testes. O OAuth, porém, não tem `state` nem PKCE, e os tokens ficam em JSON em claro (0600).
3. **A ponte Baileys não é atalho.** O nosso `docs/redes-sociais-riscos.md` §7 proíbe bibliotecas que falam o protocolo do WhatsApp. Além disso, a ponte deles é frágil: versão RC, reconexão em laço sem backoff, sem filtro de grupo nem de `status@broadcast`, sem allowlist, sem `chmod` e sem o `dist/` compilado.
4. **Em voz, MCP, memória e segurança de ferramenta o Jarvis está à frente.** Lá a fala é por turno, com VAD por RMS, sem wake word, sem barge-in e sem streaming. O cliente MCP herda o ambiente inteiro. A busca híbrida é igual ou inferior à do `memoryd`.
5. **Atalhos que valem:**
   - conector IMAP só leitura;
   - Google Calendar e Gmail só leitura (reescrevendo o OAuth);
   - rotina agendada falada (o «morning digest»);
   - parser de SKILL.md (agentskills.io) só como instrução;
   - Telegram como canal remoto **do dono**, com allowlist;
   - pequenos utilitários de backoff e redação de log.

---

## 1. Canais (`oj/channels/`, 34 arquivos, ~6,3 mil linhas)

**Arquitetura.**
- `BaseChannel` (`oj/channels/_stubs.py:37-95`) tem `connect`, `send(destino, texto, conversation_id=…)`, `on_message(handler)`, `status` e `list_channels`.
- `ChannelMessage` traz `channel`, `sender`, `content`, `conversation_id` e `session_id`.
- O registro é feito por decorador (`oj/core/registry.py:133`), com imports opcionais em `try/except ImportError` (`oj/channels/__init__.py:14-51`).
- O canal chega ao agente por três caminhos:
  - `oj/system/core.py:194-294`, com sessão `f"{canal}:{conversation_id}"`;
  - `oj/agents/channel_agent.py:92-140`;
  - `oj/server/channel_bridge.py:116`, com comandos `/help /more /agent …`.

**Lacunas transversais** (valem para todos os canais):

| Tema | O que o código faz | Evidência |
|---|---|---|
| Allowlist de contato | Só o Telegram tem (`allowed_chat_ids`; vazio aceita todos). O `channel_bridge` deixa **qualquer remetente** rodar `/agent X pause` | `oj/channels/telegram.py:398-404`, `oj/server/channel_bridge.py:197-216` |
| Rate limit / 429 | Nenhum canal trata `Retry-After`. Só existe `reconnect=True` no Discord e reenvio sem Markdown no Telegram | grep `sleep\|backoff\|429` em `oj/channels/` |
| Credenciais | Ficam em variável de ambiente, `config.toml` ou SQLite `channel_bindings` em claro. **Nenhum `chmod`/0600** em canais, bridge ou webhooks | `oj/agents/manager.py:49-56` |
| Webhooks | Assinatura conferida e falha fechada (Twilio, Meta HMAC, BlueBubbles, Sendblue). A resposta de `/whatsapp` e `/bluebubbles` é **descartada** | `oj/server/webhook_routes.py:109-122, 304-356, 287-296` |
| Testes | Só mocks. Há um contrato parametrizado para todos os canais | `tests/channels/test_channel_contract.py` |

**Lista completa dos canais.** «Real» = envia e recebe de fato. «Só envio» = `connect()` só valida a credencial e `on_message` nunca dispara.

| Canal | Status | Protocolo / auth | Risco de ToS para a conta |
|---|---|---|---|
| telegram | **real** (30 testes) | Bot API oficial, long polling, fatia em 4096 | baixo |
| discord | **real** (20) | Bot oficial (gateway + intent `message_content`), não é self-bot | baixo |
| slack / slack_daemon | **real** | Socket Mode. O daemon passa **tokens na linha de comando** (`oj/channels/slack_daemon.py:157-171`) | baixo |
| email | **real** | SMTP + IMAP `UNSEEN`, polling de 30 s; responde a **qualquer** e-mail | baixo, mas é vetor de *prompt injection* |
| gmail | **real** | Gmail API, `gmail.modify`; token gravado sem chmod (`oj/channels/gmail.py:117-119`) | baixo |
| twitter | **real** | API v2 com OAuth 1.0a próprio; auto-resposta a menções; `since_id` só em memória | médio/alto |
| twilio_sms, sendblue | **real** | APIs pagas oficiais com webhook assinado | baixo |
| webchat, webhook | **real** | fila em processo / POST de saída | nenhum |
| imessage_daemon | real, **só macOS**, fora do registro | `chat.db` somente leitura + AppleScript (`chat_identifier` entra cru no script) | médio |
| whatsapp (Cloud API) | parcial | Graph API oficial; resposta do webhook descartada; janela de 24 h não tratada | baixo, mas **não serve para conta pessoal** |
| **whatsapp_baileys** | parcial e frágil | Baileys `7.0.0-rc.9` + Node por stdio (ver §2) | **alto** |
| signal | só envio | REST de um signal-cli-rest-api externo [inferência] | médio (cliente não oficial) |
| messenger | só envio | API de Página (pymessenger); **sem Instagram** | médio; não serve para conta pessoal |
| reddit | só envio | praw; sem `conversation_id` **cria post no subreddit** | alto (spam) |
| bluebubbles | parcial | servidor BlueBubbles (Private API do macOS) | médio |
| feishu, google_chat, line, mastodon, matrix, mattermost, rocketchat, viber, zulip | só envio | APIs oficiais / tokens | baixo |
| nostr | só envio | DM kind 4 **sem criptografia** (`oj/channels/nostr_channel.py:113-120`) | baixo (privacidade ruim) |
| twitch | só envio, provável bug | `sender_id` recebe o nick em vez do id numérico [inferência] | baixo |
| irc | só envio, frágil | um socket por mensagem, sem JOIN, risco de injeção CRLF | baixo |
| teams, xmpp | **stub na prática** | Teams manda a senha como Bearer; XMPP envia sem `connect()` | — |

**Comparação com o Jarvis.** O Jarvis lê WhatsApp, Instagram, Facebook, TikTok e Discord **como o dono**, pela aba de fundo do navegador dele (ADR-0060, `extensao/social.js`), e só envia no WhatsApp, atrás do guardião (`jarvis.social.envio`). O OpenJarvis não tem nada equivalente para Instagram e TikTok. Seus canais de Discord e Messenger são **bots e páginas**, outra identidade, que não leem as DMs pessoais do dono. Para o caso de uso do dono, ler as próprias conversas, nenhum canal deles substitui o nosso.

---

## 2. A ponte WhatsApp/Baileys em detalhe

**Peças:**
- `oj/channels/whatsapp_baileys.py` (341 linhas);
- `oj/channels/whatsapp_baileys_bridge/src/bridge.ts` (156 linhas);
- `package.json` com `@whiskeysockets/baileys ^7.0.0-rc.9`; o lock fixa a RC.

| Aspecto | O que faz | Evidência |
|---|---|---|
| Ponte | Subprocesso `node dist/bridge.js --auth-dir …`, JSON por linha no stdin/stdout, sem porta | `whatsapp_baileys.py:163-170, 257-282` |
| Build | **Não há `dist/` no repositório nem passo de build.** A doc diz que vem compilado | `docs/user-guide/channels.md:533` |
| Pareamento | QR (sem *pairing code*); estado em `useMultiFileAuthState` em `~/.openjarvis/whatsapp_baileys_bridge/auth`, **sem chmod** | `bridge.ts:52,62` |
| Recebimento | Descarta `fromMe` e aceita só texto. **Não filtra grupo (`@g.us`) nem `status@broadcast`** e não confere `m.type` (histórico pode gerar respostas em lote) [inferência] | `bridge.ts:93-110` |
| Envio | `sendMessage(jid,{text})` sem presença, sem «digitando», sem intervalo, sem teto. Uma falha põe o canal inteiro em `ERROR` | `bridge.ts:132`, `whatsapp_baileys.py:217-230, 324-326` |
| Reconexão | Qualquer queda que não seja logout chama `startSocket()` **na hora, sem backoff nem limite** | `bridge.ts:74-87` |
| Logout | Só avisa; não apaga o auth nem desvincula | `bridge.ts:79-81` |
| Processo | O stderr (onde sai o QR) nunca é lido, então o pipe pode encher e travar [inferência]. Sem auto-restart. Se o Node morrer, o status não muda | `whatsapp_baileys.py:257-282` |
| Opção morta | `assistant_has_own_number` é documentada e nunca usada | `whatsapp_baileys.py:58-77` |
| Aviso de risco | Nenhum aviso de ban ou ToS na doc | grep em `docs/` |
| Testes | 24, todos em Python com `Popen` mockado; **zero teste do `bridge.ts`** | `tests/channels/test_whatsapp_baileys.py` |

**Baileys × a nossa leitura por DOM:**

| Critério | Baileys (OpenJarvis) | Extensão do Jarvis (ADR-0060) |
|---|---|---|
| Identidade para a plataforma | um «dispositivo vinculado» novo, cliente não oficial | o próprio navegador e sessão do dono (mesmo IP e impressão digital) |
| Superfície de dados | processo Node com toda a sessão e uma cadeia npm inteira | content script no host da rede + host local |
| Ler conteúdo de mensagem | sim, estruturado (é o atrativo) | hoje só título, contador e remetente; o formato das mensagens ficou para depois |
| Enviar | sem guardrail algum | guardião no código: lista, ausente, teto, madrugada, cabeçalho conferido, CDP só durante o envio |
| Fragilidade | protocolo muda e a lib RC acompanha; reconexão em laço pesa para ban | DOM muda; seletores como dados + canário |
| Permitido no Jarvis | **não** (`docs/redes-sociais-riscos.md` §7) | sim |

**Veredito: ignorar.** O único ganho real seria ler o texto das mensagens de forma estruturada. Isso se consegue estendendo `social-seletores.js` (papel/aria do painel de conversa), sem trocar de identidade. Se o dono um dia quiser Baileys, é ADR nova com decisão dele. Mesmo nesse caso, a ponte deles não serve de base: precisaria de backoff, filtro de grupo e status, allowlist, 0600, build e o nosso guardião.

---

## 3. Conectores (`oj/connectors/`, 41 arquivos, ~13,5 mil linhas, ~49 arquivos de teste)

**Base.**
- `BaseConnector` (`oj/connectors/_stubs.py:65-115`):
  - `auth_type` ∈ {oauth, local, bridge, filesystem, token};
  - `sync(since, cursor) -> Iterator[Document]`;
  - `mcp_tools()` opcional.
- `Document` (`:24-51`) traz `doc_type` (email/message/event/contact/document/note), participantes, `thread_id` e anexos com sha256.
- Router HTTP em `oj/server/connectors_router.py`. A sincronização é manual, em thread com cancelamento.
- O `SyncScheduler` (`oj/connectors/scheduler.py`) existe mas **não é instanciado** em produção [inferência por grep].

| Conector | Status | Lê / escreve | Auth | Plataforma | Testes |
|---|---|---|---|---|---|
| gmail | real | lê; **escreve** lixeira/arquivar | OAuth Google, `gmail.modify` | todas | 25 |
| gmail_imap / imap / outlook | real | **só lê** (`select INBOX readonly=True`) | senha de app (JSON 0600) | todas | 26 + 6 |
| gcalendar | real | lê; **escreve** aceitar/recusar | OAuth, escopo `calendar` completo | todas | 7 |
| gdrive | real | só lê (`drive.readonly`), exporta Docs/Sheets | OAuth | todas | 6 |
| gcontacts, google_tasks | real | só lê | OAuth | todas | 6 + 3 |
| notion | real | só lê | token de integração interna | todas | 8 |
| obsidian | real | só lê `.md/.txt` de uma pasta | caminho | todas | 9 |
| slack | real | só lê | token de usuário `xoxp-`, validado antes de gravar | todas | 18 |
| granola, oura, github_notifications, weather, hackernews, news_rss, spotify | real | só lê | API key / PAT / OAuth / nenhuma | todas | 3–14 |
| strava | real | só lê | OAuth; refresh existe mas nunca é chamado | todas | 3 |
| dropbox | **parcial** | só lê | `client_id=""` e grava o *code* como token (`oj/connectors/dropbox.py:179-197`) | todas | 6 |
| whatsapp | **parcial** | só lê export `.txt` | pasta | todas | 10 |
| imessage, apple_notes, apple_calendar, apple_contacts, apple_music, apple_health | real | só lê (SQLite `mode=ro` / osascript) | Full Disk Access | **só macOS** | 5–17 |

**Pontos fortes que valem copiar:**
- **Backoff do Gmail.** Distingue 403 de cota de 403 de permissão; 6 tentativas exponenciais com jitter até 60 s (`oj/connectors/gmail.py:59-98`). O Slack respeita `Retry-After` (`oj/connectors/slack_connector.py:138-175`).
- **Anti-SSRF.** IMAP com host livre: IP público e DNS fixado (`oj/connectors/imap.py:59-117, 147-260`). RSS com limite de 10 MB e 5 redirects (`oj/connectors/news_rss.py:29-30`).
- **Marca d'água de sync.** Só avança em sucesso e guarda o início da sync (`oj/connectors/sync_engine.py:115-182`). Defeito: o `cursor` do conector nunca é propagado (`:121`).
- **Redação de segredo em log.** Filtro no logger `httpx` que apaga `appid` da query string (`oj/connectors/weather.py:31-48`).
- **Validação antes de gravar.** Slack e Granola validam a credencial antes de sobrescrever (`oj/connectors/oauth.py:270-282`).

**Defeitos que não podem vir junto:**
- **OAuth sem `state` (CSRF) e sem PKCE.** Grep vazio em `oj/connectors/oauth.py`. O servidor loopback roda em `127.0.0.1:8789`.
- **Um único consentimento com escopos de escrita** (`calendar`, `gmail.modify`) mesmo para quem só quer ler (`oj/connectors/oauth.py:57-69`).
- **Tokens em JSON em claro.** Incluem `client_secret` e senha IMAP, sem keyring, e são copiados em **6 arquivos** (`oj/connectors/oauth.py:88-95`). O refresh atualiza um e os outros divergem [inferência]. Não guarda `expires_at`; o refresh só acontece reativo, no 401.
- **XSS refletido** na página de erro do callback: o parâmetro `error` vai cru para o HTML (`oj/server/connectors_router.py:812-820`, conferido).
- **Parser do export do WhatsApp só no formato americano** (`M/D/AA, H:MM AM/PM -`, `oj/connectors/whatsapp.py:39-41`, conferido). O export brasileiro (`15/01/2024 10:30 - Nome:`) gera zero mensagens. Pelo servidor, o conector nem conecta: o router define `_vault_path` e ele lê `_export_path` [inferência].

**Ingestão e busca:**
- `chunker.py` corta por tipo e conta tokens por espaço; a regex de sentença é inglesa.
- `store.py` usa SQLite + FTS5 `porter unicode61` e dedupe por hash de chunk.
- `embeddings.py` usa Ollama `nomic-embed-text`.
- `hybrid_search.py` combina BM25 + cosseno por varredura bruta + RRF k=60 + vizinhos do mesmo `thread_id`.
- `retriever.py` tem ColBERT opcional.

**O Jarvis já tem o equivalente ou melhor.** O `jarvis.memoryd` funde **denso + FTS5 + grafo** por RRF (`src/jarvis/memoryd/fusao.py`), com livro-razão SQLite cifrado e índice trocável (ADR-0005/0008). Ideias pontuais que valem: chunk por tipo (evento e contato nunca cortados; e-mail cortado em «Em … escreveu:»), anexar os vizinhos do mesmo fio e `unicode61 remove_diacritics 2` em vez de `porter` (stemmer inglês).

**O que o Jarvis tem hoje.** Nenhum conector de e-mail, Drive, Notion ou Obsidian. O calendário é só **rascunho `.ics` local** (`calendar.create_draft_event`, `src/jarvis/executor/arquivos.py:257`). O backend de agenda está em aberto como **D2** (ADR-0010 item 3).

---

## 4. Skills (`oj/skills/`, ~2,3 mil linhas, 222 testes)

| Peça | O que faz | Evidência |
|---|---|---|
| Formatos | (a) **SKILL.md** com frontmatter da spec agentskills.io / Anthropic Agent Skills (`name` ≤ 64 minúsculas e hífens, `description` ≤ 1024, `license`, `compatibility`, `metadata`, `allowed-tools`); (b) TOML de pipeline (`[[skill.steps]]` com `tool_name` e `arguments_template`) | `oj/skills/parser.py:28-151`, `oj/skills/loader.py:46-143` |
| Execução | **Não roda script.** A skill de instrução vira ferramenta `skill_<nome>` que **devolve o markdown** como resultado; o catálogo `<available_skills>` (nome + descrição) vai no prompt. O pipeline TOML chama as ferramentas comuns | `oj/skills/tool_adapter.py:61-71,182-184`, `oj/skills/executor.py:104-140` |
| Importação | `git clone`/`pull --ff-only` de Hermes (NousResearch/hermes-agent), OpenClaw (openclaw/skills) ou qualquer URL GitHub para `~/.openjarvis/skill-cache`. **Sem pin de commit, sem `--depth`, sem assinatura.** `scripts/` só entra com `--with-scripts`; symlinks são recusados; o nome validado impede *path traversal* | `oj/skills/sources/base.py:53-75`, `oj/skills/importer.py:72-207` |
| Tradução | Tabela de ~10 nomes do Claude Code (Bash→shell_exec, Read→file_read…) aplicada no corpo do markdown | `oj/skills/tool_translator.py:21-32` |
| Segurança | **Fraca.** A capability é autodeclarada (só barra quem *declara* `shell:execute`). Assinatura Ed25519, sha256 do índice e «scan» existem e **não são chamados**. `allowed-tools` não é aplicado. `capability_policy` é guardado e não usado | `oj/skills/security.py`, `oj/skills/index.py:24,66`, `oj/skills/manager.py:41,199` |
| Injeção | Template `{chave}` substituído por `re.sub` sem escape (conferido). Em passos `shell_exec` (ex.: `backup-files.toml`: `tar czf {destination}/…`) é injeção de comando, contida só pela confirmação interativa | `oj/skills/executor.py:205-216` |
| Empacotadas | 20 TOMLs (backup-files, calendar-prep, daily-digest, email-draft, meeting-notes, pdf-summarize, topic-research, translate-doc, web-summarize…). **Não são carregadas em runtime**, só nos testes | `oj/skills/data/`, `oj/cli/skill_cmd.py:41-48` |
| Overlay | `optimized.toml` (DSPy/GEPA) reescreve a descrição e acrescenta few-shots | `oj/skills/overlay.py:60-108` |

**Para o Jarvis.** Hoje ele não lê SKILL.md. O que vale:
- o **parser e validador da spec** (`oj/skills/parser.py`, só stdlib + YAML);
- a ideia de **catálogo nome+descrição no prompt e corpo sob demanda**. Combina com o orçamento de 16 mil caracteres da ADR-0047 e com o seletor de tools (ADR-0024).

Do jeito deles, não serve:
- importar por `git clone` sem pin;
- carregar `scripts/`;
- confiar em capability autodeclarada.

No Jarvis, uma skill seria **texto de instrução, nunca código**:
- o corpo entra como dado sob o guarda de contexto (ADR-0049);
- cada ferramenta continua atrás do PDP com o tier do manifesto;
- a origem é uma pasta local que o dono aprova, com sha256 conferido;
- `scripts/` é ignorado; se um dia rodar, roda no executor isolado (ADR-0050).

---

## 5. MCP e A2A

| Item | OpenJarvis | Jarvis hoje |
|---|---|---|
| Cliente MCP | JSON-RPC próprio, `2025-03-26`, só `tools/*`, sem paginação, resources ou prompts (`oj/mcp/client.py:65-118`) | cliente stdio próprio (ADR-0052) com promoção a manifesto, PDP e guarda |
| Transporte stdio | `Popen` **sem `env=`**: o servidor filho herda todos os segredos (`oj/mcp/transport.py:97`, conferido) | filho nasce com **ambiente vazio** + o que o manifesto declara (ADR-0023 item 2) |
| Streamable HTTP | sim: POST com `Accept: application/json, text/event-stream`, `Mcp-Session-Id`, Bearer, lê só a 1ª mensagem SSE; sem GET de stream nem retomada (`oj/mcp/transport.py:259-395`) | **não tem** |
| Ferramenta MCP externa | entra sem capability nem confirmação (`oj/tools/mcp_adapter.py`) | invisível até ser promovida; tier é nosso (ADR-0010 item 5) |
| Servidor MCP | anuncia `2025-11-25` com `readOnlyHint`/`destructiveHint`, mas é usado só **in-process** como registro (`oj/system/builder.py:480-487`) | servidor de capacidades atrás do PDP (ADR-0023) |
| A2A | rascunho antigo da spec (`/.well-known/agent.json`, `tasks/send`), síncrono, tarefas num dict sem limite, `cancel` não interrompe, aberto sem token, cliente não autentica, **rotas não montadas** (`oj/a2a/server.py`) | — |

**Veredito.** No MCP o Jarvis está à frente. O único reaproveitável é o **transporte Streamable HTTP** (~140 linhas, httpx), se o dono quiser servidores MCP remotos. Mesmo assim, só depois de uma ADR sobre rede para o cliente MCP (ADR-0010 item 4: «sem rede a menos que o servidor declare e o dono conceda»). **A2A: ignorar.**

---

## 6. Voz (`oj/speech/`, ~1,5 mil linhas, ~1,8 mil de testes)

| Aspecto | OpenJarvis | Jarvis (`src/jarvis/voz`, ADR-0017/0021/0040) |
|---|---|---|
| STT | faster-whisper `base` local; OpenAI `whisper-1`; Deepgram `nova-2` pré-gravado | Whisper local, Groq Whisper (nuvem opcional), Parakeet v3 registrado como candidato; portão de licença por motor |
| TTS | Kokoro (local, torch), OpenAI, Cartesia (`en` fixo), ElevenLabs | Piper (fonemização própria pt-BR), Edge, ElevenLabs, paramétrico, OmniVoice pessoal |
| pt-BR | o Kokoro tem o prefixo `p`, mas a lista curada não traz nenhuma voz `p*` (`oj/speech/kokoro_tts.py:33-43, ~296-330`) | foco do projeto (ADR-0016, vocabulário do dono, tom de voz) |
| Captura e VAD | `sounddevice` 16 kHz; **VAD = limiar fixo de RMS** (500, 1,5 s de silêncio) (`oj/speech/voice_io.py:9-12, 64-75`) | escuta com filtro de ruído (ADR-0043) e modos de ativação |
| Wake word | **não existe** | palavra de ativação + atalho (ADR-0021) |
| Barge-in | **não existe** (`sd.play(); sd.wait()`) | interromper por voz (ADR-0040), cancelamento por epoch (ADR-0002) |
| Streaming | **não existe** (o TTS inteiro antes de tocar) | síntese em lotes antecipados, cancelável |
| Descoberta | local primeiro; nuvem só com chave no ambiente; `health()` por motor (`oj/speech/_discovery.py`) | registro de motores com licença e aviso de nuvem só pela UI |

**Veredito: ignorar.** O Kokoro já foi avaliado e **barrado** aqui: o pt-BR dele passa pelo espeak-ng, que é GPL-3.0 (ADR-0016, ADR-0017; `docs/licencas.md:27`). Nada na pilha deles supera a nossa.

---

## 7. Presets, templates, workflow e sessões

**Presets.** Não existe `configs/openjarvis/presets/`. Os presets são `configs/openjarvis/examples/*.toml` (`tests/core/test_preset_configs.py:16-18`).

| Preset | O que faz | Agenda |
|---|---|---|
| morning-digest-linux | briefing **falado** com persona «jarvis» (`configs/openjarvis/prompts/personas/jarvis.md`); fontes oura, gmail, google_tasks, slack, gcalendar, hackernews, news_rss, weather; TTS OpenAI | `[digest] schedule = "0 7 * * *"` + fuso |
| morning-digest-mac / -minimal | o mesmo, com iMessage e Cartesia / só gmail + agenda | cron 7h / padrão |
| deep-research | agente multi-hop sobre o knowledge store + web | — |
| scheduled-monitor | agente `operative` com estado entre execuções | `jarvis scheduler create --schedule "0 9 * * 1-5"` |
| chat-simple, code-assistant, full-system-access, spec-search-quickstart | chat local; código com shell; **shell sem restrição**; busca de configuração guiada por LLM | — |

Rotas do digest em `oj/server/digest_routes.py`: atual, áudio, histórico, agenda e gerar. A doc promete «local», mas o TTS padrão do digest é **Cartesia na nuvem** (`oj/core/config.py:1752`).

**Templates** (`oj/templates/data/`, 16 TOMLs): system prompt + lista de ferramentas por papel (assistant, deep-researcher, inbox-triager, meeting-prep, monitor…). São dados simples, com 5 testes.

**Workflow** (`oj/workflow/`, 17 testes): DAG em TOML e paralelismo por estágio. Tem quatro problemas:
- **as arestas condicionais nunca são lidas** pelo engine;
- `PARALLEL` cai em «tipo desconhecido»;
- o `transform` junta todas as saídas;
- não há persistência.

**Sessões** (`oj/sessions/`, 18 testes):
- A «consolidação» apaga a metade velha e grava as 10 primeiras mensagens truncadas, com timestamp que as põe **depois** das recentes.
- `model_summarization` é stub.
- `oj/server/api_routes.py:596` importa um `openjarvis.sessions.store` que não existe.
- A identidade multicanal (`channel_ids`) existe no modelo mas não é resolvida.

**Para o Jarvis.** O que falta de verdade é a **rotina agendada falada**. O Jarvis tem alarmes (`timer.alarm_*`) e tarefas assíncronas (ADR-0022), mas não tem «às 7h, colete X, Y, Z e me fale». O conceito e a persona do preset são reaproveitáveis. Workflow, sessões e templates: ignorar. As tarefas, o `memoryd` e os presets de provedor (ADR-0056) do Jarvis já cobrem melhor.

---

## 8. Servidor, frontend web, app Tauri e deploy

| Peça | O que é | Para o Jarvis |
|---|---|---|
| `oj/server/` (FastAPI, ~13 mil linhas, ~10,6 mil de testes) | `/v1/chat/completions` compatível com OpenAI, WebSocket de chat e eventos, aprovações, digest, pesquisa, upload, webhooks; bind padrão `127.0.0.1:8000` | o Jarvis é app Qt6 local (ADR-0019) e não expõe HTTP. Duas lições valem (abaixo) |
| Proteções boas | `check_bind_safety` **encerra** se o bind não for loopback e não houver chave (`oj/server/auth_middleware.py:104-124`, conferido). WebSocket autentica por **subprotocolo** `openjarvis.auth.v1`, nunca por query string | padrão para o lado servidor do MCP (ADR-0023) se ele um dia sair do stdio |
| Problemas | sem chave (o padrão): **CSRF** por `request.json()` sem checar o Content-Type em `/v1/channels/send`, `/v1/cloud/reload` e `/v1/tools/{t}/credentials`; WebSocket sem checar `Origin` nem `Host` (DNS rebinding); `approve` sem `WHERE status='pending'` (`oj/tools/approval_store.py:265-284`); upload sem limite | lições para qualquer porta local: Content-Type estrito, Origin/Host conferidos, transição de estado atômica |
| `frontend/` | React 19 + Vite 8 + Tailwind 4 + zustand, PWA; telas Chat, Dashboard, Settings, DataSources, Agents, Logs; **chave da API no `localStorage`**; PostHog e leaderboard no Supabase | ignorar (stack e modelo de app diferentes) |
| `frontend/src-tauri/` (Tauri v2, `lib.rs` ~4,5 mil linhas) | sobe `uv run jarvis serve` (exige `uv` e faz `git clone`), Ollama como sidecar, bandeja, atalho global, deep link, updater minisign; `shell:allow-execute/spawn/kill` **sem escopo** e CSP `connect-src` aberta | ignorar; contraexemplo de capability ampla |
| `desktop/src-tauri/` | resto antigo: **binário Ollama de 77 MB no git** + `overlay.html` | — |
| `deploy/` | Dockerfile multi-stage, **não-root uid 10001**, imagens com digest; variantes GPU CUDA/ROCm; compose com chave obrigatória, mas **sem volume do jarvis** e **porta 11434 do Ollama publicada**; systemd, launchd, Windows; `render.yaml` | o Jarvis empacota AppImage/deb/rpm (ADR-0020). Só o padrão não-root + digest serve, para os contêineres de teste |
| `rust/` | 17 crates (~27,5 mil linhas) expostos por PyO3; partes do Python dependem dele | do escopo do estudo de núcleo |

---

## 9. Documentação (`docs/user-guide`, `docs/showcase`, `docs/tutorials`)

São 26 guias, 7 showcases e 6 tutoriais. A doc promete coisas que o código não entrega:
- `enforce_tool_confirmation = true` aparece como padrão e **não faz nada** (admitido em `docs/user-guide/security.md:472`).
- Não há página de voz.
- `channels-and-connectors.md:197` diz «auto-refresh coming soon».
- Os showcases são narrativas sem comando reproduzível.
- A telemetria vem ligada.
- Três páginas tratam de **mineração da cripto «Pearl»** (`docs/user-guide/mining*.md`, `pearl.md`).

Os tutoriais `messaging-hub.md` e `scheduled-ops.md` são os mais úteis como referência de UX de rotina e triagem.

---

## 10. Atribuição Apache-2.0 (vale para todo item «adaptar código»)

O OpenJarvis não tem arquivo `NOTICE`. O `LICENSE` traz `Copyright 2025 The OpenJarvis Authors`. O Jarvis também é Apache-2.0, então a licença é compatível. Ao copiar ou derivar código:

1. **Cabeçalho no arquivo derivado:** «Derivado de OpenJarvis (`<caminho original>`, commit `13706f2`), © 2025 The OpenJarvis Authors, Apache-2.0. Modificado: <o que mudou>.» A seção 4(b) exige marcar a modificação.
2. **`NOTICE` do Jarvis:** nova seção «Código de terceiros incorporado», com a linha do OpenJarvis e a lista de arquivos. O `NOTICE` é verificado por máquina (`tools/license_gate.py --verificar-atribuicao`), então convém registrar a origem em `licenses/` para o portão cobrir.
3. **Texto da licença:** o Jarvis já distribui o próprio `LICENSE` Apache-2.0, e isso basta para a cópia exigida em 4(a). Citar o projeto de origem no `NOTICE`.

**Só ideia, sem código copiado** (rotina agendada, catálogo de skills, padrões de segurança), não exige atribuição. Por honestidade, cite o estudo na ADR.

---

## 11. Backlog priorizado

Escala: **valor** e **risco** em alto/médio/baixo; **esforço** em P (≤ 1 dia), M (2–4 dias), G (≥ 1 semana). A ordem combina valor alto, risco baixo e esforço baixo, e leva em conta o que o Jarvis já tem.

### Adotar ou adaptar

| # | Item | Ação | Valor | Risco | Esforço | Razão | Atribuição |
|---|---|---|---|---|---|---|---|
| 1 | **E-mail só leitura por IMAP** (`oj/connectors/imap.py`, `gmail_imap.py`) | adaptar código | alto | baixo | M | Gmail, Outlook e qualquer provedor com senha de app, sem OAuth. `readonly=True`, anti-SSRF com DNS fixado, UIDVALIDITY. Entra como capacidade `email.read.*` (tier baixo, `data_egress` declarado) e ingere no `memoryd`. A senha de app vai para o **chaveiro** (`src/jarvis/gui/chaveiro.py`), não para JSON. Falta corrigir o sync que relê `ALL` | sim: cabeçalho + NOTICE |
| 2 | **Rotina agendada falada** («bom dia, Jarvis») (`configs/openjarvis/examples/morning-digest-linux.toml`, `oj/server/digest_routes.py`) | adaptar ideia | alto | baixo | M | O Jarvis já tem TTS pt-BR, alarmes e tarefas; falta o agendador de rotinas e os coletores (agenda, e-mail, clima, não lidas das redes do ADR-0060). Começa só com fontes locais e redes; e-mail e agenda entram com os itens 1 e 3. ADR nova | não (sem código) |
| 3 | **Google Calendar só leitura** (`oj/connectors/gcalendar.py`, `google_auth.py`) | adaptar código, reescrever o OAuth | alto | médio | M/G | Resolve a **D2** da ADR-0010 para quem usa Google. Requisitos:<br>• fluxo loopback **com `state` + PKCE**;<br>• escopo `calendar.readonly`, `client_id` do dono, nunca embutido;<br>• tokens num registro só, no chaveiro, com `expires_at` e refresh proativo;<br>• página de callback sem refletir parâmetro.<br>Escrita (aceitar/criar) continua rascunho + confirmação (`egress_representacao`) | sim (o OAuth é reescrito; o cliente da API é derivado) |
| 4 | **Utilitários de rede** (backoff Gmail `oj/connectors/gmail.py:59-98`, `Retry-After` Slack, filtro de log `oj/connectors/weather.py:31-48`, limites do RSS `oj/connectors/news_rss.py:29-30`) | adaptar código | médio | baixo | P | Pequenos, sem dependência além de httpx/stdlib. Servem aos itens 1, 3 e 7 e ao `web.*`. O filtro de log reforça a política de «segredo nunca no log» | sim |
| 5 | **Pasta de notas (Obsidian/Markdown) → memória** (`oj/connectors/obsidian.py`) | adaptar ideia | médio | baixo | P | Leitura de `.md` por mtime, só nas raízes que o dono liberar (`files.*` já tem raízes). Usar com o chunk por título, sem o `porter` inglês | não, se reescrito; sim, se copiado |
| 6 | **Telegram como canal remoto do dono** (`oj/channels/telegram.py`) | adaptar código | médio/alto | médio | M | Falar com o Jarvis fora do PC por API oficial (risco de ToS baixo). Exige ADR, com:<br>• allowlist com **só o chat_id do dono**, sem pareamento aberto;<br>• token no chaveiro;<br>• tudo que chega vira `FinalTranscript` digitado, sob o mesmo PDP;<br>• nível de acesso remoto mais baixo (ADR-0009): nada perigoso sem o dono na máquina;<br>• comando «parar».<br>Do código deles: fatiamento em 4096, `drop_pending_updates`, fallback de parse_mode | sim |
| 7 | **SKILL.md (agentskills.io) como instrução** (`oj/skills/parser.py`, catálogo do `oj/skills/manager.py`) | adaptar código (parser) + ideia (catálogo) | médio | médio | M | Dá acesso ao ecossistema de skills (Anthropic, Hermes, OpenClaw) **como texto**: catálogo nome+descrição no prompt e corpo sob demanda. Regras:<br>• origem local aprovada, com sha256;<br>• sem `scripts/`, sem `git clone` automático;<br>• o corpo entra como dado sob o guarda (ADR-0049);<br>• `allowed-tools` só pode **restringir**.<br>O risco é *prompt injection*, contido pelo PDP | sim (parser) |
| 8 | **Notion só leitura** (`oj/connectors/notion.py`) | adaptar código | médio | baixo | P/M | Token de integração interna, só as páginas que o dono compartilhar. Útil se ele usar Notion; perguntar antes | sim |
| 9 | **Google Drive / Gmail API só leitura** (`oj/connectors/gdrive.py`, `gmail.py`) | adaptar depois do item 3 | médio | médio | M | Reaproveita o OAuth do item 3 com `drive.readonly`/`gmail.readonly` (nunca `gmail.modify`). Para Gmail, o item 1 já resolve sem OAuth | sim |
| 10 | **Transporte MCP Streamable HTTP** (`oj/mcp/transport.py:259-395`) | adaptar código | baixo/médio | médio | P/M | Só se o dono quiser servidores MCP remotos. Pede emenda à ADR-0052 (rede para o cliente MCP, Bearer no chaveiro). Completar com GET de stream e retomada | sim |
| 11 | **Import do export do WhatsApp para a memória** (ideia de `oj/connectors/whatsapp.py`) | reescrever | baixo/médio | baixo | P | Histórico das conversas sem tocar na conta (arquivo que o dono exporta). O parser deles não lê o formato brasileiro: escrever o nosso (Android `dd/mm/aaaa HH:MM - Nome:` e iOS `[dd/mm/aaaa, HH:MM:SS] Nome:`), com fuso local | não |
| 12 | **Lições de porta local** (`check_bind_safety`, auth por subprotocolo WS, contraexemplos de CSRF, `approve` sem estado) | adotar padrão | baixo | baixo | P | Checklist para o lado servidor do MCP (ADR-0023) e para o host da extensão. Transição de estado atômica (`WHERE status='pending'`) vale para confirmações e tarefas | não |

### Ignorar

| Item | Razão |
|---|---|
| **Ponte WhatsApp/Baileys** | Proibida por `docs/redes-sociais-riscos.md` §7 (só com ADR nova e decisão do dono). Além disso: RC, reconexão sem backoff, sem filtro de grupo e status, sem allowlist nem 0600, `dist/` ausente, zero teste do TS. O ganho (texto estruturado) vem estendendo `social-seletores.js` |
| WhatsApp Cloud API, Messenger (Página), Discord bot | Outra identidade (comercial, página ou bot). Não lê as conversas pessoais do dono; a ADR-0060 já descartou as APIs oficiais por isso |
| Twitter/X, Reddit, Mastodon, Nostr | Auto-resposta e postagem com risco de spam e ban; nenhum pedido do dono. Nostr manda DM sem criptografia |
| Signal (signal-cli-rest-api) | Só envio, cliente não oficial (dispositivo vinculado) e servidor externo. Se o dono preferir Signal ao Telegram, é estudo separado |
| Demais canais (Slack, Teams, Matrix, XMPP, LINE, Viber, Feishu, Zulip, Rocket.Chat, IRC, Twitch, Twilio, Sendblue, BlueBubbles, iMessage) | Fora do uso do dono, só envio, stub, pago ou macOS |
| Conectores Apple (iMessage, Notes, Calendar, Contacts, Music, Health) | Só macOS; o dono usa Linux (Nobara) |
| Oura, Strava, Spotify, Granola, GitHub, HackerNews | Sem pedido; Strava sem refresh. Viram itens só se o dono pedir (HackerNews/RSS como fonte da rotina do item 2 é trivial) |
| Pipeline de ingestão e busca híbrida | O `memoryd` já faz denso + FTS5 + grafo com RRF, livro-razão cifrado e índice trocável. Só as ideias pontuais da §3 |
| Pilha de voz | Inferior à nossa (sem wake word, barge-in nem streaming; VAD por RMS); Kokoro barrado por licença do espeak-ng |
| Cliente/servidor MCP (exceto o item 10) | O nosso isola o ambiente e passa pelo PDP; o deles herda segredos e não confirma |
| A2A | Rascunho antigo da spec, aberto sem token, não montado |
| Workflow, sessões, templates | Bugs (condição que não roteia, consolidação que perde dados, import quebrado); o Jarvis tem tarefas, memória e presets melhores |
| Skills TOML de pipeline e as 20 empacotadas | Template sem escape (injeção em `shell_exec`); nem são carregadas por eles |
| Servidor FastAPI, SPA React, Tauri, Docker/Render | Modelo de app diferente (Qt6 local, AppImage/deb/rpm); CSRF, chave no `localStorage` e shell sem escopo são contraexemplos |

### Ordem sugerida
1. **Item 4** (utilitários, P), como base.
2. **Item 1** (IMAP), com uma ADR curta de «conectores só leitura».
3. **Item 2** (rotina falada) sobre o que já existe.
4. **Item 3** (Calendar), que fecha a D2.
5. **Item 6** (Telegram) e **item 7** (skills) dependem de decisão do dono: canal remoto e skills de terceiros mudam a superfície de ataque.
