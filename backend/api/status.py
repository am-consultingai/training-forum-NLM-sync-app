from fastapi import APIRouter, Query
from backend.database import get_connection
from backend.app_config import get_downloads_dir, is_configured

router = APIRouter(prefix="/api/status", tags=["status"])

REASON_MAP = {
    "done":             "synced",
    "failed":           "failed",
    "skipped":          "skipped",
    "not_downloaded":   "not_downloaded",
    "needs_processing": "needs_processing",
}


def _classify(dl: str, proc: str) -> str:
    if proc == "done":       return "synced"
    if proc == "failed" or dl == "failed": return "failed"
    if proc == "skipped" or dl == "skipped": return "skipped"
    if dl in ("pending", "failed") and proc == "pending": return "not_downloaded"
    return "needs_processing"


@router.get("/summary")
def get_summary():
    conn = get_connection()
    total_files = conn.execute(
        "SELECT COUNT(*) FROM drive_files WHERE is_folder=0"
    ).fetchone()[0]

    if total_files == 0:
        conn.close()
        return {
            "ever_synced": False,
            "downloads_dir_configured": is_configured(),
            "downloads_dir": get_downloads_dir(),
            "total_files": 0,
            "needs_update": [],
            "needs_update_total": 0,
            "counts": {},
        }

    rows = conn.execute(
        """SELECT df.id, df.name, df.drive_path, df.mime_type,
                  fp.download_status, fp.processing_status, fp.processing_type,
                  fp.processing_error, fp.download_error
           FROM drive_files df
           LEFT JOIN file_processing fp ON fp.drive_file_id = df.id
           WHERE df.is_folder = 0"""
    ).fetchall()
    conn.close()

    counts = {"total": 0, "synced": 0, "needs_processing": 0,
              "needs_download": 0, "failed": 0, "skipped": 0}
    needs_update = []

    for r in rows:
        counts["total"] += 1
        dl   = r["download_status"]   or "pending"
        proc = r["processing_status"] or "pending"
        cat  = _classify(dl, proc)

        if cat == "synced":           counts["synced"] += 1
        elif cat == "failed":         counts["failed"] += 1
        elif cat == "skipped":        counts["skipped"] += 1
        elif cat == "not_downloaded": counts["needs_download"] += 1
        else:                         counts["needs_processing"] += 1

        if cat != "synced" and cat != "skipped":
            needs_update.append({
                "id": r["id"], "name": r["name"],
                "drive_path": r["drive_path"],
                "reason": cat,
                "error": r["processing_error"] or r["download_error"],
            })

    pending_orphans = conn.execute("SELECT COUNT(*) FROM pending_orphans").fetchone()[0]

    return {
        "ever_synced": total_files > 0,
        "downloads_dir_configured": is_configured(),
        "downloads_dir": get_downloads_dir(),
        "total_files": counts["total"],
        "needs_update": needs_update[:50],
        "needs_update_total": len(needs_update),
        "counts": counts,
        "pending_orphans": pending_orphans,
    }


@router.get("/files")
def get_files_by_category(
    category: str = Query("all"),   # all | synced | failed | not_downloaded | needs_processing | skipped
    page: int = Query(0, ge=0),
    per_page: int = Query(50, ge=1, le=200),
):
    conn = get_connection()
    rows = conn.execute(
        """SELECT df.id, df.name, df.drive_path, df.mime_type, df.relevance,
                  fp.download_status, fp.processing_status, fp.processing_type,
                  fp.processing_error, fp.download_error
           FROM drive_files df
           LEFT JOIN file_processing fp ON fp.drive_file_id = df.id
           WHERE df.is_folder = 0
           ORDER BY df.drive_path"""
    ).fetchall()
    conn.close()

    items = []
    for r in rows:
        dl   = r["download_status"]   or "pending"
        proc = r["processing_status"] or "pending"
        cat  = _classify(dl, proc)
        if category != "all" and cat != category:
            continue
        items.append({
            "id": r["id"], "name": r["name"],
            "drive_path": r["drive_path"],
            "mime_type": r["mime_type"],
            "relevance": r["relevance"] or "relevant",
            "category": cat,
            "download_status": dl,
            "processing_status": proc,
            "processing_type": r["processing_type"],
            "error": r["processing_error"] or r["download_error"],
        })

    total = len(items)
    page_items = items[page * per_page : (page + 1) * per_page]
    return {
        "category": category,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "items": page_items,
    }


@router.post("/reset-failed")
def reset_failed():
    """Reset all failed files back to pending so the next sync retries them."""
    conn = get_connection()
    conn.execute(
        """UPDATE file_processing
           SET download_status  = CASE WHEN download_status  = 'failed' THEN 'pending' ELSE download_status  END,
               processing_status = CASE WHEN processing_status = 'failed' THEN 'pending' ELSE processing_status END,
               download_error = NULL, processing_error = NULL,
               updated_at = datetime('now')
           WHERE download_status = 'failed' OR processing_status = 'failed'"""
    )
    affected = conn.execute("SELECT changes()").fetchone()[0]
    conn.commit()
    conn.close()
    return {"reset": affected}
