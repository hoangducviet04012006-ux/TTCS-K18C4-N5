param([switch]$NoBrowser, [switch]$StopAfterCheck, [int]$Port = 8765,
      [string]$DatabaseName = 'demo_sprint123_realistic.db')
$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $demoRoot 'backend'
$logRoot = Join-Path $demoRoot '.demo-logs'
$started = $null
try {
    if ($DatabaseName -notin @('demo_sprint123_realistic.db', 'demo_sprint123.db')) {
        throw 'This launcher only supports demo databases inside .sprint123-trial; refusing another database.'
    }
    if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Use -Port between 1024 and 65535.' }
    $demoDatabase = Join-Path $demoRoot ".sprint123-trial/$DatabaseName"
    $pythonExe = Join-Path $backendRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Create backend/.venv and install backend/requirements.txt first.' }
    $requestedPort = $Port
    $portFound = $false
    for ($candidate = $requestedPort; $candidate -le [Math]::Min(65535, $requestedPort + 99); $candidate++) {
        $reservation = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidate)
        $reservation.Server.ExclusiveAddressUse = $true
        try {
            $reservation.Start()
            $Port = $candidate
            $portFound = $true
            break
        } catch [System.Net.Sockets.SocketException] {
            $listeners = Get-NetTCPConnection -State Listen -LocalPort $candidate -ErrorAction SilentlyContinue
            $owners = ($listeners.OwningProcess | Sort-Object -Unique) -join ', '
            if (-not $owners) { $owners = 'unknown' }
            Write-Host "Port $candidate unavailable; PID: $owners. Keeping existing processes; trying next port."
        } finally { $reservation.Stop() }
    }
    if (-not $portFound) { throw 'No available port in the next 100 ports. Specify -Port with another range.' }
    if ($Port -ne $requestedPort) { Write-Host "Selected free port: $Port (requested $requestedPort)." }
    if (-not (Test-Path -LiteralPath $demoDatabase -PathType Leaf)) { throw 'Demo database missing. Follow docs/DEMO.md: explicit --prepare-only once; startup does not seed.' }
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $arguments = @('-m', 'scripts.run_sprint123_demo', '--db', ('"' + $demoDatabase + '"'), '--port', "$Port")
    $started = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot "$runId-sprint123.log") -RedirectStandardError (Join-Path $logRoot "$runId-sprint123-error.log")
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    do {
        if ($started.HasExited) { throw "Demo exited. See $logRoot/$runId-sprint123-error.log" }
        try {
            $scope = Invoke-RestMethod "http://127.0.0.1:$Port/demo-scope" -TimeoutSec 2
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
            if ($scope.scope -eq 'sprint123' -and $scope.synthetic -and $scope.database_name -eq $DatabaseName -and $scope.database_path -eq $demoDatabase -and $scope.code_root -eq $demoRoot -and $health.database -eq 'connected') { $ready = $true; break }
        } catch { }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    if (-not $ready) { throw 'Synthetic demo did not become ready; no fallback to original DB.' }
    $httpListener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Where-Object { $_.LocalAddress -eq '127.0.0.1' } | Select-Object -First 1
    $httpProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($httpListener.OwningProcess)"
    if ($httpListener.OwningProcess -ne $started.Id -and $httpProcess.ParentProcessId -ne $started.Id) {
        throw 'Port changed ownership during startup; refusing to open another server.'
    }
    $page = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing
    if ($page.Content -notmatch 'maxSprint:3') { throw 'Unexpected frontend configuration.' }
    Write-Host "Sprint 1-3 TEST ONLY: http://127.0.0.1:$Port/"
    Write-Host "Code root: $demoRoot"
    Write-Host "Database: $demoDatabase"
    Write-Host 'Login: s123_farm@demo.local; password: private .sprint123-trial/credentials.local (never logged)'
    Write-Host "Demo process PID: $($started.Id); stop with Stop-Process -Id $($started.Id)"
    if (-not $NoBrowser -and -not $StopAfterCheck) { Start-Process "http://127.0.0.1:$Port/" }
    if ($StopAfterCheck) { Stop-Process -Id $started.Id }
} catch {
    if ($started -and -not $started.HasExited) { Stop-Process -Id $started.Id -ErrorAction SilentlyContinue }
    Write-Host "[LOI] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
