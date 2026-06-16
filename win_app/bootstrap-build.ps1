<#
  bootstrap-build.ps1 - set up a Windows machine, download the code, and build the
  installer locally. No GitHub account or sign-in required.

  What it does:
    1. ensures Python 3.12 is installed (via winget, only if missing),
    2. downloads the repo as a ZIP (the repo is public; no auth, no Git needed),
    3. runs win_app\build.ps1, which builds everything inside a self-contained
       .build folder (venv, portable Node, portable Inno Setup, all deps) and
       produces dist\installer\DriveSyncManager-Setup-<ver>.exe,
    4. (with -Run) launches the finished installer.

  build.ps1 self-cleans .build, so the only thing installed machine-wide is Python.

  This is a standalone bootstrap: save just this one file and run it.

  Usage (from PowerShell):
    powershell -ExecutionPolicy Bypass -File bootstrap-build.ps1
    powershell -ExecutionPolicy Bypass -File bootstrap-build.ps1 -Run
    powershell -ExecutionPolicy Bypass -File bootstrap-build.ps1 -Dir C:\dev\dsm

  Note: some winget installs may prompt for elevation (UAC). If a tool was just
  installed but isn't found yet, open a NEW PowerShell window and re-run - the
  script is idempotent (installs are skipped, the code is re-downloaded, it builds).
#>
param(
    [string]$Repo   = "am-consultingai/training-forum-NLM-sync-app",
    [string]$Branch = "master",
    [string]$Dir    = "$HOME\dev\training-forum-NLM-sync-app",
    [switch]$Run                       # launch the installer after building
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Update-SessionPath {
    # Pull the freshly-updated PATH from the registry into this session so tools
    # installed moments ago become callable without reopening PowerShell.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ";"
}

function Ensure-Tool {
    param([string]$WingetId, [string]$Command, [string]$ExistsPath)
    $have = ($Command -and (Get-Command $Command -ErrorAction SilentlyContinue)) -or
            ($ExistsPath -and (Test-Path $ExistsPath))
    if ($have) { Write-Host "    [skip] $WingetId already present" -ForegroundColor DarkGray; return }
    Write-Host "    [install] $WingetId" -ForegroundColor Yellow
    winget install --id $WingetId -e --source winget `
        --accept-package-agreements --accept-source-agreements --disable-interactivity
    Update-SessionPath
}

# 0. winget present? ----------------------------------------------------------
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}

# 1. System prerequisites -----------------------------------------------------
# Only Python is needed system-wide; build.ps1 provisions Node and Inno Setup into
# its own .build folder and cleans them up, so they aren't installed machine-wide.
Write-Host "==> Installing system prerequisites" -ForegroundColor Cyan
Ensure-Tool -WingetId "Python.Python.3.12" -Command "python"
Update-SessionPath

$missing = @("python") | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) }
if ($missing) {
    Write-Warning ("Just-installed tools not on PATH yet: {0}" -f ($missing -join ", "))
    Write-Warning "Open a NEW PowerShell window and re-run this script (installs will be skipped)."
    exit 1
}

# 2. Download the code (public repo ZIP - no auth, no Git) --------------------
Write-Host "==> Downloading $Repo ($Branch)" -ForegroundColor Cyan
$zip = Join-Path $env:TEMP "dsm-src.zip"
$tmp = Join-Path $env:TEMP "dsm-src"
$url = "https://github.com/$Repo/archive/refs/heads/$Branch.zip"
Invoke-WebRequest -Uri $url -OutFile $zip
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
if (Test-Path $Dir) { Remove-Item -Recurse -Force $Dir }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Dir) | Out-Null
Move-Item -Path $inner.FullName -Destination $Dir
Write-Host "    code -> $Dir" -ForegroundColor DarkGray

# 3. Build --------------------------------------------------------------------
Write-Host "==> Building the installer (downloads deps; takes a few minutes)" -ForegroundColor Cyan
& (Join-Path $Dir "win_app\build.ps1")

# 4. Report / launch ----------------------------------------------------------
$exe = Get-ChildItem -Path (Join-Path $Dir "dist\installer") -Filter *.exe -ErrorAction SilentlyContinue |
       Select-Object -First 1
if (-not $exe) { throw "Build finished but no installer was found under dist\installer." }

Write-Host "`nDone. Installer:" -ForegroundColor Green
Write-Host "  $($exe.FullName)" -ForegroundColor Green

if ($Run) {
    Write-Host "==> Launching the installer..." -ForegroundColor Cyan
    Start-Process -FilePath $exe.FullName
}
