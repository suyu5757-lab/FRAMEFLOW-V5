[CmdletBinding()]
param(
    [switch]$OpenBrowser,
    [switch]$RuntimeOnly,
    [switch]$AllowDuringMaintenance,
    [string]$RuntimeConfigPath = '',
    [int]$Port = 8787,
    [string]$BindHost = '127.0.0.1'
)

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
$formalPython = Join-Path $frameflowRoot '.venv\Scripts\python.exe'
$logDirectory = Join-Path $frameflowRoot 'data\logs'
$logPath = Join-Path $logDirectory 'frameflow-runtime-startup.log'
$openCodeTask = 'FRAMEFLOW OpenCode Agent Runtime'
$frameflowTask = 'FRAMEFLOW-V3-Service'
$maintenancePath = Join-Path $frameflowRoot 'data\.cutover-maintenance.json'

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-StackLog {
    param([string]$Message)
    Add-Content -LiteralPath $logPath -Value ('{0:u} {1}' -f (Get-Date), $Message)
}

function Get-ListenerPids {
    param([int]$ListenerPort)
    $matches = @(netstat -ano -p tcp | Select-String (':{0}\s+\S+\s+LISTENING\s+(\d+)\s*$' -f $ListenerPort))
    return @($matches | ForEach-Object { [int]$_.Matches[0].Groups[1].Value } | Select-Object -Unique)
}

function Test-Listener {
    param([int]$ListenerPort)
    return @(Get-ListenerPids -ListenerPort $ListenerPort).Count -gt 0
}

function Wait-Until {
    param(
        [scriptblock]$Condition,
        [int]$TimeoutSeconds,
        [string]$Name
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (& $Condition) {
            Write-StackLog "$Name is ready."
            return
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)

    throw "$Name did not become ready within $TimeoutSeconds seconds. See $logPath."
}

function Test-OpenCodeHealthy {
    try {
        $result = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:4096/global/health' -TimeoutSec 2
        return $result.healthy -eq $true
    } catch {
        return $false
    }
}

function Get-TargetValidation {
    if (-not (Test-Path -LiteralPath $formalPython)) {
        throw "Formal interpreter is missing: $formalPython"
    }
    $arguments = @('-m', 'core.runtime.production_launcher', '--validate-only')
    if ($RuntimeConfigPath -and $RuntimeConfigPath.Trim()) {
        $arguments += @('--config', [IO.Path]::GetFullPath($RuntimeConfigPath))
    }
    $rendered = (& $formalPython @arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Runtime target validation failed: $rendered"
    }
    try {
        return $rendered | ConvertFrom-Json
    } catch {
        throw "Runtime target validation returned invalid evidence: $rendered"
    }
}

function Assert-CutoverMaintenanceInactive {
    if (-not (Test-Path -LiteralPath $maintenancePath)) {
        return
    }
    try {
        $state = Get-Content -Raw -LiteralPath $maintenancePath | ConvertFrom-Json
        $expires = [DateTimeOffset]::Parse([string]$state.expires_at_utc)
    } catch {
        throw "Invalid cutover maintenance token blocks runtime startup: $maintenancePath"
    }
    if ($expires -le [DateTimeOffset]::UtcNow) {
        Write-StackLog "Ignoring expired cutover maintenance token: $maintenancePath"
        return
    }
    if ($AllowDuringMaintenance -and $state.allow_runtime_start -eq $true) {
        Write-StackLog 'Explicit target runtime start permitted by the active maintenance token.'
        return
    }
    throw "Cutover maintenance is active; runtime startup is paused by $maintenancePath"
}

function Get-RuntimeHealth {
    param([int]$HealthPort)
    try {
        return Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:{0}/api/health" -f $HealthPort) -TimeoutSec 2
    } catch {
        return $null
    }
}

function Get-RuntimeDoctor {
    param([int]$HealthPort)
    try {
        return Invoke-RestMethod -UseBasicParsing -Uri ("http://127.0.0.1:{0}/api/system/doctor" -f $HealthPort) -TimeoutSec 2
    } catch {
        return $null
    }
}

function Test-ExpectedRuntime {
    param(
        [object]$Target,
        [int]$HealthPort
    )
    $health = Get-RuntimeHealth -HealthPort $HealthPort
    $doctor = Get-RuntimeDoctor -HealthPort $HealthPort
    if (-not $health -or -not $doctor) {
        return $false
    }
    return $health.runtime_mode -eq [string]$Target.mode -and
        ([string]$Target.mode -ne 'v5' -or $health.ready -eq $true) -and
        [IO.Path]::GetFullPath([string]$doctor.database) -eq [IO.Path]::GetFullPath([string]$Target.runtime_db)
}

function Assert-ExpectedRuntime {
    param(
        [object]$Target,
        [int]$HealthPort
    )
    $health = Get-RuntimeHealth -HealthPort $HealthPort
    $doctor = Get-RuntimeDoctor -HealthPort $HealthPort
    if (-not $health -or -not $doctor) {
        throw "Expected $($Target.mode) runtime did not return health and doctor evidence on port $HealthPort."
    }
    if ($health.runtime_mode -ne [string]$Target.mode) {
        throw "Runtime mode mismatch: expected=$($Target.mode) actual=$($health.runtime_mode)."
    }
    if ([string]$Target.mode -eq 'v5' -and $health.ready -ne $true) {
        $failing = if ($health.readiness -and $health.readiness.failing_predicates) {
            ($health.readiness.failing_predicates -join ',')
        } else {
            'not_reported'
        }
        throw "V5 readiness gate failed: status=$($health.status) ready=$($health.ready) failing_predicates=$failing."
    }
    if ([IO.Path]::GetFullPath([string]$doctor.database) -ne [IO.Path]::GetFullPath([string]$Target.runtime_db)) {
        throw "Runtime database mismatch: expected=$($Target.runtime_db) actual=$($doctor.database)."
    }
    return [ordered]@{
        Health = $health
        Doctor = $doctor
        ListenerPids = @(Get-ListenerPids -ListenerPort $HealthPort)
    }
}

function Start-FormalRuntime {
    param([object]$Target)
    $arguments = @(
        '-m', 'core.runtime.production_launcher', '--start',
        '--host', $BindHost, '--port', "$Port"
    )
    if ($RuntimeConfigPath -and $RuntimeConfigPath.Trim()) {
        $arguments += @('--config', [IO.Path]::GetFullPath($RuntimeConfigPath))
    }
    $rendered = (& $formalPython @arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Formal mode-aware runtime launcher failed for $($Target.mode): $rendered"
    }
    Write-StackLog "Explicitly started $($Target.mode) runtime through $formalPython."
    return $rendered | ConvertFrom-Json
}

try {
    Write-StackLog 'Starting FRAMEFLOW mode-aware runtime stack.'
    Assert-CutoverMaintenanceInactive
    $target = Get-TargetValidation

    if ($RuntimeOnly) {
        if (-not (Test-Listener -ListenerPort $Port)) {
            [void](Start-FormalRuntime -Target $target)
        } else {
            Write-StackLog "Port $Port already has a listener; validating it against the selected $($target.mode) target."
        }
        Wait-Until -Condition { Test-ExpectedRuntime -Target $target -HealthPort $Port } -TimeoutSeconds 45 -Name "$($target.mode) FRAMEFLOW runtime on $Port"
        [void](Assert-ExpectedRuntime -Target $target -HealthPort $Port)
        Write-StackLog "FRAMEFLOW $($target.mode) runtime-only startup completed."
        exit 0
    }

    if (-not (Test-Listener -ListenerPort 4096)) {
        Write-StackLog "Starting $openCodeTask."
        Start-ScheduledTask -TaskName $openCodeTask
    } else {
        Write-StackLog 'OpenCode already listens on 127.0.0.1:4096; reusing it.'
    }
    Wait-Until -Condition { Test-OpenCodeHealthy } -TimeoutSeconds 45 -Name 'OpenCode on 4096'

    if (Test-Listener -ListenerPort $Port) {
        [void](Assert-ExpectedRuntime -Target $target -HealthPort $Port)
        Write-StackLog "Formal FRAMEFLOW $($target.mode) runtime already listens on 127.0.0.1:$Port; reusing it."
    } else {
        Assert-CutoverMaintenanceInactive
        Write-StackLog "Starting $frameflowTask through its mode-aware runtime action."
        Start-ScheduledTask -TaskName $frameflowTask
    }
    Wait-Until -Condition { Test-ExpectedRuntime -Target $target -HealthPort $Port } -TimeoutSeconds 45 -Name "$($target.mode) FRAMEFLOW runtime on $Port"
    [void](Assert-ExpectedRuntime -Target $target -HealthPort $Port)

    if ($OpenBrowser) {
        Start-Process ("http://127.0.0.1:{0}/" -f $Port)
        Write-StackLog 'Opened FRAMEFLOW workbench in the default browser.'
    }
    Write-StackLog 'FRAMEFLOW mode-aware runtime stack startup completed.'
} catch {
    Write-StackLog ("Startup failed: {0}" -f $_.Exception.Message)
    exit 1
}
