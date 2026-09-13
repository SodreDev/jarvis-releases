# Plano 06 — Painel Web "Stark-Classic"

> Nota do usuário: "a interface web não é literalmente uma dashboard p colocar coisas do sistema, mas sim para quando eu pedir pesquisas de certos tipos de informações seja em conjunto ou não ele pode colocar janelas e embedings lá… tipo um painel globalizado stark classic."

## Estado Atual

- `ui/index.html` — HTML único, embed simples consumido por `pywebview`.
- Sem componentes reutilizáveis, sem temas, sem painel temático multi-card.

## Conceito

Painel web **dinâmico e temático**, comandado por voz/chat. Quando o usuário pede pesquisa, o JARVIS pode renderizar **cards heterogêneos** lado a lado:
- iframe de site,
- embed de YouTube/Twitter,
- foto,
- gráfico/embed financeiro,
- bloco de código,
- thread de fórum,
- mini-mapa,
- card de notícia.

Tudo organizado por **tema** (Política, Investimentos, Notícias, Código, Fóruns, Custom).

## Plano

### Stack

- **Frontend**: HTML/CSS/JS puro inicialmente (mantém `pywebview` simples). Migração futura opcional para React/Next se a complexidade exigir.
- **Backend**: FastAPI **local** (`api/server.py`) escutando em `127.0.0.1:8765`, opcional via toggle `PANEL_API_ENABLED=False` default.
- **Transport**: WebSocket para push de novos cards do JARVIS → painel.

### Estrutura

```
dashboard/
├── server.py          ← FastAPI + WebSocket
├── card_factory.py    ← gera spec de card a partir de intent ("pesquisa: dolar hoje" → card_cotacao + card_news)
├── themes/
│   ├── politica.json
│   ├── investimentos.json
│   ├── noticias.json
│   ├── codigo.json
│   ├── foruns.json
│   └── custom.json
└── static/
    ├── index.html
    ├── styles.css
    └── app.js
```

### Modelo de Card

```json
{
  "id": "uuid",
  "type": "iframe|embed_yt|image|chart|code|markdown|news|map|custom",
  "title": "Dolar hoje",
  "theme": "investimentos",
  "size": "1x1|1x2|2x2|fullwidth",
  "content": { /* type-specific */ },
  "actions": [ {"label": "Atualizar", "intent": "refresh_cotacao"} ],
  "ttl": 3600,
  "created_at": "ISO"
}
```

### Fluxo

1. Usuário fala: "JARVIS, monta painel de investimentos hoje".
2. Intent classifier → `panel_compose(tema="investimentos")`.
3. `card_factory` consulta tools: cotação, notícias econômicas, gráfico crypto, agenda Fed.
4. Gera lista de cards → envia via WebSocket ao painel.
5. Painel anima entrada (grid responsivo, drag-to-rearrange).

### Temas (regras de composição)

Cada `themes/*.json` lista:
- cards padrão para o tema,
- tools relevantes,
- estética (paleta, ícones).

```json
{
  "name": "investimentos",
  "default_cards": ["cotacao_principais", "noticias_economia", "fed_calendar"],
  "palette": {"primary": "#00ffd1", "bg": "#0a0e1a"},
  "icon": "trending-up"
}
```

### Tools dispará-veis pelo painel

Cada card pode ter botões que reenviam intents (via WS) → JARVIS responde com novo card ou narração TTS.

### Identidade visual "Stark"

- Fundo escuro azulado (#0a0e1a).
- Detalhes neon ciano (#00d8ff) — alinhado com paleta JARVIS atual (`_CYAN`).
- Tipografia: monospace para dados, sans-serif geométrica para títulos (Inter).
- Animações sutis de entrada (slide + fade), HUD-like.

## Decisões pendentes

1. **Painel embutido no JARVIS** (mesma janela pywebview, tab) **ou janela separada**? Recomendação: janela separada, em monitor secundário (plano 05). Toggle.
2. **Persistência de layouts**: salvar último arranjo do painel? Sim, em `data/panel_state.json`.
3. **Embeds iframe**: alguns sites bloqueiam (X-Frame-Options). Estratégia: tentar iframe; se falhar, mostrar screenshot estático via Playwright.
4. **Painel acessível remotamente?** Default NÃO (bind 127.0.0.1). Toggle `PANEL_REMOTE=False`.

## Riscos

- Iframe quebrado por CSP de muitos sites — solução screenshot fallback.
- WebSocket reconnect / state sync.
- Performance com muitos cards (>20) — virtualização do grid.

## Referências de código

- [ui/index.html](../../ui/index.html) — base atual a evoluir
- [ui/core/jarvis-bridge.js](../../ui/core/jarvis-bridge.js) — bridge JS↔Python

## Histórico

- 2026-05-25 — Plano criado.
