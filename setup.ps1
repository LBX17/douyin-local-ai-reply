$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw '请先安装 Node.js LTS（https://nodejs.org/），并重新打开安装入口。'
    }
    $taskPython = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    & $taskPython -c "import sys; assert sys.version_info >= (3,11), '需要 Python 3.11 或更新版本'"
    if ($LASTEXITCODE -ne 0) { throw '请安装 Python 3.11/3.12（https://www.python.org/），安装时勾选 Add Python to PATH。' }
    & $taskPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 环境失败。' }
    & '.\.venv\Scripts\python.exe' -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw '更新 pip 失败，请检查网络。' }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 依赖安装失败，请检查网络。' }
    & npm.cmd ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Node.js 依赖安装失败，请检查网络。' }
    & '.\.venv\Scripts\python.exe' -m playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw '浏览器安装失败，请检查网络后重新运行。' }
    & '.\.venv\Scripts\python.exe' -c "from app_settings import initialize_local_files; initialize_local_files()"
    if ($LASTEXITCODE -ne 0) { throw '初始化配置失败。' }
    Write-Host '安装完成。双击 start.bat 打开助手，然后配置 AI。' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
