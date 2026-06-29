"""Surface chunk files CREATED or DELETED on Drive during a sync, so the user can
keep NotebookLM in step: a newly-created chunk is a source they must ADD; a removed
one is a source they must DELETE. Without this, NotebookLM silently drifts from the
Drive output folder. Notices persist until the user acknowledges them.
"""
from fastapi import APIRouter

from backend.database import get_connection

router = APIRouter(prefix="/api/notices", tags=["notices"])


@router.get("")
def list_notices():
    """Pending NotebookLM notices, split into sources to add (created) and to
    remove (deleted)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT action, chunk_filename, drive_file_id, created_at "
        "FROM chunk_notices ORDER BY action, chunk_filename"
    ).fetchall()
    conn.close()
    created = [dict(r) for r in rows if r["action"] == "created"]
    deleted = [dict(r) for r in rows if r["action"] == "deleted"]
    return {"count": len(rows), "created": created, "deleted": deleted}


@router.post("/dismiss")
def dismiss_notices():
    """User has reconciled NotebookLM → clear the pending notices."""
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM chunk_notices").fetchone()[0]
    conn.execute("DELETE FROM chunk_notices")
    conn.commit()
    conn.close()
    return {"dismissed": n}
