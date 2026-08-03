# Fetch, verify, and install the pinned Obscura stealth binary.
#
# Non-interactive by design: build.ps1 calls this to produce a bundle-ready
# vendor/obscura/ before PyInstaller runs, and setup.ps1 calls it for a
# developer's local install. Always downloads the exact version+asset pinned
# in third_party/obscura/manifest.json - never "latest" - and always verifies
# the download's SHA-256 against the hash recorded IN THAT FILE (not a hash
# fetched alongside the archive, which would just be trusting the same
# potentially-compromised source twice).
#
# Usage: powershell -File scripts/fetch-obscura.ps1 [-Platform windows-x86_64] [-Force]

param(
    [string]$Platform = "windows-x86_64",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$manifestPath = Join-Path $root "third_party\obscura\manifest.json"
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json

$entry = $manifest.platforms.$Platform
if (-not $entry) {
    throw "no manifest entry for platform '$Platform' (edit third_party/obscura/manifest.json to add one)"
}

$vendorObscura = Join-Path $root "vendor\obscura"
$exePath = Join-Path $vendorObscura "obscura.exe"

if ((Test-Path $exePath) -and -not $Force) {
    Write-Host "  Obscura: already installed at $exePath" -ForegroundColor Green
    exit 0
}

if (-not $entry.asset.EndsWith(".zip")) {
    throw "fetch-obscura.ps1 only extracts .zip archives today (got '$($entry.asset)'); " +
          "the Linux/macOS setup script needs its own tar.gz extraction path."
}

$url = "https://github.com/$($manifest.repo)/releases/download/$($manifest.version)/$($entry.asset)"
$zip = Join-Path $env:TEMP $entry.asset

Write-Host "  Downloading Obscura $($manifest.version) ($Platform)..."
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing

$actualHash = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
$expectedHash = $entry.sha256.ToLower()
if ($actualHash -ne $expectedHash) {
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    throw "Obscura download hash mismatch for $($entry.asset)!`n  expected: $expectedHash`n  actual:   $actualHash`nRefusing to install an artifact that doesn't match the pinned manifest."
}
Write-Host "  Hash verified against third_party/obscura/manifest.json" -ForegroundColor Green

New-Item -ItemType Directory -Force -Path $vendorObscura | Out-Null
Expand-Archive -Path $zip -DestinationPath $vendorObscura -Force
Remove-Item $zip -Force

# the archive may nest the exe one level down; flatten it
$exe = Get-ChildItem -Path $vendorObscura -Filter "obscura.exe" -Recurse | Select-Object -First 1
if (-not $exe) { throw "obscura.exe not found inside $($entry.asset) after extraction" }
if ($exe.DirectoryName -ne $vendorObscura) {
    Move-Item $exe.FullName $exePath -Force
}

Write-Host "  Obscura installed: $exePath" -ForegroundColor Green
