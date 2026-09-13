# Plano 04 — Browser Automation com Perfil Dedicado

## Estado Atual

- `pyautogui` usado para automações visuais (cliques, hotkeys) — interferência global.
- `playwright` listado em requirements mas pouco usado em fluxos críticos.
- WhatsApp Web e Instagram operam pelo cliente/desktop do usuário.
- Sem pool de contextos persistentes, sem perfil dedicado por plataforma.

## Problema

- `pyautogui` rouba o mouse/teclado — usuário não consegue trabalhar enquanto JARVIS opera.
- Falhas de focus = clique no lugar errado.
- Sem isolamento → uma plataforma atrapalha outra (uma janela do Chrome focada quebra fluxo de outra).

## Plano

### Arquitetura — `browser/`

```
browser/
├── pool.py             ← BrowserPool: gerencia contextos persistentes
├── profiles.py         ← carrega/cria perfis isolados em data/browser_profiles/
├── automations/
│   ├── whatsapp_web.py
│   ├── instagram_web.py
│   ├── discord_web.py
│   ├── gmail_web.py
│   └── …
├── interceptor.py      ← network mocking, request capture
└── fallback_pyauto.py  ← documentação de quando pyautogui é necessário
```

### Playwright como motor principal

- 1 instância Playwright na boot → produz contextos persistentes (`browser_context.storage_state`) por automação.
- Cada automação: `context = pool.get_or_create("whatsapp_web", profile="jarvis")`.
- Cookies, localStorage, cache → `data/browser_profiles/jarvis/whatsapp_web/`.
- Modo **headful por padrão** durante setup (QR code/login interativo); migra para **headless** após primeira sessão estabelecida.

### Janela própria, sem roubar a tela

- Contexto Playwright abre janela em **monitor secundário** quando disponível (plano 05).
- Se monitor único: janela minimizada/em segundo plano. Cliques internos via API Playwright, não OS.
- Screenshot disponível via `page.screenshot()` — nunca via `mss`/`pyautogui` no fluxo principal.

### Pool e quotas

- Limite de N contextos abertos (default 3).
- LRU eviction com `storage_state` salvo antes de descartar.
- Healthcheck periódico: navega a página simples, mede latência.

### Modo "shadow" para usuário

- Quando JARVIS opera no perfil **user**, browser dedicado tem `--user-data-dir=data/browser_profiles/user/...`.
- Nunca toca no perfil padrão do Chrome/Edge do usuário.
- Toggle `BROWSER_SHARE_USER_PROFILE=False` (default) — se True, pode reutilizar perfil principal (NÃO recomendado).

### Quando manter pyautogui

- Aplicativos nativos sem alternativa (Electron sem CDP, jogos, BIOS-like).
- Operações de OS (Win+D, Alt+Tab) onde Playwright não faz sentido.
- Documentar em `browser/fallback_pyauto.py` cada caso de uso justificado.

## Alternativas pesquisadas

- **Selenium**: mantém-se como fallback se Playwright travar. Mais lento, menos features modernas.
- **Puppeteer (via pyppeteer)**: redundante com Playwright.
- **pywinauto / pywinctl / pygetwindow**: úteis para apps nativos — incluir como complemento, não substituto.
- **mss / screeninfo**: screenshots e detecção de tela — ok para vision pipeline.

## Decisões pendentes

1. **Chromium vs Firefox vs WebKit**: para automação. Recomendação: Chromium (compat máxima com WA/IG/Discord web).
2. **Headless por default?** Não — primeira execução precisa headful para login. Após autenticar, headless ON.
3. **Sidecar de WhatsApp** (`wppconnect`): roda em Node.js separado ou via Playwright direto? Recomendação: Playwright direto reduz dependências.

## Riscos

- Playwright pesado em RAM com vários contextos. Mitigar: pool LRU + suspender contextos ociosos.
- Sites detectam automação → usar `playwright-stealth` quando necessário.

## Referências de código

- [requirements.txt](../../requirements.txt) — playwright já listado
- [comandos/browser_ctrl.py](../../comandos/browser_ctrl.py) — base atual de browser
- [comandos/janela_ctrl.py](../../comandos/janela_ctrl.py) — pyautogui-heavy a ser rebaixado

## Histórico

- 2026-05-25 — Plano criado.
