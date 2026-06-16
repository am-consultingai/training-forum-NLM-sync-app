# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller build spec for the Drive Sync Manager Windows app.

Produces a ONE-DIR bundle whose entry point is win_app/launcher.py (the tray app).
It bundles the Python backend, the win_app package, the built React frontend, the
shared OAuth client JSON, and ffmpeg.exe. It deliberately does NOT bundle the
Whisper model or the CUDA libraries — those are downloaded on first launch.

Build on Windows:  pyinstaller win_app\\DriveSyncManager.spec
(see win_app/README.md for the full build pipeline / build.ps1)
"""
import os
from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
)

# SPECPATH is the directory containing this spec (…/win_app); repo root is its parent.
WIN_APP = SPECPATH
REPO = os.path.dirname(WIN_APP)

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("backend")
    + collect_submodules("win_app")
    + [
        "faster_whisper",
        "ctranslate2",
        "huggingface_hub",
        "apscheduler.schedulers.asyncio",
        "google_auth_oauthlib.flow",
        "pystray._win32",
        "PIL.Image",
        "PIL.ImageDraw",
    ]
)

datas = (
    collect_data_files("faster_whisper")
    + collect_data_files("huggingface_hub")
    + [
        (os.path.join(REPO, "frontend", "dist"), "frontend_dist"),
        (os.path.join(WIN_APP, "vendor", "ffmpeg.exe"), "."),
        # NOTE: the OAuth client JSON is deliberately NOT bundled — the user loads it
        # at runtime via Settings (stored in %LOCALAPPDATA%\DriveSyncManager\creds).
    ]
)

binaries = collect_dynamic_libs("ctranslate2")


a = Analysis(
    [os.path.join(WIN_APP, "launcher.py")],
    pathex=[REPO],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DriveSyncManager",
    console=False,           # tray app — no console window
    disable_windowed_traceback=False,
    icon=os.path.join(WIN_APP, "app.ico") if os.path.exists(os.path.join(WIN_APP, "app.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="DriveSyncManager",   # -> dist/DriveSyncManager/
)
