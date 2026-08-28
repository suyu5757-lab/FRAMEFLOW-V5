[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$frameflowRoot = 'D:\11067\CodexWorkspaces\frameflow-v3'
$openCodeRoot = 'D:\11067\Codex\2026-08-13\video-2'
$hiddenRunner = Join-Path $frameflowRoot 'scripts\run-hidden.vbs'
$startupScript = Join-Path $frameflowRoot 'scripts\start-frameflow-stack.ps1'
$openCodeTaskName = 'FRAMEFLOW OpenCode Agent Runtime'
$frameflowTaskName = 'FRAMEFLOW-V3-Service'
$shutdownTaskName = 'FRAMEFLOW OpenCode Runtime Shutdown'
$startupTaskName = 'FRAMEFLOW Runtime Startup'

function Quote-Argument {
    param([string]$Value)
    return '"{0}"' -f $Value.Replace('"', '""')
}

function Get-TaskXml {
    param([string]$TaskName)
    [xml]$xml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    return $xml
}

function Set-NodeText {
    param(
        [xml]$Xml,
        [System.Xml.XmlElement]$Parent,
        [string]$Name,
        [string]$Value
    )
    $node = $Xml.CreateElement($Name, $Xml.DocumentElement.NamespaceURI)
    $node.InnerText = $Value
    [void]$Parent.AppendChild($node)
}

function Set-TaskAction {
    param(
        [xml]$Xml,
        [string]$Executable,
        [string]$Arguments,
        [string]$WorkingDirectory
    )
    $actions = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="Actions"]')
    if ($null -eq $actions) {
        throw 'Task XML is missing the Actions element.'
    }
    while ($actions.HasChildNodes) {
        [void]$actions.RemoveChild($actions.FirstChild)
    }
    $exec = $Xml.CreateElement('Exec', $Xml.DocumentElement.NamespaceURI)
    Set-NodeText -Xml $Xml -Parent $exec -Name 'Command' -Value $Executable
    Set-NodeText -Xml $Xml -Parent $exec -Name 'Arguments' -Value $Arguments
    Set-NodeText -Xml $Xml -Parent $exec -Name 'WorkingDirectory' -Value $WorkingDirectory
    [void]$actions.AppendChild($exec)
}

function Remove-TaskTriggers {
    param([xml]$Xml)
    $triggers = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="Triggers"]')
    if ($null -ne $triggers) {
        [void]$triggers.ParentNode.RemoveChild($triggers)
    }
}

function Set-LogonTrigger {
    param(
        [xml]$Xml,
        [string]$UserId
    )
    Remove-TaskTriggers -Xml $Xml
    $principals = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="Principals"]')
    if ($null -eq $principals) {
        throw 'Task XML is missing the Principals element.'
    }
    $triggers = $Xml.CreateElement('Triggers', $Xml.DocumentElement.NamespaceURI)
    $logon = $Xml.CreateElement('LogonTrigger', $Xml.DocumentElement.NamespaceURI)
    Set-NodeText -Xml $Xml -Parent $logon -Name 'UserId' -Value $UserId
    [void]$triggers.AppendChild($logon)
    [void]$principals.ParentNode.InsertBefore($triggers, $principals)
}

function Set-TaskDescriptionAndUri {
    param(
        [xml]$Xml,
        [string]$TaskName,
        [string]$Description
    )
    $registration = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="RegistrationInfo"]')
    if ($null -eq $registration) {
        throw 'Task XML is missing RegistrationInfo.'
    }
    $descriptionNode = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="RegistrationInfo"]/*[local-name()="Description"]')
    if ($null -eq $descriptionNode) {
        $descriptionNode = $Xml.CreateElement('Description', $Xml.DocumentElement.NamespaceURI)
        [void]$registration.AppendChild($descriptionNode)
    }
    $descriptionNode.InnerText = $Description
    $uri = $Xml.SelectSingleNode('/*[local-name()="Task"]/*[local-name()="RegistrationInfo"]/*[local-name()="URI"]')
    if ($null -eq $uri) {
        $uri = $Xml.CreateElement('URI', $Xml.DocumentElement.NamespaceURI)
        [void]$registration.AppendChild($uri)
    }
    $uri.InnerText = "\$TaskName"
}

function Save-TaskXml {
    param(
        [string]$TaskName,
        [xml]$Xml
    )
    Register-ScheduledTask -TaskName $TaskName -TaskPath '\' -Xml $Xml.OuterXml -Force | Out-Null
}

if (-not (Test-Path -LiteralPath $hiddenRunner)) {
    throw "Missing hidden runner: $hiddenRunner"
}
if (-not (Test-Path -LiteralPath $startupScript)) {
    throw "Missing startup script: $startupScript"
}

# The two service tasks deliberately have no trigger. They can only be started
# by the ordered FRAMEFLOW stack launcher, so neither creates a visible console
# during logon nor starts independently of the workbench.
$openCodeXml = Get-TaskXml -TaskName $openCodeTaskName
Set-TaskAction -Xml $openCodeXml -Executable "$env:WINDIR\System32\wscript.exe" -Arguments (@(
    (Quote-Argument $hiddenRunner),
    (Quote-Argument "$env:WINDIR\System32\cmd.exe"),
    (Quote-Argument ('/d /c ""{0}\runtime\opencode-runtime.cmd""' -f $openCodeRoot)),
    (Quote-Argument $openCodeRoot)
) -join ' ') -WorkingDirectory $openCodeRoot
Remove-TaskTriggers -Xml $openCodeXml
Save-TaskXml -TaskName $openCodeTaskName -Xml $openCodeXml

$frameflowXml = Get-TaskXml -TaskName $frameflowTaskName
$logonUserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
Set-TaskAction -Xml $frameflowXml -Executable "$env:WINDIR\System32\wscript.exe" -Arguments (@(
    (Quote-Argument $hiddenRunner),
    (Quote-Argument "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"),
    (Quote-Argument ('-NoProfile -ExecutionPolicy Bypass -File ""{0}"" -RuntimeOnly' -f $startupScript)),
    (Quote-Argument $frameflowRoot)
) -join ' ') -WorkingDirectory $frameflowRoot
Set-TaskDescriptionAndUri -Xml $frameflowXml -TaskName $frameflowTaskName -Description 'Historical FRAMEFLOW V3 task name retained for operational compatibility; action invokes the mode-aware runtime launcher and honors data/runtime-startup.json.'
Remove-TaskTriggers -Xml $frameflowXml
Save-TaskXml -TaskName $frameflowTaskName -Xml $frameflowXml

# Clone the trusted FRAMEFLOW task definition so its SID, interactive token and
# elevation settings stay intact, then make it the sole logon orchestrator.
$startupXml = Get-TaskXml -TaskName $frameflowTaskName
Set-TaskDescriptionAndUri -Xml $startupXml -TaskName $startupTaskName -Description 'Starts OpenCode, waits for it, starts the mode-aware FRAMEFLOW runtime selected by runtime-startup.json, then opens the workbench. Services run silently and are stopped by the FRAMEFLOW shutdown task.'
Set-TaskAction -Xml $startupXml -Executable "$env:WINDIR\System32\wscript.exe" -Arguments (@(
    (Quote-Argument $hiddenRunner),
    (Quote-Argument "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"),
    (Quote-Argument ('-NoProfile -ExecutionPolicy Bypass -File ""{0}"" -OpenBrowser' -f $startupScript)),
    (Quote-Argument $frameflowRoot)
) -join ' ') -WorkingDirectory $frameflowRoot
Set-LogonTrigger -Xml $startupXml -UserId $logonUserId
Save-TaskXml -TaskName $startupTaskName -Xml $startupXml

# Retain the existing Event ID 1074 shutdown trigger but run its cleanup script
# hidden. The cleanup script now stops both on-demand service tasks.
$shutdownXml = Get-TaskXml -TaskName $shutdownTaskName
Set-TaskAction -Xml $shutdownXml -Executable "$env:WINDIR\System32\wscript.exe" -Arguments (@(
    (Quote-Argument $hiddenRunner),
    (Quote-Argument "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"),
    (Quote-Argument ('-NoProfile -ExecutionPolicy Bypass -File ""{0}""' -f (Join-Path $openCodeRoot 'runtime\stop-opencode-runtime.ps1'))),
    (Quote-Argument $openCodeRoot)
) -join ' ') -WorkingDirectory $openCodeRoot
Save-TaskXml -TaskName $shutdownTaskName -Xml $shutdownXml

Write-Output 'FRAMEFLOW runtime tasks configured.'
