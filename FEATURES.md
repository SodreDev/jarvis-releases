# Features Implementadas — JARVIS

> Lista viva. Cada item entra aqui no momento em que o código é escrito (independente de estar "ligado" no `main.py` ou não).
> Status: 🟢 pronto p/ testar · 🟡 parcial · 🔴 não testado · ⚪ wired-in no main

Última atualização: 2026-05-25 — Sprint 1 concluído.

---

## Sprint 1 — Fundação modular ✅

Toda a Sprint 1 vive em paralelo com `main.py` (que **não foi tocado**). Os novos módulos são opt-in; o wiring acontece quando você for testar.

### Estrutura geral
- 🟢 `planning/roadmap/` com 14 documentos (índice + 12 planos + PRINCIPIOS).
- 🟢 `FEATURES.md` (este arquivo) como changelog vivo.

### Pacote `jarvis/` (Plano 01 — Fase A)
- 🟢 Subpacotes com `__init__.py`: `config/`, `credentials/`, `browser/`, `messaging/`, `intents/`, `llm/`, `connectors/`, `memory/`, `dashboard/`, `monitor/`, `filesystem/`, `plugins/`, `mcp/`, `api/`.
- 🟢 `jarvis/__init__.py` expõe `__version__ = "0.1.0-modular"`.

### Configuração tipada (Plano 12)
- 🟢 `jarvis/config/defaults.py` — todos os toggles em `False`.
- 🟢 `jarvis/config/schema.py` — Pydantic v2 com fallback dataclass.
- 🟢 `jarvis/config/loader.py` — TOML em `%APPDATA%/JARVIS/config.user.toml` → `./config.user.toml` → defaults.
- 🟢 `jarvis/config/paths.py` — paths relativos, nada hardcoded.
- 🟢 `config.user.example.toml` na raiz documentando todas as opções.
- 🟢 `python -m jarvis.config.loader` (testado: tudo OFF).

### Cofre de credenciais (Plano 03)
- 🟢 `jarvis/credentials/vault.py` — Vault auto-tier.
- 🟢 Tier 1 (default): JSON com chmod 0600 em `%APPDATA%/JARVIS/credentials/profiles/<profile>/<key>.json`.
- 🟢 Tier 2 (opt-in): AES-GCM + PBKDF2-HMAC-SHA256 (200k) sob `security.vault_encrypted=True`.
- 🟢 Audit log em `logs/credentials_access.jsonl` (sem valores).
- 🟢 Perfis: `jarvis`, `user`, `shared`.
- 🟢 CLI `python -m jarvis.credentials.vault list|set|get`. **Testado:** set/get/delete round-trip ok.

### Browser leve, humano e isolado (Plano 04) — atende à sua restrição de não interferir no teclado/mouse
- 🟢 `jarvis/browser/profiles.py` — `user_data_dir` separado por `(perfil, plataforma)` em `data/browser_profiles/<profile>/<platform>/`.
- 🟢 `jarvis/browser/launcher.py` — flags Chromium otimizadas:
  - `--disable-blink-features=AutomationControlled` (stealth básico)
  - `--mute-audio`, `--no-first-run`, `--disable-features=Translate,AcceptCHFrame,MediaRouter,OptimizationHints`
  - `--disable-background-timer-throttling`, `--disable-renderer-backgrounding`, `--disable-backgrounding-occluded-windows` (continua leve mesmo minimizado)
  - `--window-position=-32000,0` (janela fora da área visível, não rouba foco do usuário).
- 🟢 `jarvis/browser/human.py` — comportamento humano via API do Playwright (NÃO via teclado/mouse do SO):
  - `human_pause(min,max)` — pausas configuráveis.
  - `human_type(target, text)` — delays gaussianos, WPM configurável, pausas extras em pontuação.
  - `human_click(locator)` — hover + jitter aleatório (px configurável) + clique com delay.
  - `human_scroll(page)` — easing cubic-in-out.
- 🟢 `jarvis/browser/pool.py` — `BrowserPool` LRU (default 3 contextos), `launch_persistent_context` preserva login entre execuções, stealth via `add_init_script` (sem dependência externa). Bridge sync `run_sync(coro)`.
- 🟢 `jarvis/browser/smoke.py` — `python -m jarvis.browser.smoke <platform> <profile> [url]`.
- 🟢 **Toda operação via API Playwright** (`page.click`, `page.fill`, `mouse.wheel` dentro do contexto). PyAutoGUI rebaixado a fallback documentado.

### Mensageria abstrata (Plano 02 — base)
- 🟢 `jarvis/messaging/base.py` — `MessageBackend` Protocol + `Message`/`SendResult`/`Contact` + decorator `@register_backend(platform, profile)`.
- 🟢 `jarvis/messaging/router.py` — `MessagingRouter` resolve por (plataforma, perfil) respeitando `messaging.default_profile` e `messaging.ambiguity_policy`.
- 🟢 `jarvis/messaging/stubs.py` — 7 backends-stub registrados: WhatsApp jarvis+user, Instagram jarvis+user, Discord jarvis, Telegram jarvis, Gmail user (todos `is_available=False` até implementação real). **Testado.**

### Intents (Plano 01 — Fase B)
- 🟢 `jarvis/intents/registry.py` — `IntentRegistry` + `IntentMatch` (confidence + payload).
- 🟢 `jarvis/intents/spotify.py` — proof of concept: regex Spotify migrados (pause/resume/next/previous/mute/unmute/vol±/now_playing/play c/ tipo). **Testado**, 4/5 frases batem.
- 🟡 Outros domínios (sistema, mensageria, pesquisa, alarmes) ficam para Sprint 2.

### LLM client unificado (Plano 01 — Fase D)
- 🟢 `jarvis/llm/client.py` — `LLMClient` thread-safe:
  - Substitui os 4 métodos do `main.py` (`_lm_chat`/`_lm_chat_stream`/`_groq_chat`/`_groq_chat_stream`).
  - `client.chat(text, *, system, stream, provider='auto', history_key)`.
  - Histórico múltiplo por chave; scrub num único ponto; auto-fallback LM Studio ↔ Groq.
  - Lê `groq_api_key` do vault (`shared`) com fallback para env var. **Testado.**

### Migração (Plano 12)
- 🟢 `tools/migrate_to_user_config.py`:
  - Lê `config.py` + `credentials/.env` + env vars.
  - Gera `config.user.toml` no APPDATA (não sobrescreve).
  - Popula vault tier-1 com chaves detectadas.
  - Dry-run por default; use `--apply` para gravar. **Testado.**

### Validação final
- 🟢 `main.py` continua parseando (`ast.parse`).
- 🟢 31 módulos `jarvis/` importam sem erro.
- 🟢 `playwright` já está em requirements; antes do primeiro browser real: `playwright install chromium`.

---

## Como testar (sugestão de ordem)

1. **Config**
   ```powershell
   .\.venv\Scripts\python.exe -m jarvis.config.loader
   ```

2. **Vault**
   ```powershell
   .\.venv\Scripts\python.exe -m jarvis.credentials.vault set teste meu_valor --profile shared
   .\.venv\Scripts\python.exe -m jarvis.credentials.vault list --profile shared
   .\.venv\Scripts\python.exe -m jarvis.credentials.vault get teste --profile shared
   ```

3. **Intents Spotify** (compare com `main.py`)
   ```powershell
   .\.venv\Scripts\python.exe -c "from jarvis.intents import get_registry; r=get_registry(); print(r.detect('pausa a musica'))"
   ```

4. **LLM client** (precisa LM Studio ou GROQ_API_KEY)
   ```powershell
   .\.venv\Scripts\python.exe -c "from jarvis.llm import get_client; print(get_client().chat('oi'))"
   ```

5. **Migração para `config.user.toml`** (dry-run primeiro!)
   ```powershell
   .\.venv\Scripts\python.exe -m tools.migrate_to_user_config
   .\.venv\Scripts\python.exe -m tools.migrate_to_user_config --apply
   ```

6. **Browser smoke**
   ```powershell
   .\.venv\Scripts\python.exe -m playwright install chromium
   .\.venv\Scripts\python.exe -m jarvis.browser.smoke teste jarvis https://example.com
   ```
   Esperado: janela aparece **fora da tela visível**, **não rouba** seu mouse/teclado, fecha após 5s.

---

## Build / executável (live-source)

O `launcher.py` já injeta o repo no `sys.path` → **todo `.py` do pacote `jarvis/` é live** (edita salva e roda no próximo restart do JARVIS, sem rebuild).

**1 rebuild único é necessário** para o exe puxar as 3 wheels novas (`pydantic`, `playwright`, `cryptography` já estava). Depois disso, qualquer mudança em `jarvis/*.py` é instantânea.

Preparado nesta sprint:
- 🟢 `launcher.py` — bloco `if False: import jarvis.*` força o scanner a empacotar tudo.
- 🟢 `JARVIS.spec` — `collect_all('pydantic')`, `collect_all('playwright')`, `collect_all('cryptography')`, `collect_all('openai')` + hiddenimports completos do pacote `jarvis/`.
- 🟢 `requirements.txt` — `pydantic>=2.0`, `playwright>=1.40`, `tomli` (fallback) declarados.

Comando do rebuild (executar **uma vez** após Sprint 1):
```powershell
.\.venv\Scripts\python.exe -m playwright install chromium   # se ainda não rodou
.\.venv\Scripts\python.exe -m PyInstaller JARVIS.spec --noconfirm
```

Quando precisar recompilar de novo (raro):
- Adicionar **novo pacote pip** com binários nativos.
- Mudar `launcher.py` ou `JARVIS.spec`.
- Mudar assets em `ui/`, `gesture_interface/`, `config/`.

Editar qualquer `.py` (incluindo `main.py`, `comandos/*`, `jarvis/*`) → **não precisa rebuildar**.

---

## Sprint 2 — Backends Chromium reais (sem APIs) + mais intents ✅

**Regra de ouro reforçada** (ver [PRINCIPIOS.md §0](planning/roadmap/PRINCIPIOS.md)):
> Toda mensageria acontece dentro do **Chromium** (Playwright), simulando humano,
> com janela off-screen. **PROIBIDO** usar `instagrapi`, `discord.py`,
> `python-telegram-bot`, Gmail API, `pywhatkit`, etc. Zero risco de ban.

### Backends concretos Chromium-only
- 🟢 [jarvis/messaging/web_base.py](jarvis/messaging/web_base.py) — `WebChatBackend` base:
  - Cada subclasse declara: `URL_HOME`, `URL_CHAT_PATTERN`, `SEL_COMPOSER`, `SEL_SEND_BUTTON`, `SEL_LOGGED_IN`, `SEL_LOGIN_HINT`, `LOGIN_TIMEOUT_S`.
  - `send()` síncrono que internamente faz: `pool.start()` → `get_context` → `_ensure_logged_in` → `open_chat` → `human_type` → `human_click`/Enter → `post_send_check`.
  - `is_available()` retorna True somente se já existe pasta de sessão (cookies salvos).
  - `_ensure_logged_in()` espera o usuário escanear QR/digitar senha na primeira vez (timeout configurável).
- 🟢 [jarvis/messaging/backends/whatsapp_web.py](jarvis/messaging/backends/whatsapp_web.py) — web.whatsapp.com (deep-link `?phone=`).
- 🟢 [jarvis/messaging/backends/instagram_web.py](jarvis/messaging/backends/instagram_web.py) — instagram.com/direct (busca via UI, sem instagrapi).
- 🟢 [jarvis/messaging/backends/discord_web.py](jarvis/messaging/backends/discord_web.py) — discord.com/app (sem discord.py).
- 🟢 [jarvis/messaging/backends/telegram_web.py](jarvis/messaging/backends/telegram_web.py) — web.telegram.org/k/.
- 🟢 [jarvis/messaging/backends/gmail_web.py](jarvis/messaging/backends/gmail_web.py) — mail.google.com (compose → assunto → corpo → enviar).
- 🟢 `jarvis/messaging/stubs.py` virou shim de compat re-exportando os backends novos.
- 🟢 **10 backends registrados** (5 plataformas × 2 perfis `jarvis`/`user`).

### Mais intents migradas do main.py
- 🟢 [jarvis/intents/sistema.py](jarvis/intents/sistema.py) — encerrar, volume sistema, mute, screenshot, minimizar/maximizar/fechar janela, lock, abrir app.
- 🟢 [jarvis/intents/mensageria.py](jarvis/intents/mensageria.py) — detecta plataforma + ação (`send`/`read`/`open`) + extrai `dest`, `content`, `profile_hint`.
- 🟢 Registry com **ordem prioritária**: mensageria → sistema → spotify (mais específico primeiro).
- 🟢 **7/7 frases de teste** batem corretamente (validado).

### Bridge LLM opt-in
- 🟢 [jarvis/llm/bridge.py](jarvis/llm/bridge.py) — `maybe_install_bridge(jarvis_obj)`:
  - Quando `llm.use_modular_client = true` no TOML, faz monkey-patch dos 4 métodos `_lm_chat*`/`_groq_chat*` do `JarvisApp`.
  - **Não modifica `main.py`** — você ativa quando quiser testar; basta uma linha adicionada em `__init__`.
  - Default: OFF (zero efeito colateral).
- 🟢 `llm.use_modular_client` adicionado ao schema + defaults.

### Validação final
- 🟢 `main.py` continua parseando (`ast.parse`).
- 🟢 Todos os 35+ módulos `jarvis/` importam.
- 🟢 10 backends registrados; intents passam todos os testes.

---

## Como testar Sprint 2

1. **Detecção de intents** (não toca main, só compara):
   ```powershell
   .\.venv\Scripts\python.exe -c "from jarvis.intents import get_registry; r=get_registry(); [print(t, '->', r.detect(t)) for t in ['pausa a musica','manda whats pro joao dizendo oi','le mensagens do instagram','encerrar']]"
   ```

2. **Backend WhatsApp Web (primeira execução faz QR)**:
   ```powershell
   .\.venv\Scripts\python.exe -m playwright install chromium
   .\.venv\Scripts\python.exe -c "from jarvis.messaging import get_backend; b=get_backend('whatsapp','user'); print(b.send('5511999999999', 'teste'))"
   ```
   Esperado:
   - Janela Chromium abre em `-32000,0` (fora da tela). **Importante**: para escanear QR, você precisa MOVER a janela manualmente (vou criar uma flag `first_login` na Sprint 3 para abrir visível só na 1ª vez). Por ora: edite `config.user.toml` → `[browser] off_screen_position = false` antes do primeiro login.
   - Cookies salvos em `data/browser_profiles/user/whatsapp/`.
   - Restarts seguintes: login automático, janela permanece off-screen, mensagem enviada com digitação humana.

3. **Bridge LLM** (ative em `config.user.toml`):
   ```toml
   [llm]
   use_modular_client = true
   ```
   Depois, em `main.py`, adicione **uma linha** no início de `JarvisApp.__init__()`:
   ```python
   from jarvis.llm.bridge import maybe_install_bridge; maybe_install_bridge(self)
   ```
   Pronto — os 4 métodos `_lm_chat*`/`_groq_chat*` passam a usar `jarvis.llm.LLMClient`.

---

## Próximas sprints (você decide quando)


- **Sprint 2 — Wiring no `main.py`**
  - Substituir `_lm_chat*` por `jarvis.llm.LLMClient`.
  - Migrar detectores de regex restantes para `jarvis/intents/*.py` (sistema, mensageria, pesquisa, alarmes, pomodoro, agenda, etc.).
  - Trocar leitura de secrets em `config.py` por `vault.get(...)`.
- **Sprint 3 — Conectores reais** (Planos 02 + 04)
  - `WhatsAppWebUserBackend` usando `BrowserPool` + `human_*`.
  - `InstagramJarvisBackend` (sessão isolada do `instagrapi`).
  - Discord bot (`discord.py`) para perfil `jarvis`.
- **Sprint 4 — Painel Stark** (Plano 06), memória SQLite (Plano 07), permissões refinadas (Plano 09).
- **Sprint 5 — Documentos** (Planos 10+11), MCP (Plano 08).
