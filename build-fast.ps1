# build-fast.ps1 — rebuild rápido do JARVIS.exe
#
# Diferenças vs. build limpo:
#   • SEM --clean  → reaproveita análise/cache do PyInstaller (5-10x mais rápido)
#   • UPX desligado no spec → sem compressão lenta
#   • --log-level WARN     → menos ruído no terminal
#
# Use ESTE script no dia-a-dia. Só rode build "limpo" se algo bugar:
#   .\.venv\Scripts\python.exe -m PyInstaller JARVIS.spec --clean --noconfirm
#
# LEMBRE: pra mudanças em .py (main.py, comandos/, core/, etc.) você
# NÃO precisa rebuildar — o launcher.py carrega o source ao vivo.
# Basta fechar e reabrir o JARVIS.exe. Use rebuild só quando:
#   - instalou pacote pip novo
#   - mudou ui/, config/, gesture_data/
#   - mudou launcher.py ou JARVIS.spec

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Garante que o exe não está rodando (senão PyInstaller falha ao escrever)
$proc = Get-Process JARVIS -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "[build-fast] JARVIS.exe está rodando. Feche-o e rode de novo." -ForegroundColor Yellow
    exit 1
}

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "[build-fast] .venv não encontrado em $python" -ForegroundColor Red
    exit 1
}

$t0 = Get-Date
Write-Host "[build-fast] Iniciando build incremental (sem --clean, sem UPX)..." -ForegroundColor Cyan

& $python -m PyInstaller JARVIS.spec --noconfirm --log-level WARN

$dt = (Get-Date) - $t0
Write-Host ("[build-fast] Concluído em {0:N1}s." -f $dt.TotalSeconds) -ForegroundColor Green

if (Test-Path "dist\JARVIS\JARVIS.exe") {
    $exe = Get-Item "dist\JARVIS\JARVIS.exe"
    Write-Host ("[build-fast] dist/JARVIS/JARVIS.exe  ({0:N1} MB)" -f ($exe.Length / 1MB))
}
