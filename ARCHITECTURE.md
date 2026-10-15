# Arquitetura do J.A.R.V.I.S

Visão técnica do projeto para quem vai contribuir ou entender o código. Para a lista de
funcionalidades e instalação, veja o [README](README.md).

---

## Visão geral

JARVIS é um assistente de IA desktop para **Windows**, escrito em **Python**, com UI em
**pywebview** (WebView2). Conecta múltiplos LLMs (Groq, LM Studio local, Gemini) a um
grande conjunto de ferramentas — controle do sistema, automação web, mensageria, mídia,
biblioteca de jogos, geração de documentos — acionáveis por voz, chat ou gestos.

O empacotamento usa **PyInstaller** (`.exe`) + **Inno Setup** (instalador), e a
atualização é feita via **GitHub Releases** (`updater/check_update.py`).

---

## Arquitetura dupla (importante)

O código vive em **duas camadas em paralelo**, fruto de uma migração incremental em
andamento:

### 1. `main.py` — monolito ativo (~12,4k linhas)
É o **app de produção** hoje. Contém:
- `JarvisApp` — UI pywebview, captura de áudio, wake-word/PTT, histórico, estado de comando.
- `JarvisApi` — ponte JavaScript ↔ Python exposta ao WebView.
- Integração com LLM (streaming e não-streaming), dispatch de ferramentas, ~150 regex de
  intenção, e fluxos de confirmação/estado.

### 2. Pacote `jarvis/` — camada modular nova (`v0.1.0-modular`, ~2,85k linhas)
Alvo da migração, hoje **majoritariamente opt-in**. A integração com o `main.py` é
mínima (paths de histórico, monkey-patch opcional do cliente LLM em `jarvis/llm/bridge.py`
atrás de flag, checagem do Chromium no boot, fallback de Instagram). Vários subpacotes
ainda são **stubs**: `memory/`, `dashboard/`, `filesystem/`, `mcp/`, `plugins/`,
`connectors/`, `api/`. As fases da migração estão documentadas em `planning/roadmap/`.

**Duplicação legado → modular** (a consolidar ao longo da migração):

| Domínio | Legado (ativo) | Modular (novo) |
|---|---|---|
| Config | `config.py` (dict plano, ~74 KB) | `jarvis/config/` (TOML tipado) |
| Mensageria | `comandos/msg_sender.py` + `core/jarvis_prefix_router.py` + `core/person_memory.py` | `jarvis/messaging/` (router + backends) |
| Browser | `comandos/browser_ctrl.py` (ThreadPool Playwright) | `jarvis/browser/` (pool + perfis) |
| Intenções | regex espalhadas no `main.py` | `jarvis/intents/` (registry) |

---

## Mapa de pastas

```
main.py / launcher.py / version.py / VERSION / config.py   entry points + config legado
comandos/        ~40 módulos *_ctrl.py + tool_registry.py (tools p/ LLM) + executor.py (intents legados)
core/            infra runtime: event_bus, ambient_listener, proactive_engine, config_manager,
                 person_registry/memory, game_*; core/dev_mode/ (ponte VSCode)
jarvis/          pacote modular novo (config, credentials/vault, browser, messaging, llm, intents, …)
classifiers/     embeddings (sentence-transformers) p/ classificação de intenção
documents/       geração de PDF/DOCX/XLSX/PPTX + charts
entity/          app_detector (Levenshtein) + descoberta de jogos/bibliotecas
security/        sanitizer, vault (em memória), permissions
VozIa/           engines de TTS (kokoro offline, edge, elevenlabs, gemini) + normalizador
updater/         check_update.py (auto-update via GitHub Releases)
tools/           make_release.py (pipeline de release) + migrate_to_user_config.py
installer/       jarvis.iss (Inno Setup)        plugins/  loader + plugin "hello" de exemplo
config/          intents.json (apps_cache.json é cache de runtime, gitignored)
ui/              frontend pywebview: index.html (Stark) + themes/ (macos, minimal) + core/jarvis-bridge.js
gesture_interface/  MediaPipe local: gesture_engine, eye_tracker, canvas2d, workspace3d (Three.js)
dashboard/       FastAPI :8765 (painel Stark, WebSocket)       ide/  FastAPI /ide (editor + terminal)
vscode_extension/jarvis-dev-bridge  extensão TypeScript, WebSocket :6589 p/ Copilot
planning/roadmap/  docs das fases da migração modular
credentials/     dados pessoais e chaves (gitignored; só .env.example/.gitkeep/README versionados)
data/            runtime: browser_profiles, people_memory, img_cache, temp_charts (gitignored)
```

---

## Configuração e credenciais (em camadas)

Ordem de precedência (legado):
`config.py` (defaults) → `os.environ` (carregado de `credentials/.env`) →
`jarvis_prefs.json` (seção `settings`) → overrides por módulo.

Em paralelo, o sistema novo `jarvis/config/` carrega `config.user.toml` de
`%APPDATA%/JARVIS/` (ou da raiz, em dev). Todos os caminhos são detectados via
`sys.frozen`/`__file__` — **sem caminhos hard-coded** no código.

**Segredos nunca entram no git.** Tudo em `credentials/` é gitignored, exceto o template
`.env.example`, o `README.md` e o `.gitkeep`. O vault novo (`jarvis/credentials/vault.py`)
suporta Tier 1 (JSON por perfil) e Tier 2 (AES-GCM opcional), com trilha de auditoria.

---

## Ciclo build → run → update

### Padrão "live-source" (`launcher.py`)
O `.exe` (PyInstaller) carrega as dependências nativas do bundle (`_internal/`) mas
**executa os `.py` direto da pasta do projeto** (dois níveis acima do exe, ou via
`JARVIS_SOURCE`). Resultado: mudanças em `.py` valem no próximo restart **sem recompilar**.
Só é preciso recompilar para novas wheels nativas, mudança de assets, ou do próprio launcher.

### Pipeline de release (`tools/make_release.py`)
8 etapas, abortando em qualquer falha:
1. **scan de segredos** (regex contra OpenAI/Groq/Gemini/GitHub PAT/AWS/etc.) — aborta se achar
2. **bump** do arquivo `VERSION`
3. **PyInstaller** → `dist/JARVIS/JARVIS.exe`
4. **Inno Setup** → `installer/output/JARVIS_Setup_vX.Y.Z.exe`
5. **payload** → `installer/output/update_payload_vX.Y.Z.zip` (somente `.py` + config seguro)
6. **SHA256SUMS.txt**
7. **release notes** (template markdown para editar)
8. **git tag** local `vX.Y.Z`

> O script **nunca** roda `git push` nem `gh release create` automaticamente — a
> publicação é manual. Flags úteis: `--scan-only`, `--skip-build` (payload-only, rápido),
> `--skip-installer`, `--skip-tag`.

### Atualização (`updater/check_update.py`)
Compara `VERSION` com `releases/latest` de `SodreDev/jarvis-releases`, baixa o
`update_payload` (ou o instalador), e extrai com validação anti-traversal, **preservando**
`credentials/`, `data/`, `temp/`, `logs/`, `build/`, `dist/`, `.venv/`, `.git/`.

### Artefatos NÃO versionados
`build/`, `dist/`, `installer/output/` (instaladores de 366 MB, payloads, checksums) são
**gitignored** de propósito — eles vão para o **GitHub Releases**, não para o repositório.

---

## Surfaces de UI (5)

1. **App principal** — pywebview, `ui/` (temas Stark/macOS/minimal) via `jarvis-bridge.js`.
2. **Gestos** — `gesture_interface/`, MediaPipe **local** (nenhum frame sai do processo).
3. **Dashboard** — FastAPI em `:8765` (painel + WebSocket).
4. **IDE** — FastAPI em `/ide` (editor + terminal multi-sessão).
5. **Extensão VSCode** — TypeScript, WebSocket `:6589` → Copilot (uso local; sem TLS/auth).

---

## Dívida técnica conhecida

- `main.py` é um *god object* (UI + áudio + LLM + dispatch + estado num só arquivo).
- Duplo caminho de dispatch (regex legado vs tool-calling do LLM) e ~150 regex hardcoded.
- Histórico de chat sem janela deslizante (pode crescer sem limite em sessões longas).
- Sem suíte de testes (`pytest`) e sem telemetria estruturada (logs via `print`).
- `main.py.bak` e `requirements.txt.bak` órfãos (ignorados; podem ser apagados).
- Migração para o pacote `jarvis/` incompleta (ver tabela de duplicação e `planning/roadmap/`).
