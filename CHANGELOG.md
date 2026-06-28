# Changelog

All notable changes to sHaRe sync are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
