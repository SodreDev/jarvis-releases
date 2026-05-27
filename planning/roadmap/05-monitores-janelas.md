# Plano 05 — Monitores & Janelas Multi-Tela

## Estado Atual

- `janela_ctrl.py` controla janela ativa (snap, minimizar, maximizar) com `pygetwindow` + Windows API.
- Sem detecção formal de monitores múltiplos.
- Sem distribuição inteligente de janelas.

## Problema

- Em setup multi-monitor, JARVIS abre tudo na tela principal — bagunça.
- Painel "Stark" (plano 06) precisa saber em qual tela renderizar.
- Browser automations (plano 04) precisam saber em qual monitor podem rodar sem atrapalhar.

## Plano

### Camada — `monitor/screens.py`

```python
@dataclass
class Screen:
    id: int                # 0 = primário
    name: str              # "DISPLAY1" / "\\.\DISPLAY1"
    bounds: Rect           # x, y, w, h em virtual desktop
    work_area: Rect        # área útil (descontando taskbar)
    is_primary: bool
    dpi: int
    refresh_hz: int | None

def list_screens() -> list[Screen]: ...
def primary() -> Screen: ...
def screen_at(point: tuple[int,int]) -> Screen: ...
```

Bibliotecas:
- **`screeninfo`** (cross-platform) — base.
- **`mss`** — screenshots por monitor.
- **Windows API** via `ctypes` (`EnumDisplayMonitors`) — fallback para detalhes extras.
- **`pywinctl`** — wrapper cross-platform que entende multi-monitor.

### Políticas de posicionamento

Configuráveis em `config.py`:

```python
WINDOW_PLACEMENT = {
    "panel_stark":      "secondary_or_primary",   # painel web
    "browser_jarvis":   "secondary",               # automação WA/IG/etc.
    "logs_viewer":      "tertiary_or_off",         # se houver 3+ telas
    "tts_overlay":      "primary_top_right",
}
```

### Função `place_window(hwnd, policy)`

- Resolve policy → `Screen`.
- Move janela (Windows API `SetWindowPos`) para o monitor escolhido.
- Snap opcional (esquerda/direita/quadrante).

### Multi-monitor para o usuário (cenário Stark)

- Monitor 1 = uso pessoal (JARVIS não toca).
- Monitor 2 = browser automations e painel Stark.
- Monitor 3 = logs/dashboard secundário.

Quando só há 1 monitor: tudo minimizado em segundo plano + atalho pra trazer ao topo.

## Decisões pendentes

1. **Linux**: `Xlib`/`pywinctl` cobrem? Sim, validar com Wayland (pode precisar de `pywayland`).
2. **Detecção de "qual monitor o usuário está usando"**: por foco da janela ativa. Sem heurística complexa.
3. **DPI scaling**: já temos? Provavelmente não. Adicionar tratamento `SetProcessDpiAwareness` na boot.

## Riscos

- Wayland: APIs de window placement são limitadas. Documentar feature degradada.
- Mudanças hot-plug de monitor: invalidar cache de screens em event.

## Referências de código

- [comandos/janela_ctrl.py](../../comandos/janela_ctrl.py)
- [requirements.txt](../../requirements.txt) — adicionar `screeninfo`, `pywinctl`

## Histórico

- 2026-05-25 — Plano criado.
