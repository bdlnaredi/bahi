' Runs TallySync.ps1 without flashing a window (used by Task Scheduler)
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & here & "\TallySync.ps1""", 0, False
