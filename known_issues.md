# Known Issues

## 1. Corrupt/legacy `.doc` & `.ppt` files stall extraction (LibreOffice timeout)

**Where:** `backend/services/extractor.py` → `_libreoffice_convert` (`timeout=120`),
called from `extract_text` for `.doc`/`.ppt`.

**Issue:** when a `.doc`/`.ppt` is corrupt or not a valid OLE file, LibreOffice's
headless `--convert-to` hangs until its **120-second timeout — for every such file**.
On a fresh/relocated data folder these are attempted in the download/process loop, so
~10 bad legacy files cost ~120 s each ≈ **~20 minutes** of wasted wall-time before
they're marked `failed`. (The pure-Python OLE fallback fails instantly, but
LibreOffice is preferred and tried first when installed.)

**Impact:** one-time per fresh folder. After the first attempt the files become
`failed` → terminal, so subsequent syncs skip them (and the sync early-exits). Not a
problem on steady-state machines.

**Desired behavior:** make bad files fail fast — e.g.
- lower the LibreOffice convert timeout (120 s → ~20 s), and/or
- cheaply validate OLE structure *before* invoking LibreOffice (the pure-Python
  reader already detects "not a valid OLE file" instantly) and skip the subprocess
  when it won't succeed.

**Status:** open — deferred.

---

## 2. New chunk files aren't auto-added as NotebookLM sources

**Where:** the NotebookLM side, in relation to `backend/jobs/job_runner.py` chunk
upload and `backend/services/drive_upload.py`.

**Context:** Google's automatic Google-Drive syncing for NotebookLM (Workspace
Updates, 2026-05-26) auto-updates Drive-backed sources every few minutes. Our pipeline
now cooperates with it: chunks are **updated in place with stable fileIds** (so
auto-sync refreshes content) and obsolete chunks are **hard-deleted** from Drive (so
auto-sync drops them). *(These were the previously-listed chunk-rewrite and
orphan-GC issues — both now resolved.)*

**Issue:** native auto-sync only refreshes *sources that already exist* in the
notebook — it does **not add new files** as sources. When a group grows and produces
**additional** chunk files (e.g. 1 part → 3 parts), the new Drive files are uploaded
but must still be added to the notebook **manually** (or via the NotebookLM Enterprise
API `notebooks.sources.batchCreate`).

**Desired behavior / mitigations:**
- Add genuinely-new chunks as notebook sources programmatically (Enterprise API), or
- Pad to a fixed maximum chunk count per group so the notebook's source set stays
  constant and only *content* changes — which native auto-sync fully covers.

**Status:** open — external NotebookLM limitation; in-place updates and orphan removal
are already handled on our side.

---

_Resolved & removed (2026-06-09): chunk files rewritten every run (stable content hash
+ write-on-change + per-group rebuild); obsolete chunks never garbage-collected (chunk
GC/reconciliation added)._
