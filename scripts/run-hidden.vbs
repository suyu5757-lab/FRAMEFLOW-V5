Option Explicit

' Runs one command without creating a console window.
' Arguments: executable path, arguments, working directory.
If WScript.Arguments.Count <> 3 Then
    WScript.Quit 87
End If

Dim shell, executable, commandArguments, workingDirectory, command
Set shell = CreateObject("WScript.Shell")

executable = WScript.Arguments(0)
commandArguments = WScript.Arguments(1)
workingDirectory = WScript.Arguments(2)

shell.CurrentDirectory = workingDirectory
command = Chr(34) & executable & Chr(34)
If Len(commandArguments) > 0 Then
    command = command & " " & commandArguments
End If

shell.Run command, 0, False
