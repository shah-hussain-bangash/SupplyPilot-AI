$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv')) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' } }
    & '.\.venv\Scripts\python.exe' -m pip install -r backend/requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Push-Location -LiteralPath 'frontend'
    try { npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }; npm.cmd run build; if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' } } finally { Pop-Location }
    if (-not $env:DEMO_PASSWORD) { throw 'Set $env:DEMO_PASSWORD to your own password (at least 12 characters), then run setup again.' }
    Push-Location -LiteralPath 'backend'
    try {
        & '..\.venv\Scripts\python.exe' -m supplypilot.manage migrate
        if ($LASTEXITCODE -ne 0) { throw 'Migration failed.' }
        & '..\.venv\Scripts\python.exe' -m supplypilot.manage seed
        if ($LASTEXITCODE -ne 0) { throw 'Seed failed.' }
    } finally { Pop-Location }
    Write-Host 'Ready. Run .\scripts\start.ps1, then open http://127.0.0.1:8000'
} finally { Pop-Location }
