Dim sh, exe, exeArgs, workDir
If WScript.Arguments.Count < 3 Then WScript.Quit 2
exe = WScript.Arguments(0)
exeArgs = WScript.Arguments(1)
workDir = WScript.Arguments(2)
Set sh = CreateObject("Shell.Application")
sh.ShellExecute exe, exeArgs, workDir, "runas", 1