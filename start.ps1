$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show('请先双击 setup.bat 完成安装。', '尚未安装') | Out-Null
    exit 1
}
$taskData = Join-Path $PSScriptRoot 'datas'
New-Item -ItemType Directory -Path $taskData -Force | Out-Null
$taskArguments = '-X utf8 "' + (Join-Path $PSScriptRoot 'app.py') + '"'
Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskData 'startup.out.log') -RedirectStandardError (Join-Path $taskData 'startup.err.log')
