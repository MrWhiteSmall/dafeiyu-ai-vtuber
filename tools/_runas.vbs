Dim sh, exePath, workDir
If WScript.Arguments.Count < 2 Then WScript.Quit 2
workDir = WScript.Arguments(0)
exePath = WScript.Arguments(1)
Set sh = CreateObject("Shell.Application")
sh.ShellExecute exePath, "", workDir, "runas", 1