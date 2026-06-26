# Changelog

All notable changes to sHaRe sync are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
