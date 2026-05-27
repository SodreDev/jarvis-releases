# ─────────────────────────────────────────────────────────────────────────────
#  dev.ps1 — JARVIS em modo desenvolvimento (sem PyInstaller, sem rebuild)
# ─────────────────────────────────────────────────────────────────────────────
#
#  Roda main.py direto pelo Python da venv. Vantagens:
#    • Toda alteração em .py reflete na PRÓXIMA execução (sem rebuild de ~10min)
#    • config.py tem hot-reload automático (watcher a cada 10s)
#    • CSS/HTML/JS recarregam ao apertar F5 ou Ctrl+R dentro da janela
#    • Devtools do WebView2 habilitado (clique direito → Inspect)
#
#  Uso:
#    .\dev.ps1
#
#  Fluxo recomendado quando mexer no código:
#    1. Edita .py/.js/.css/.html
#    2. Se mudou só UI (CSS/HTML/JS) → F5 dentro da janela do JARVIS
#    3. Se mudou config.py → automático em ≤10s
#    4. Se mudou main.py ou outro .py → fecha (Ctrl+C neste terminal) e .\dev.ps1
#
#  Só precisa buildar (.\rebuild.ps1 ou JARVIS.spec) quando for distribuir o exe.
# ─────────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Ativa venv se ainda não estiver ativa
if (-not $env:VIRTUAL_ENV) {
    Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned -Force
    & "$PSScriptRoot\.venv\Scripts\Activate.ps1"
}

$env:JARVIS_DEV_MODE = "1"
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  JARVIS DEV MODE  ·  alterações em .py refletem na próxima run" -ForegroundColor Cyan
Write-Host "  F5 / Ctrl+R dentro da janela → recarrega UI sem reiniciar" -ForegroundColor Cyan
Write-Host "  config.py → hot-reload automático" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\main.py"
