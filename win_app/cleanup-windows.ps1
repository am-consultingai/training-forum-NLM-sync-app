<#
  cleanup-windows.ps1 - find and remove a Drive Sync Manager installation.

  Everything here is per-user, so no admin is needed. It:
    1. stops the app if it's running,
    2. runs the registered uninstaller (proper removal) if present,
    3. sweeps any residue: app folder, Start Menu + Desktop shortcuts, and the
       Add/Remove Programs entry,
    4. optionally removes the downloaded data (model, CUDA libs, sign-in token,
       synced data).

  It does NOT remove the shared Visual C++ runtime - other applications depend on it.

  Usage:
    powershell -ExecutionPolicy Bypass -File cleanup-windows.ps1              # asks about the data folder
    powershell -ExecutionPolicy Bypass -File cleanup-windows.ps1 -IncludeData # also delete data, no prompt
    powershell -ExecutionPolicy Bypass -File cleanup-windows.ps1 -DryRun      # report only, remove nothing
#>
param(
    [switch]$IncludeData,   # also delete the data folder without prompting
    [switch]$DryRun         # show what would be removed, but remove nothing
)

$installDir = Join-Path $env:LOCALAPPDATA "Programs\DriveSyncManager"
$dataDir    = Join-Path $env:LOCALAPPDATA "DriveSyncManager"
$startMenu  = Join-Path ([Environment]::GetFolderPath('Programs')) "Drive Sync Manager"
$desktopLnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "Drive Sync Manager.lnk"

function Remove-Path($path, $label) {
    if (-not (Test-Path $path)) { Write-Host "  [not found] $label" -ForegroundColor DarkGray; return }
    if ($DryRun)               { Write-Host "  [would remove] $label : $path" -ForegroundColor Yellow; return }
    try {
        Remove-Item $path -Recurse -Force -ErrorAction Stop
        Write-Host "  [removed] $label : $path" -ForegroundColor Green
    } catch {
        Write-Host "  [FAILED]  $label : $path -- $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "==> Drive Sync Manager cleanup" -ForegroundColor Cyan

# 1. Stop the app if it's running (otherwise its files are locked).
$proc = Get-Process DriveSyncManager -ErrorAction SilentlyContinue
if ($proc) {
    if ($DryRun) { Write-Host "  [would stop] running DriveSyncManager.exe" -ForegroundColor Yellow }
    else { $proc | Stop-Process -Force; Write-Host "  [stopped] running DriveSyncManager.exe" -ForegroundColor Green }
}

# 2. Proper uninstall via the registered uninstaller, if present.
$unins = Join-Path $installDir "unins000.exe"
if (Test-Path $unins) {
    if ($DryRun) { Write-Host "  [would run] uninstaller: $unins" -ForegroundColor Yellow }
    else {
        Write-Host "  [running] uninstaller (silent)..." -ForegroundColor Green
        Start-Process -Wait -FilePath $unins -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART"
    }
}

# 3. Sweep residue (covers partial/failed installs where the uninstaller is gone).
Write-Host "Files & shortcuts:" -ForegroundColor Cyan
Remove-Path $installDir "app folder"
Remove-Path $startMenu  "Start Menu shortcut"
Remove-Path $desktopLnk "Desktop shortcut"

# 4. Add/Remove Programs entries (per-user hive).
Write-Host "Registry (Add/Remove Programs):" -ForegroundColor Cyan
$keys = Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" -ErrorAction SilentlyContinue |
        Where-Object { ($_ | Get-ItemProperty -ErrorAction SilentlyContinue).DisplayName -like "*Drive Sync*" }
if ($keys) {
    foreach ($k in $keys) {
        if ($DryRun) { Write-Host "  [would remove] registry key $($k.PSChildName)" -ForegroundColor Yellow }
        else {
            try { Remove-Item $k.PSPath -Recurse -Force -ErrorAction Stop; Write-Host "  [removed] registry key $($k.PSChildName)" -ForegroundColor Green }
            catch { Write-Host "  [FAILED]  registry key $($k.PSChildName) -- $($_.Exception.Message)" -ForegroundColor Red }
        }
    }
} else { Write-Host "  [not found] no Add/Remove Programs entry" -ForegroundColor DarkGray }

# 5. Downloaded data (model, CUDA libs, token, synced data).
Write-Host "Downloaded data:" -ForegroundColor Cyan
if (Test-Path $dataDir) {
    $bytes = (Get-ChildItem $dataDir -Recurse -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    $size  = "{0:N2} GB" -f (($bytes) / 1GB)
    if ($DryRun) {
        Write-Host "  [would remove if confirmed] data folder ($size): $dataDir" -ForegroundColor Yellow
    } else {
        $remove = $IncludeData
        if (-not $IncludeData) {
            $ans = Read-Host "  Delete data folder ($size) at $dataDir ? [y/N]"
            $remove = ($ans -match '^(y|yes)$')
        }
        if ($remove) { Remove-Path $dataDir "data folder" }
        else { Write-Host "  [kept] data folder: $dataDir" -ForegroundColor DarkGray }
    }
} else {
    Write-Host "  [not found] no data folder" -ForegroundColor DarkGray
}

Write-Host "`nDone. The shared Visual C++ runtime was left installed (other apps may need it)." -ForegroundColor Cyan
