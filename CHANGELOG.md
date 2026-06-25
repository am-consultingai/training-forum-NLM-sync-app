# Changelog

All notable changes to sHaRe sync are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## 1.1.0 — 2026-06-25

### Fixed
- **Sync no longer aborts entirely when a single file fails to download.** A long
  path, a timeout, or a network hiccup used to crash the whole run; the problem
  file is now skipped and the sync continues. (Root cause: a shadowing local
  `import time` in `run_sync` raised `NameError` from the download-retry path.)
- **Deeply-nested folders with long (incl. Hebrew) names now download on every
  Windows machine**, regardless of the system long-path setting — destination
  paths use the Windows extended-length (`\\?\`) form, lifting the 260-char limit.
- **Folder names containing `/`** (e.g. `Leaders / Managers Dev`) no longer split
  into extra nested folders; a `/` or `\` inside a Drive name is kept literal.
- **Audio-extraction failures now report ffmpeg's actual error** instead of a
  generic message, so the real cause is recorded.
- **The packaged app ignores a stray `.env`** in its launch directory, which could
  otherwise silently point it at the wrong model or database.
- Use the OS temp directory for intermediate audio instead of a hardcoded `/tmp`.

### Added
- **Automatic GPU → CPU fallback for transcription.** The GPU is validated at load
  time; if it can't be used for any reason, transcription falls back to CPU and the
  fallback is recorded in the run log instead of failing the file.
