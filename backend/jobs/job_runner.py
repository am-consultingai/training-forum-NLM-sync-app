import asyncio
import hashlib
import json
import logging
import os
import queue
import re
import shutil
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from backend.config import settings
from backend.app_config import (
    get_downloads_dir, get_mirror_dir, get_chunks_dir,
    get_effective_source_folder_id, get_effective_output_folder_id,
    get_effective_extracted_text_folder_id,
    get_ignore_extensions, data_rel, data_abs,
)
from backend.database import get_connection
from backend.services.drive_sync import (
    GOOGLE_EXPORT_MAP,
    _run_with_timeout,
    detect_change,
    download_file,
    export_google_file,
    get_drive_service,
    list_all_files,
)
from backend.services.drive_upload import (
    upload_chunk, upload_text_file, ensure_drive_folder_path,
    download_drive_text, delete_drive_file,
)
from backend.services.extractor import (
    TRANSCRIBE_EXTS,
    VIDEO_EXTS,
    clean_text,
    extract_audio_from_video,
    extract_text,
    get_processing_type,
)
from backend.services.chunker import build_chunks, content_hash, _safe_group_name

log = logging.getLogger(__name__)

_event_queues: list[asyncio.Queue] = []
_active_run_id: Optional[int] = None


def get_active_run_id() -> Optional[int]:
    return _active_run_id


def subscribe_events() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _event_queues.append(q)
    return q


def unsubscribe_events(q: asyncio.Queue):
    try:
        _event_queues.remove(q)
    except ValueError:
        pass


# ── Background progress-event persistence ─────────────────────────────────────
# _emit() runs on the sync thread, which processes thousands of files per run and
# emits a file_status event for each. Writing those rows synchronously stalls the
# sync whenever the DB is busy (under lock contention a single INSERT can block
# for seconds), which on a fresh-DB Windows restore made the run crawl ~2s/file.
# So _emit pushes to the live SSE stream inline (instant, never gated on the DB)
# and hands the row to this single background writer, which batches inserts on one
# connection. If the DB is contended the rows queue or drop — the progress_events
# table is only a replay buffer for UIs that connect mid-run, and the live SSE
# push already delivered the event — but the SYNC THREAD never waits on it.
_pe_queue: "queue.Queue" = queue.Queue(maxsize=20000)
_pe_writer_started = False
_pe_lock = threading.Lock()
_pe_dropped = 0
_pe_last_drop_log = 0.0


def _progress_writer_loop():
    conn = None
    global _pe_dropped, _pe_last_drop_log
    while True:
        first = _pe_queue.get()
        batch = [first] if first is not None else []
        # Opportunistically drain whatever else is queued so a burst of per-file
        # events commits as ONE transaction — far fewer lock acquisitions.
        for _ in range(499):
            try:
                row = _pe_queue.get_nowait()
            except queue.Empty:
                break
            if row is not None:
                batch.append(row)
        if not batch:
            continue
        try:
            if conn is None:
                conn = get_connection()
            conn.executemany(
                "INSERT INTO progress_events (run_id, event_type, payload) VALUES (?,?,?)",
                batch,
            )
            conn.commit()
        except Exception:  # noqa: BLE001
            # Telemetry is droppable; the writer must NEVER die (a dead writer
            # means no progress rows for the rest of the process). Catch everything
            # — "database is locked" (OperationalError) or any other error — reset
            # the connection, drop this batch, and log a throttled summary instead
            # of one line per event.
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            conn = None
            _pe_dropped += len(batch)
            now = time.monotonic()
            if now - _pe_last_drop_log > 30:
                log.warning("Dropped %d progress event(s) — DB busy (live SSE unaffected)", _pe_dropped)
                _pe_last_drop_log = now
            time.sleep(0.1)


def _ensure_progress_writer():
    global _pe_writer_started
    with _pe_lock:
        if not _pe_writer_started:
            threading.Thread(target=_progress_writer_loop, name="progress-writer", daemon=True).start()
            _pe_writer_started = True


def _emit(loop: asyncio.AbstractEventLoop, run_id: int, event_type: str, payload: dict):
    payload["run_id"] = run_id
    payload_str = json.dumps(payload, ensure_ascii=False)

    # Deliver to live SSE subscribers FIRST and inline — non-blocking, never gated
    # on the DB, so the UI keeps updating regardless of DB contention.
    msg = {"type": event_type, **payload}
    for q in list(_event_queues):
        loop.call_soon_threadsafe(q.put_nowait, msg)

    # Hand persistence to the background writer; never write on the sync thread.
    _ensure_progress_writer()
    try:
        _pe_queue.put_nowait((run_id, event_type, payload_str))
    except queue.Full:
        pass  # telemetry backlog full — drop; the live push already delivered it


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_rel_path(drive_path: str) -> str:
    """Relative path of a source file's extracted text within the mirror folder:
    the source path with a trailing '.txt' (forward-slash separated).

    Note: a Drive file name may itself contain '/'. We deliberately treat such a
    slash as a path separator (consistent with how source files are downloaded and
    with how `list_all_files` builds drive_path), so the mirror layout round-trips
    identically on every machine."""
    return drive_path.replace("\\", "/") + ".txt"


# Characters illegal in Windows (Win32/NTFS) file names. '/' and '\' are path
# separators, handled by splitting into components first. We sanitize on EVERY
# platform so the on-disk layout — and the relative paths stored in the DB — are
# identical everywhere and a data folder stays portable across OSes. A Drive name
# may legally contain '"', ':', '?', '*', etc. (fine on Linux, where local dev
# runs), but those make an unwritable path on Windows: open() raises
# [Errno 22] Invalid argument. Unicode (e.g. Hebrew) is preserved — only the
# forbidden ASCII set is replaced.
_WIN_ILLEGAL_RE = re.compile(r'[<>:"|?*\x00-\x1f]')
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}


def _safe_component(name: str) -> str:
    """One path segment made safe for the local filesystem (Windows-strict)."""
    name = _WIN_ILLEGAL_RE.sub("_", name).rstrip(" .")  # trailing space/dot illegal on Windows
    if not name:
        return "_"
    if name.split(".", 1)[0].upper() in _WIN_RESERVED:
        name = "_" + name  # avoid reserved device names (CON, NUL, COM1, …)
    return name


def _safe_local_components(rel_path: str) -> list:
    """Split a forward-slash drive/rel path into filesystem-safe components.
    Embedded name-slashes are treated as separators (consistent with how the
    mirror layout and source downloads are built)."""
    return [_safe_component(p) for p in rel_path.replace("\\", "/").split("/") if p]


def _extracted_local_path(extracted_dir: str, drive_path: str) -> str:
    """Local on-disk path for a source file's extracted text, mirroring the source
    tree. Derived from the rel path so name-slashes nest consistently, with each
    component sanitized for the local filesystem."""
    rel = _extract_rel_path(drive_path)
    return os.path.join(extracted_dir, *_safe_local_components(rel))


def _group_of(drive_path: str) -> str:
    """Top-level folder of a source file — the chunk group it belongs to."""
    parts = drive_path.replace("\\", "/").split("/")
    return parts[0] if len(parts) > 1 else "Root"


_CHUNK_GROUP_RE = re.compile(r"^(.*)_Part\d+\.txt$")


def _chunk_safe_group(filename: str) -> Optional[str]:
    """The safe group name encoded in a chunk filename like 'HR_General_Part3.txt'."""
    m = _CHUNK_GROUP_RE.match(filename)
    return m.group(1) if m else None


def _mirror_entry_valid(entry: dict, drive_item: dict) -> bool:
    """Is a mirror .txt still a valid extract of the CURRENT source version?

    Compares the provenance stamped in the mirror file's appProperties against the
    live source metadata: md5 for binary files, modifiedTime for Google-native
    files (which have no md5). Without provenance we cannot trust it → invalid.
    """
    props = entry.get("appProperties") or {}
    src_md5 = drive_item.get("md5Checksum")
    if src_md5:
        return props.get("source_md5") == src_md5
    src_modified = drive_item.get("modifiedTime")
    if src_modified:
        return props.get("source_modified") == src_modified
    return False


def _update_run(conn: sqlite3.Connection, run_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE sync_runs SET {sets} WHERE id = ?", (*kwargs.values(), run_id))
    conn.commit()


def run_sync(triggered_by: str = "manual", main_loop: asyncio.AbstractEventLoop = None):
    """Full pipeline. Runs in a thread pool executor."""
    global _active_run_id
    loop = main_loop or asyncio.new_event_loop()

    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO sync_runs (triggered_by, status) VALUES (?,?) RETURNING id",
        (triggered_by, "running"),
    )
    run_id = cur.fetchone()[0]
    conn.commit()
    _active_run_id = run_id

    def emit(event_type: str, payload: dict):
        _emit(loop, run_id, event_type, payload)

    def _listing_progress(kind: str):
        """Throttled progress callback for a long Drive listing — emits every ~200
        items so the Discover phase visibly ticks up instead of looking frozen."""
        state = {"last": 0}
        def cb(n: int):
            if n - state["last"] >= 200:
                state["last"] = n
                emit("stage_change", {"stage": "discover", "message": f"Listing {kind}… {n} found"})
        return cb

    try:
        downloads_dir = get_downloads_dir()
        extracted_dir = get_mirror_dir()
        extracted_folder_id = get_effective_extracted_text_folder_id()
        ignore_exts = set(get_ignore_extensions())
        emit("stage_change", {"stage": "connecting", "message": "Connecting to Google Drive"})

        service = get_drive_service(settings.google_credentials_path, settings.google_token_path)

        # Per-thread Drive clients for parallel downloads. The googleapiclient
        # `service` wraps a single non-thread-safe HTTP transport, so each worker
        # thread builds its own (cheap: static discovery, ~4 ms each). The main
        # client above just refreshed the token, so workers won't race on token.json.
        _dl_tls = threading.local()

        def _dl_service():
            s = getattr(_dl_tls, "svc", None)
            if s is None:
                s = get_drive_service(settings.google_credentials_path, settings.google_token_path)
                _dl_tls.svc = s
            return s

        def _download_many(jobs, label, stage="hydrate", max_workers=8):
            """jobs: list of (key, file_id, dest_abs). Downloads concurrently (skips
            files already present locally). Returns (key, dest_abs, content_hash, error)
            tuples. Network round-trips run in parallel; callers do DB writes serially."""
            results = []
            if not jobs:
                return results
            total = len(jobs)
            n = {"v": 0}

            def _task(job):
                key, fid, dest = job
                try:
                    if not os.path.exists(dest):
                        download_drive_text(_dl_service(), fid, dest)
                    return (key, dest, content_hash(dest), None)
                except Exception as e:
                    return (key, dest, None, str(e))

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                for r in ex.map(_task, jobs):
                    results.append(r)
                    n["v"] += 1
                    if n["v"] % 50 == 0 or n["v"] == total:
                        emit("stage_change", {"stage": stage, "message": f"{label}… {n['v']}/{total}"})
            return results

        # ── Phase 1: Discover ──
        emit("stage_change", {"stage": "discover", "message": "Listing source files…"})
        for attempt in range(3):
            try:
                drive_items = list_all_files(service, get_effective_source_folder_id(),
                                             progress_cb=_listing_progress("source files"),
                                             with_app_properties=False,
                                             service_factory=_dl_service)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                emit("stage_change", {"stage": "discover", "message": f"Retrying listing (attempt {attempt+2}/3): {e}"})
                time.sleep(5 * (attempt + 1))
        now = _now()

        existing_ids = {
            row["id"]: dict(row)
            for row in conn.execute("SELECT * FROM drive_files").fetchall()
        }

        # Upsert ONLY new/changed rows (skip the write for unchanged files/folders
        # — avoids ~1.4k redundant UPDATEs per sync). Track changed source files so
        # downstream phases can be gated on "did anything actually change".
        FOLDER_MIME = "application/vnd.google-apps.folder"
        file_count = sum(1 for it in drive_items if it["mimeType"] != FOLDER_MIME)
        changed_source_ids: set[str] = set()
        changed_groups: set[str] = set()
        for item in drive_items:
            is_folder = item["mimeType"] == FOLDER_MIME
            existing = existing_ids.get(item["id"])
            parent = item.get("parents", [None])[0]
            if existing is not None and (
                existing["name"] == item["name"]
                and existing["drive_path"] == item["drive_path"]
                and existing["parent_id"] == parent
                and existing["md5_checksum"] == item.get("md5Checksum")
                and existing["modified_time"] == item.get("modifiedTime")
            ):
                continue  # unchanged — skip the DB write entirely
            conn.execute(
                """INSERT INTO drive_files (id, name, mime_type, drive_path, parent_id,
                   size_bytes, md5_checksum, modified_time, is_folder, last_seen_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name, mime_type=excluded.mime_type,
                     drive_path=excluded.drive_path, parent_id=excluded.parent_id,
                     size_bytes=excluded.size_bytes, md5_checksum=excluded.md5_checksum,
                     modified_time=excluded.modified_time, last_seen_at=excluded.last_seen_at""",
                (
                    item["id"], item["name"], item["mimeType"], item["drive_path"], parent,
                    item.get("size"), item.get("md5Checksum"), item.get("modifiedTime"),
                    1 if is_folder else 0, now,
                ),
            )
            if not is_folder:
                conn.execute(
                    "INSERT OR IGNORE INTO file_processing (drive_file_id) VALUES (?)",
                    (item["id"],),
                )
                changed_source_ids.add(item["id"])
                changed_groups.add(_safe_group_name(_group_of(item["drive_path"])))
                # If the file moved between groups, the OLD group's chunk must rebuild too.
                if existing is not None and existing["drive_path"] != item["drive_path"]:
                    changed_groups.add(_safe_group_name(_group_of(existing["drive_path"])))

        conn.commit()
        _update_run(conn, run_id, files_discovered=file_count)
        emit("stage_change", {"stage": "discover", "files_discovered": file_count,
                              "message": f"{len(changed_source_ids)} new/changed of {file_count}"})

        # ── Deletion detection (cheap) + early-exit when nothing changed ──
        current_ids = {it["id"] for it in drive_items}
        deleted_ids = [oid for oid, old in existing_ids.items()
                       if not old["is_folder"] and oid not in current_ids]

        def _count(sql):
            return conn.execute(sql).fetchone()[0]
        # 'failed' is terminal here — those files only retry on a source change
        # (caught by changed_source_ids) or an explicit Reset, not every sync.
        pending_proc = _count("SELECT COUNT(*) FROM file_processing WHERE processing_status NOT IN ('done','skipped','failed')")
        unsynced_extract = _count(
            "SELECT COUNT(*) FROM file_processing WHERE processing_status='done' AND processed_path IS NOT NULL "
            "AND (extracted_drive_file_id IS NULL OR extracted_uploaded_hash IS NULL OR extracted_uploaded_hash <> content_hash)")
        pending_chunking = _count("SELECT COUNT(*) FROM file_processing WHERE processing_status='done' AND chunking_status='pending'")
        pending_upload = _count("SELECT COUNT(*) FROM chunks WHERE upload_status='pending'")

        if (not changed_source_ids and not deleted_ids and pending_proc == 0
                and unsynced_extract == 0 and pending_chunking == 0 and pending_upload == 0):
            # #4 Early-exit: nothing new/changed/deleted and no outstanding work.
            downloaded = _count("SELECT COUNT(*) FROM file_processing WHERE download_status='done'")
            _update_run(conn, run_id, files_downloaded=downloaded, files_processed=0,
                        files_failed=0, chunks_uploaded=0, status="done", finished_at=_now())
            emit("run_complete", {"status": "done", "files_processed": 0,
                                  "chunks_uploaded": 0, "message": "Up to date — nothing changed"})
            return

        # ── List the extracted-text mirror — ONLY when actually needed ──
        # It's read for: cache-hit reuse of new/changed/pending files, hydrating
        # done-but-not-yet-mirrored files, and orphan cleanup after deletions. In
        # steady state (nothing changed, DB fully in sync) the listing is skipped,
        # saving a full ~1.4k-file Drive walk.
        done_no_extract = _count(
            "SELECT COUNT(*) FROM file_processing WHERE processing_status='done' AND extracted_drive_file_id IS NULL")
        need_mirror = bool(changed_source_ids) or pending_proc > 0 or done_no_extract > 0 or bool(deleted_ids)
        # rel_path ('<source path>.txt') -> {id, appProperties, modifiedTime}
        mirror_index: dict[str, dict] = {}
        if extracted_folder_id and need_mirror:
            emit("stage_change", {"stage": "discover", "message": "Listing extracted-text mirror…"})
            try:
                for m in list_all_files(service, extracted_folder_id,
                                        progress_cb=_listing_progress("extracted-text mirror"),
                                        service_factory=_dl_service):
                    if m["mimeType"] != "application/vnd.google-apps.folder":
                        mirror_index[m["drive_path"].replace("\\", "/")] = m
                emit("stage_change", {"stage": "discover",
                                      "message": f"Found {len(mirror_index)} cached extracts on Drive"})
            except Exception as e:
                emit("stage_change", {"stage": "discover",
                                      "message": f"Could not list extracted-text folder: {e}"})

        # ── Hydrate local state from Drive ──
        # The Drive mirror + chunks folders are the source of truth for derived
        # state; the local DB is a cache. Seed it from Drive so a fresh/relocated
        # machine reuses all prior work (no re-download, no re-transcription, no
        # duplicate chunks). Mirror files whose source is gone are recorded as
        # pending orphans for the user to review — never auto-deleted.
        dirty_groups: set[str] = set()
        src_by_path = {
            it["drive_path"].replace("\\", "/"): it
            for it in drive_items
            if it["mimeType"] != "application/vnd.google-apps.folder"
        }

        if extracted_folder_id and mirror_index:
            emit("stage_change", {"stage": "hydrate", "message": "Restoring extracted text from Drive…"})
            # #8: load processing rows once instead of one SELECT per mirror entry.
            proc_by_id = {
                r["drive_file_id"]: r for r in conn.execute(
                    "SELECT drive_file_id, processing_status, processed_path, extracted_drive_file_id FROM file_processing"
                ).fetchall()
            }
            seeded = 0
            jobs = []                # (source_fid, mirror_drive_id, expected_abs)
            mid_by_fid: dict = {}
            for rel_path, m in list(mirror_index.items()):
                if not rel_path.endswith(".txt"):
                    continue
                source_path = rel_path[:-4]
                src = src_by_path.get(source_path)
                if src is None:
                    # No source at THIS PATH — do NOT delete. A path discrepancy must
                    # never destroy a valid extract (this is exactly what wrongly wiped
                    # ~681 extracts). True orphans (source genuinely gone) are detected
                    # by stable source_id below and queued for the user's review.
                    continue
                if not _mirror_entry_valid(m, src):
                    continue  # source changed since extract → let it reprocess below
                fid = src["id"]
                expected = _extracted_local_path(extracted_dir, source_path)
                existing = proc_by_id.get(fid)
                if (existing and existing["processing_status"] == "done"
                        and existing["extracted_drive_file_id"] == m["id"]
                        and existing["processed_path"] == data_rel(expected)
                        and os.path.exists(expected)):
                    continue  # already seeded and present locally — fast path
                jobs.append((fid, m["id"], expected))
                mid_by_fid[fid] = m["id"]

            # Download all needed extracts CONCURRENTLY (the network round-trips run
            # in parallel); then write the seed rows serially (single SQLite writer).
            # Commit in batches rather than holding one write transaction open across
            # all ~1.3k rows: a long-held writer keeps the UI's polling reads waiting
            # and starves the progress-event writer, so seeding could crawl. Frequent
            # commits release the lock between batches and surface progress sooner.
            for (fid, expected, h, err) in _download_many(jobs, "Restoring extracted text"):
                if err:
                    emit("stage_change", {"stage": "hydrate", "message": f"Hydrate failed: {err}"})
                    continue
                mid = mid_by_fid[fid]
                conn.execute("INSERT OR IGNORE INTO file_processing (drive_file_id) VALUES (?)", (fid,))
                conn.execute(
                    """UPDATE file_processing SET
                         download_status='skipped',
                         processing_status='done', processed_path=?, processed_at=?,
                         content_hash=?, processing_progress=1.0, chunking_status='pending',
                         extracted_drive_file_id=?, extracted_uploaded_hash=?,
                         processing_error=NULL, updated_at=?
                       WHERE drive_file_id=?""",
                    (data_rel(expected), _now(), h, mid, h, _now(), fid),
                )
                seeded += 1
                if seeded % 100 == 0:
                    conn.commit()
            conn.commit()
            emit("stage_change", {"stage": "hydrate",
                                  "message": f"Restored {seeded} extract(s)"})

        # ── Detect orphan extracts (source genuinely gone) by STABLE source_id ──
        # Never by path: a path discrepancy must not flag a live file. Nothing is
        # deleted here — orphans are recorded for explicit user review/approval
        # (POST /api/orphans/delete trashes them, recoverably). Only run when we have
        # a real mirror listing, so a transient listing failure can't clear the list.
        if extracted_folder_id and mirror_index:
            orphan_rows = []
            for rel_path, m in mirror_index.items():
                if not rel_path.endswith(".txt"):
                    continue
                sid = (m.get("appProperties") or {}).get("source_id")
                if sid and sid not in current_ids:
                    orphan_rows.append((m["id"], os.path.basename(rel_path), rel_path, sid, _now()))
            conn.execute("DELETE FROM pending_orphans")
            if orphan_rows:
                conn.executemany(
                    "INSERT OR REPLACE INTO pending_orphans "
                    "(mirror_drive_id, name, drive_path, source_id, detected_at) VALUES (?,?,?,?,?)",
                    orphan_rows,
                )
                emit("stage_change", {"stage": "hydrate",
                      "message": f"Found {len(orphan_rows)} extract(s) with no matching source — "
                                 f"review in the app before deletion (nothing deleted)"})
            conn.commit()

        # ── Hydrate chunks from Drive — only when the local chunk set is incomplete ──
        # On a fresh/relocated machine this reuses existing Drive chunk IDs (no
        # duplicates). In steady state (all chunks present locally with their Drive
        # IDs) the chunks-folder listing + checks are skipped.
        ch_total = _count("SELECT COUNT(*) FROM chunks")
        need_chunk_hydration = ch_total == 0
        if not need_chunk_hydration:
            for r in conn.execute("SELECT chunk_path, output_drive_file_id FROM chunks").fetchall():
                if not r["output_drive_file_id"] or not (r["chunk_path"] and os.path.exists(data_abs(r["chunk_path"]))):
                    need_chunk_hydration = True
                    break
        hydrate_output_id = get_effective_output_folder_id()
        if hydrate_output_id and need_chunk_hydration:
            try:
                jobs = []          # (fname, chunk_drive_id, local_abs)
                id_by_name: dict = {}
                for ch in list_all_files(service, hydrate_output_id):
                    if ch["mimeType"] == "application/vnd.google-apps.folder":
                        continue
                    fname = ch["name"]
                    local = os.path.join(get_chunks_dir(), fname)
                    id_by_name[fname] = ch["id"]
                    row = conn.execute(
                        "SELECT chunk_path, output_drive_file_id FROM chunks WHERE chunk_filename=?",
                        (fname,),
                    ).fetchone()
                    if (row and row["output_drive_file_id"] == ch["id"]
                            and row["chunk_path"] == data_rel(local) and os.path.exists(local)):
                        continue
                    jobs.append((fname, ch["id"], local))
                hydrated_chunks = 0
                for (fname, local, h, err) in _download_many(jobs, "Restoring chunks"):
                    if err:
                        continue
                    conn.execute(
                        """INSERT INTO chunks (chunk_filename, chunk_path, content_hash, upload_status, output_drive_file_id, uploaded_at)
                           VALUES (?,?,?,'done',?,?)
                           ON CONFLICT(chunk_filename) DO UPDATE SET
                             chunk_path=excluded.chunk_path, content_hash=excluded.content_hash,
                             upload_status='done', output_drive_file_id=excluded.output_drive_file_id,
                             updated_at=excluded.uploaded_at""",
                        (fname, data_rel(local), h, id_by_name[fname], _now()),
                    )
                    hydrated_chunks += 1
                conn.commit()
                if hydrated_chunks:
                    emit("stage_change", {"stage": "hydrate", "message": f"Restored {hydrated_chunks} chunk file(s) from Drive"})
            except Exception as e:
                emit("stage_change", {"stage": "hydrate", "message": f"Could not restore chunks: {e}"})

        # ── Reconcile deletions ──
        # Any non-folder file previously in the DB but absent from the current
        # source listing was deleted at the source. Remove its extracted text
        # (Drive mirror + local) and DB rows; mark its group for chunk rebuild.
        deleted_count = 0
        for old_id in deleted_ids:
            old = existing_ids[old_id]
            old_path = old["drive_path"]
            dirty_groups.add(_safe_group_name(_group_of(old_path)))
            # Source is gone: drop its local DB rows and rebuild its group's chunk.
            # Its mirror .txt is NOT deleted here — it's surfaced as a pending orphan
            # (detected by source_id above) for the user to review and approve.
            conn.execute("DELETE FROM file_processing WHERE drive_file_id=?", (old_id,))
            conn.execute("DELETE FROM drive_files WHERE id=?", (old_id,))
            deleted_count += 1
        if deleted_count:
            conn.commit()
            emit("stage_change", {"stage": "discover",
                                  "message": f"Removed {deleted_count} deleted source file(s)"})

        # ── Phases 2 + 3: Download & Process in parallel ──
        # Main thread downloads files and feeds proc_queue.
        # Process thread drains proc_queue and extracts/transcribes.
        # They overlap: GPU is busy transcribing while network fetches the next file.
        emit("stage_change", {"stage": "download", "message": "Downloading and processing files in parallel"})

        conn.execute("UPDATE file_processing SET download_status='pending' WHERE download_status='downloading'")
        conn.commit()

        # Unbounded queue: the download loop (network-bound) must never block on the
        # transcription worker (GPU-bound, minutes per file). Items are tiny metadata
        # dicts — the downloaded files live on disk — so memory is a non-issue.
        proc_queue: queue.Queue = queue.Queue()
        process_results = {"processed": 0, "failed": 0}

        def _process_worker():
            p_conn = get_connection()
            transcriber = None
            try:
                while True:
                    try:
                        finfo = proc_queue.get(timeout=600)
                    except queue.Empty:
                        break
                    if finfo is None:
                        break

                    file_id = finfo["id"]
                    src_path = finfo["path"]
                    proc_type = finfo["proc_type"]
                    drive_path = finfo["drive_path"]
                    # Mirror name keeps the full source name + '.txt'
                    # (e.g. learning_hr.mp4 -> learning_hr.mp4.txt)
                    out_path = _extracted_local_path(extracted_dir, drive_path)
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)

                    p_conn.execute(
                        "UPDATE file_processing SET processing_status='extracting', processing_type=?, processing_started_at=?, updated_at=? WHERE drive_file_id=?",
                        (proc_type, _now(), _now(), file_id),
                    )
                    p_conn.commit()
                    emit("file_status", {"file_id": file_id, "name": finfo["name"],
                                         "stage": "processing", "status": "extracting"})

                    try:
                        if proc_type == "google_export":
                            shutil.copy2(src_path, out_path)

                        elif proc_type == "extract":
                            text, ok = extract_text(src_path)
                            if ok:
                                with open(out_path, "w", encoding="utf-8") as f:
                                    f.write(clean_text(text))
                            else:
                                raise ValueError(f"Extraction failed: {text}")

                        elif proc_type == "transcribe":
                            # Load model lazily on first transcription file
                            if transcriber is None:
                                emit("stage_change", {"stage": "process", "message": "Loading transcription model"})
                                try:
                                    from backend.services.transcriber import Transcriber
                                    transcriber = Transcriber(
                                        settings.whisper_model_path,
                                        device=settings.whisper_device or "auto",
                                        compute_type=settings.whisper_compute_type or "auto",
                                    )
                                    if getattr(transcriber, "fallback_reason", None):
                                        emit("stage_change", {"stage": "process",
                                              "message": f"GPU transcription unavailable ({transcriber.fallback_reason}) — falling back to CPU"})
                                    emit("stage_change", {"stage": "process", "message": f"Transcription model loaded — device: {transcriber.device} ({transcriber.compute_type})"})
                                except Exception as te:
                                    raise ValueError(f"Transcriber load failed: {te}")

                            ext = os.path.splitext(src_path)[1].lower()
                            audio_path = src_path
                            tmp_audio = None
                            if ext in VIDEO_EXTS:
                                fd, tmp_audio = tempfile.mkstemp(suffix=".mp3", dir=tempfile.gettempdir())
                                os.close(fd)
                                try:
                                    extract_audio_from_video(src_path, tmp_audio, settings.ffmpeg_path)
                                except Exception:
                                    os.remove(tmp_audio)
                                    raise  # carries ffmpeg's stderr → recorded as processing_error
                                audio_path = tmp_audio

                            _fid, _fname = file_id, finfo["name"]

                            def progress_cb(p, _fid=_fid, _fname=_fname):
                                p_conn.execute(
                                    "UPDATE file_processing SET processing_progress=?, processing_status='transcribing', updated_at=? WHERE drive_file_id=?",
                                    (p, _now(), _fid),
                                )
                                p_conn.commit()
                                emit("file_status", {"file_id": _fid, "name": _fname,
                                                      "stage": "processing", "status": "transcribing",
                                                      "progress": p})

                            try:
                                transcriber.transcribe_file(audio_path, out_path, progress_callback=progress_cb)
                            finally:
                                if tmp_audio and os.path.exists(tmp_audio):
                                    os.remove(tmp_audio)

                        h = content_hash(out_path)
                        p_conn.execute(
                            "UPDATE file_processing SET processing_status='done', processed_path=?, processed_at=?, content_hash=?, processing_progress=1.0, chunking_status='pending', updated_at=? WHERE drive_file_id=?",
                            (data_rel(out_path), _now(), h, _now(), file_id),
                        )
                        p_conn.commit()
                        process_results["processed"] += 1
                        emit("file_status", {"file_id": file_id, "name": finfo["name"],
                                              "stage": "processing", "status": "done"})

                    except Exception as e:
                        p_conn.execute(
                            "UPDATE file_processing SET processing_status='failed', processing_error=?, updated_at=? WHERE drive_file_id=?",
                            (str(e), _now(), file_id),
                        )
                        p_conn.commit()
                        process_results["failed"] += 1
                        emit("file_status", {"file_id": file_id, "name": finfo["name"],
                                              "stage": "processing", "status": "failed", "error": str(e)})
            finally:
                p_conn.close()

        process_thread = threading.Thread(target=_process_worker, daemon=True, name="process-worker")
        process_thread.start()

        # ── Classify each file (fast; no network) into download jobs ──
        # cache_jobs: mirror has a valid extract → just fetch the .txt (no processing)
        # src_jobs:   needs the source file downloaded, then extracted/transcribed
        cache_jobs = []   # (item, expected_abs, mirror_id, proc_type)
        src_jobs = []     # (item, dest_abs, kind, export_mime, proc_type)
        for item in drive_items:
            if item["mimeType"] == "application/vnd.google-apps.folder":
                continue
            existing = existing_ids.get(item["id"])
            change = detect_change(existing, item)
            proc_type = get_processing_type(item["mimeType"], item["name"], ignore_exts)
            safe_path = os.path.join(*_safe_local_components(item["drive_path"]))

            if change == "unchanged":
                proc = conn.execute(
                    "SELECT download_status, processing_status, downloaded_path FROM file_processing WHERE drive_file_id=?",
                    (item["id"],),
                ).fetchone()
                if proc:
                    # Unchanged + already terminal → don't redo it (failed retries only
                    # on a source change or explicit Reset).
                    if proc["processing_status"] in ("done", "failed", "skipped"):
                        emit("file_status", {"file_id": item["id"], "name": item["name"],
                                             "stage": "download", "status": "skipped"})
                        continue
                    if proc["download_status"] == "done" and proc["downloaded_path"]:
                        proc_queue.put({"id": item["id"], "name": item["name"],
                                        "path": data_abs(proc["downloaded_path"]),
                                        "proc_type": proc_type, "drive_path": item["drive_path"]})
                        emit("file_status", {"file_id": item["id"], "name": item["name"],
                                             "stage": "download", "status": "done"})
                        continue

            if proc_type != "skip":
                entry = mirror_index.get(_extract_rel_path(item["drive_path"]))
                if entry and _mirror_entry_valid(entry, item):
                    cache_jobs.append((item, _extracted_local_path(extracted_dir, item["drive_path"]),
                                       entry["id"], proc_type))
                    continue

            if item["mimeType"] in GOOGLE_EXPORT_MAP:
                export_mime, ext = GOOGLE_EXPORT_MAP[item["mimeType"]]
                dest = os.path.join(downloads_dir, os.path.splitext(safe_path)[0] + ext)
                src_jobs.append((item, dest, "google_export", export_mime, "google_export"))
            elif proc_type != "skip":
                dest = os.path.join(downloads_dir, safe_path)
                src_jobs.append((item, dest, "binary", None, proc_type))
            else:
                conn.execute(
                    "UPDATE file_processing SET download_status='skipped', processing_status='skipped', updated_at=? WHERE drive_file_id=?",
                    (_now(), item["id"]),
                )
        conn.commit()

        # ── Parallel cache-hit .txt downloads → seed 'done' (no processing) ──
        if cache_jobs:
            cmap = {it["id"]: (it, exp, mid, pt) for (it, exp, mid, pt) in cache_jobs}
            for (fid, exp, h, err) in _download_many(
                    [(it["id"], mid, exp) for (it, exp, mid, pt) in cache_jobs],
                    "Reusing cached extracts", stage="download"):
                it, _e, mid, pt = cmap[fid]
                if err:
                    emit("file_status", {"file_id": fid, "name": it["name"], "stage": "download",
                                         "status": "failed", "error": f"cache fetch: {err}"})
                    continue
                conn.execute(
                    """UPDATE file_processing SET download_status='skipped', processing_status='done',
                         processing_type=?, processed_path=?, processed_at=?, content_hash=?,
                         processing_progress=1.0, chunking_status='pending', extracted_drive_file_id=?,
                         extracted_uploaded_hash=?, processing_error=NULL, updated_at=? WHERE drive_file_id=?""",
                    (pt, data_rel(exp), _now(), h, mid, h, _now(), fid),
                )
            conn.commit()

        # ── Parallel SOURCE downloads → enqueue for processing as each finishes ──
        # Downloads run concurrently (per-thread Drive clients); the single process
        # worker drains the queue and extracts/transcribes, overlapping with downloads.
        if src_jobs:
            for (it, dest, kind, em, pt) in src_jobs:
                conn.execute("UPDATE file_processing SET download_status='downloading', updated_at=? WHERE drive_file_id=?",
                             (_now(), it["id"]))
            conn.commit()
            emit("file_status", {"stage": "download", "status": "downloading",
                                 "name": f"{len(src_jobs)} source file(s)"})

            def _src_task(job):
                it, dest, kind, em, pt = job
                err = None
                for attempt in range(3):
                    try:
                        if kind == "google_export":
                            export_google_file(_dl_service(), it["id"], em, dest)
                        else:
                            download_file(_dl_service(), it["id"], dest)
                        return (job, None)
                    except Exception as e:
                        err = e
                        time.sleep(2 * (attempt + 1))
                return (job, str(err))

            with ThreadPoolExecutor(max_workers=8) as ex:
                for fut in as_completed([ex.submit(_src_task, j) for j in src_jobs]):
                    job, err = fut.result()
                    it, dest, kind, em, pt = job
                    if err:
                        conn.execute("UPDATE file_processing SET download_status='failed', download_error=?, updated_at=? WHERE drive_file_id=?",
                                     (err, _now(), it["id"]))
                        conn.commit()
                        emit("file_status", {"file_id": it["id"], "name": it["name"],
                                             "stage": "download", "status": "failed", "error": err})
                    else:
                        conn.execute("UPDATE file_processing SET download_status='done', downloaded_path=?, downloaded_at=?, updated_at=? WHERE drive_file_id=?",
                                     (data_rel(dest), _now(), _now(), it["id"]))
                        conn.commit()
                        proc_queue.put({"id": it["id"], "name": it["name"], "path": dest,
                                        "proc_type": pt, "drive_path": it["drive_path"]})
                        emit("file_status", {"file_id": it["id"], "name": it["name"],
                                             "stage": "download", "status": "done"})

        # Signal end of downloads, then wait for the worker to fully drain the
        # queue. A fixed timeout is wrong here: the media backlog can take many
        # hours, and a premature return would run chunk+upload without the
        # stragglers AND stamp the run 'done' while the daemon worker keeps
        # going (its later-finished files would then never get chunked/uploaded
        # until the next sync). So wait until the worker exits, with stall
        # detection as the only escape hatch.
        proc_queue.put(None)
        _stall_limit = 3600   # seconds of zero processing progress => treat as stalled
        _seen = process_results["processed"] + process_results["failed"]
        _last_change = time.monotonic()
        while process_thread.is_alive():
            process_thread.join(timeout=60)
            _cur = process_results["processed"] + process_results["failed"]
            if _cur != _seen:
                _seen = _cur
                _last_change = time.monotonic()
                emit("stage_change", {"stage": "process",
                                      "message": f"Processing… {_cur} files done"})
            elif time.monotonic() - _last_change > _stall_limit:
                emit("stage_change", {"stage": "process",
                                      "message": "Processing stalled — proceeding with completed files"})
                break

        downloaded = conn.execute(
            "SELECT COUNT(*) FROM file_processing WHERE download_status='done'"
        ).fetchone()[0]
        _update_run(conn, run_id,
                    files_downloaded=downloaded,
                    files_processed=process_results["processed"],
                    files_failed=process_results["failed"])

        # ── Phase 3.5: Sync extracted text → Drive mirror ──
        # Upload every freshly-produced (or not-yet-mirrored) extract to the shared
        # mirror folder, stamping source provenance so other machines can reuse it.
        # This also migrates pre-existing local transcripts on first run.
        if extracted_folder_id:
            emit("stage_change", {"stage": "extract_sync",
                                  "message": "Uploading extracted text to Drive"})
            folder_cache: dict = {}
            # #5: filter to extracts that actually need (re)uploading at the SQL
            # level — no Python scan + stat() over the whole done-set every run.
            to_upload = conn.execute(
                """SELECT fp.drive_file_id, fp.processed_path, fp.content_hash,
                          fp.extracted_drive_file_id, fp.extracted_uploaded_hash,
                          df.drive_path, df.name, df.md5_checksum, df.modified_time
                   FROM file_processing fp
                   JOIN drive_files df ON df.id = fp.drive_file_id
                   WHERE fp.processing_status='done' AND fp.processed_path IS NOT NULL
                     AND (fp.extracted_drive_file_id IS NULL
                          OR fp.extracted_uploaded_hash IS NULL
                          OR fp.extracted_uploaded_hash <> fp.content_hash)"""
            ).fetchall()
            extract_uploaded = 0
            for row in to_upload:
                local_path = data_abs(row["processed_path"])
                if not local_path or not os.path.exists(local_path):
                    continue
                cur_hash = row["content_hash"] or content_hash(local_path)
                # Skip if already uploaded at this content hash
                if row["extracted_drive_file_id"] and row["extracted_uploaded_hash"] == cur_hash:
                    continue
                rel = _extract_rel_path(row["drive_path"])
                rel_dir = os.path.dirname(rel)
                # Last path segment only: a name-slash is treated as a separator,
                # so the Drive file name never contains '/' and round-trips on relist.
                name = os.path.basename(rel)
                existing_id = row["extracted_drive_file_id"]
                if not existing_id:
                    entry = mirror_index.get(rel)
                    existing_id = entry["id"] if entry else None
                app_props = {
                    "source_id": row["drive_file_id"],
                    "source_md5": row["md5_checksum"] or "",
                    "source_modified": row["modified_time"] or "",
                }
                try:
                    parent_id = ensure_drive_folder_path(service, extracted_folder_id, rel_dir, folder_cache)
                    new_id = upload_text_file(
                        service, local_path, parent_id, name=name,
                        existing_drive_id=existing_id, app_properties=app_props,
                        max_retries=settings.max_upload_retries,
                    )
                    conn.execute(
                        "UPDATE file_processing SET extracted_drive_file_id=?, extracted_uploaded_hash=?, updated_at=? WHERE drive_file_id=?",
                        (new_id, cur_hash, _now(), row["drive_file_id"]),
                    )
                    conn.commit()
                    extract_uploaded += 1
                    # Throttled per-file progress so the UI shows live movement
                    # without flooding the log with ~1.4k lines.
                    if extract_uploaded == 1 or extract_uploaded % 10 == 0:
                        emit("stage_change", {"stage": "extract_sync",
                                              "message": f"Uploading extracted text… {extract_uploaded} done — {name}"})
                except Exception as e:
                    emit("stage_change", {"stage": "extract_sync",
                                          "message": f"Failed to upload {name}: {e}"})
            emit("stage_change", {"stage": "extract_sync",
                                  "message": f"Uploaded {extract_uploaded} extract(s) to Drive"})

        # ── Phase 4: Chunk ──
        emit("stage_change", {"stage": "chunk", "message": "Building text chunks"})

        # #3: only rebuild groups whose content actually changed. A file processed,
        # cache-hit, or hydrated this run leaves chunking_status='pending'; deleted
        # files mark their group dirty. Untouched groups keep their existing chunks —
        # we don't re-read all ~130 MB of extracts on every sync.
        pending_chunk_groups = {
            _safe_group_name(_group_of(r["drive_path"]))
            for r in conn.execute(
                "SELECT df.drive_path FROM file_processing fp JOIN drive_files df ON df.id=fp.drive_file_id "
                "WHERE fp.processing_status='done' AND fp.chunking_status='pending'").fetchall()
        }
        chunk_dirty = dirty_groups | pending_chunk_groups | changed_groups

        all_processed = conn.execute(
            """SELECT fp.processed_path, fp.content_hash, fp.drive_file_id, df.drive_path,
                      COALESCE(df.relevance, 'relevant') AS relevance
               FROM file_processing fp
               JOIN drive_files df ON df.id = fp.drive_file_id
               WHERE fp.processing_status = 'done' AND fp.processed_path IS NOT NULL"""
        ).fetchall()

        from backend.app_config import get_chunk_size_mb
        chunk_size_bytes = int(get_chunk_size_mb() * 1024 * 1024)

        chunk_files = []
        for row in all_processed:
            if row["relevance"] == "not_relevant":
                continue
            parts = row["drive_path"].replace("\\", "/").split("/")
            group = parts[0] if len(parts) > 1 else "Root"
            if _safe_group_name(group) not in chunk_dirty:
                continue  # group unchanged — keep its chunks as-is, skip rebuild
            abs_processed = data_abs(row["processed_path"])
            if not abs_processed or not os.path.exists(abs_processed):
                continue
            chunk_files.append({
                "name": os.path.basename(abs_processed),
                "path": abs_processed,
                "group": group,
                "drive_file_id": row["drive_file_id"],
            })

        # Groups rebuilt this run (safe names) and the chunk filenames produced.
        # Both feed the orphan GC below.
        built_safe_groups = {_safe_group_name(cf["group"]) for cf in chunk_files}
        produced_filenames: set[str] = set()

        if chunk_files:
            new_chunks = build_chunks(chunk_files, get_chunks_dir(), chunk_size_bytes=chunk_size_bytes)
            produced_filenames = {ch["filename"] for ch in new_chunks}
            for ch in new_chunks:
                existing_chunk = conn.execute(
                    "SELECT id, content_hash, output_drive_file_id FROM chunks WHERE chunk_filename=?",
                    (ch["filename"],),
                ).fetchone()
                if existing_chunk:
                    if existing_chunk["content_hash"] != ch["hash"]:
                        conn.execute(
                            "UPDATE chunks SET chunk_path=?, content_hash=?, upload_status='pending', updated_at=? WHERE chunk_filename=?",
                            (data_rel(ch["path"]), ch["hash"], _now(), ch["filename"]),
                        )
                else:
                    conn.execute(
                        "INSERT INTO chunks (chunk_filename, chunk_path, content_hash, upload_status) VALUES (?,?,?,'pending')",
                        (ch["filename"], data_rel(ch["path"]), ch["hash"]),
                    )

            # Mark EVERY done file in a rebuilt group as chunked — not just those
            # whose text landed in a chunk. A file can be 'done' yet contribute no
            # chunk content (empty/whitespace extract, or flagged not-relevant); if
            # we only advanced files that made it into a chunk, those would stay
            # chunking_status='pending' forever and permanently block the
            # nothing-changed early-exit. Once its group has been built, a file is
            # accounted for either way.
            for row in all_processed:
                if _safe_group_name(_group_of(row["drive_path"])) in chunk_dirty:
                    conn.execute(
                        "UPDATE file_processing SET chunking_status='done', updated_at=? WHERE drive_file_id=?",
                        (_now(), row["drive_file_id"]),
                    )
            conn.commit()

        # ── Garbage-collect obsolete chunks ──
        # For every group we rebuilt this run (or whose source was deleted), any
        # chunk row that the new build did NOT produce is now obsolete: delete its
        # Drive file (so NotebookLM stops indexing it), its local file, and its row.
        # Scoping to rebuilt/deleted groups protects chunks of groups that simply
        # had no processed files this run (e.g. a transient failure) from deletion.
        gc_scope = built_safe_groups | chunk_dirty
        if gc_scope:
            removed = 0
            for chunk in conn.execute(
                "SELECT id, chunk_filename, chunk_path, output_drive_file_id FROM chunks"
            ).fetchall():
                sg = _chunk_safe_group(chunk["chunk_filename"])
                if sg in gc_scope and chunk["chunk_filename"] not in produced_filenames:
                    if chunk["output_drive_file_id"]:
                        try:
                            delete_drive_file(service, chunk["output_drive_file_id"])
                        except Exception:
                            pass
                    local_chunk = data_abs(chunk["chunk_path"])
                    if local_chunk and os.path.exists(local_chunk):
                        try:
                            os.remove(local_chunk)
                        except Exception:
                            pass
                    conn.execute("DELETE FROM chunks WHERE id=?", (chunk["id"],))
                    removed += 1
            if removed:
                conn.commit()
                emit("stage_change", {"stage": "chunk",
                                      "message": f"Removed {removed} obsolete chunk(s)"})

        # ── Phase 5: Upload to output Drive ──
        emit("stage_change", {"stage": "upload", "message": "Uploading chunks to output Drive folder"})

        pending_chunks = conn.execute(
            "SELECT * FROM chunks WHERE upload_status='pending'"
        ).fetchall()

        uploaded_count = 0
        for chunk in pending_chunks:
            try:
                drive_file_id = upload_chunk(
                    service,
                    data_abs(chunk["chunk_path"]),
                    get_effective_output_folder_id(),
                    chunk["output_drive_file_id"],
                    max_retries=settings.max_upload_retries,
                )
                conn.execute(
                    "UPDATE chunks SET upload_status='done', output_drive_file_id=?, uploaded_at=?, updated_at=? WHERE id=?",
                    (drive_file_id, _now(), _now(), chunk["id"]),
                )
                conn.commit()
                uploaded_count += 1
                emit("stage_change", {"stage": "upload", "chunk": chunk["chunk_filename"],
                                       "status": "done", "chunks_uploaded": uploaded_count})
            except Exception as e:
                conn.execute(
                    "UPDATE chunks SET upload_status='failed', upload_error=?, updated_at=? WHERE id=?",
                    (str(e), _now(), chunk["id"]),
                )
                conn.commit()
                emit("stage_change", {"stage": "upload", "chunk": chunk["chunk_filename"],
                                       "status": "failed", "error": str(e)})

        _update_run(conn, run_id, chunks_uploaded=uploaded_count,
                    status="done", finished_at=_now())
        emit("run_complete", {
            "status": "done",
            "files_processed": process_results["processed"],
            "chunks_uploaded": uploaded_count,
        })

    except Exception as e:
        _update_run(conn, run_id, status="failed", finished_at=_now(), error_message=str(e))
        emit("run_complete", {"status": "failed", "error": str(e)})
        raise
    finally:
        _active_run_id = None
        for q in list(_event_queues):
            loop.call_soon_threadsafe(q.put_nowait, None)
        conn.close()
        if main_loop is None:
            loop.close()
