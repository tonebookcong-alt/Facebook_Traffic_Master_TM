Set WshShell = CreateObject("WScript.Shell")
strCurDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir

Set fso = CreateObject("Scripting.FileSystemObject")
strPython = strCurDir & "\python_runtime\python.exe"
strFlag = strCurDir & "\installed.flag"

If Not fso.FileExists(strFlag) Then
    WshShell.Run """" & strPython & """ -m playwright install chromium", 1, True
    Set flagFile = fso.CreateTextFile(strFlag, True)
    flagFile.WriteLine "Installed"
    flagFile.Close
End If

WshShell.Environment("PROCESS")("PYTHONPATH") = strCurDir & "\core"
WshShell.Environment("PROCESS")("FTM_ROOT_DIR") = strCurDir

WshShell.Run """" & strPython & """ """ & strCurDir & "\core\webui.pyc""", 0, False
WScript.Sleep 3500
WshShell.Run "http://127.0.0.1:5001"
