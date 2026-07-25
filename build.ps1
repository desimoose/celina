# Build Reveriebot.exe (single-file, no console).
$ErrorActionPreference = "Stop"

Write-Host "Installing build + desktop deps..."
python -m pip install -r requirements-desktop.txt
python -m pip install pyinstaller

Write-Host "Building..."
python -m PyInstaller reveriebot.spec --noconfirm --clean

$exe = Join-Path $PSScriptRoot "dist\Reveriebot.exe"
if (Test-Path $exe) {
    Write-Host "Built: $exe"
} else {
    Write-Error "Build finished but dist\Reveriebot.exe not found."
}
