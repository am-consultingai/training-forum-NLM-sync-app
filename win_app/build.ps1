<#
  build.ps1 - build the Windows installer in a fully SELF-CONTAINED way.

  Everything transient is created under <repo>\.build:
    * an isolated Python venv (your existing Python is used only to spawn it - it is
      never modified, and no global site-packages or pip cache are touched),
    * pip + npm caches,
    * temp downloads (ffmpeg, VC++ redist, Node),
    * a portable Node toolchain,
    * if needed, a throwaway portable Inno Setup,
    * PyInstaller's work directory.

  All cache/temp environment variables are redirected into .build, so NOTHING is
  written to your user profile or %TEMP%. The .build folder is deleted at the end
  (use -KeepBuildEnv to keep it for faster re-runs). Delete the repo folder and no
  trace remains anywhere on disk.

  Output: dist\installer\DriveSyncManager-Setup-<ver>.exe

  Prerequisites: Windows x64 + an existing Python 3.x on PATH. Node and Inno Setup
  are provisioned automatically into .build if not already present.

  Usage:
    powershell -ExecutionPolicy Bypass -File win_app\build.ps1
    powershell -ExecutionPolicy Bypass -File win_app\build.ps1 -KeepBuildEnv
    powershell -ExecutionPolicy Bypass -File win_app\build.ps1 -SkipInstaller
#>
param(
    [switch]$KeepBuildEnv,   # keep .build (and provisioned tools) for faster re-runs
    [switch]$SkipInstaller,  # build the app folder only, skip the .exe installer
    [switch]$SkipFrontend    # reuse an existing frontend\dist
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$WinApp = $PSScriptRoot
$Repo   = Split-Path -Parent $WinApp
Set-Location $Repo

$NodeVersion = "v20.18.1"   # portable Node LTS pulled into .build

# Everything transient lives here.
$BuildRoot = Join-Path $Repo ".build"
$Venv  = Join-Path $BuildRoot "venv"
$Cache = Join-Path $BuildRoot "cache"
$Tmp   = Join-Path $BuildRoot "tmp"
$Tools = Join-Path $BuildRoot "tools"
$null = New-Item -ItemType Directory -Force -Path $BuildRoot, $Cache, $Tmp, $Tools

# Remember env we override so we can restore it afterward.
$prev = @{
    PIP_CACHE_DIR    = $env:PIP_CACHE_DIR
    npm_config_cache = $env:npm_config_cache
    TMP = $env:TMP; TEMP = $env:TEMP; Path = $env:Path
}
# Redirect every cache + temp dir into .build so nothing lands in your profile.
$env:PIP_CACHE_DIR    = Join-Path $Cache "pip"
$env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
$env:npm_config_cache = Join-Path $Cache "npm"
$env:TMP  = $Tmp
$env:TEMP = $Tmp

$portableInno = $null   # set if we install a throwaway Inno Setup into .build

try {
    # 1. Isolated Python venv ------------------------------------------------
    Write-Host "==> Creating isolated Python venv (.build\venv)" -ForegroundColor Cyan
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python not found on PATH. Install Python 3.12 (winget install Python.Python.3.12) and re-run."
    }
    if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & python -m venv $Venv }
    $py = Join-Path $Venv "Scripts\python.exe"
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt pyinstaller

    # 2. Bundled binaries: ffmpeg + VC++ redist -> win_app\vendor ------------
    Write-Host "==> Fetching bundled binaries (ffmpeg, VC++ redist)" -ForegroundColor Cyan
    $vendor = Join-Path $WinApp "vendor"
    $null = New-Item -ItemType Directory -Force -Path $vendor
    $ffmpeg = Join-Path $vendor "ffmpeg.exe"
    if (-not (Test-Path $ffmpeg)) {
        $z = Join-Path $Tmp "ffmpeg.zip"
        Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $z
        $ex = Join-Path $Tmp "ffmpeg"
        Expand-Archive $z -DestinationPath $ex -Force
        Copy-Item (Get-ChildItem $ex -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName $ffmpeg -Force
    }
    $vc = Join-Path $vendor "vc_redist.x64.exe"
    if (-not (Test-Path $vc)) { Invoke-WebRequest "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vc }

    # 3. Frontend build with a portable Node ---------------------------------
    if (-not $SkipFrontend) {
        Write-Host "==> Provisioning portable Node $NodeVersion (.build\tools)" -ForegroundColor Cyan
        $nodeDir = Join-Path $Tools "node-$NodeVersion-win-x64"
        if (-not (Test-Path $nodeDir)) {
            $nz = Join-Path $Tmp "node.zip"
            Invoke-WebRequest "https://nodejs.org/dist/$NodeVersion/node-$NodeVersion-win-x64.zip" -OutFile $nz
            Expand-Archive $nz -DestinationPath $Tools -Force
        }
        $env:Path = "$nodeDir;$env:Path"
        Write-Host "==> Building frontend" -ForegroundColor Cyan
        Push-Location (Join-Path $Repo "frontend")
        try {
            if (Test-Path "package-lock.json") { npm ci } else { npm install }
            npm run build
        } finally { Pop-Location }
    }

    # 4. PyInstaller (work dir + dist inside the repo) -----------------------
    Write-Host "==> PyInstaller" -ForegroundColor Cyan
    if (Test-Path "dist\DriveSyncManager") { Remove-Item -Recurse -Force "dist\DriveSyncManager" }
    & $py -m PyInstaller "win_app\DriveSyncManager.spec" --noconfirm `
        --workpath (Join-Path $BuildRoot "pyinstaller") `
        --distpath (Join-Path $Repo "dist")

    if ($SkipInstaller) {
        Write-Host "`nDone (app folder only): dist\DriveSyncManager\DriveSyncManager.exe" -ForegroundColor Green
        return
    }

    # 5. Inno Setup - system copy if present, else a throwaway portable one ---
    Write-Host "==> Inno Setup installer" -ForegroundColor Cyan
    $iscc = (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source
    if (-not $iscc) {
        $sys = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
        if (Test-Path $sys) { $iscc = $sys }
    }
    if (-not $iscc) {
        Write-Host "    no Inno Setup found - installing a throwaway copy into .build\tools" -ForegroundColor DarkGray
        $isexe = Join-Path $Tmp "innosetup.exe"
        Invoke-WebRequest "https://jrsoftware.org/download.php/is.exe" -OutFile $isexe
        $portableInno = Join-Path $Tools "innosetup"
        Start-Process -Wait -FilePath $isexe -ArgumentList `
            "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/NOICONS","/CURRENTUSER","/DIR=$portableInno"
        $iscc = Join-Path $portableInno "ISCC.exe"
    }
    if (-not (Test-Path $iscc)) { throw "Inno Setup compiler (ISCC.exe) not available." }
    & $iscc "win_app\installer.iss"

    $exe = Get-ChildItem (Join-Path $Repo "dist\installer") -Filter *.exe -ErrorAction SilentlyContinue |
           Select-Object -First 1
    Write-Host "`nDone. Installer:" -ForegroundColor Green
    Write-Host "  $($exe.FullName)" -ForegroundColor Green
}
finally {
    # Restore the environment we changed.
    $env:PIP_CACHE_DIR    = $prev.PIP_CACHE_DIR
    $env:npm_config_cache = $prev.npm_config_cache
    $env:TMP = $prev.TMP; $env:TEMP = $prev.TEMP; $env:Path = $prev.Path

    if ($KeepBuildEnv) {
        Write-Host "==> Kept build environment at .build (-KeepBuildEnv)" -ForegroundColor DarkGray
    } else {
        Write-Host "==> Cleaning up build environment (.build)" -ForegroundColor Cyan
        # Remove the throwaway Inno Setup first so its registry/uninstall entry goes too.
        $unins = if ($portableInno) { Join-Path $portableInno "unins000.exe" } else { $null }
        if ($unins -and (Test-Path $unins)) {
            try { Start-Process -Wait -FilePath $unins -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" } catch {}
        }
        Remove-Item -Recurse -Force $BuildRoot -ErrorAction SilentlyContinue
    }
}
