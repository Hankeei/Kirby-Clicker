# Build the distributable Windows executable.
#
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#
# Output: dist\KirbyClicker.exe  (one file, no Python installation required)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

py -3.13 -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

$assets = Join-Path $PSScriptRoot "assets"
$readme = Join-Path $PSScriptRoot "README.md"

py -3.13 -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name KirbyClicker `
    --icon "$assets\icon.ico" `
    --add-data "$assets;assets" `
    --add-data "$readme;." `
    --collect-all PySide6.QtMultimedia `
    --distpath dist `
    --workpath build/work `
    --specpath build `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$exe = Get-Item -LiteralPath (Join-Path $PSScriptRoot "dist\KirbyClicker.exe")
$sizeMb = [math]::Round($exe.Length / 1MB, 1)
Write-Host "Built: $($exe.FullName) ($sizeMb MB)"
