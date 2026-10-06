# Starts the backend and the frontend in two windows (Windows).
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = Get-Location
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .\.venv\Scripts\Activate.ps1; python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 5001"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Start-Sleep -Seconds 4
Start-Process "http://127.0.0.1:5173"
