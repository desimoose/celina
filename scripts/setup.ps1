# Reveriebot - optional tool installer.
#
# Nothing here is required: the app runs without any of it. This fetches the
# heavy research tools into vendor/ and asks before every download.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$vendor = Join-Path $root "vendor"
New-Item -ItemType Directory -Force -Path $vendor | Out-Null

function Confirm-Step($message) {
    $answer = Read-Host "$message [y/N]"
    return $answer -match '^(y|yes)$'
}

Write-Host ""
Write-Host "  Reveriebot optional tools" -ForegroundColor Cyan
Write-Host "  The app already works without these."
Write-Host ""

# --- Obscura: stealth headless browser (prebuilt Windows binary) ---
$obscuraDir = Join-Path $vendor "obscura"
if (Test-Path (Join-Path $obscuraDir "obscura.exe")) {
    Write-Host "  Obscura: already installed" -ForegroundColor Green
}
elseif (Confirm-Step "  Download Obscura? (~43 MB, prebuilt x86_64 Windows binary from GitHub releases)") {
    $api = "https://api.github.com/repos/h4ckf0r0day/obscura/releases/latest"
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "reveriebot" }
    $asset = $release.assets | Where-Object { $_.name -like "*x86_64-windows*" } | Select-Object -First 1

    if (-not $asset) { throw "no Windows asset in the latest release" }

    $zip = Join-Path $env:TEMP $asset.name
    Write-Host "  downloading $($asset.name) ..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing

    New-Item -ItemType Directory -Force -Path $obscuraDir | Out-Null
    Expand-Archive -Path $zip -DestinationPath $obscuraDir -Force
    Remove-Item $zip -Force

    # the archive may nest the exe one level down; flatten it
    $exe = Get-ChildItem -Path $obscuraDir -Filter "obscura.exe" -Recurse | Select-Object -First 1
    if ($exe -and $exe.DirectoryName -ne $obscuraDir) {
        Move-Item $exe.FullName (Join-Path $obscuraDir "obscura.exe") -Force
    }
    Write-Host "  Obscura installed" -ForegroundColor Green
}

# --- Agent-Reach: 15-platform read/search ---
if (Get-Command agent-reach -ErrorAction SilentlyContinue) {
    Write-Host "  Agent-Reach: already installed" -ForegroundColor Green
}
elseif (Confirm-Step "  Install Agent-Reach? (pip install, pulls requests/yt-dlp/feedparser)") {
    python -m pip install --user agent-reach
    Write-Host "  Agent-Reach installed" -ForegroundColor Green
}

# --- last30days: engagement-scored brief (stdlib only) ---
$last30 = Join-Path $vendor "last30days"
if (Test-Path $last30) {
    Write-Host "  last30days: already present" -ForegroundColor Green
}
elseif (Confirm-Step "  Clone last30days? (small; stdlib-only Python, no deps)") {
    git clone --depth 1 https://github.com/mvanhorn/last30days-skill $last30
    Write-Host "  last30days cloned" -ForegroundColor Green
}

Write-Host ""
Write-Host "  Done. Restart the server to pick up new tools." -ForegroundColor Cyan
Write-Host ""
