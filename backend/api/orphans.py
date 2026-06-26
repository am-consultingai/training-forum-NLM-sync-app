"""Review + (soft-)delete mirror extracts whose source file no longer exists.

The sync NEVER deletes these automatically — it only records them (detected by the
extract's stable `source_id`, so a path discrepancy can't flag a live file). The
user reviews them here and explicitly approves removal, which **trashes** the Drive
file (recoverable) rather than hard-deleting it.
"""
import logging

from fastapi import APIRouter

from backend.config import settings
from backend.database import get_connection
from backend.services.drive_sync import get_drive_service
from backend.services.drive_upload import trash_drive_file

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orphans", tags=["orphans"])


@router.get("")
def list_orphans():
    """Mirror extracts with no matching source, pending the user's decision."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT mirror_drive_id, name, drive_path, source_id, detected_at "
        "FROM pending_orphans ORDER BY drive_path"
    ).fetchall()
    conn.close()
    return {"count": len(rows), "orphans": [dict(r) for r in rows]}


@router.post("/delete")
def delete_orphans():
    """User approved removal → move each orphan extract to Drive trash (recoverable),
    then clear it from the pending list. Returns how many were trashed."""
    conn = get_connection()
    rows = conn.execute("SELECT mirror_drive_id FROM pending_orphans").fetchall()
    ids = [r["mirror_drive_id"] for r in rows]
    if not ids:
        conn.close()
        return {"trashed": 0, "failed": 0}

    service = get_drive_service(settings.google_credentials_path, settings.google_token_path)
    trashed = failed = 0
    for fid in ids:
        try:
            trash_drive_file(service, fid)
            conn.execute("DELETE FROM pending_orphans WHERE mirror_drive_id=?", (fid,))
            trashed += 1
        except Exception as e:  # noqa: BLE001
            log.warning("Failed to trash orphan %s: %s", fid, e)
            failed += 1
    conn.commit()
    conn.close()
    return {"trashed": trashed, "failed": failed}


@router.post("/dismiss")
def dismiss_orphans():
    """User chose to keep the files → clear the pending list without deleting anything."""
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM pending_orphans").fetchone()[0]
    conn.execute("DELETE FROM pending_orphans")
    conn.commit()
    conn.close()
    return {"dismissed": n}
