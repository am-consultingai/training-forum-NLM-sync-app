<#
  get-installer.ps1 — build the Windows installer in GitHub Actions and download it.

  Runs the whole cloud-build flow from your PowerShell prompt:
    1. triggers the "Build Windows installer" workflow on GitHub,
    2. waits for the Windows runner to build it (live progress),
    3. downloads the finished DriveSyncManager-Setup-*.exe,
    4. optionally launches it.

  You do NOT need this repo cloned or any build tools installed — only the GitHub
  CLI (gh). Save this one file anywhere and run it.

  Prerequisites:
    * GitHub CLI:  winget install GitHub.cli
    * Logged in :  gh auth login   (as an account with access to the repo)

  Examples:
    powershell -ExecutionPolicy Bypass -File get-installer.ps1
    powershell -ExecutionPolicy Bypass -File get-installer.ps1 -Run
    powershell -ExecutionPolicy Bypass -File get-installer.ps1 -OutDir C:\Temp\dsm
#>
param(
    [string]$Repo   = "am-consultingai/training-forum-NLM-sync-app",
    [string]$Ref    = "master",
    [string]$OutDir = "$HOME\Downloads\DriveSyncManager",
    [switch]$Run                      # launch the installer after download
)

$ErrorActionPreference = "Stop"
$workflow = "windows-build.yml"
$artifact = "DriveSyncManager-Setup"

# 1. Preconditions ------------------------------------------------------------
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI not found. Install it with:  winget install GitHub.cli"
}
gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Not logged in to GitHub. Run:  gh auth login"
}

Write-Host "==> Triggering '$workflow' on $Repo ($Ref)" -ForegroundColor Cyan
$before = (gh run list --workflow $workflow --repo $Repo --limit 1 --json databaseId -q '.[0].databaseId' 2>$null)
gh workflow run $workflow --ref $Ref --repo $Repo

# 2. Find the run we just started --------------------------------------------
Write-Host "==> Waiting for the run to appear..." -ForegroundColor Cyan
$runId = $null
for ($i = 0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 3
    $latest = (gh run list --workflow $workflow --repo $Repo --limit 1 --json databaseId -q '.[0].databaseId' 2>$null)
    if ($latest -and ($latest -ne $before)) { $runId = $latest; break }
}
if (-not $runId) { throw "Timed out waiting for the workflow run to start." }
Write-Host "    run id: $runId" -ForegroundColor DarkGray
Write-Host "    web:    https://github.com/$Repo/actions/runs/$runId" -ForegroundColor DarkGray

# 3. Watch it to completion (non-zero exit if it fails) -----------------------
Write-Host "==> Building on the Windows runner (this takes a few minutes)..." -ForegroundColor Cyan
gh run watch $runId --repo $Repo --exit-status
if ($LASTEXITCODE -ne 0) {
    throw "The build failed. See the log:  gh run view $runId --repo $Repo --log-failed"
}

# 4. Download the installer artifact ------------------------------------------
Write-Host "==> Downloading the installer to $OutDir" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
gh run download $runId --repo $Repo --name $artifact --dir $OutDir

$exe = Get-ChildItem -Path $OutDir -Recurse -Filter *.exe | Select-Object -First 1
if (-not $exe) { throw "Downloaded the artifact but found no .exe under $OutDir." }

Write-Host "`nDone. Installer:" -ForegroundColor Green
Write-Host "  $($exe.FullName)" -ForegroundColor Green

# 5. Optionally launch it -----------------------------------------------------
if ($Run) {
    Write-Host "==> Launching the installer..." -ForegroundColor Cyan
    Start-Process -FilePath $exe.FullName
}
