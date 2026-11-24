# Build the native Windows release. Python/Qt are only retained for regression tests.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$cargo = Get-Command cargo -ErrorAction SilentlyContinue
if ($cargo) { $cargoExe = $cargo.Source }
else { $cargoExe = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe' }
if (-not (Test-Path -LiteralPath $cargoExe)) { throw 'Install Rust stable and Visual Studio C++ Build Tools with the Windows SDK first.' }
$savedFlags = $env:RUSTFLAGS
try {
    $env:RUSTFLAGS = (($savedFlags + ' -C target-feature=+crt-static').Trim())
    & $cargoExe build --manifest-path native/Cargo.toml --release --locked
    if ($LASTEXITCODE -ne 0) { throw 'Native Rust build failed' }
} finally { $env:RUSTFLAGS = $savedFlags }
New-Item -ItemType Directory -Force -Path dist,build | Out-Null
Copy-Item -LiteralPath native/target/release/KirbyClicker.exe -Destination dist/KirbyClicker.exe
# Preserve the documented frozen-check entry point, with a tracked test implementation.
'& (Join-Path $PSScriptRoot "..\tools\verify_native_exe.ps1")' |
    Set-Content -LiteralPath build/verify_exe_env.ps1 -Encoding utf8
$exe = Get-Item -LiteralPath dist/KirbyClicker.exe
Write-Host "Built: $($exe.FullName) ($($exe.Length) bytes)"
