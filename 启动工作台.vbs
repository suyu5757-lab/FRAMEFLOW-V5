Option Explicit

' Silent user-facing launcher. It delegates startup ordering and health checks
' to start-frameflow-stack.ps1, then opens the workbench only after readiness.
Dim shell, command
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "D:\11067\CodexWorkspaces\frameflow-v3"
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\11067\CodexWorkspaces\frameflow-v3\scripts\start-frameflow-stack.ps1"" -OpenBrowser"
shell.Run command, 0, False
