Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strCurDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strCurDir

strPython = ""
If fso.FileExists("C:\Python312\python.exe") Then
    strPython = "C:\Python312\python.exe"
ElseIf fso.FileExists(strCurDir & "\python_runtime\python.exe") Then
    strPython = strCurDir & "\python_runtime\python.exe"
Else
    strPython = "python"
End If

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
