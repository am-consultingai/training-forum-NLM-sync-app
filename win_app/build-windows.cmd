@echo off
REM ===================================================================
REM  Build the sHaRe sync Windows installer.
REM  Double-click this file (or run it from a terminal).
REM
REM  It downloads the bootstrap script into DEST, then builds everything
REM  self-contained under DEST\src. The finished installer ends up at:
REM      DEST\src\dist\installer\sHaRe-sync-Setup-1.0.0.exe
REM
REM  Change DEST below to build somewhere other than E:\temp_junk.
REM ===================================================================
set "DEST=E:\temp_junk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%DEST%'; New-Item $d -ItemType Directory -Force | Out-Null; Set-Location $d; iwr 'https://raw.githubusercontent.com/am-consultingai/training-forum-NLM-sync-app/master/win_app/bootstrap-build.ps1' -OutFile 'bootstrap-build.ps1'; powershell -ExecutionPolicy Bypass -File '.\bootstrap-build.ps1' -Dir ($d + '\src')"

echo.
pause
