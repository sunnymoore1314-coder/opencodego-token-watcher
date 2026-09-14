# Run from any working directory after installing requirements-build.txt.
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskBuildPython = Join-Path $taskProjectRoot '.build-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskBuildPython)) {
    throw 'Create .build-venv and install requirements-build.txt first.'
}
Push-Location -LiteralPath $taskProjectRoot
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $taskProjectRoot 'build\pyinstaller-cache'
    & $taskBuildPython -m PyInstaller --noconfirm opencodego-token-watcher.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    # Use Unicode codepoints so this script also works in Windows PowerShell 5.1.
    $taskExeName = 'OpenCode' + [char]0x7528 + [char]0x91CF + [char]0x76D1 + [char]0x6D4B + '.exe'
    Copy-Item -LiteralPath 'dist\opencodego-token-watcher.exe' -Destination $taskExeName -Force
    Write-Output (Join-Path $taskProjectRoot $taskExeName)
} finally {
    Pop-Location
}
