[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Enter', 'StartTarget', 'RestoreAutostartPolicy', 'RestoreLegacy', 'Inspect')]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$StatePath,

    [string]$RuntimeConfigPath = ''
)

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
$canonicalDatabase = Join-Path $frameflowRoot 'data\frameflow.db'
$startupTask = 'FRAMEFLOW Runtime Startup'
$serviceTask = 'FRAMEFLOW-V3-Service'
$maintenanceTasks = @($startupTask, $serviceTask)
$maintenancePath = Join-Path $frameflowRoot 'data\.cutover-maintenance.json'
$runtimeLauncher = Join-Path $frameflowRoot 'scripts\start-frameflow-stack.ps1'
$formalPython = Join-Path $frameflowRoot '.venv\Scripts\python.exe'
$resolvedRuntimeConfigPath = if ($RuntimeConfigPath -and $RuntimeConfigPath.Trim()) {
    [IO.Path]::GetFullPath($RuntimeConfigPath)
} else {
    Join-Path $frameflowRoot 'data\runtime-startup.json'
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-State {
    param([object]$Value)
    $resolved = [IO.Path]::GetFullPath($StatePath)
    $parent = [IO.Path]::GetDirectoryName($resolved)
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    [IO.File]::WriteAllText(
        $resolved,
        ($Value | ConvertTo-Json -Depth 12),
        $utf8NoBom
    )
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-MaintenanceToken {
    if (Test-Path -LiteralPath $maintenancePath) {
        throw "Refusing existing cutover maintenance token: $maintenancePath"
    }
    $token = [ordered]@{
        version = 1
        state_path = [IO.Path]::GetFullPath($StatePath)
        created_at_utc = [DateTimeOffset]::UtcNow.ToString('o')
        expires_at_utc = [DateTimeOffset]::UtcNow.AddHours(2).ToString('o')
        allow_runtime_start = $false
    }
    [IO.File]::WriteAllText(
        $maintenancePath,
        ($token | ConvertTo-Json -Depth 4),
        $utf8NoBom
    )
    return $token
}

function Preserve-MaintenanceToken {
    param([string]$Suffix)
    if (-not (Test-Path -LiteralPath $maintenancePath)) {
        return $null
    }
    $destination = "$StatePath.$Suffix-maintenance-token.json"
    if (Test-Path -LiteralPath $destination) {
        throw "Refusing existing maintenance token evidence: $destination"
    }
    Move-Item -LiteralPath $maintenancePath -Destination $destination
    return $destination
}

function Get-OwnerPid {
    $matches = @(netstat -ano -p tcp | Select-String '^\s*TCP\s+127\.0\.0\.1:8787\s+\S+\s+LISTENING\s+(\d+)\s*$')
    if ($matches.Count -eq 0) {
        return $null
    }
    if ($matches.Count -ne 1) {
        throw "Expected at most one 127.0.0.1:8787 listener; found $($matches.Count)."
    }
    return [int]$matches[0].Matches[0].Groups[1].Value
}

function Get-ProcessEvidence {
    param([int]$ProcessId)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
    if (-not $process) {
        return [ordered]@{ ProcessId = $ProcessId; Missing = $true }
    }
    return [ordered]@{
        ProcessId = [int]$process.ProcessId
        ParentProcessId = [int]$process.ParentProcessId
        Name = [string]$process.Name
        ExecutablePath = [string]$process.ExecutablePath
        CommandLine = [string]$process.CommandLine
        CreationDate = [string]$process.CreationDate
        SessionId = [int]$process.SessionId
    }
}

function Get-DoctorEvidence {
    try {
        return Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/system/doctor' -TimeoutSec 3
    } catch {
        return $null
    }
}

function Assert-ExpectedFrameflowOwner {
    param(
        [int]$OwnerPid,
        [hashtable]$Process,
        $Doctor,
        [string]$ExpectedDatabase = $canonicalDatabase
    )
    if ($Process.Name -ne 'python.exe') {
        throw "Port 8787 owner is not Python: PID=$OwnerPid Name=$($Process.Name)."
    }
    if (-not $Doctor) {
        throw "Port 8787 owner did not return FRAMEFLOW doctor evidence: PID=$OwnerPid."
    }
    $expectedFrontend = [IO.Path]::GetFullPath((Join-Path $frameflowRoot 'web\dist'))
    $actualFrontend = [IO.Path]::GetFullPath([string]$Doctor.frontend_dist)
    $expectedDatabase = [IO.Path]::GetFullPath($ExpectedDatabase)
    $actualDatabase = [IO.Path]::GetFullPath([string]$Doctor.database)
    if ($actualFrontend -ne $expectedFrontend -or $actualDatabase -ne $expectedDatabase) {
        throw "Port 8787 owner is not the formal FRAMEFLOW runtime: PID=$OwnerPid."
    }
}

function Get-TaskStateEvidence {
    $result = [ordered]@{}
    foreach ($taskName in $maintenanceTasks) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $info = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
        $result[$taskName] = [ordered]@{
            Enabled = [bool]$task.Settings.Enabled
            State = [string]$task.State
            LastRunTime = [string]$info.LastRunTime
            LastTaskResult = [int]$info.LastTaskResult
            TriggerCount = @($task.Triggers | Where-Object { $null -ne $_ }).Count
            Actions = @($task.Actions | ForEach-Object {
                [ordered]@{
                    Execute = [string]$_.Execute
                    Arguments = [string]$_.Arguments
                    WorkingDirectory = [string]$_.WorkingDirectory
                }
            })
        }
    }
    return $result
}

function Set-TaskEnabledState {
    param([string]$TaskName, [bool]$Enabled)
    if ($Enabled) {
        Enable-ScheduledTask -TaskName $TaskName | Out-Null
    } else {
        Disable-ScheduledTask -TaskName $TaskName | Out-Null
    }
}

function Get-HealthEvidence {
    try {
        return Invoke-RestMethod -UseBasicParsing -Uri 'http://127.0.0.1:8787/api/health' -TimeoutSec 3
    } catch {
        return $null
    }
}

function Get-TargetValidationEvidence {
    if (-not (Test-Path -LiteralPath $formalPython)) {
        throw "Formal interpreter is missing: $formalPython"
    }
    $arguments = @('-m', 'core.runtime.production_launcher', '--validate-only')
    if (Test-Path -LiteralPath $resolvedRuntimeConfigPath) {
        $arguments += @('--config', $resolvedRuntimeConfigPath)
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

function Assert-TargetRuntime {
    param([object]$Target)
    $ownerPid = Get-OwnerPid
    if (-not $ownerPid) {
        throw "Expected $($Target.mode) runtime is not listening on 8787."
    }
    $process = Get-ProcessEvidence -ProcessId $ownerPid
    $doctor = Get-DoctorEvidence
    Assert-ExpectedFrameflowOwner -OwnerPid $ownerPid -Process $process -Doctor $doctor -ExpectedDatabase ([string]$Target.runtime_db)
    $health = Get-HealthEvidence
    if (-not $health) {
        throw "Expected $($Target.mode) runtime did not return health on 8787."
    }
    if ([string]$health.runtime_mode -ne [string]$Target.mode) {
        throw "Runtime mode mismatch during lifecycle: expected=$($Target.mode) actual=$($health.runtime_mode)."
    }
    return [ordered]@{
        OwnerPid = $ownerPid
        Process = $process
        Doctor = $doctor
        Health = $health
        VerifiedAt = (Get-Date).ToUniversalTime().ToString('o')
    }
}

function Set-ExplicitRuntimeStartPermission {
    if (-not (Test-Path -LiteralPath $maintenancePath)) {
        throw "Active maintenance token is missing: $maintenancePath"
    }
    $token = Get-Content -Raw -LiteralPath $maintenancePath | ConvertFrom-Json
    $token | Add-Member -NotePropertyName allow_runtime_start -NotePropertyValue $true -Force
    [IO.File]::WriteAllText(
        $maintenancePath,
        ($token | ConvertTo-Json -Depth 8),
        $utf8NoBom
    )
}

function Invoke-TargetRuntimeStart {
    param([object]$Target)
    if (-not (Test-Path -LiteralPath $runtimeLauncher)) {
        throw "Mode-aware runtime launcher is missing: $runtimeLauncher"
    }
    Set-ExplicitRuntimeStartPermission
    $arguments = @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runtimeLauncher,
        '-RuntimeOnly', '-AllowDuringMaintenance'
    )
    if ($RuntimeConfigPath -and $RuntimeConfigPath.Trim()) {
        $arguments += @('-RuntimeConfigPath', $resolvedRuntimeConfigPath)
    }
    $rendered = (& powershell.exe @arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Explicit $($Target.mode) runtime start failed: $rendered"
    }
    return Assert-TargetRuntime -Target $Target
}

function Restore-AutostartPolicy {
    param(
        [object]$StateValue,
        [string]$ExpectedMode = ''
    )
    if (-not $StateValue.MaintenancePaused) {
        throw 'Maintenance state does not prove paused startup sources.'
    }
    if (-not $StateValue.TargetRuntimeStarted) {
        throw 'Autostart policy cannot be restored before the target runtime is explicitly started and verified.'
    }
    if ($ExpectedMode -and [string]$StateValue.TargetRuntimeMode -ne $ExpectedMode) {
        throw "Lifecycle target mode mismatch: expected=$ExpectedMode actual=$($StateValue.TargetRuntimeMode)"
    }
    $target = Get-TargetValidationEvidence
    if ([string]$target.mode -ne [string]$StateValue.TargetRuntimeMode) {
        throw "Current startup target changed during maintenance: expected=$($StateValue.TargetRuntimeMode) actual=$($target.mode)"
    }
    $runtimeEvidence = Assert-TargetRuntime -Target $target
    $serviceOriginal = $StateValue.OriginalTasks.PSObject.Properties[$serviceTask].Value
    $startupOriginal = $StateValue.OriginalTasks.PSObject.Properties[$startupTask].Value
    $serviceOriginallyEnabled = [bool]$serviceOriginal.Enabled
    $startupOriginallyEnabled = [bool]$startupOriginal.Enabled

    # This is policy restoration only.  The explicit runtime is already proven
    # above; enabling a zero-trigger/on-logon task cannot stand in for a process
    # start and must never be treated as one.
    $restoredTokenEvidence = Preserve-MaintenanceToken -Suffix 'restored'
    $StateValue | Add-Member -NotePropertyName RestoredTokenEvidence -NotePropertyValue $restoredTokenEvidence -Force
    Set-TaskEnabledState -TaskName $serviceTask -Enabled $serviceOriginallyEnabled
    Set-TaskEnabledState -TaskName $startupTask -Enabled $startupOriginallyEnabled
    $StateValue | Add-Member -NotePropertyName AutostartPolicyRestored -NotePropertyValue $true -Force
    $StateValue | Add-Member -NotePropertyName Restored -NotePropertyValue $true -Force
    $StateValue | Add-Member -NotePropertyName RestoredAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
    $StateValue | Add-Member -NotePropertyName RestoredOwnerPid -NotePropertyValue $runtimeEvidence.OwnerPid -Force
    $StateValue | Add-Member -NotePropertyName RestoredRuntimeEvidence -NotePropertyValue $runtimeEvidence -Force
    $StateValue | Add-Member -NotePropertyName RestoredTasks -NotePropertyValue (Get-TaskStateEvidence) -Force
    Write-State -Value $StateValue
    return $StateValue
}

function Wait-PortFreeEvidence {
    $timeline = @()
    for ($index = 0; $index -lt 12; $index += 1) {
        $currentOwner = Get-OwnerPid
        $timeline += [ordered]@{
            Sample = $index
            UTC = (Get-Date).ToUniversalTime().ToString('o')
            OwnerPid = $currentOwner
        }
        if ($currentOwner) {
            Start-Sleep -Milliseconds 250
            continue
        }
        if ($index -ge 3) {
            return $timeline
        }
        Start-Sleep -Milliseconds 250
    }
    return $timeline
}

if ($Mode -eq 'Inspect') {
    $ownerPid = Get-OwnerPid
    $process = if ($ownerPid) { Get-ProcessEvidence -ProcessId $ownerPid } else { $null }
    $doctor = if ($ownerPid) { Get-DoctorEvidence } else { $null }
    [ordered]@{
        Mode = 'Inspect'
        OwnerPid = $ownerPid
        Process = $process
        Doctor = $doctor
        Tasks = Get-TaskStateEvidence
    } | ConvertTo-Json -Depth 12
    exit 0
}

if ($Mode -eq 'Enter') {
    if (Test-Path -LiteralPath $StatePath) {
        throw "Refusing to reuse maintenance state: $StatePath"
    }
    $taskState = Get-TaskStateEvidence
    $ownerPid = Get-OwnerPid
    $process = if ($ownerPid) { Get-ProcessEvidence -ProcessId $ownerPid } else { $null }
    $parent = if ($process -and $process.ParentProcessId) {
        Get-ProcessEvidence -ProcessId $process.ParentProcessId
    } else { $null }
    $doctor = if ($ownerPid) { Get-DoctorEvidence } else { $null }
    if ($ownerPid) {
        Assert-ExpectedFrameflowOwner -OwnerPid $ownerPid -Process $process -Doctor $doctor
        if (-not (Test-IsAdministrator)) {
            throw 'Stopping the elevated FRAMEFLOW backend requires an elevated maintenance controller.'
        }
    }
    $state = [ordered]@{
        Version = 1
        ControllerElevated = Test-IsAdministrator
        EnteredAt = (Get-Date).ToUniversalTime().ToString('o')
        OriginalTasks = $taskState
        RuntimeWasListening = [bool]$ownerPid
        EntryOwnerPid = $ownerPid
        EntryProcess = $process
        EntryParent = $parent
        EntryDoctor = $doctor
        Timeline = @([ordered]@{ Stage = 'T0'; OwnerPid = $ownerPid })
        MaintenancePaused = $false
        MaintenanceTaskStates = [ordered]@{
            $startupTask = 'Disabled'
            $serviceTask = 'Disabled'
        }
        Restored = $false
    }
    try {
        if ([int]$taskState[$serviceTask].TriggerCount -ne 0) {
            throw "$serviceTask must remain on-demand with zero triggers."
        }
        $token = Write-MaintenanceToken
        $state['MaintenanceToken'] = $token
        foreach ($taskName in $maintenanceTasks) {
            Disable-ScheduledTask -TaskName $taskName | Out-Null
        }
        $state.MaintenancePaused = $true
        $state.Timeline += [ordered]@{ Stage = 'T1'; Event = 'token_active_tasks_disabled' }
        Write-State -Value $state
        if ($ownerPid) {
            Stop-Process -Id $ownerPid -ErrorAction Stop
            $state.Timeline += [ordered]@{ Stage = 'T2'; Event = 'owner_stop_requested'; OwnerPid = $ownerPid }
        }
        $samples = @(Wait-PortFreeEvidence)
        $state.Timeline += $samples
        $remaining = Get-OwnerPid
        if ($remaining) {
            throw "Port 8787 remained occupied after verified FRAMEFLOW shutdown: PID=$remaining."
        }
        $taskAfter = Get-TaskStateEvidence
        foreach ($taskName in $maintenanceTasks) {
            if ($taskAfter[$taskName].Enabled) {
                throw "Maintenance task was not disabled: $taskName"
            }
        }
        $state['PortFree'] = $true
        $state['RespawnDetected'] = [bool](@($samples | Where-Object { $_.OwnerPid -and $_.OwnerPid -ne $ownerPid }).Count)
        if ($state.RespawnDetected) {
            throw 'A replacement 8787 owner appeared during maintenance observation.'
        }
        Write-State -Value $state
        $state | ConvertTo-Json -Depth 12
        exit 0
    } catch {
        $state['FailedTokenEvidence'] = Preserve-MaintenanceToken -Suffix 'failed'
        $state['Failure'] = [string]$_.Exception.Message
        Write-State -Value $state
        foreach ($taskName in $maintenanceTasks) {
            Set-TaskEnabledState -TaskName $taskName -Enabled ([bool]$taskState[$taskName].Enabled)
        }
        if ($ownerPid -and -not (Get-OwnerPid) -and $taskState[$serviceTask].Enabled) {
            Start-ScheduledTask -TaskName $serviceTask
        }
        throw
    }
}

$stateValue = Get-Content -Raw -LiteralPath $StatePath | ConvertFrom-Json

if ($Mode -eq 'StartTarget') {
    if (-not $stateValue.MaintenancePaused) {
        throw 'Target runtime cannot start before maintenance sources are paused.'
    }
    $currentTasks = Get-TaskStateEvidence
    foreach ($taskName in $maintenanceTasks) {
        if ($currentTasks[$taskName].Enabled) {
            throw "Target runtime cannot start while scheduled task is enabled: $taskName"
        }
    }
    if (Get-OwnerPid) {
        throw 'Target runtime cannot start while port 8787 is occupied.'
    }
    $target = Get-TargetValidationEvidence
    $runtimeEvidence = Invoke-TargetRuntimeStart -Target $target
    $stateValue | Add-Member -NotePropertyName TargetRuntimeMode -NotePropertyValue ([string]$target.mode) -Force
    $stateValue | Add-Member -NotePropertyName TargetRuntimeDatabase -NotePropertyValue ([string]$target.runtime_db) -Force
    $stateValue | Add-Member -NotePropertyName TargetRuntimeConfig -NotePropertyValue ([string]$target.config_path) -Force
    $stateValue | Add-Member -NotePropertyName TargetRuntimeStarted -NotePropertyValue $true -Force
    $stateValue | Add-Member -NotePropertyName TargetRuntimeStartedAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
    $stateValue | Add-Member -NotePropertyName TargetRuntimeEvidence -NotePropertyValue $runtimeEvidence -Force
    $stateValue.Timeline += [ordered]@{
        Stage = 'T3'
        Event = 'target_runtime_explicitly_started_and_verified'
        Mode = [string]$target.mode
        OwnerPid = $runtimeEvidence.OwnerPid
    }
    Write-State -Value $stateValue
    $stateValue | ConvertTo-Json -Depth 16
    exit 0
}

if ($Mode -eq 'RestoreAutostartPolicy') {
    $restored = Restore-AutostartPolicy -StateValue $stateValue
    $restored | ConvertTo-Json -Depth 16
    exit 0
}

if ($Mode -eq 'RestoreLegacy') {
    $restored = Restore-AutostartPolicy -StateValue $stateValue -ExpectedMode 'legacy'
    $restored | ConvertTo-Json -Depth 16
    exit 0
}

throw "Unsupported maintenance mode: $Mode"
