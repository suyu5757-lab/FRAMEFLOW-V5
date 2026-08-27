[CmdletBinding()]
param(
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
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

function Test-Listener {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
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

function Test-FormalFrameflow {
    try {
        $doctor = Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/system/doctor' -TimeoutSec 2
        return $doctor.frontend_dist -like "$frameflowRoot\web\dist*" -and $doctor.database -eq "$frameflowRoot\data\frameflow.db"
    } catch {
        return $false
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
    if ($expires -gt [DateTimeOffset]::UtcNow) {
        throw "Cutover maintenance is active; runtime startup is paused by $maintenancePath"
    }
    Write-StackLog "Ignoring expired cutover maintenance token: $maintenancePath"
}

try {
    Write-StackLog 'Starting FRAMEFLOW runtime stack.'
    Assert-CutoverMaintenanceInactive

    if (-not (Test-Listener -Port 4096)) {
        Write-StackLog "Starting $openCodeTask."
        Start-ScheduledTask -TaskName $openCodeTask
    } else {
        Write-StackLog 'OpenCode already listens on 127.0.0.1:4096; reusing it.'
    }
    Wait-Until -Condition { Test-OpenCodeHealthy } -TimeoutSeconds 45 -Name 'OpenCode on 4096'

    if (Test-Listener -Port 8787) {
        if (-not (Test-FormalFrameflow)) {
            throw 'Port 8787 is occupied by a process that is not the formal FRAMEFLOW V3 runtime.'
        }
        Write-StackLog 'Formal FRAMEFLOW runtime already listens on 127.0.0.1:8787; reusing it.'
    } else {
        Assert-CutoverMaintenanceInactive
        Write-StackLog "Starting $frameflowTask."
        Start-ScheduledTask -TaskName $frameflowTask
    }
    Wait-Until -Condition { Test-FormalFrameflow } -TimeoutSeconds 45 -Name 'FRAMEFLOW V3 on 8787'

    if ($OpenBrowser) {
        Start-Process 'http://127.0.0.1:8787/'
        Write-StackLog 'Opened FRAMEFLOW workbench in the default browser.'
    }
    Write-StackLog 'FRAMEFLOW runtime stack startup completed.'
} catch {
    Write-StackLog ("Startup failed: {0}" -f $_.Exception.Message)
    exit 1
}
