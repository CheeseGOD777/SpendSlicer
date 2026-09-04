# Build CostSight.exe and wrap it in a distributable .zip.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
#
# Output: dist\CostSight-<version>-windows-x64.zip
#
# The build is UNSIGNED. SmartScreen will show "Windows protected your PC" on
# first run; users click "More info" then "Run anyway". See docs/DESKTOP.md.
# To sign instead, set WINDOWS_CERT_FILE and WINDOWS_CERT_PASSWORD.
#
# A .zip rather than an installer: CostSight keeps all its state in
# %USERPROFILE%\.cache\costsight and writes nothing to the registry, so there is
# nothing for an uninstaller to undo. Unzip and run.

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$AppName = "CostSight"
$Version = (Select-String -Path "costsight\__init__.py" -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$Zip = "dist\$AppName-$Version-windows-x64.zip"

Write-Host "==> Building $AppName $Version (x64)"

Write-Host "==> Frontend"
Push-Location frontend
npm ci
npm run build
Pop-Location

Write-Host "==> Icons"
python packaging\make_icons.py

Write-Host "==> PyInstaller"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
$env:COSTSIGHT_VERSION = $Version
pyinstaller packaging\costsight.spec --noconfirm

$ExePath = "dist\$AppName\$AppName.exe"
if (-not (Test-Path $ExePath)) { throw "ERROR: $ExePath was not produced" }

# Optional Authenticode signing.
if ($env:WINDOWS_CERT_FILE -and $env:WINDOWS_CERT_PASSWORD) {
    Write-Host "==> Signing"
    & signtool sign `
        /f $env:WINDOWS_CERT_FILE `
        /p $env:WINDOWS_CERT_PASSWORD `
        /fd SHA256 `
        /tr http://timestamp.digicert.com `
        /td SHA256 `
        $ExePath
    if ($LASTEXITCODE -ne 0) { throw "signtool failed" }
} else {
    Write-Host "==> No signing certificate set - shipping unsigned"
}

Write-Host "==> Packing .zip"
Remove-Item -Force $Zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\$AppName\*" -DestinationPath $Zip -CompressionLevel Optimal

$Size = "{0:N0} MB" -f ((Get-Item $Zip).Length / 1MB)
Write-Host ""
Write-Host "Built: $Zip ($Size)"
if (-not $env:WINDOWS_CERT_FILE) {
    Write-Host ""
    Write-Host "This build is unsigned. SmartScreen will warn on first run;"
    Write-Host "users click 'More info' then 'Run anyway'."
}
