import json
import os
import subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.config import settings
from backend.app_config import (
    is_configured,
    get_chunk_size_mb, set_chunk_size_mb,
    get_effective_source_folder_id, get_effective_output_folder_id,
    set_source_folder, set_output_folder, folder_url,
    get_effective_extracted_text_folder_id, set_extracted_text_folder,
    get_data_root, set_data_root, get_db_path,
    get_downloads_dir, get_mirror_dir, get_chunks_dir,
    get_ignore_extensions, set_ignore_extensions,
)

router = APIRouter(prefix="/api/config", tags=["config"])


class ChunkSizeRequest(BaseModel):
    chunk_size_mb: float


class FolderUrlRequest(BaseModel):
    url: str


class PathRequest(BaseModel):
    path: str


class IgnoreExtRequest(BaseModel):
    extensions: list[str]


class OAuthClientRequest(BaseModel):
    # The full OAuth client JSON downloaded from Google Cloud Console, as an object.
    client: dict


@router.get("")
def get_config():
    source_id = get_effective_source_folder_id()
    output_id = get_effective_output_folder_id()
    extracted_id = get_effective_extracted_text_folder_id()
    return {
        "source_drive_folder_id": source_id,
        "output_drive_folder_id": output_id,
        "extracted_text_drive_folder_id": extracted_id,
        "source_folder_url": folder_url(source_id),
        "output_folder_url": folder_url(output_id),
        "extracted_text_folder_url": folder_url(extracted_id),
        "sync_schedule_hour": settings.sync_schedule_hour,
        "sync_schedule_minute": settings.sync_schedule_minute,
        "whisper_model_path": settings.whisper_model_path,
        # Single data root + its derived (read-only) internal layout
        "data_folder": get_data_root(),
        "data_folder_configured": is_configured(),
        "db_path": get_db_path(),
        "downloads_dir": get_downloads_dir(),
        "mirror_dir": get_mirror_dir(),
        "chunks_dir": get_chunks_dir(),
        "ignore_extensions": get_ignore_extensions(),
        "chunk_size_mb": get_chunk_size_mb(),
    }


@router.post("/source-folder")
def update_source_folder(body: FolderUrlRequest):
    try:
        return set_source_folder(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/output-folder")
def update_output_folder(body: FolderUrlRequest):
    try:
        return set_output_folder(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/extracted-text-folder")
def update_extracted_text_folder(body: FolderUrlRequest):
    try:
        return set_extracted_text_folder(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/data-folder")
def set_data_folder(body: PathRequest):
    """Set the single local data root (holds the database + downloads/ mirror/ chunks/).
    Takes effect immediately — the new folder's database is initialized live, so no
    app restart is needed. Connections resolve the DB path per-call, so subsequent
    requests use the new folder."""
    from backend.database import get_connection, init_db

    path = body.path.strip()
    if not path:
        raise HTTPException(status_code=400, detail="Path cannot be empty")
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.exists(parent):
        raise HTTPException(status_code=400, detail=f"Parent directory does not exist: {parent}")

    # Refuse mid-sync: switching the database out from under a running sync would
    # leave it half-written against the wrong folder.
    conn = get_connection()
    try:
        running = conn.execute("SELECT id FROM sync_runs WHERE status='running' LIMIT 1").fetchone()
    finally:
        conn.close()
    if running:
        raise HTTPException(status_code=409, detail="Can't change the data folder while a sync is running. Wait for it to finish, then try again.")

    saved = set_data_root(path)
    # Create the new folder's structure + database tables now, so the change is
    # live without a restart.
    init_db()
    return {
        "data_folder": saved,
        "db_path": get_db_path(),
        "downloads_dir": get_downloads_dir(),
        "mirror_dir": get_mirror_dir(),
        "chunks_dir": get_chunks_dir(),
        "restart_required": False,
    }


@router.post("/ignore-extensions")
def update_ignore_extensions(body: IgnoreExtRequest):
    return {"ignore_extensions": set_ignore_extensions(body.extensions)}


@router.post("/chunk-size")
def update_chunk_size(body: ChunkSizeRequest):
    if body.chunk_size_mb <= 0:
        raise HTTPException(status_code=400, detail="chunk_size_mb must be positive")
    saved = set_chunk_size_mb(body.chunk_size_mb)
    return {"chunk_size_mb": saved}


# ── Google OAuth client credentials ───────────────────────────────────────────
# The OAuth client JSON is NOT shipped with the app. The user loads it once here;
# it is written to the writable credentials path and read by the auth flow.

def _client_node(client: dict) -> dict:
    """Return the 'installed' or 'web' sub-object of a Google OAuth client JSON."""
    node = client.get("installed") or client.get("web")
    if not isinstance(node, dict):
        raise HTTPException(
            status_code=400,
            detail="Not a Google OAuth client file (missing an 'installed' or 'web' section).",
        )
    if not node.get("client_id") or not node.get("client_secret"):
        raise HTTPException(
            status_code=400,
            detail="OAuth client file is missing client_id / client_secret.",
        )
    return node


@router.get("/oauth-client")
def get_oauth_client_status():
    """Whether a Google OAuth client has been loaded, and its (non-secret) client_id."""
    path = settings.google_credentials_path
    if not os.path.exists(path):
        return {"configured": False, "client_id": None}
    try:
        with open(path) as f:
            node = _client_node(json.load(f))
        return {"configured": True, "client_id": node["client_id"]}
    except HTTPException:
        return {"configured": False, "client_id": None}
    except Exception:
        return {"configured": False, "client_id": None}


@router.post("/oauth-client")
def set_oauth_client(body: OAuthClientRequest):
    """Save the user-provided Google OAuth client JSON to the credentials path."""
    node = _client_node(body.client)  # validates shape; raises 400 otherwise
    path = settings.google_credentials_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(body.client, f, indent=2)
    return {"configured": True, "client_id": node["client_id"]}


def _win_to_wsl(path: str) -> str:
    """Convert a Windows path like C:\\Users\\foo to /mnt/c/Users/foo."""
    path = path.replace("\\", "/")
    if len(path) >= 2 and path[1] == ":":
        drive = path[0].lower()
        rest = path[2:].lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return path


@router.get("/browse-folder")
def browse_folder():
    """Open a native OS folder picker and return the selected path."""
    ps_exe = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

    # WSL: PowerShell opens a Windows folder browser; result written to temp file
    # (capture_output=True prevents the dialog from showing, so use a temp file instead)
    if os.path.exists(ps_exe):
        tmp_wsl = "/tmp/drive_folder_pick.txt"
        # Get the Windows UNC path to the WSL temp file
        wpath_result = subprocess.run(
            ["wslpath", "-w", tmp_wsl], capture_output=True, text=True
        )
        win_tmp = wpath_result.stdout.strip()
        if not win_tmp:
            win_tmp = r"\\wsl.localhost\Ubuntu\tmp\drive_folder_pick.txt"

        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$owner = New-Object System.Windows.Forms.Form; "
            "$owner.TopMost = $true; "
            "$owner.Size = New-Object System.Drawing.Size(1,1); "
            "$owner.StartPosition = 'CenterScreen'; "
            "$owner.Show(); "
            "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$d.Description = 'Select download folder for Drive Sync'; "
            "$d.ShowNewFolderButton = $true; "
            "$result = $d.ShowDialog($owner); "
            "$owner.Dispose(); "
            f'$p = if ($result -eq "OK") {{ $d.SelectedPath }} else {{ "" }}; '
            f'[System.IO.File]::WriteAllText("{win_tmp}", $p)'
        )
        try:
            if os.path.exists(tmp_wsl):
                os.remove(tmp_wsl)
            proc = subprocess.Popen(
                [ps_exe, "-NoProfile", "-STA", "-WindowStyle", "Hidden", "-Command", ps_script]
            )
            proc.wait(timeout=120)
            if os.path.exists(tmp_wsl):
                win_path = open(tmp_wsl).read().strip()
                if win_path:
                    return {"path": _win_to_wsl(win_path), "display_path": win_path}
            return {"path": "", "display_path": ""}  # user cancelled
        except (subprocess.TimeoutExpired, Exception):
            try:
                proc.kill()
            except Exception:
                pass

    # Linux fallback: tkinter (for native Linux, not WSL)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select a folder for Drive downloads")
        root.destroy()
        if folder:
            return {"path": folder, "display_path": folder}
        return {"path": "", "display_path": ""}
    except Exception:
        pass

    raise HTTPException(
        status_code=503,
        detail="Could not open a folder picker. Please type the path manually.",
    )
