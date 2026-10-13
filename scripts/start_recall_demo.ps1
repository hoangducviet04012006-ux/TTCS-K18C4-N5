param([int]$Port = 8766, [string]$DatabaseName = "demo_3b2b.db")
$ErrorActionPreference = "Stop"
if ($DatabaseName -notmatch '^[a-zA-Z0-9_-]+\.db$') { throw "Use a simple .db filename" }
$demoRoot = Split-Path -Parent $PSScriptRoot
$demoPython = Join-Path $demoRoot 'backend/.venv/Scripts/python.exe'
$demoDatabase = Join-Path $demoRoot ".recall-trial/$DatabaseName"
Push-Location (Join-Path $demoRoot 'backend')
try {
    Write-Host "Recall TEST ONLY: http://127.0.0.1:$Port/"
    Write-Host "Login recall_inspector / RecallDemo!2026; Ctrl+C to stop."
    & $demoPython -m scripts.run_recall_demo --db $demoDatabase --port $Port
    if ($LASTEXITCODE -ne 0) { throw "Recall demo failed; no fallback to original database." }
} finally { Pop-Location }
