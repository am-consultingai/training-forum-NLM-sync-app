<#
  build.ps1 — one-command Windows build for Drive Sync Manager.

  Produces dist\installer\DriveSyncManager-Setup-<ver>.exe.

  Prerequisites (see win_app\README.md):
    * Windows x64
    * Python 3.12 on PATH
    * Node.js (npm) on PATH
    * Inno Setup 6 (iscc.exe) — optional; skipped with -SkipInstaller
    * win_app\oauth_client.json replaced with the real shared OAuth client

  Run from the repo root:   powershell -ExecutionPolicy Bypass -File win_app\build.ps1
#>
param(
    [switch]$SkipInstaller,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot   # repo root (parent of win_app)
$WinApp = $PSScriptRoot
Set-Location $Repo

Write-Host "==> Build venv + dependencies" -ForegroundColor Cyan
if (-not (Test-Path ".venv-build")) { python -m venv .venv-build }
$py = Join-Path $Repo ".venv-build\Scripts\python.exe"
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt pyinstaller

Write-Host "==> Fetch ffmpeg.exe" -ForegroundColor Cyan
$ffmpeg = Join-Path $WinApp "vendor\ffmpeg.exe"
if (-not (Test-Path $ffmpeg)) {
    $zip = Join-Path $env:TEMP "ffmpeg-win64.zip"
    $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip
    $extract = Join-Path $env:TEMP "ffmpeg-extract"
    if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
    Expand-Archive -Path $zip -DestinationPath $extract
    $found = Get-ChildItem -Path $extract -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
    Copy-Item $found.FullName $ffmpeg -Force
    Write-Host "    ffmpeg.exe -> $ffmpeg"
} else {
    Write-Host "    already present: $ffmpeg"
}

Write-Host "==> Fetch Visual C++ redistributable" -ForegroundColor Cyan
$vcredist = Join-Path $WinApp "vendor\vc_redist.x64.exe"
if (-not (Test-Path $vcredist)) {
    Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vcredist
    Write-Host "    vc_redist.x64.exe -> $vcredist"
} else {
    Write-Host "    already present: $vcredist"
}

if (-not $SkipFrontend) {
    Write-Host "==> Build frontend (vite)" -ForegroundColor Cyan
    Push-Location (Join-Path $Repo "frontend")
    if (Test-Path "package-lock.json") { npm ci } else { npm install }
    npm run build   # tsc typecheck + vite build
    Pop-Location
}

Write-Host "==> PyInstaller" -ForegroundColor Cyan
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
if (Test-Path "dist\DriveSyncManager") { Remove-Item -Recurse -Force "dist\DriveSyncManager" }
& $py -m PyInstaller "win_app\DriveSyncManager.spec" --noconfirm

if ($SkipInstaller) {
    Write-Host "`nDone (one-dir only): dist\DriveSyncManager\DriveSyncManager.exe" -ForegroundColor Green
    return
}

Write-Host "==> Inno Setup installer" -ForegroundColor Cyan
$iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $iscc)) { throw "Inno Setup (iscc.exe) not found. Install it, or re-run with -SkipInstaller." }
& $iscc "win_app\installer.iss"

Write-Host "`nDone. Installer in dist\installer\" -ForegroundColor Green
