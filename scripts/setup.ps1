# One-time setup for Windows (PowerShell).
# Run from the project folder:   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "`n[1/5] Checking tools..." -ForegroundColor Cyan
foreach ($tool in @("python", "node", "npm")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not installed or not on PATH." }
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) { Write-Warning "Ollama not found. Install it from https://ollama.com/download" }

Write-Host "[2/5] Creating Python virtual environment (.venv)..." -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

Write-Host "[3/5] Creating .env from .env.example..." -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    $tess = "C:\Program Files\Tesseract-OCR\tesseract.exe"
    if (Test-Path $tess) { (Get-Content .env) -replace '^TESSERACT_CMD=.*', "TESSERACT_CMD=$tess" | Set-Content .env }
}

Write-Host "[4/5] Installing frontend packages..." -ForegroundColor Cyan
Push-Location frontend; npm install; Pop-Location

Write-Host "[5/5] Downloading AI models with Ollama..." -ForegroundColor Cyan
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    ollama pull llama3.2:3b
    ollama pull embeddinggemma
}

Write-Host "`nSetup complete. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\start.ps1" -ForegroundColor Green
