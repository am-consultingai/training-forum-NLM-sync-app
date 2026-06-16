import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.database import get_connection
from backend.jobs.job_runner import get_active_run_id, run_sync
from backend.jobs.scheduler import get_executor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _is_running(conn) -> bool:
    row = conn.execute(
        "SELECT id FROM sync_runs WHERE status='running' LIMIT 1"
    ).fetchone()
    return row is not None


@router.post("/trigger")
async def trigger_sync():
    conn = get_connection()
    if _is_running(conn):
        run_id = conn.execute(
            "SELECT id FROM sync_runs WHERE status='running' LIMIT 1"
        ).fetchone()["id"]
        conn.close()
        raise HTTPException(status_code=409, detail={"message": "Sync already running", "run_id": run_id})
    conn.close()

    main_loop = asyncio.get_running_loop()

    def _run():
        try:
            run_sync("manual", main_loop=main_loop)
        except Exception:
            log.exception("run_sync raised an exception")

    main_loop.run_in_executor(get_executor(), _run)
    return {"message": "Sync started"}


@router.get("/status")
def get_status():
    conn = get_connection()
    running = conn.execute(
        "SELECT * FROM sync_runs WHERE status='running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if running:
        conn.close()
        return {"active": True, "run": dict(running)}

    last = conn.execute(
        "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {"active": False, "run": dict(last) if last else None}


@router.get("/runs")
def list_runs():
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sync_runs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM sync_runs WHERE id=?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return dict(row)


@router.get("/live-progress")
def get_live_progress():
    """Authoritative snapshot of download + processing state, read straight from the DB.

    The UI polls this so the progress bars stay correct regardless of SSE event gaps.
    """
    conn = get_connection()

    run = conn.execute(
        "SELECT files_discovered FROM sync_runs WHERE status='running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    total = run["files_discovered"] if run else 0

    dl = conn.execute(
        """SELECT
             SUM(CASE WHEN download_status IN ('done','skipped') THEN 1 ELSE 0 END) AS done,
             SUM(CASE WHEN download_status = 'done' THEN 1 ELSE 0 END) AS downloaded
           FROM file_processing"""
    ).fetchone()

    proc = conn.execute(
        """SELECT
             SUM(CASE WHEN processing_status IN ('done','skipped') THEN 1 ELSE 0 END) AS done,
             SUM(CASE WHEN processing_status = 'failed' THEN 1 ELSE 0 END) AS failed,
             SUM(CASE WHEN processing_status = 'done' AND chunking_status = 'done' THEN 1 ELSE 0 END) AS chunked
           FROM file_processing"""
    ).fetchone()

    chunks = conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN upload_status = 'done' THEN 1 ELSE 0 END) AS uploaded
           FROM chunks"""
    ).fetchone()

    # Mirror (extracted-text → Drive) upload progress
    mirror = conn.execute(
        """SELECT
             SUM(CASE WHEN processing_status = 'done' AND processed_path IS NOT NULL THEN 1 ELSE 0 END) AS total,
             SUM(CASE WHEN extracted_drive_file_id IS NOT NULL THEN 1 ELSE 0 END) AS uploaded
           FROM file_processing"""
    ).fetchone()

    mirror_file = conn.execute(
        """SELECT df.name FROM file_processing fp
           JOIN drive_files df ON df.id = fp.drive_file_id
           WHERE fp.extracted_drive_file_id IS NOT NULL
           ORDER BY fp.updated_at DESC LIMIT 1"""
    ).fetchone()

    # Current pipeline stage + message — from the latest stage_change event of the
    # running run. Lets the UI show "what's happening now" via polling alone
    # (survives tab switches / reloads, independent of the SSE stream).
    import json as _json
    stage = stage_message = None
    if run:
        ev = conn.execute(
            """SELECT pe.payload FROM progress_events pe
               JOIN sync_runs sr ON sr.id = pe.run_id
               WHERE sr.status = 'running' AND pe.event_type = 'stage_change'
               ORDER BY pe.id DESC LIMIT 1"""
        ).fetchone()
        if ev:
            try:
                p = _json.loads(ev["payload"])
                stage = p.get("stage")
                stage_message = p.get("message")
            except Exception:
                pass

    downloading = conn.execute(
        """SELECT df.name FROM file_processing fp
           JOIN drive_files df ON df.id = fp.drive_file_id
           WHERE fp.download_status = 'downloading'
           ORDER BY fp.updated_at DESC LIMIT 1"""
    ).fetchone()

    tx = conn.execute(
        """SELECT df.name, fp.processing_progress
           FROM file_processing fp
           JOIN drive_files df ON df.id = fp.drive_file_id
           WHERE fp.processing_status = 'transcribing'
           ORDER BY fp.updated_at DESC LIMIT 1"""
    ).fetchone()

    conn.close()
    return {
        "total": total,
        "stage": stage,
        "stage_message": stage_message,
        # NOTE: dl_done counts *downloaded* files — not "synced to NotebookLM".
        # The pipeline truth is: downloaded -> processed -> mirror -> chunked -> uploaded.
        "dl_done": dl["done"] or 0,
        "downloading_file": downloading["name"] if downloading else None,
        "proc_done": proc["done"] or 0,
        "proc_failed": proc["failed"] or 0,
        "chunked": proc["chunked"] or 0,
        "mirror_total": mirror["total"] or 0,
        "mirror_uploaded": mirror["uploaded"] or 0,
        "mirror_file": mirror_file["name"] if mirror_file else None,
        "chunks_total": chunks["total"] or 0,
        "chunks_uploaded": chunks["uploaded"] or 0,
        "transcribing_file": tx["name"] if tx else None,
        "transcribing_pct": round((tx["processing_progress"] or 0) * 100) if tx else 0,
    }
