# Plano 12 — Config Padrão & Instalador (Default OFF)

> Crítico: o JARVIS vai virar instalador para terceiros. Sem este plano, ele vaza segredos pessoais.

## Estado Atual

- `config.py` mistura: API keys (preenchidas com chaves do dono atual), prompts, toggles, caminhos absolutos.
- Não existe `config.template.py`.
- Nenhum gating de feature por toggle (a maioria liga automaticamente).
- Instalador inexistente.

## Problema

- Distribuir hoje vazaria todas as credenciais pessoais.
- Pessoas instalando teriam features pesadas (Spotify, IG, WA) ligadas sem nem ter configurado nada.
- Sem onboarding wizard.

## Plano

### Separação dos `config`

```
config/
├── __init__.py              ← API pública (re-exporta de defaults + user)
├── defaults.py              ← TODOS os toggles em False/seguro
├── prompts.py               ← prompts de LLM (não-secreto)
├── paths.py                 ← caminhos relativos (sem hardcode de C:\Users\lilia)
└── schema.py                ← validação Pydantic do user config

# fora do repo, no disco do usuário:
%APPDATA%/JARVIS/config.user.toml   ← config do usuário
%APPDATA%/JARVIS/credentials/        ← vault (plano 03)
```

`config.py` atual vira `config/defaults.py` com **TODOS os segredos removidos** e **todos os toggles em `False`**.

### TOML para config do usuário

```toml
[general]
language = "pt-BR"
tts_voice = "pt-BR-AntonioNeural"

[voice]
wake_word_enabled = false      # default OFF
ptt_enabled = true             # PTT é menos intrusivo, default ON
mic_device = "default"

[features]
spotify = false
whatsapp = false
instagram = false
discord = false
telegram = false
gmail = false
panel_stark = false
documents_generation = false
ocr = false
embeddings = false
mcp_server = false

[security]
profile = "normal"             # normal | paranoid | kiosk
confirm_destructive = true
allowed_dirs = ["~/Downloads", "~/Documents", "~/Desktop"]

[llm]
provider = "groq"              # groq | lmstudio | ollama
groq_model = "llama-3.3-70b-versatile"
classifier_model = "llama-3.1-8b-instant"

[messaging]
default_profile = "jarvis"     # jarvis | user

[panel]
enabled = false
port = 8765
remote_access = false          # bind 127.0.0.1
```

### Wizard de primeira execução

CLI/GUI passo a passo:

1. Idioma.
2. Modo de ativação (PTT recomendado por ser mínimo intrusivo).
3. Voz/TTS — escolher modelo (mostrar samples).
4. LLM — usar Groq (precisa key) ou LM Studio local?
5. **Pular tudo o resto** — features avançadas ficam OFF; usuário liga quando quiser via UI.
6. Vault setup (senha mestra opcional).

### Mapa de toggles → módulos

| Feature | Toggle | Impacto se OFF |
|---------|--------|----------------|
| Spotify | `features.spotify` | tools `controle_spotify` desregistradas; nenhum import de `spotipy`. |
| WhatsApp | `features.whatsapp` | tools `enviar_whatsapp` ocultas; nenhum import de `pywhatkit`. |
| Instagram | `features.instagram` | idem para `instagrapi`. |
| Painel Stark | `features.panel_stark` | servidor FastAPI não inicia. |
| Geração docs | `features.documents_generation` | bibliotecas pesadas não importadas. |
| OCR | `features.ocr` | `pytesseract` não importado, função degradada. |
| Embeddings | `features.embeddings` | tier 2 da memória desligado. |

Implementação: lazy import dentro das funções de cada tool, gateadas por `if config.features.X`.

### Instalador

#### Windows
- `JARVIS-installer.exe` via Inno Setup ou NSIS.
- Bundles: Python embeddable + venv + dependências mínimas.
- Optionals (Tesseract, Playwright browsers, modelos locais) — download sob demanda.

#### Linux (futuro)
- AppImage ou Flatpak.
- `.deb` / AUR.

#### macOS (futuro)
- `.dmg` com app bundle.

### Migração para o usuário existente

- Script `tools/migrate_to_user_config.py`:
  - Lê `config.py` atual.
  - Extrai segredos → `credentials/` (plano 03).
  - Extrai toggles → `config.user.toml`.
  - Backup do `config.py` antigo.

## Decisões pendentes

1. **TOML vs YAML vs JSON p/ config**: TOML recomendado (legível, suportado nativo no Python 3.11+).
2. **Pydantic v2 para schema**: sim, rapidíssimo e dá hint helpful.
3. **Wizard CLI vs GUI**: ambos. Boot detecta se há config válido; se não, oferece os dois.

## Riscos

- Atrasar este plano = não dá pra distribuir. **Bloqueante.**
- Quebrar a build do dono atual ao migrar. Mitigar: manter `config.py` antigo carregável como fallback por 1 versão.

## Referências de código

- [config.py](../../config.py) — fonte atual
- [requirements.txt](../../requirements.txt) — pesos a tornar opcionais

## Histórico

- 2026-05-25 — Plano criado.
