# Drive → NotebookLM Sync Manager

A local web app that keeps a Google Drive folder in sync with NotebookLM. It walks a
source Drive folder, extracts readable text from every document (and **transcribes
Hebrew audio/video** with Whisper), packs that text into large chunk files, and writes
them to an output Drive folder that NotebookLM auto-syncs from. Run it manually from a
dashboard or let it run on a daily schedule.

---

## How to run it

### Prerequisites (one-time)

- **Python 3.12** with the project virtualenv at `.venv` (dependencies in
  `requirements.txt`), and **Node.js** for the frontend (`frontend/`).
- **Google OAuth client credentials** JSON on disk (path set by
  `GOOGLE_CREDENTIALS_PATH` in `.env`). The OAuth client must allow the redirect URI
  `http://localhost:8000/api/auth/callback`.
- For transcription: a local **faster-whisper** model (`WHISPER_MODEL_PATH`) and
  **ffmpeg** (`FFMPEG_PATH`). A CUDA GPU is used automatically if present; otherwise it
  falls back to CPU.
- **LibreOffice** (optional) — improves extraction of legacy `.doc`/`.ppt` files.

Configuration lives in two places:
- **`.env`** — credentials paths, Whisper/ffmpeg settings, schedule time, retries
  (loaded by `backend/config.py`).
- **`app_config.json`** — the Drive folder IDs, the local `data_root`, chunk size, and
  ignored extensions (editable from the UI; see `backend/app_config.py`).

### Start

```bash
./start.sh
```

This launches both servers and waits for the backend health check:

- **Backend** (FastAPI/uvicorn) on `http://localhost:8000` → logs at `/tmp/learnin_backend.log`
- **Frontend** (Vite/React) on `http://localhost:5173` → logs at `/tmp/learnin_frontend.log`

Then open **http://localhost:5173**. Press **Ctrl+C** in the terminal to stop both.

> `start.sh` also adds the venv's bundled NVIDIA CUDA libraries to `LD_LIBRARY_PATH` so
> ctranslate2 (Whisper) finds them on GPU machines.

### First-run authorization

On first launch you won't have a Google token yet. The UI shows an **auth banner** —
click it to start the OAuth flow (`/api/auth/start`), approve Drive access in Google,
and you'll be redirected back to the app. The token is saved to `GOOGLE_TOKEN_PATH` and
reused on later runs. Confirm your source / output / extracted-text Drive folders in the
**Settings** panel before your first sync.

### Trigger a sync

Click **Sync** in the UI (or `POST http://localhost:8000/api/sync/trigger`). Only one
sync runs at a time. A daily run also fires automatically at the time set by
`SYNC_SCHEDULE_HOUR` / `SYNC_SCHEDULE_MINUTE` (default 02:00), via APScheduler.

---

## What to expect while it runs

Progress streams live to the dashboard over **Server-Sent Events** — you'll see the
pipeline move through named stages, a per-file status tree, and a running log. Typical
stage sequence:

1. **Connecting** → **Discover** — lists the source folder (ticks up every ~200 files)
   and detects what's new, changed, or deleted. If nothing changed and there's no
   outstanding work, the run **early-exits** with *"Up to date — nothing changed"*.
2. **Hydrate** — on a fresh or relocated machine, restores prior work from Drive
   (cached extracts + existing chunks) so nothing is re-downloaded or re-transcribed.
3. **Download + Process (parallel)** — source files download concurrently (8 workers)
   while a single worker extracts/transcribes them. The **transcription model loads
   lazily** on the first audio/video file (you'll see *"Loading transcription model"*),
   and long transcriptions report a progress percentage per file.
4. **Extract-sync** — uploads newly produced text to the extracted-text mirror folder
   on Drive (stamped with source provenance for cross-machine reuse).
5. **Chunk** — rebuilds chunk files **only for groups whose content changed**, and
   garbage-collects obsolete chunks.
6. **Upload** — writes/updates chunk files in the output Drive folder, then marks the
   run **done** with counts (files processed, chunks uploaded).

**Timing notes:**
- The **first run on a fresh folder is slow** — everything must be downloaded,
  extracted, and (for media) transcribed; transcription is minutes per file on CPU.
  Subsequent runs are incremental and usually fast.
- **Known one-time stall:** a handful of corrupt legacy `.doc`/`.ppt` files can each
  cost ~120 s on a LibreOffice timeout before being marked `failed` (then skipped
  forever after). See `known_issues.md`.
- A run that makes **zero processing progress for 60 minutes** is treated as stalled
  and proceeds with whatever completed.
- Failed files are non-fatal — they're marked `failed` and the run continues. Use
  **Reset failed** in the UI (`/api/status/reset-failed`) to retry them.

When it finishes you'll see a completion event with the number of files processed and
chunks uploaded. NotebookLM then refreshes its Drive-backed sources automatically (with
one caveat — see *Known limitations*).

---

## What it's for

The owner keeps a Google Drive folder of learning material — PDFs, Office documents, and
**Hebrew audio/video** — and wants NotebookLM to stay current without manual work. This
app automates that bridge: it converts every source file into plain text NotebookLM can
ingest, keeps the output folder reconciled with the source (adds, updates, and deletes),
and runs daily so the notebook is always up to date.

It cooperates with Google's native NotebookLM↔Drive auto-sync by updating chunk files
**in place with stable file IDs** (so content refreshes) and **hard-deleting** obsolete
chunks (so they drop out of the notebook).

---

## Architecture

**Stack:** Python **FastAPI** backend + **React/TypeScript/Vite** frontend, **SQLite**
for state, **APScheduler** for the daily cron, and **SSE** for real-time progress.

### Pipeline (5 phases)

```
Discover → (Hydrate) → Download + Process → Extract-sync → Chunk → Upload
```

Orchestrated by `backend/jobs/job_runner.py::run_sync`, which runs in a thread pool and
emits progress events. Key design points:

- **Drive is the source of truth; the local DB is a cache.** A fresh or relocated
  machine reseeds all derived state from Drive — no duplicate work, no duplicate chunks.
- **Incremental everywhere.** Change detection (md5 for binaries, modifiedTime for
  Google-native files) gates each phase; only changed groups are re-chunked.
- **Download/transcribe overlap.** Network-bound downloads run in parallel with the
  GPU-bound transcription worker via an unbounded queue.

### Three Drive folders

| Folder | Role |
| --- | --- |
| **Source** (`source_drive_folder_id`) | Input — the material to sync (read-only to the app). |
| **Extracted-text mirror** (`extracted_text_drive_folder_id`) | Per-file `.txt` extracts mirroring the source tree; enables cross-machine reuse. |
| **Output** (`output_drive_folder_id`) | The chunk files NotebookLM syncs from. |

### Local data layout

All local paths derive from a single **`data_root`** (set in `app_config.json`), so
relocating it moves everything:

```
<data_root>/
  sync.db        # SQLite: drive_files, file_processing, chunks, sync_runs, progress_events
  downloads/     # downloaded source files
  transcripts/   # local extracted-text mirror (a.k.a. mirror/)
  chunks/        # built chunk files (e.g. HR_General_Part1.txt)
```

### Backend layout

```
backend/
  main.py                  # FastAPI app, CORS, startup (init_db + scheduler), /api/health
  config.py                # .env-backed settings (paths, Whisper, schedule)
  app_config.py            # user-settable config in app_config.json (folders, data_root, chunk size)
  database.py              # SQLite schema + connection + startup recovery
  api/                     # routes: auth, config, files, status, sync, progress
  jobs/job_runner.py       # the 5-phase pipeline + SSE event bridge
  jobs/scheduler.py        # APScheduler daily trigger
  services/
    drive_sync.py          # Drive list / change-detect / download / export
    drive_upload.py        # upload/update/delete chunk + text files on Drive
    extractor.py           # text extraction (PDF/DOCX/PPTX/Excel, LibreOffice fallback)
    transcriber.py         # faster-whisper Hebrew transcription (model loaded once)
    chunker.py             # build size-bounded chunk files per group
```

### Key HTTP endpoints

| Method & path | Purpose |
| --- | --- |
| `GET /api/health` | Liveness check (used by `start.sh`). |
| `GET /api/auth/status`, `GET /api/auth/start`, `GET /api/auth/callback` | Google OAuth flow. |
| `POST /api/sync/trigger` | Start a sync (one at a time). |
| `GET /api/sync/status`, `/runs`, `/runs/{id}`, `/live-progress` | Run status & history. |
| `GET /api/progress/stream` (SSE), `/events` | Live + recent progress events. |
| `GET /api/status/summary`, `/files` · `POST /api/status/reset-failed` | Dashboard stats; retry failed files. |
| `GET /api/files`, `/{id}` · `POST /api/files/{id}` (flag) | File tree; mark a file relevant/not. |
| `GET /api/config` · `POST /api/config/*` | Read/update folders, data folder, chunk size, ignored extensions. |

---

## Troubleshooting

- **Backend won't start** → `tail -f /tmp/learnin_backend.log`. `start.sh` aborts if the
  health check fails within 15 s.
- **"Credentials file not found"** in the auth banner → fix `GOOGLE_CREDENTIALS_PATH` in
  `.env` (and ensure the OAuth client lists the `…/api/auth/callback` redirect URI).
- **Transcription fails to load** → check `WHISPER_MODEL_PATH`, `FFMPEG_PATH`, and (GPU)
  that the CUDA libs line printed by `start.sh`. It falls back to CPU when no GPU.
- **A sync looks frozen on the first run** → it's likely transcribing media (minutes per
  file) or stuck on a bad legacy `.doc`/`.ppt` (see `known_issues.md`).

## Known limitations

See **`known_issues.md`**. The main external one: NotebookLM's native auto-sync refreshes
existing sources but **does not add brand-new chunk files** as sources — when a group
grows from 1 part to several, the new parts must be added to the notebook manually (or
via the NotebookLM Enterprise API).

---

## Related scripts in this repo

The repo also contains standalone Google Apps Script tools (`fetch_email.gs`,
`fetch_emails_v2.gs`) that export Gmail messages to a Google Sheet/CSV. These are
**separate** from the sync app and run in the Apps Script editor, not via `start.sh`.
Earlier prototypes live in `old_script/` (reference only — their logic was ported into
`backend/services/`).
