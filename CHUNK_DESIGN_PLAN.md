# Consolidated Chunk Design + Execution Plan  *(throwaway — delete after implementation)*

Merges two parallel Claude sessions into one design:

| Session | Angle | Slug |
|---|---|---|
| A — **chunk content / format** | What goes *inside* a chunk: Excel bloat, provenance links, NotebookLM citing | `86354372` |
| B — **chunk lifecycle / indexing** | What counts as processed→chunked→uploaded; run-completion; status accounting | `287afbc5` |

They are two halves of one system. Their shared surface is the **`chunks` table + the chunk-build/upload phase + the `chunking_status` field**.

---

## 0. Current state (read before doing anything)

- **The backend server is RUNNING and actively transcribing** the video backlog (~17 h of media, serial, ~15–27 min/video). **Do not restart it** until the queue drains — it would kill in-flight transcription.
- Code already edited **this session but inert** (old code still in the live process; activates on next restart):
  - `extractor.py` — `.xlsx`/`.xls` empty-row/col trim; `clean_text` per-line rstrip + blank-collapse.
  - `chunker.py` — `_normalize()` on chunk read.
  - Verified: `HC Main BU` 110 MB → 377 KB; existing bloated intermediate auto-heals to 377 KB on next chunk rebuild.
- Therefore: everything below lands on the **next clean restart**, which should happen **after** the current queue drains.

---

## PART A — Chunk content / format

### A1. Excel bloat — ✅ DONE (verify only)
Root cause: `pd.read_excel` serialized the full Excel used-range (~1 M empty rows × ~110 cols) → 114 M tab chars. Fixed via `dropna(how="all")` (xlsx) + column/row filtering (xls), plus `_normalize` defense in the chunker.
- **Verify after restart:** re-run a sync (or re-chunk) and confirm `HR_General_Part2…25` collapse to ~1 healthy chunk and `data/chunks` real-text ratio is 80–90% everywhere.

### A2. Provenance markers — ⬜ TODO (enables "link to original file")
NotebookLM cannot fetch/browse; it can only repeat a link that is already in the source text. So embed a stable Drive deep-link next to the content, densely enough that any cited passage has one nearby.

- **Link format (no API call needed — `drive_file_id` already in scope):**
  `https://drive.google.com/open?id=<drive_file_id>`  (universal redirect for any file type)
- **Marker format:** `[source: «<original name>» https://drive.google.com/open?id=<id>]`
- **Density:** at each file-section boundary **and** every ~50 lines within a section (periodic markers are what actually land in NotebookLM's retrieved window).

**Code targets:**
1. `job_runner.py:417-430` — `chunk_files` already carries `drive_file_id`. Also carry a precomputed `drive_link`.
2. `chunker.py build_chunks` (`backend/services/chunker.py:66`) — change the item tuple from `(name, text)` to include `drive_link` (or pass a parallel dict). Thread it through `flush`/`_split_by_size`/`_write_chunk`.
3. `chunker.py _write_chunk` (`:33`) —
   - Manifest `=== FILE LIST ===`: append the Drive link per file.
   - `=== START FILE: <name> ===`: add a `Source: <link>` line.
   - Inject a compact `[source: «name» <link>]` line every ~50 lines of the file body (helper that walks `text.splitlines()`).
4. Keep markers out of the byte-accounting edge cases: count their bytes toward chunk size so a marker-heavy file can't overflow `chunk_size_bytes`.

### A3. NotebookLM custom instruction — ⬜ TODO (manual, user pastes once)
NotebookLM web app → open notebook → Chat panel → Customize / chat-settings (sliders icon; gradual rollout). Paste:

> "Each source is a concatenation of multiple original files. A line of the form
> `[source: «FILENAME» <url>]` marks where each original file's content begins.
> When you answer, always include the Drive link from the nearest preceding
> `[source: …]` marker so the user can open the original file. Never invent a link;
> only use links that appear in the sources."

Fallback if the Customize box isn't available for the account: add a tiny `_README_format.txt` source with the same text, or prepend the instruction per question.

---

## PART B — Chunk lifecycle / indexing

### B1. Run "finishes" before processing does — ⬜ TODO (root cause of session B)
`job_runner.py:393` joins the process worker with a **fixed 2 h timeout** (`process_thread.join(timeout=7200)`). The video backlog is ~17 h, so:
- `join` times out → main flow proceeds to chunk+upload with only the files done so far.
- Run stamped `status='done'` (`:486-487`) while the **daemon** worker keeps transcribing for hours.
- Stragglers finish with `chunking_status='pending'` but the chunk phase already ran → **they never reach NotebookLM** until a later sync.

**Fix options (pick one):**
- **(Preferred) Drain, don't time out:** replace the fixed `join(7200)` with a loop that waits until `proc_queue` is empty **and** the worker is idle (or `join()` with no/very-large timeout, periodically emitting progress + checking an abort flag). Only then run chunk+upload and mark the run `done`.
- **(Cheaper, also valid) Post-chunk reconciliation pass:** after chunk+upload, query for any `processing_status='done' AND chunking_status='pending'` files; if present, run one more chunk+upload before stamping `done`. Combine with B2.

### B2. `chunking_status` is a dangling index — ⬜ TODO (the seam between A and B)
- Defined `database.py:49`, set to `'pending'` at `job_runner.py:259`, displayed `files.py:49/81`, reset to `'pending'` on manual re-chunk `files.py:135`.
- **Never set to `'done'` anywhere.** So the per-file "is this in a chunk yet?" index is permanently `pending` for everything — the tree can't truthfully show chunk state, and there's no cheap way to find un-chunked stragglers.

**Fix:** in the chunk phase (`job_runner.py:432-444+`), after a file's content is written into a chunk, set its `chunking_status='done'`. Then:
- The reconciliation query in B1 becomes trivial and correct.
- The tree badge can distinguish "processed" from "processed **and** chunked/uploaded."

### B3. "Synced" means two different things — ⬜ TODO (session B's presenting symptom)
- Sync bar `/sync/live-progress` (`backend/api/sync.py:82,97,127`) → `dl_done` = `download_status IN ('done','skipped')` → really means **"downloaded."**
- Tree badge keys off `processing_status==='done'` → means **"processed."**
- Result: bar says "all synced" while tree shows "pending."

**Fix (presentation, low risk):**
- Relabel the headline metric, or base the "synced" headline on the **last** pipeline stage that matters for NotebookLM (uploaded / chunked), not download.
- Surface the real pipeline as distinct counters: Downloaded · Processed · Chunked · Uploaded — sourced from `download_status`, `processing_status`, `chunking_status`, and `chunks.upload_status` respectively. With B2 wired, all four become truthful.

---

## Unified data model (single source of truth after this work)

Per file (`file_processing`): `download_status → processing_status → chunking_status`, plus `chunks.upload_status` for the chunk it landed in. A file is **"in NotebookLM"** iff its content's chunk has `upload_status='done'`. Every UI number derives from exactly one of these columns — no more divergent denominators.

---

## Execution plan (ordered)

> Gate: **do not restart the server until the current transcription queue drains.** Steps 1–5 are code edits (safe; inert until restart). Step 0 and 6+ are operational.

0. **Wait for queue drain** (Session B already has a watcher). Confirm: `0 pending, 0 transcribing`.
1. **A1 verify** — already coded; nothing to write, just confirm post-restart.
2. **A2 provenance** — edit `job_runner.py` (drive_link) → `chunker.py` (thread + `_write_chunk` markers + periodic injector + byte accounting).
3. **B2 `chunking_status='done'`** — set in chunk phase after a file is emitted into a chunk (`job_runner.py` chunk loop).
4. **B1 drain-not-timeout** (or post-chunk reconciliation pass) — `job_runner.py:393` + finalize block `:486`.
5. **B3 status semantics** — `backend/api/sync.py` live-progress payload + frontend StatusBadge/SyncPanel labels + counters.
6. **Restart server** (only now). Trigger one full sync.
7. **Verify end-to-end:**
   - `data/chunks` real-text ratio healthy; `HR_General` renumbered; junk parts gone.
   - A cited NotebookLM answer shows a working `drive.google.com/open?id=…` link to the original.
   - Bar + tree agree; stragglers are chunked+uploaded; `chunking_status='done'` for all uploaded files.
8. **Delete this file** and fold any durable decisions into project memory (`…/memory/`).

## Risk / sequencing notes
- Steps 2–5 touch the chunk/upload phase and the worker join — all in `job_runner.py` chunk region + `chunker.py` + `sync.py`. Keep them in one restart cycle.
- B1 "drain" must still honor the abort/cancel path so a user can stop a multi-hour run.
- Provenance markers increase chunk text slightly; re-confirm chunk count/size after A2.
