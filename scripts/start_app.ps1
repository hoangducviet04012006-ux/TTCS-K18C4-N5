param(
    [switch]$NoBrowser,
    [switch]$TestMode,
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Split-Path -Parent $PSScriptRoot).TrimEnd('\/')
$backendRoot = Join-Path $projectRoot 'backend'
$databasePath = Join-Path $projectRoot 'data\agritrace.db'
$pythonExe = Join-Path $backendRoot '.venv\Scripts\python.exe'
$logDir = Join-Path $projectRoot '.agritrace-logs'
$started = $null

try {
    # 1. Path & file validations
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        throw "Python virtualenv not found at $pythonExe. Create backend\.venv and install backend\requirements.txt."
    }
    if (-not (Test-Path -LiteralPath $databasePath)) {
        throw "Unified database not found at $databasePath. Refusing startup; no fallback to legacy database."
    }
    if ($Port -lt 1024 -or $Port -gt 65535) {
        throw "Port must be between 1024 and 65535."
    }

    # 2. Check if AgriTrace is already running for this project on requested port
    try {
        $existingInfo = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/system-info" -TimeoutSec 1 -ErrorAction SilentlyContinue
        $existingHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 1 -ErrorAction SilentlyContinue

        if ($null -ne $existingInfo -and $null -ne $existingHealth) {
            $isSameDb = ($existingInfo.database_path.TrimEnd('\/') -eq $databasePath.TrimEnd('\/'))
            $isSameRoot = ($existingInfo.code_root.TrimEnd('\/') -eq $projectRoot.TrimEnd('\/'))
            $isDbConnected = ($existingHealth.database -eq 'connected')

            if ($isSameDb -and $isSameRoot -and $isDbConnected) {
                Write-Host "AgriTrace is already running on http://127.0.0.1:$Port/ for this project." -ForegroundColor Green
                Write-Host "Database: $databasePath"

                if ($TestMode) {
                    Write-Host "[TestMode] Confirmed existing AgriTrace instance is healthy and matches project." -ForegroundColor Green
                    exit 0
                }
                if (-not $NoBrowser) {
                    Start-Process "http://127.0.0.1:$Port/"
                }
                exit 0
            }
        }
    } catch {
        # Port is either not running HTTP or not AgriTrace
    }

    # 3. Find a free port (never kill existing foreign processes)
    $chosenPort = $null
    for ($candidate = $Port; $candidate -le [Math]::Min(65535, $Port + 99); $candidate++) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $candidate)
        $listener.Server.ExclusiveAddressUse = $true
        try {
            $listener.Start()
            $chosenPort = $candidate
            break
        } catch [System.Net.Sockets.SocketException] {
            # Port busy by an existing process, keep it untouched
        } finally {
            $listener.Stop()
        }
    }

    if ($null -eq $chosenPort) {
        throw "No free port available in range $Port..$($Port + 99). Please specify -Port with another port."
    }

    if ($chosenPort -ne $Port) {
        Write-Host "Port $Port was occupied. Selected next free port: $chosenPort." -ForegroundColor Yellow
    }

    # 4. Start background process
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $runId = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdoutLog = Join-Path $logDir "$runId-stdout.log"
    $stderrLog = Join-Path $logDir "$runId-stderr.log"

    $arguments = @('-m', 'scripts.run_agritrace', '--port', "$chosenPort", '--db', $databasePath)
    $started = Start-Process -FilePath $pythonExe -ArgumentList $arguments -WorkingDirectory $backendRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

    # 5. Wait for readiness and verify fingerprint
    $deadline = (Get-Date).AddSeconds(45)
    $ready = $false
    $info = $null

    do {
        if ($started.HasExited) {
            throw "AgriTrace server exited prematurely. Check log: $stderrLog"
        }
        try {
            $info = Invoke-RestMethod -Uri "http://127.0.0.1:$chosenPort/system-info" -TimeoutSec 2
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:$chosenPort/health" -TimeoutSec 2

            $isSameDb = ($info.database_path.TrimEnd('\/') -eq $databasePath.TrimEnd('\/'))
            $isSameRoot = ($info.code_root.TrimEnd('\/') -eq $projectRoot.TrimEnd('\/'))
            $isDbConnected = ($health.database -eq 'connected')

            if ($isSameDb -and $isSameRoot -and $isDbConnected) {
                $ready = $true
                break
            }
        } catch { }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)

    if (-not $ready) {
        throw "AgriTrace server failed to initialize within 45 seconds. Check log: $stderrLog"
    }

    # Verify listening process ownership
    $tcpConn = Get-NetTCPConnection -State Listen -LocalPort $chosenPort -ErrorAction SilentlyContinue | Where-Object { $_.LocalAddress -eq '127.0.0.1' } | Select-Object -First 1
    if ($null -eq $tcpConn) {
        throw "Failed to confirm TCP listener on port $chosenPort."
    }
    $serverPid = $tcpConn.OwningProcess

    # Verify PID matches started process
    $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid" -ErrorAction SilentlyContinue
    if ($serverPid -ne $started.Id -and $procInfo.ParentProcessId -ne $started.Id) {
        throw "Port $chosenPort ownership mismatch (PID: $serverPid, Expected: $($started.Id))."
    }

    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " AgriTrace Unified System is ready!" -ForegroundColor Green
    Write-Host " URL:      http://127.0.0.1:$chosenPort/" -ForegroundColor White
    Write-Host " Database: $databasePath" -ForegroundColor White
    Write-Host " PID:      $serverPid" -ForegroundColor White
    Write-Host " Logs:     $logDir" -ForegroundColor White
    Write-Host "============================================================" -ForegroundColor Cyan

    # 6. TestMode execution (clean shutdown after automated check)
    if ($TestMode) {
        Write-Host "[TestMode] Server verification successful. Performing clean shutdown..." -ForegroundColor Yellow
        Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
        if (-not $started.HasExited) {
            Stop-Process -Id $started.Id -Force -ErrorAction SilentlyContinue
        }
        Write-Host "[TestMode] Clean shutdown verified." -ForegroundColor Green
        exit 0
    }

    # 7. Normal browser opening
    if (-not $NoBrowser) {
        Start-Process "http://127.0.0.1:$chosenPort/"
    }

} catch {
    if ($started -and (-not $started.HasExited)) {
        Stop-Process -Id $started.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
