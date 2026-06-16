import sqlite3
import os
from backend.app_config import get_db_path, get_data_root, ensure_data_dirs


def get_connection() -> sqlite3.Connection:
    # `timeout` is the C-level busy timeout; pair it with the PRAGMA below so both
    # the driver and the engine wait out transient locks instead of failing fast.
    conn = sqlite3.connect(get_db_path(), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    # Wait out transient locks (DrvFS/Windows mounts can be slower than ext4).
    conn.execute("PRAGMA busy_timeout=30000")
    # WAL lets the UI's read-polling run concurrently with the sync's writer
    # WITHOUT either blocking the other — essential here, since several connections
    # touch this DB at once. PRAGMA journal_mode returns the resulting mode rather
    # than raising, so check it: if WAL didn't engage (a filesystem that can't back
    # the -shm/-wal files), fall back to DELETE explicitly.
    try:
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            conn.execute("PRAGMA journal_mode=DELETE")
    except Exception:
        pass
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
