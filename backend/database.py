import logging
import sqlite3
import os
from backend.app_config import get_db_path, get_data_root, ensure_data_dirs

log = logging.getLogger(__name__)


def get_connection(busy_timeout_ms: int = 30000) -> sqlite3.Connection:
    # `timeout` is the C-level busy timeout; pair it with the PRAGMA below so both
    # the driver and the engine wait out transient locks instead of failing fast.
    # Callers that must never stall the caller thread on a contended DB (e.g. the
    # best-effort progress-event writer) pass a short busy_timeout_ms.
    conn = sqlite3.connect(get_db_path(), check_same_thread=False, timeout=busy_timeout_ms / 1000)
    conn.row_factory = sqlite3.Row
    # Wait out transient locks (DrvFS/Windows mounts can be slower than ext4).
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
    conn.execute("PRAGMA foreign_keys=ON")
    # WAL is the DB's persistent journal mode (established once in init_db); every
    # connection inherits it. Pair it with synchronous=NORMAL — in WAL this is
    # crash-safe (no corruption; at worst the last commit is lost on a power cut)
    # and skips the full fsync that synchronous=FULL does on EVERY commit. That
    # fsync is near-free on ext4 but very slow on Windows/NTFS (amplified by AV
    # scanning); leaving it on FULL makes the fresh-DB first-run hydrate (thousands
    # of writes) crawl and starves concurrent writers into "database is locked".
    # The DB is a rebuildable cache seeded from Drive, so NORMAL's durability
    # trade-off is acceptable even if WAL ever failed to engage.
    conn.execute("PRAGMA synchronous=NORMAL")
    # NOTE: journal mode is deliberately NOT set here. Running `PRAGMA
    # journal_mode=WAL` on each connection (incl. the UI's frequent read-poll
    # connections) needs a write lock just to set up, so it would fight the sync
    # writer for locks on every request — the opposite of what we want.
    return conn


def _set_journal_mode(conn: sqlite3.Connection) -> str:
    """Switch the DB to WAL (persists in the file header). WAL lets the UI's
    read-polling and the sync's writer run concurrently without blocking each
    other. PRAGMA journal_mode returns the resulting mode rather than raising, so
    if WAL didn't engage (a filesystem that can't back the -shm/-wal files), fall
    back to DELETE explicitly. Call once, at startup, while nothing else is using
    the DB — converting to WAL needs an exclusive moment."""
    try:
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal":
            conn.execute("PRAGMA journal_mode=DELETE")
        return mode
    except Exception as e:  # noqa: BLE001
        log.warning("Could not set journal_mode: %s", e)
        return "unknown"


def _migrate_transcripts_to_mirror():
    """The local extracted-text tree was previously `transcripts/`; it is now
    `mirror/`. Rename it once so existing extracts aren't re-downloaded from Drive.
    Tolerates an already-created empty `mirror/` (replaces it); never clobbers a
    non-empty `mirror/`."""
    root = get_data_root()
    old = os.path.join(root, "transcripts")
    new = os.path.join(root, "mirror")
    if not os.path.isdir(old):
        return
    if os.path.exists(new):
        try:
            if os.listdir(new):
                return  # mirror already has content — don't clobber
            os.rmdir(new)
        except Exception:
            return
    try:
        os.rename(old, new)
    except Exception:
        pass


def init_db():
    # Migrate before creating dirs, else an empty mirror/ would block the rename.
    _migrate_transcripts_to_mirror()
    ensure_data_dirs()
    conn = get_connection()
    # Establish WAL now, while this is the only open connection — it persists in the
    # DB header so every later connection inherits it. Logged so launcher.log shows
    # the effective mode (a stuck/locked sync usually means WAL didn't engage).
    mode = _set_journal_mode(conn)
    log.info("SQLite journal_mode=%s (db=%s)", mode, get_db_path())
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS drive_files (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            mime_type       TEXT NOT NULL,
            drive_path      TEXT NOT NULL,
            parent_id       TEXT,
            size_bytes      INTEGER,
            md5_checksum    TEXT,
            modified_time   TEXT,
            is_folder       INTEGER NOT NULL DEFAULT 0,
            last_seen_at    TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_drive_files_parent ON drive_files(parent_id);
        CREATE INDEX IF NOT EXISTS idx_drive_files_path ON drive_files(drive_path);

        CREATE TABLE IF NOT EXISTS file_processing (
            drive_file_id           TEXT PRIMARY KEY REFERENCES drive_files(id),
            download_status         TEXT NOT NULL DEFAULT 'pending',
            downloaded_path         TEXT,
            download_error          TEXT,
            downloaded_at           TEXT,
            processing_status       TEXT NOT NULL DEFAULT 'pending',
            processing_type         TEXT,
            processed_path          TEXT,
            processing_progress     REAL DEFAULT 0.0,
            processing_error        TEXT,
            processing_started_at   TEXT,
            processed_at            TEXT,
            chunking_status         TEXT NOT NULL DEFAULT 'pending',
            content_hash            TEXT,
            updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_filename          TEXT NOT NULL UNIQUE,
            chunk_path              TEXT NOT NULL,
            source_files            TEXT NOT NULL DEFAULT '[]',
            content_hash            TEXT,
            upload_status           TEXT NOT NULL DEFAULT 'pending',
            output_drive_file_id    TEXT,
            uploaded_at             TEXT,
            upload_error            TEXT,
            created_at              TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            triggered_by        TEXT NOT NULL DEFAULT 'scheduler',
            status              TEXT NOT NULL DEFAULT 'running',
            files_discovered    INTEGER DEFAULT 0,
            files_downloaded    INTEGER DEFAULT 0,
            files_processed     INTEGER DEFAULT 0,
            files_skipped       INTEGER DEFAULT 0,
            files_failed        INTEGER DEFAULT 0,
            chunks_uploaded     INTEGER DEFAULT 0,
            started_at          TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at         TEXT,
            error_message       TEXT
        );

        CREATE TABLE IF NOT EXISTS progress_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      INTEGER REFERENCES sync_runs(id),
            event_type  TEXT NOT NULL,
            payload     TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_progress_run ON progress_events(run_id, id);

        -- Mirror extracts whose source file no longer exists (detected by stable
        -- source_id). Recorded for explicit user review; NEVER auto-deleted.
        CREATE TABLE IF NOT EXISTS pending_orphans (
            mirror_drive_id  TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            drive_path       TEXT,
            source_id        TEXT,
            detected_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)

    conn.commit()

    # Migrations for columns added after initial schema
    migrations = [
        "ALTER TABLE drive_files ADD COLUMN relevance TEXT NOT NULL DEFAULT 'relevant'",
        # Mirror (extracted-text) Drive sync state, per processed file
        "ALTER TABLE file_processing ADD COLUMN extracted_drive_file_id TEXT",
        "ALTER TABLE file_processing ADD COLUMN extracted_uploaded_hash TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # column already exists

    # Relativize any legacy absolute / CWD-relative paths so the data folder is a
    # portable, self-contained bundle. Idempotent (only touches legacy-shaped rows).
    try:
        legacy = conn.execute(
            """SELECT fp.drive_file_id, df.drive_path FROM file_processing fp
               JOIN drive_files df ON df.id = fp.drive_file_id
               WHERE fp.processed_path IS NOT NULL
                 AND (fp.processed_path LIKE '/%' OR fp.processed_path LIKE 'data/%')"""
        ).fetchall()
        for r in legacy:
            rel = os.path.join("mirror", *((r["drive_path"].replace("\\", "/") + ".txt").split("/")))
            conn.execute("UPDATE file_processing SET processed_path=? WHERE drive_file_id=?",
                         (rel, r["drive_file_id"]))
        conn.execute("UPDATE chunks SET chunk_path = 'chunks/' || chunk_filename "
                     "WHERE chunk_path LIKE '/%' OR chunk_path LIKE 'data/%'")
        conn.execute("UPDATE file_processing SET downloaded_path=NULL "
                     "WHERE downloaded_path LIKE '/%' OR downloaded_path LIKE 'data/%'")
        conn.commit()
    except Exception:
        pass

    # Reset orphaned state from a previous crash/restart (runs against the active
    # DB regardless of where the data folder points).
    try:
        conn.execute("UPDATE sync_runs SET status='failed', finished_at=datetime('now'), "
                     "error_message='Server restarted' WHERE status='running'")
        conn.execute("UPDATE file_processing SET download_status='pending' WHERE download_status='downloading'")
        conn.execute("UPDATE file_processing SET processing_status='pending', processing_error=NULL "
                     "WHERE processing_status IN ('extracting','transcribing')")
        conn.commit()
    except Exception:
        pass

    conn.close()
