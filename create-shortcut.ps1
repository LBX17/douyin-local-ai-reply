$ErrorActionPreference = 'Stop'
$taskDesktop = [Environment]::GetFolderPath('Desktop')
$taskShell = New-Object -ComObject WScript.Shell
$taskShortcut = $taskShell.CreateShortcut((Join-Path $taskDesktop 'Douyin AI Reply.lnk'))
$taskShortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$taskShortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $PSScriptRoot 'start.ps1') + '"'
$taskShortcut.WorkingDirectory = $PSScriptRoot
$taskShortcut.Description = '抖音私信助手：登录、AI 配置、试聊和自动回复'
$taskShortcut.Save()
Write-Host '已在桌面创建 Douyin AI Reply 快捷入口。'
