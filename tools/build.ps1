# Run from any working directory after installing requirements-build.txt.
$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskBuildPython = Join-Path $taskProjectRoot '.build-venv3126\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskBuildPython)) {
    throw 'Create .build-venv3126 with Python 3.12.6 and install requirements-build.txt first.'
}
Push-Location -LiteralPath $taskProjectRoot
try {
    $env:PYINSTALLER_CONFIG_DIR = Join-Path $taskProjectRoot 'build\pyinstaller-cache'
    # Tcl_Init can see the extracted directory yet fail before assigning tcl_library.
    # Stage a tiny bootstrap init.tcl that fixes the variable, then sources the official file.
    $taskTclDir = Join-Path $taskProjectRoot 'build\python3126\tcl\tcl8.6'
    $taskTclInit = Join-Path $taskTclDir 'init.tcl'
    $taskTclReal = Join-Path $taskTclDir 'init_real.tcl'
    Copy-Item -LiteralPath $taskTclInit -Destination $taskTclReal -Force
    [System.IO.File]::WriteAllText(
        $taskTclInit,
        "set ::tcl_library [file dirname [info script]]`nsource [file join `$::tcl_library init_real.tcl]`n",
        [System.Text.UTF8Encoding]::new($false))
    try {
        & $taskBuildPython -m PyInstaller --clean --noconfirm opencodego-token-watcher.spec
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
    } finally {
        Move-Item -LiteralPath $taskTclReal -Destination $taskTclInit -Force
    }
    # Use Unicode codepoints so this script also works in Windows PowerShell 5.1.
    $taskExeName = 'OpenCode' + [char]0x7528 + [char]0x91CF + [char]0x76D1 + [char]0x6D4B + '.exe'
    Copy-Item -LiteralPath 'dist\opencodego-token-watcher.exe' -Destination $taskExeName -Force
    Write-Output (Join-Path $taskProjectRoot $taskExeName)
} finally {
    Pop-Location
}
