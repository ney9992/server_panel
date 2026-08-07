' Запуск SrvMan без консольного окна — для двойного клика из проводника.
Set WshShell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir
pythonw = scriptDir & "\.venv\Scripts\pythonw.exe"

If CreateObject("Scripting.FileSystemObject").FileExists(pythonw) Then
    WshShell.Run """" & pythonw & """ -m client.main", 0, False
Else
    MsgBox "Не найден " & pythonw & vbCrLf & vbCrLf & _
        "Сначала выполните в PowerShell (один раз):" & vbCrLf & _
        "python -m venv .venv" & vbCrLf & _
        ".venv\Scripts\activate" & vbCrLf & _
        "pip install -r requirements.txt", vbExclamation, "SrvMan"
End If
