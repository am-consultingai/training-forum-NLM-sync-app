import io
import os
import time

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from backend.paths import long_path


def _find_file_by_name(service, parent_folder_id: str, name: str) -> str | None:
    """Return the ID of a non-trashed file named `name` directly under
    `parent_folder_id`, or None. Used to make uploads idempotent by name: Drive
    happily creates a SECOND file with the same name in a folder, so without this
    a machine that doesn't already know a chunk's Drive ID would create a duplicate
    (e.g. a second Majors_Part5.txt) instead of updating the existing one."""
    if not parent_folder_id:
        return None
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"'{parent_folder_id}' in parents and trashed=false and name='{safe}'"
    resp = (
        service.files()
        .list(q=q, fields="files(id,modifiedTime)", pageSize=10,
              orderBy="modifiedTime desc",
              supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
    )
    files = resp.get("files", [])
    return files[0]["id"] if files else None


VALID_RELEVANCE = ("relevant", "not_relevant")


def relevance_from_props(app_properties: dict | None) -> str | None:
    """Read the cross-machine relevance flag stamped on a mirror extract's
    appProperties. Returns 'relevant'/'not_relevant', or None when the extract
    carries no explicit stamp (legacy extract — leave the local value untouched
    rather than forcing it back to the default)."""
    rel = (app_properties or {}).get("relevance")
    return rel if rel in VALID_RELEVANCE else None


def dedupe_by_name(files: list[dict]) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """Group Drive files by name and pick one survivor per name (the most recently
    modified). Pure — does NO Drive calls — so it's unit-testable.

    files: dicts with at least 'id', 'name', and optionally 'modifiedTime'.
    Returns (id_by_name, to_trash) where id_by_name maps name -> survivor id and
    to_trash is a list of (name, file_id) duplicates to remove."""
    by_name: dict[str, list[dict]] = {}
    for f in files:
        by_name.setdefault(f["name"], []).append(f)
    id_by_name: dict[str, str] = {}
    to_trash: list[tuple[str, str]] = []
    for name, group in by_name.items():
        group = sorted(group, key=lambda d: d.get("modifiedTime") or "", reverse=True)
        id_by_name[name] = group[0]["id"]
        for extra in group[1:]:
            to_trash.append((name, extra["id"]))
    return id_by_name, to_trash


def reconcile_chunks_by_name(tracked, present_by_name: dict) -> tuple[list, list]:
    """Decide — by FILENAME — what to do with locally-tracked chunks given the Drive
    output folder's current {name: id}. A chunk's cross-machine identity is its name,
    not its Drive ID, so this avoids a machine rebuilding/re-uploading a chunk that
    another machine merely (re)created under a different ID. Pure (no Drive calls).

    tracked: iterable of (filename, output_drive_file_id).
    Returns (adopt, missing):
      adopt   = [(filename, drive_id)] present under a DIFFERENT id → re-point only.
      missing = [filename] absent from the folder entirely → must be rebuilt.
    """
    adopt, missing = [], []
    for fname, current_id in tracked:
        drive_id = present_by_name.get(fname)
        if drive_id is None:
            missing.append(fname)
        elif drive_id != current_id:
            adopt.append((fname, drive_id))
    return adopt, missing


def update_app_properties(service, file_id: str, app_properties: dict) -> None:
    """Metadata-only update of a Drive file's appProperties (no media re-upload).
    Used to push a relevance toggle to the mirror extract so the flag travels to
    every machine, even when the extract's content hasn't changed."""
    service.files().update(
        fileId=file_id, body={"appProperties": app_properties},
        fields="id", supportsAllDrives=True,
    ).execute()


def upload_text_file(
    service,
    local_path: str,
    parent_folder_id: str,
    name: str | None = None,
    existing_drive_id: str | None = None,
    app_properties: dict | None = None,
    max_retries: int = 3,
) -> tuple[str, bool]:
    """Upload or update a text file in a Drive folder. Returns (drive_file_id, created)
    where `created` is True only when a brand-new Drive file was made (vs an in-place
    update of an existing one). Callers use `created` to report a new NotebookLM source.

    - `name` defaults to the local basename (used only when creating).
    - `app_properties` are custom key/value metadata stored on the Drive file
      (used to record source provenance for cross-machine cache validation).
    """
    for attempt in range(max_retries):
        try:
            media = MediaFileUpload(long_path(local_path), mimetype="text/plain", resumable=False)
            target_name = name or os.path.basename(local_path)
            # Idempotent by name: if the caller didn't hand us an ID, look one up by
            # name in the target folder before creating. This guarantees one Drive
            # file per name regardless of local-DB state, killing cross-machine
            # duplicates at the upload layer.
            target_id = existing_drive_id or _find_file_by_name(
                service, parent_folder_id, target_name
            )
            if target_id:
                body = {}
                if app_properties:
                    body["appProperties"] = app_properties
                file = (
                    service.files()
                    .update(fileId=target_id, media_body=media, body=body or None,
                            fields="id", supportsAllDrives=True)
                    .execute()
                )
                return file["id"], False
            else:
                metadata = {
                    "name": target_name,
                    "parents": [parent_folder_id],
                }
                if app_properties:
                    metadata["appProperties"] = app_properties
                file = (
                    service.files()
                    .create(body=metadata, media_body=media, fields="id",
                            supportsAllDrives=True)
                    .execute()
                )
                return file["id"], True
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
) -> tuple[str, bool]:
    """Upload or update a chunk file in the output Drive folder.
    Returns (drive_file_id, created)."""
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
