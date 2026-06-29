import io
import os
import time

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from backend.paths import long_path


def upload_text_file(
    service,
    local_path: str,
    parent_folder_id: str,
    name: str | None = None,
    existing_drive_id: str | None = None,
    app_properties: dict | None = None,
    max_retries: int = 3,
) -> str:
    """Upload or update a text file in a Drive folder. Returns the Drive file ID.

    - `name` defaults to the local basename (used only when creating).
    - `app_properties` are custom key/value metadata stored on the Drive file
      (used to record source provenance for cross-machine cache validation).
    """
    for attempt in range(max_retries):
        try:
            media = MediaFileUpload(long_path(local_path), mimetype="text/plain", resumable=False)
            if existing_drive_id:
                body = {}
                if app_properties:
                    body["appProperties"] = app_properties
                file = (
                    service.files()
                    .update(fileId=existing_drive_id, media_body=media, body=body or None)
                    .execute()
                )
            else:
                metadata = {
                    "name": name or os.path.basename(local_path),
                    "parents": [parent_folder_id],
                }
                if app_properties:
                    metadata["appProperties"] = app_properties
                file = (
                    service.files()
                    .create(body=metadata, media_body=media, fields="id")
                    .execute()
                )
            return file["id"]
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

    raise RuntimeError("unreachable")


def upload_chunk(
    service,
    chunk_path: str,
    output_folder_id: str,
    existing_drive_id: str | None,
    max_retries: int = 3,
) -> str:
    """Upload or update a chunk file in the output Drive folder. Returns the Drive file ID."""
    return upload_text_file(
        service, chunk_path, output_folder_id,
        existing_drive_id=existing_drive_id, max_retries=max_retries,
    )


def ensure_drive_folder_path(service, root_folder_id: str, rel_dir: str, cache: dict) -> str:
    """`mkdir -p` on Drive: ensure each segment of `rel_dir` exists under
    `root_folder_id`, creating missing folders. Returns the leaf folder ID.

    `cache` maps a normalized relative dir path -> folder ID and is reused across
    calls within a run so each folder is looked up/created at most once.
    """
    rel_dir = (rel_dir or "").replace("\\", "/").strip("/")
    if rel_dir in cache:
        return cache[rel_dir]
    if rel_dir == "":
        cache[""] = root_folder_id
        return root_folder_id

    parent_rel, _, leaf = rel_dir.rpartition("/")
    parent_id = ensure_drive_folder_path(service, root_folder_id, parent_rel, cache)

    # Look for an existing child folder with this name
    safe = leaf.replace("'", "\\'")
    q = (
        f"'{parent_id}' in parents and trashed=false "
        f"and mimeType='application/vnd.google-apps.folder' and name='{safe}'"
    )
    resp = service.files().list(q=q, fields="files(id,name)", pageSize=1).execute()
    files = resp.get("files", [])
    if files:
        fid = files[0]["id"]
    else:
        meta = {
            "name": leaf,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        fid = service.files().create(body=meta, fields="id").execute()["id"]

    cache[rel_dir] = fid
    return fid


def download_drive_text(service, file_id: str, dest_path: str):
    """Download a (text) Drive file by ID to dest_path."""
    os.makedirs(os.path.dirname(long_path(dest_path)), exist_ok=True)
    request = service.files().get_media(fileId=file_id)
    with open(long_path(dest_path), "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()


def delete_drive_file(service, file_id: str):
    service.files().delete(fileId=file_id).execute()


def trash_drive_file(service, file_id: str):
    """Soft-delete: move the file to Drive trash (recoverable for ~30 days) instead
    of permanently deleting it. Used for orphan cleanup, which is a heuristic — so a
    mistaken removal can always be undone from trash."""
    service.files().update(
        fileId=file_id, body={"trashed": True}, supportsAllDrives=True
    ).execute()
