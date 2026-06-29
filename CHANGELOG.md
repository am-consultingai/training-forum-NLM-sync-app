# Changelog

All notable changes to sHaRe sync are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## 1.2.1 — 2026-06-29

### Fixed
- **No more needless re-chunk/re-upload when another machine already made the
  chunks.** A chunk's identity across machines is its *filename*, not its Drive file
  ID (each machine that creates a file gets a different ID). The 1.2.0
  "regenerate-missing" check compared Drive IDs, so a second machine — whose local
  DB recorded different IDs for the same-named chunks — saw them all as "missing"
  and rebuilt + re-uploaded everything on an idle sync, even with no source changes.
  Reconciliation is now by **filename**: if a chunk's name is present on Drive under
  a different ID, the app simply **adopts** that ID; it only rebuilds when the name
  is genuinely absent. (The stray re-uploads were harmless — they updated the
  existing files in place, no duplicates, no false "new source" alerts — just
  wasteful.)

## 1.2.0 — 2026-06-29

### Added
- **The app now actively reports NotebookLM-relevant changes to the output set.**
  Whenever a sync **creates** a new chunk file (a new Drive source you must *add* to
  NotebookLM) or **removes** one (a source you must *delete*), it's surfaced in a
  prominent, persistent banner — "Add N new sources / Remove N sources" with the
  exact filenames — and dismissed only when you acknowledge it. Previously a new
  source was created silently, so NotebookLM could be missing information with no
  signal (the same severity as a deletion). Backed by a new `/api/notices` endpoint
  and a `chunk_notices` record; the change list is also included in the run-complete
  event.

### Fixed
- **Chunks deleted from the Drive output folder are now regenerated on the next
  sync.** If chunk files are removed on Drive (externally, or to force a clean
  rebuild), an otherwise-idle sync detects they're missing, rebuilds the affected
  groups, and re-uploads them — instead of reporting "up to date" and leaving you
  with no chunks. New chunks created this way are reported via the banner above.

### Changed
- Chunk uploads now report whether each file was newly **created** vs **updated in
  place**, which drives the new-source notification. (Updates still reuse the same
  Drive file ID, so NotebookLM keeps the existing source — see 1.1.8.)

## 1.1.9 — 2026-06-29

### Fixed
- **"Ignore" (relevance) now travels across machines.** Marking a file as ignored
  was stored only in the local database, so a sync on a *different* machine didn't
  know about it — it treated the file as relevant and re-added it to a chunk,
  silently undoing the exclusion. The flag is now stamped on the extract's Drive
  `appProperties`: it's pushed immediately when you toggle it, re-stamped on every
  extract upload, and read back on every machine during hydration (the Drive mirror
  is the source of truth). A file ignored on any machine stays ignored everywhere.

### Internal
- **Regression test suite + CI gate.** Added unit tests for the edge cases behind
  the recent fixes — deterministic chunk packing (order-independent), idempotent
  upload-by-name (no duplicate chunks), the duplicate-cleanup picker, and the
  relevance round-trip through Drive `appProperties`. The Windows build now runs
  these tests first and fails if any regress.

## 1.1.8 — 2026-06-29

### Fixed
- **Chunk count is now identical on every machine (no more "8 chunks become
  13").** Chunks were packed into `Group_PartN.txt` files in whatever order the
  database returned rows — which differs per machine — so the same sources packed
  into a different number of parts with different content, and everything looked
  "changed" and re-uploaded. Source files are now packed in a stable order (by
  Drive path), so the chunk set is deterministic across machines.
- **A sync on a second machine no longer creates duplicate chunks with names that
  already exist on Drive** (e.g. a second `Majors_Part5.txt`). Chunk upload is now
  idempotent by name: before creating a file it looks one up by name in the output
  folder and updates that instead of creating a duplicate (Drive allows multiple
  files with the same name). Works regardless of what the local database knows.
- **Existing duplicate chunks are cleaned up automatically.** Each sync now scans
  the output folder and, for any name with more than one Drive file, keeps the
  most-recently-modified one and moves the rest to Drive trash (recoverable),
  re-pointing local records at the survivor.

## 1.1.7 — 2026-06-29

### Fixed
- **Deeply-nested files now process on machines that don't have Windows long-path
  support enabled.** The earlier `\\?\` fix covered downloads but not the extract/
  transcript writes or source reads — so on a machine without `LongPathsEnabled`,
  processing a file under a very deep (incl. Hebrew) folder tree crashed the whole
  process worker with `WinError 206` / `[Errno 2]`, which then failed every later
  file too. Now every local file operation (extract dir + write, text extraction,
  ffmpeg input, transcript write, chunk reads, hashing, existence checks) uses the
  extended-length path form, and a per-file path failure can no longer kill the
  worker. Audio is also normalized through ffmpeg so the transcriber never receives
  an over-260-char path.

## 1.1.6 — 2026-06-29

### Changed
- **While a sync is running, the Status Summary now opens on the Total / pipeline
  view by default**, so the live flow of the process — Connect → Discover → Download
  → Process → Mirror → Chunk → Upload, with the active stage highlighted — is
  front-and-center. You can still click into any other stat mid-run.

## 1.1.5 — 2026-06-29

### Fixed
- **Stale "Operation timed out after 120s" no longer lingers on files that downloaded
  fine.** A download that timed out once then succeeded on retry kept the old error
  text (`download_status` became `done` but `download_error` wasn't cleared), so the
  file showed a warning even though it was fully downloaded. The error is now cleared
  on a successful download.

## 1.1.4 — 2026-06-29

### Fixed
- **Large files (videos) no longer fail to download with "Operation timed out after
  120s".** The download had a flat 120-second cap on the *entire* transfer, which big
  files on a shared connection can't meet — they timed out, retried 3×, and failed
  (leaving meeting-recording videos un-transcribed). The timeout is now a **stall
  guard**: the download runs in 10 MB chunks and only aborts if **no data arrives**
  for the timeout window, so a file takes as long as it legitimately needs.

## 1.1.3 — 2026-06-28

### Changed
- **System-tray launcher hardened.** A failure to create the tray icon no longer
  takes the whole app down — it's logged and the server keeps running (still usable
  from the browser). The tray image is normalized to a clean 64×64 to avoid a
  blank/odd render. Note: Windows still places new tray icons in the **hidden-icons
  overflow** by default (expand the `^` near the clock, or pin via Taskbar settings)
  — an app can't self-promote out of it.

## 1.1.2 — 2026-06-28

### Fixed
- **`/status/summary` no longer errors every poll.** The new `pending_orphans`
  count was queried after the DB connection was already closed, raising
  `sqlite3.ProgrammingError: Cannot operate on a closed database` on each status
  poll (cosmetic — the sync was unaffected, but the status numbers/orphan banner
  stopped updating and the log filled with the trace). The query now runs before
  the connection is closed.

## 1.1.1 — 2026-06-28

### Fixed
- **GPU transcription now actually loads cuBLAS/cuDNN.** The bundled CUDA libs were
  registered only via `os.add_dll_directory()`, which ctranslate2's lazy (first-
  inference) loader doesn't search — so the model loaded on CUDA but the first GEMM
  failed with `cublas64_12.dll … cannot be loaded`. The CUDA `bin` dirs are now also
  prepended to `PATH`, which the standard loader does search. The GPU→CPU fallback
  from 1.1.0 remains as the safety net.

## 1.1.0 — 2026-06-25

### Safety
- **Mirror extracts are never auto-deleted anymore.** The cleanup that removed an
  extract when it couldn't match it to a source *by path* could wrongly destroy
  valid work when paths differed. Orphans are now detected by a **stable source ID**
  (immune to path/rename differences), **never deleted automatically**, and surfaced
  in the app — "Found N extracts without a matching source. Delete or keep?" Approved
  deletions go to **Drive trash** (recoverable ~30 days), not a permanent delete.

### Changed
- **Cache matching now keys off the stable Drive `source_id`, not the file path.**
  Deciding whether a source already has a usable extract — on both fresh-machine
  hydration and per-file classification — matches the extract to its source by the
  immutable `source_id` stamped on it, and uses md5 (binary) / modifiedTime
  (Google-native) only to confirm it's current. A renamed/moved source, or any
  path-scheme difference, no longer forces a needless re-download/re-transcription.
  Path is kept solely as a fallback for legacy extracts without the stamp. (Verified
  live: all 752 current extracts carry `source_id`.)

### Fixed
- **Sync no longer aborts entirely when a single file fails to download.** A long
  path, a timeout, or a network hiccup used to crash the whole run; the problem
  file is now skipped and the sync continues. (Root cause: a shadowing local
  `import time` in `run_sync` raised `NameError` from the download-retry path.)
- **Deeply-nested folders with long (incl. Hebrew) names now download on every
  Windows machine**, regardless of the system long-path setting — destination
  paths use the Windows extended-length (`\\?\`) form, lifting the 260-char limit.
- **Audio-extraction failures now report ffmpeg's actual error** instead of a
  generic message, so the real cause is recorded.
- **The packaged app ignores a stray `.env`** in its launch directory, which could
  otherwise silently point it at the wrong model or database.
- Use the OS temp directory for intermediate audio instead of a hardcoded `/tmp`.

### Added
- **Automatic GPU → CPU fallback for transcription.** The GPU is validated at load
  time; if it can't be used for any reason, transcription falls back to CPU and the
  fallback is recorded in the run log instead of failing the file.
