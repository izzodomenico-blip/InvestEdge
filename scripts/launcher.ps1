# InvestEdge launcher - avvio one-click affidabile
# Modalita produzione: frontend buildato servito da uvicorn, una sola porta.
# Auto-fix silenzioso: venv, dipendenze, build, DB seed.

[CmdletBinding()]
param(
    [int]$PortStart = 8001,
    [int]$PortEnd = 8010,
    [switch]$NoBrowser,
    [switch]$ForceReinstall,
    [switch]$ForceRebuild,
    [switch]$ForceSeed
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# --- Path layout ---
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$DataDir = Join-Path $ProjectRoot "data"
$VenvDir = Join-Path $BackendDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ReqFile = Join-Path $BackendDir "requirements.txt"
$ReqHashFile = Join-Path $VenvDir ".req_hash.txt"
$PkgFile = Join-Path $FrontendDir "package.json"
$PkgLockFile = Join-Path $FrontendDir "package-lock.json"
$PkgHashFile = Join-Path $FrontendDir ".pkg_hash.txt"
$NodeModulesDir = Join-Path $FrontendDir "node_modules"
$DistDir = Join-Path $FrontendDir "dist"
$DistIndex = Join-Path $DistDir "index.html"
$SrcDir = Join-Path $FrontendDir "src"
$DbFile = Join-Path $DataDir "investedge.db"
$SeedScript = Join-Path $ProjectRoot "scripts\seed_database.py"
$LockFile = Join-Path $DataDir ".investedge.lock"
$LogFile = Join-Path $DataDir "launcher.log"

# --- Logging ---
if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir -Force | Out-Null
}

function Write-Log {
    param([string]$Level, [string]$Message)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "[$ts] [$Level] $Message"
    Add-Content -Path $LogFile -Value $line -Encoding utf8
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN" { "Yellow" }
        "OK" { "Green" }
        default { "Cyan" }
    }
    Write-Host $line -ForegroundColor $color
}

function Stop-WithError {
    param([string]$Message)
    Write-Log "ERROR" $Message
    Write-Host ""
    Write-Host "Premi INVIO per chiudere..." -ForegroundColor Yellow
    [void][Console]::ReadLine()
    exit 1
}

Write-Log "INFO" "=== InvestEdge launcher avviato ==="
Write-Log "INFO" "Project root: $ProjectRoot"

# --- Lock file ---
if (Test-Path $LockFile) {
    $existingPid = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existingPid) {
        $proc = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($proc) {
            $lockPort = Get-Content $LockFile -ErrorAction SilentlyContinue | Select-Object -Skip 1 -First 1
            Write-Log "WARN" "InvestEdge gia attivo (PID $existingPid, porta $lockPort). Apro il browser."
            if (-not $NoBrowser -and $lockPort) {
                Start-Process "http://127.0.0.1:$lockPort"
            }
            exit 0
        } else {
            Write-Log "INFO" "Lock stale rimosso (PID $existingPid non attivo)."
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
        }
    }
}

# --- Python check ---
$pythonExe = $null
foreach ($candidate in @("py -3", "python", "python3")) {
    try {
        $parts = $candidate -split " ", 2
        $version = & $parts[0] $parts[1] --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $version -match "Python 3\.(1[1-9]|[2-9]\d)") {
            $pythonExe = $candidate
            Write-Log "OK" "Python trovato: $version"
            break
        }
    } catch { }
}
if (-not $pythonExe) {
    Stop-WithError "Python 3.11+ non trovato. Installa Python da https://www.python.org/downloads/"
}

# --- Venv ---
if (-not (Test-Path $VenvPython)) {
    Write-Log "INFO" "Creo venv in $VenvDir ..."
    $parts = $pythonExe -split " ", 2
    if ($parts.Length -eq 2) {
        & $parts[0] $parts[1] -m venv $VenvDir
    } else {
        & $parts[0] -m venv $VenvDir
    }
    if (-not (Test-Path $VenvPython)) {
        Stop-WithError "Creazione venv fallita."
    }
    Write-Log "OK" "Venv creato."
}

# --- Dipendenze Python ---
function Get-FileHash256 {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return "" }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash
}

$reqHashNow = Get-FileHash256 $ReqFile
$reqHashSaved = if (Test-Path $ReqHashFile) { Get-Content $ReqHashFile -Raw -ErrorAction SilentlyContinue } else { "" }
if ($ForceReinstall -or $reqHashNow -ne ($reqHashSaved -replace "\s","")) {
    Write-Log "INFO" "Installo/aggiorno dipendenze Python..."
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r $ReqFile --quiet
    if ($LASTEXITCODE -ne 0) {
        Stop-WithError "pip install fallito. Vedi log."
    }
    Set-Content -Path $ReqHashFile -Value $reqHashNow -Encoding utf8 -NoNewline
    Write-Log "OK" "Dipendenze Python aggiornate."
} else {
    Write-Log "OK" "Dipendenze Python gia aggiornate."
}

# --- Node check ---
$nodeOk = $false
try {
    $nodeVer = & node --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Log "OK" "Node trovato: $nodeVer"
        $nodeOk = $true
    }
} catch { }
if (-not $nodeOk) {
    Stop-WithError "Node.js non trovato. Installa da https://nodejs.org/"
}

# --- Dipendenze frontend ---
$pkgHashSource = if (Test-Path $PkgLockFile) { $PkgLockFile } else { $PkgFile }
$pkgHashNow = Get-FileHash256 $pkgHashSource
$pkgHashSaved = if (Test-Path $PkgHashFile) { Get-Content $PkgHashFile -Raw -ErrorAction SilentlyContinue } else { "" }
$needInstall = $ForceReinstall -or (-not (Test-Path $NodeModulesDir)) -or ($pkgHashNow -ne ($pkgHashSaved -replace "\s",""))
if ($needInstall) {
    Write-Log "INFO" "Installo/aggiorno dipendenze frontend (npm install)..."
    Push-Location $FrontendDir
    try {
        & npm install --silent 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Stop-WithError "npm install fallito."
        }
    } finally {
        Pop-Location
    }
    Set-Content -Path $PkgHashFile -Value $pkgHashNow -Encoding utf8 -NoNewline
    Write-Log "OK" "Dipendenze frontend aggiornate."
} else {
    Write-Log "OK" "Dipendenze frontend gia aggiornate."
}

# --- Build frontend ---
$needBuild = $ForceRebuild -or (-not (Test-Path $DistIndex))
if (-not $needBuild -and (Test-Path $SrcDir)) {
    $distTime = (Get-Item $DistIndex).LastWriteTime
    $srcNewest = Get-ChildItem -Path $SrcDir -Recurse -File |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($srcNewest -and $srcNewest.LastWriteTime -gt $distTime) {
        $needBuild = $true
    }
    $viteCfg = Join-Path $FrontendDir "vite.config.ts"
    if (Test-Path $viteCfg) {
        $viteCfgTime = (Get-Item $viteCfg).LastWriteTime
        if ($viteCfgTime -gt $distTime) { $needBuild = $true }
    }
}
# Force rebuild if dist exists ma usa ancora /assets/ (vecchio layout) invece di /static/
if (-not $needBuild -and (Test-Path $DistIndex)) {
    $indexContent = Get-Content $DistIndex -Raw -ErrorAction SilentlyContinue
    if ($indexContent -match '"/assets/' -or $indexContent -match "'/assets/") {
        Write-Log "INFO" "Dist usa layout vecchio /assets/, forzo rebuild."
        $needBuild = $true
    }
}
if ($needBuild) {
    Write-Log "INFO" "Build frontend in corso (npm run build)..."
    Push-Location $FrontendDir
    try {
        & npm run build 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Stop-WithError "npm run build fallito. Vedi $LogFile"
        }
    } finally {
        Pop-Location
    }
    Write-Log "OK" "Build frontend completata."
} else {
    Write-Log "OK" "Build frontend gia aggiornata."
}

# --- DB seed ---
function Test-DbEmpty {
    param([string]$Db)
    if (-not (Test-Path $Db)) { return $true }
    if ((Get-Item $Db).Length -lt 4096) { return $true }
    return $false
}

if ($ForceSeed -or (Test-DbEmpty $DbFile)) {
    Write-Log "INFO" "Inizializzo database (seed)..."
    Push-Location $ProjectRoot
    try {
        & $VenvPython $SeedScript --reset 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Pop-Location
            Stop-WithError "Seed database fallito."
        }
    } finally {
        Pop-Location
    }
    Write-Log "OK" "Database inizializzato."
} else {
    Write-Log "OK" "Database gia presente."
}

# --- Porta libera ---
function Test-PortFree {
    param([int]$Port)
    $listener = $null
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) { $listener.Stop() }
    }
}

$selectedPort = 0
for ($p = $PortStart; $p -le $PortEnd; $p++) {
    if (Test-PortFree -Port $p) {
        $selectedPort = $p
        break
    }
}
if ($selectedPort -eq 0) {
    Stop-WithError "Nessuna porta libera tra $PortStart e $PortEnd."
}
Write-Log "OK" "Porta selezionata: $selectedPort"

# --- Lock con PID corrente ---
Set-Content -Path $LockFile -Value "$PID`n$selectedPort" -Encoding utf8

# --- Avvio uvicorn ---
$env:INVESTEDGE_SERVE_FRONTEND = "1"
$env:PYTHONPATH = $ProjectRoot

$url = "http://127.0.0.1:$selectedPort"
Write-Log "INFO" "Avvio backend su $url ..."
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  InvestEdge in avvio su $url" -ForegroundColor Green
Write-Host "  Premi Ctrl+C per fermare." -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""

# Apri browser in background quando il server risponde
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($Url)
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            try {
                $r = Invoke-WebRequest -Uri "$Url/health" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
                if ($r.StatusCode -eq 200) {
                    Start-Process $Url
                    break
                }
            } catch { }
        }
    } -ArgumentList $url | Out-Null
}

# Trap per cleanup
$cleanup = {
    Write-Log "INFO" "Shutdown in corso..."
    if (Test-Path $LockFile) {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
    Write-Log "OK" "Lock rimosso. Ciao!"
}

try {
    Push-Location $ProjectRoot
    & $VenvPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $selectedPort
} finally {
    Pop-Location
    & $cleanup
}
