[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
$taskName = 'FRAMEFLOW-V3-Service'
$hiddenRunner = Join-Path $frameflowRoot 'scripts\run-hidden.vbs'
$startupScript = Join-Path $frameflowRoot 'scripts\start-frameflow-stack.ps1'
$windowsPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'

function Quote-Argument {
    param([string]$Value)
    return '"{0}"' -f $Value.Replace('"', '""')
}

$actionArguments = (@(
    (Quote-Argument $hiddenRunner),
    (Quote-Argument $windowsPowerShell),
    (Quote-Argument ('-NoProfile -ExecutionPolicy Bypass -File ""{0}"" -RuntimeOnly' -f $startupScript)),
    (Quote-Argument $frameflowRoot)
) -join ' ')
$newAction = New-ScheduledTaskAction -Execute "$env:WINDIR\System32\wscript.exe" -Argument $actionArguments -WorkingDirectory $frameflowRoot
Set-ScheduledTask -TaskName $taskName -Action $newAction -ErrorAction Stop | Out-Null
$afterXml = [xml](Export-ScheduledTask -TaskName $taskName -ErrorAction Stop)
$afterAction = $afterXml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="Actions"]/*[local-name()="Exec"]')
if ($null -eq $afterAction) {
    throw "Updated $taskName has no Exec action."
}
if ([string]$afterAction.Arguments -notlike '*start-frameflow-stack.ps1*' -or [string]$afterAction.Arguments -notlike '*-RuntimeOnly*') {
    throw "Updated $taskName action was not verified as mode-aware: $($afterAction.Arguments)"
}
Write-Output "Updated only $taskName to the mode-aware runtime launcher."
