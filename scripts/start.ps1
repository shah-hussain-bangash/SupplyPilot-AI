$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath (Join-Path $projectRoot 'backend')
try { & '..\.venv\Scripts\python.exe' -m uvicorn supplypilot.main:app --host 127.0.0.1 --port 8000 } finally { Pop-Location }
