[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Enter', 'Restore', 'Inspect')]
    [string]$Mode,

    [Parameter(Mandatory = $true)]
    [string]$StatePath
)

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
$canonicalDatabase = Join-Path $frameflowRoot 'data\frameflow.db'
$startupTask = 'FRAMEFLOW Runtime Startup'
$serviceTask = 'FRAMEFLOW-V3-Service'
$maintenanceTasks = @($startupTask, $serviceTask)
$maintenancePath = Join-Path $frameflowRoot 'data\.cutover-maintenance.json'
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
        $Doctor
    )
    if ($Process.Name -ne 'python.exe') {
        throw "Port 8787 owner is not Python: PID=$OwnerPid Name=$($Process.Name)."
    }
    if (-not $Doctor) {
        throw "Port 8787 owner did not return FRAMEFLOW doctor evidence: PID=$OwnerPid."
    }
    $expectedFrontend = [IO.Path]::GetFullPath((Join-Path $frameflowRoot 'web\dist'))
    $actualFrontend = [IO.Path]::GetFullPath([string]$Doctor.frontend_dist)
    $expectedDatabase = [IO.Path]::GetFullPath($canonicalDatabase)
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
if (-not $stateValue.MaintenancePaused) {
    throw 'Maintenance state does not prove paused startup sources.'
}
$serviceOriginal = $stateValue.OriginalTasks.PSObject.Properties[$serviceTask].Value
$startupOriginal = $stateValue.OriginalTasks.PSObject.Properties[$startupTask].Value
$serviceOriginallyEnabled = [bool]$serviceOriginal.Enabled
$startupOriginallyEnabled = [bool]$startupOriginal.Enabled
$currentTasks = Get-TaskStateEvidence
foreach ($taskName in $maintenanceTasks) {
    if ($currentTasks[$taskName].Enabled) {
        throw "Scheduled task is not maintenance-disabled: $taskName"
    }
}
$restoredTokenEvidence = Preserve-MaintenanceToken -Suffix 'restored'
$stateValue | Add-Member -NotePropertyName RestoredTokenEvidence -NotePropertyValue $restoredTokenEvidence -Force
Set-TaskEnabledState -TaskName $serviceTask -Enabled $serviceOriginallyEnabled
if ($stateValue.RuntimeWasListening) {
    if (Get-OwnerPid) {
        throw 'Refusing lifecycle restore because port 8787 is already occupied.'
    }
    Start-ScheduledTask -TaskName $serviceTask
    $deadline = (Get-Date).AddSeconds(45)
    do {
        $restoredOwner = Get-OwnerPid
        if ($restoredOwner) {
            $restoredProcess = Get-ProcessEvidence -ProcessId $restoredOwner
            $restoredDoctor = Get-DoctorEvidence
            Assert-ExpectedFrameflowOwner -OwnerPid $restoredOwner -Process $restoredProcess -Doctor $restoredDoctor
            break
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    if (-not $restoredOwner) {
        throw 'FRAMEFLOW runtime did not reclaim 8787 during lifecycle restore.'
    }
}
Set-TaskEnabledState -TaskName $startupTask -Enabled $startupOriginallyEnabled
$stateValue.Restored = $true
$stateValue | Add-Member -NotePropertyName RestoredAt -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
$stateValue | Add-Member -NotePropertyName RestoredOwnerPid -NotePropertyValue (Get-OwnerPid) -Force
$stateValue | Add-Member -NotePropertyName RestoredTasks -NotePropertyValue (Get-TaskStateEvidence) -Force
Write-State -Value $stateValue
$stateValue | ConvertTo-Json -Depth 12
