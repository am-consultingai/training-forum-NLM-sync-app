"""
Filesystem locations for the app, working both in dev (a source checkout) and
when frozen into a PyInstaller bundle on Windows.

Two kinds of locations:

* **Writable runtime state** — the Whisper model, downloaded CUDA libs, the OAuth
  token, ``app_config.json`` and the data folder — all live under a per-user
  *app home* directory (``%LOCALAPPDATA%\\sHaRe-sync`` on Windows). The
  install dir under ``Program Files`` is read-only, so nothing runtime goes there.

* **Read-only bundled assets** — the shared OAuth client JSON, ffmpeg, and the
  built frontend — are read from the frozen bundle dir, or from the repo in dev.

Override the app home with the ``SHARE_SYNC_HOME`` env var (handy for tests).
"""
import os
import shutil
import sys

APP_NAME = "sHaRe-sync"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _repo_root() -> str:
    """Repo root in a dev checkout: paths.py -> app_core -> win_app -> <repo>."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Writable per-user state ──────────────────────────────────────────────────

def app_home() -> str:
    """Writable per-user directory holding all runtime state. Created on access."""
    override = os.environ.get("SHARE_SYNC_HOME")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME)
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_NAME)
    else:
        base = os.path.join(
            os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
            APP_NAME,
        )
    os.makedirs(base, exist_ok=True)
    return base


def model_dir() -> str:
    """Where the ivrit-ai/whisper-large-v3-ct2 model is downloaded on first run."""
    return os.path.join(app_home(), "model")


def cuda_dir() -> str:
    """Where the NVIDIA cuBLAS/cuDNN wheels are installed on first run (GPU only)."""
    return os.path.join(app_home(), "cuda")


def creds_dir() -> str:
    d = os.path.join(app_home(), "creds")
    os.makedirs(d, exist_ok=True)
    return d


def token_path() -> str:
    """OAuth token (written per machine, against the shared Google account)."""
    return os.path.join(creds_dir(), "token.json")


def oauth_client_path() -> str:
    """The Google OAuth client JSON. NOT bundled with the app — the user loads it
    once via Settings, and it is stored here in the writable app home."""
    return os.path.join(creds_dir(), "oauth_client.json")


def default_data_root() -> str:
    """Default data root (downloads/ mirror/ chunks/ sync.db) under app home."""
    return os.path.join(app_home(), "data")


# ── Read-only bundled assets ─────────────────────────────────────────────────

def bundled_dir() -> str:
    """Directory holding read-only bundled assets.

    Frozen: PyInstaller's extraction dir (``sys._MEIPASS`` for one-file) or the
    executable's dir (one-dir). Dev: the repo root.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return _repo_root()


def frontend_dist_dir() -> str:
    """The built React app that FastAPI serves."""
    if is_frozen():
        return os.path.join(bundled_dir(), "frontend_dist")
    return os.path.join(_repo_root(), "frontend", "dist")


def default_ffmpeg() -> str:
    """Path to ffmpeg. Bundled binary when frozen, else PATH lookup, else the
    repo's vendored copy, else the bare name (relies on PATH at call time)."""
    if is_frozen():
        exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        return os.path.join(bundled_dir(), exe)
    found = shutil.which("ffmpeg")
    if found:
        return found
    vendored = os.path.join(_repo_root(), "win_app", "vendor",
                            "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
    return vendored if os.path.exists(vendored) else "ffmpeg"
