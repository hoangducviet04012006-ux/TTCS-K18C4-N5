param(
    [int]$Port = 0
)

$projectRoot = (Split-Path -Parent $PSScriptRoot).TrimEnd('\/')
$stoppedAny = $false

$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' }

if ($Port -gt 0) {
    $listeners = $listeners | Where-Object { $_.LocalPort -eq $Port }
} else {
    $listeners = $listeners | Where-Object { $_.LocalPort -ge 8765 -and $_.LocalPort -le 8865 }
}

foreach ($tcp in $listeners) {
    $p = $tcp.LocalPort
    try {
        $info = Invoke-RestMethod -Uri "http://127.0.0.1:$p/system-info" -TimeoutSec 1 -ErrorAction SilentlyContinue
        if ($null -ne $info -and $info.code_root.TrimEnd('\/') -eq $projectRoot) {
            $pidToStop = $tcp.OwningProcess
            Write-Host "Stopping AgriTrace on port $p (PID: $pidToStop)..." -ForegroundColor Yellow
            Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
            $stoppedAny = $true
        }
    } catch { }
}

if ($stoppedAny) {
    Write-Host "AgriTrace server(s) stopped." -ForegroundColor Green
} else {
    Write-Host "No active AgriTrace server found for project: $projectRoot" -ForegroundColor Cyan
}
