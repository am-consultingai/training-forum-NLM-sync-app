# Drive Sync Manager — Windows desktop app

This folder packages the Drive → NotebookLM sync app as a Windows installer for
non-technical users. The user double-clicks `Setup.exe`, gets a tray app that runs
the backend (which serves the React UI) on `http://localhost:8000`, downloads the
Hebrew transcription model on first launch, signs into the shared Google account,
and syncs.

**v1 scope:** manual sync only (no automatic daily run), Windows only, single
shared Google account. See *Follow-ups* at the bottom.

---

## What's in here

| File | Purpose |
|------|---------|
| `app_core/paths.py` | Resolves writable (per-user) vs bundled (read-only) locations. Re-exported by `backend/paths.py`. |
| `app_core/bootstrap.py` | First-run download of the model + (NVIDIA only) CUDA libs. |
| `app_core/setup_api.py` | `/api/setup/*` endpoints driving the first-run screen. |
| `launcher.py` | Tray app; PyInstaller entry point. Starts the backend, opens the browser. |
| `DriveSyncManager.spec` | PyInstaller one-dir build spec. |
| `installer.iss` | Inno Setup script (per-user install, no admin prompt). |
| `build.ps1` | One-command build: deps → ffmpeg → frontend → PyInstaller → installer. |
| `oauth_client.sample.json` | Sample showing the OAuth client shape. **Not bundled** — see below. |
| `vendor/` | `ffmpeg.exe` lands here (fetched by `build.ps1`). |

### Where things live at runtime

```
%LOCALAPPDATA%\Programs\DriveSyncManager\   app install (read-only)
%LOCALAPPDATA%\DriveSyncManager\            writable state:
    app_config.json   model\   cuda\   creds\token.json   data\
```

The lean installer (~80 MB) carries no model or CUDA libs. On first launch the app
downloads the model (`ivrit-ai/whisper-large-v3-ct2`, ~3 GB) and, on NVIDIA
machines, the cuBLAS/cuDNN wheels. No GPU → transcription runs on CPU (slower).

### End-user requirements

The user needs **no Python/Node/ffmpeg** — those are bundled. They just run
`Setup.exe` (no admin prompt; per-user install). What's required:

- **Windows 10/11 x64.**
- **Internet on first launch** (for the model / GPU-lib download) and **~6–8 GB free disk**.
- **Microsoft Visual C++ 2015-2022 x64 runtime** — required by the native libraries.
  The installer installs it silently and only when it's missing (the one step that
  can raise a UAC prompt, and only on a machine that lacks it).
- **NVIDIA GPU driver** — *optional*, only for GPU speed. The downloaded CUDA libs are
  the runtime, not the kernel driver; if the driver/GPU is absent the app
  automatically falls back to CPU. An app installer can't install GPU drivers.

---

## Google OAuth setup (one-time, by you)

Each install signs into **one shared Google account**. The OAuth client is **not
shipped inside the app** — you create it once and distribute the JSON file to your
users, who load it from **Settings → Google sign-in** on first run (it's stored under
`%LOCALAPPDATA%\DriveSyncManager\creds\oauth_client.json`, never in the installer).

1. In the shared account's [Google Cloud Console](https://console.cloud.google.com/),
   create (or pick) a project and enable the **Google Drive API**.
2. **OAuth consent screen** → User type **External** → fill the basics →
   **Publish app** (set status to *In production*). Publishing avoids the
   ~7-day refresh-token expiry that "Testing" mode imposes on the Drive scope, which
   would otherwise silently break sign-in.
3. **Credentials → Create credentials → OAuth client ID → Application type
   "Desktop app"**. (A "Web application" client also works if you add the redirect
   URI below.)
4. Add authorized redirect URI: `http://localhost:8000/api/auth/callback`
   (Desktop-app clients allow loopback redirects; add it explicitly if you chose Web.)
5. Download the client JSON. Hand this file to each user (e.g. over a secure channel).
   In the app they open **Settings → Google sign-in → Choose JSON file…** and select
   it, then click **Connect Google Drive**.

`oauth_client.sample.json` in this folder shows the expected shape.

---

## Build (on Windows)

Prerequisites: Windows x64, **Python 3.12**, **Node.js**, and **Inno Setup 6**
(for the installer step). Then, from the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File win_app\build.ps1
```

This will:
1. create a build venv and install `requirements.txt` + PyInstaller,
2. fetch `ffmpeg.exe` and `vc_redist.x64.exe` into `win_app\vendor\`,
3. build the frontend with `npm run build` into `frontend\dist`,
4. run PyInstaller → `dist\DriveSyncManager\`,
5. compile the installer → `dist\installer\DriveSyncManager-Setup-<ver>.exe`.

Flags: `-SkipInstaller` (one-dir only), `-SkipFrontend` (reuse existing `dist`).

### Building must happen on Windows
PyInstaller is not a cross-compiler — the Windows `.exe`/installer must be built on
Windows (a Windows VM or a GitHub Actions `windows-latest` runner). You cannot build
it from Linux/WSL.

---

## Test checklist (clean Windows VM, no Python/CUDA)

1. Run the installer → tray icon appears → browser opens to `http://localhost:8000`.
2. First-run screen downloads the model (and CUDA libs on a GPU box) → app loads.
3. Settings → Google sign-in → load the OAuth client JSON → Connect → consent on the
   shared account → "Drive connected".
4. Pick a data folder → **Sync now** → files download, transcribe, chunk, upload to
   the output Drive folder.
5. On a non-GPU box: confirm the CPU notice appears and transcription still works.

---

## Follow-ups (out of v1 scope)

- **Automatic daily sync** across multiple machines (a Drive-based lock so only one
  online machine runs it). The scheduler is gated by `ENABLE_SCHEDULER` and off by
  default in the packaged build.
- **macOS build** (Metal/whisper.cpp backend, `.dmg`, notarization).
- **Code signing** the Windows installer to avoid the SmartScreen warning.
