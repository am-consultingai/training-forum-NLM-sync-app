import io
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
}


def _token_has_drive_scope(token_path: str) -> bool:
    try:
        with open(token_path) as f:
            data = json.load(f)
        scopes = data.get("scopes", [])
        return any("drive" in s for s in scopes)
    except Exception:
        return False


def get_drive_service(credentials_path: str, token_path: str):
    """Load credentials from token_path. Raises if not authorized or Drive scopes missing.
    Auth is handled separately via /api/auth/start → /api/auth/callback."""
    if not os.path.exists(token_path):
        raise PermissionError(
            "Not authorized. Please connect Google Drive from the app first."
        )

    if not _token_has_drive_scope(token_path):
        raise PermissionError(
            "Google token lacks Drive access. Please re-authorize from the app."
        )

    creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    if not creds.valid:
        raise PermissionError(
            "Google credentials are invalid. Please re-authorize from the app."
        )

    return build("drive", "v3", credentials=creds)


_FIELDS_FULL = "nextPageToken,files(id,name,mimeType,md5Checksum,modifiedTime,size,parents,appProperties)"
# Source change-detection doesn't need appProperties (mirror-only) or size — a
# smaller field set means smaller/faster page responses.
_FIELDS_SLIM = "nextPageToken,files(id,name,mimeType,md5Checksum,modifiedTime,parents)"


_FOLDER_MIME = "application/vnd.google-apps.folder"


def _list_one_folder(svc, folder_id: str, path_prefix: str, fields: str) -> list[dict]:
    """List the direct children of one folder (all pages). Each page fetch is
    guarded by a 30s timeout. Stamps each item's drive_path."""
    out = []
    page_token = None
    while True:
        req = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields=fields, pageToken=page_token, pageSize=1000,
        )
        resp = _run_with_timeout(req.execute, timeout_seconds=30)
        for item in resp.get("files", []):
            item["drive_path"] = f"{path_prefix}/{item['name']}" if path_prefix else item["name"]
            out.append(item)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return out


def list_all_files(service, root_folder_id: str, progress_cb=None, with_app_properties: bool = True,
                   service_factory=None, max_workers: int = 8) -> list[dict]:
    """BFS walk of a Drive folder. Returns a flat list of file/folder metadata,
    each stamped with `drive_path`.

    progress_cb(count): optional callback with the running item count (live UI).
    with_app_properties=False trims fields (source folder doesn't need them).
    service_factory: if given (a callable returning a per-CALLING-THREAD Drive
    client), the BFS runs CONCURRENTLY — folders are listed in parallel, ~Nx
    faster, since the cost is per-call latency, not bandwidth. Each subfolder is
    fed back as a new task as it's discovered. The single shared `service` is used
    only for the sequential fallback (service_factory=None)."""
    fields = _FIELDS_FULL if with_app_properties else _FIELDS_SLIM
    results: list[dict] = []

    if service_factory is None:
        # Sequential BFS (single client).
        queue = [(root_folder_id, "")]
        while queue:
            folder_id, path_prefix = queue.pop(0)
            for item in _list_one_folder(service, folder_id, path_prefix, fields):
                results.append(item)
                if item["mimeType"] == _FOLDER_MIME:
                    queue.append((item["id"], item["drive_path"]))
            if progress_cb:
                try:
                    progress_cb(len(results))
                except Exception:
                    pass
        return results

    # Parallel BFS: a pool of per-thread clients; subfolders are submitted as new
    # tasks as soon as they're found. The main thread owns `results` (no locking).
    def _task(folder_id, path_prefix):
        last = None
        for attempt in range(3):
            try:
                return _list_one_folder(service_factory(), folder_id, path_prefix, fields)
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise last

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        pending = {ex.submit(_task, root_folder_id, "")}
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for fut in done:
                for item in fut.result():
                    results.append(item)
                    if item["mimeType"] == _FOLDER_MIME:
                        pending.add(ex.submit(_task, item["id"], item["drive_path"]))
            if progress_cb:
                try:
                    progress_cb(len(results))
                except Exception:
                    pass
    return results


def detect_change(existing: dict | None, drive_item: dict) -> str:
    """Returns 'new', 'changed', or 'unchanged'."""
    if existing is None:
        return "new"
    # Google-native files have no md5; use modifiedTime
    if drive_item.get("md5Checksum"):
        if existing["md5_checksum"] != drive_item["md5Checksum"]:
            return "changed"
    else:
        if existing["modified_time"] != drive_item.get("modifiedTime"):
            return "changed"
    return "unchanged"


def _run_with_timeout(fn, timeout_seconds: int = 120):
    """Run fn() in a thread; raise TimeoutError if it doesn't finish in time."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_seconds)
        except FuturesTimeout:
            raise TimeoutError(f"Operation timed out after {timeout_seconds}s")


def _long_path(path: str) -> str:
    r"""On Windows, return an extended-length (\\?\) form of an absolute path so paths
    longer than the 260-char MAX_PATH can be created/opened regardless of the
    machine's LongPathsEnabled registry setting. Used ONLY at the filesystem-call
    boundary — never stored in the DB or shown to the user. No-op off Windows."""
    if os.name != "nt":
        return path
    p = os.path.abspath(path)
    return p if p.startswith("\\\\?\\") else "\\\\?\\" + p


def download_file(service, file_id: str, dest_path: str, timeout: int = 120):
    os.makedirs(os.path.dirname(_long_path(dest_path)), exist_ok=True)

    def _do():
        request = service.files().get_media(fileId=file_id)
        with open(_long_path(dest_path), "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    try:
        _run_with_timeout(_do, timeout)
    except TimeoutError:
        # Remove partial file so a retry starts clean
        if os.path.exists(_long_path(dest_path)):
            os.remove(_long_path(dest_path))
        raise


def export_google_file(service, file_id: str, mime_type: str, dest_path: str, timeout: int = 60):
    os.makedirs(os.path.dirname(_long_path(dest_path)), exist_ok=True)

    def _do():
        request = service.files().export_media(fileId=file_id, mimeType=mime_type)
        with open(_long_path(dest_path), "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

    try:
        _run_with_timeout(_do, timeout)
    except TimeoutError:
        if os.path.exists(_long_path(dest_path)):
            os.remove(_long_path(dest_path))
        raise
