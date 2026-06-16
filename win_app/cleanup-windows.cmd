@echo off
REM ===================================================================
REM  Remove a Drive Sync Manager installation (per-user; no admin).
REM  Double-click this file (or run it from a terminal).
REM
REM  It removes the app, its shortcuts, and the Add/Remove Programs entry,
REM  and ASKS before deleting the downloaded data (model / sign-in / data).
REM  The shared Visual C++ runtime is left installed.
REM ===================================================================
echo This will UNINSTALL Drive Sync Manager (app + shortcuts + registry entry).
echo It will ASK before deleting the downloaded data folder.
echo.
echo Close this window now to abort, or
pause

powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location $env:TEMP; iwr 'https://raw.githubusercontent.com/am-consultingai/training-forum-NLM-sync-app/master/win_app/cleanup-windows.ps1' -OutFile 'cleanup-windows.ps1'; powershell -ExecutionPolicy Bypass -File '.\cleanup-windows.ps1'"

echo.
pause
