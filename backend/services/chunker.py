import os
import re
import hashlib
from typing import Optional

DEFAULT_CHUNK_SIZE_BYTES = int(5 * 1024 * 1024)   # 5 MB default
# NotebookLM rejects a source at >= 500,000 words. Cap chunk *content* well below
# that (with margin for the manifest header + inline provenance markers, and to
# stay safely clear of NotebookLM's limit).
DEFAULT_MAX_WORDS = 300_000


def _byte_size(text: str) -> int:
    return len(text.encode("utf-8"))


def _word_count(text: str) -> int:
    return len(text.split())


def _split_by_limits(text: str, byte_limit: int, word_limit: int):
    """Yield pieces that each fit within BOTH the byte and word limits.

    Splits on line boundaries (no mid-line cuts); a single line that alone
    exceeds a limit is hard-split by words as a fallback.
    """
    cur: list[str] = []
    cur_bytes = 0
    cur_words = 0
    for line in text.split("\n"):
        lb = _byte_size(line) + 1          # +1 for the newline
        lw = len(line.split())
        if cur and (cur_bytes + lb > byte_limit or cur_words + lw > word_limit):
            yield "\n".join(cur)
            cur, cur_bytes, cur_words = [], 0, 0
        if lb > byte_limit or lw > word_limit:
            # pathological single line: flush and emit it in word-bounded slices
            if cur:
                yield "\n".join(cur)
                cur, cur_bytes, cur_words = [], 0, 0
            for piece in _split_long_line(line, byte_limit, word_limit):
                yield piece
            continue
        cur.append(line)
        cur_bytes += lb
        cur_words += lw
    if cur:
        yield "\n".join(cur)


def _split_long_line(line: str, byte_limit: int, word_limit: int):
    cur: list[str] = []
    cb = 0
    cw = 0
    for w in line.split(" "):
        wb = _byte_size(w) + 1
        if cur and (cb + wb > byte_limit or cw + 1 > word_limit):
            yield " ".join(cur)
            cur, cb, cw = [], 0, 0
        cur.append(w)
        cb += wb
        cw += 1
    if cur:
        yield " ".join(cur)


def _safe_group_name(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)


def _normalize(text: str) -> str:
    """Strip trailing per-line whitespace and collapse blank-line runs.

    Defends against bloated intermediates (e.g. sparse-spreadsheet rows that are
    nothing but tab separators) so a chunk can't fill MBs with empty padding.
    """
    text = text.replace("\x00", "")
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def drive_link(drive_file_id: Optional[str]) -> str:
    """Universal Drive deep-link (redirects to the right viewer for any file type)."""
    return f"https://drive.google.com/open?id={drive_file_id}" if drive_file_id else ""


MARKER_EVERY_LINES = 50


def _source_marker(name: str, link: str) -> str:
    return f"[source: «{name}»{(' ' + link) if link else ''}]"


def _with_source_markers(text: str, name: str, link: str, every: int = MARKER_EVERY_LINES) -> str:
    """Repeat a compact provenance marker through the text.

    NotebookLM cites an arbitrary passage and cannot fetch links, so a marker only
    helps if it lands inside the retrieved window. Sprinkling one every `every`
    lines (and at the top) means any cited snippet has a Drive link nearby.
    """
    marker = _source_marker(name, link)
    lines = text.split("\n")
    out = [marker]
    for i, ln in enumerate(lines, 1):
        out.append(ln)
        if i % every == 0 and i < len(lines):
            out.append(marker)
    return "\n".join(out)


def _render_chunk(group_name: str, part_num: int, items: list[dict]) -> str:
    """Render a chunk's full text: manifest header + delimited file sections.

    items: list of {"name": str, "text": str, "link": str} — `text` already has
    inline provenance markers injected.

    Deliberately contains NO volatile fields (e.g. a generation timestamp): the
    output is a pure function of its content, so an unchanged chunk hashes
    identically across runs and is neither re-written nor re-uploaded (which would
    otherwise make NotebookLM re-index needlessly).
    """
    out: list[str] = []
    # Manifest header
    out.append("=== CHUNK MANIFEST ===")
    out.append(f"Group: {group_name}")
    out.append(f"Part: {part_num}")
    out.append(f"Files: {len(items)}")
    out.append("=== FILE LIST ===")
    for it in items:
        link = it.get("link") or ""
        out.append(f"  {it['name']}{('  ' + link) if link else ''}")
    out.append("=== END MANIFEST ===")
    out.append("")

    # File sections
    for it in items:
        link = it.get("link") or ""
        out.append(f"=== START FILE: {it['name']} ===")
        if link:
            out.append(f"Source: {link}")
        out.append(it["text"])
        out.append(f"=== END FILE: {it['name']} ===")
        out.append("")
    return "\n".join(out)


def _hash_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _write_chunk(filepath: str, group_name: str, part_num: int, items: list[dict]) -> str:
    """Render and write a chunk only if its content changed. Returns the content hash.

    Writing only on change avoids needless disk churn and keeps mtimes stable.
    """
    content = _render_chunk(group_name, part_num, items)
    new_hash = _hash_str(content)
    if content_hash(filepath) == new_hash:
        return new_hash  # unchanged — leave the file (and its fileId) untouched
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return new_hash


def content_hash(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def build_chunks(
    files: list[dict],
    output_dir: str,
    chunk_size_bytes: int = DEFAULT_CHUNK_SIZE_BYTES,
    max_words: int = DEFAULT_MAX_WORDS,
) -> list[dict]:
    """
    files: list of {"name": str, "path": str, "group": str, "drive_file_id": str}
    chunk_size_bytes: max bytes per output file (configurable, default 5 MB)
    max_words: max words of content per output file (NotebookLM caps sources at
               <500k words; default leaves margin for manifest + markers)
    Returns list of {"filename", "path", "hash", "drive_file_ids": [str, ...]}.
    """
    os.makedirs(output_dir, exist_ok=True)
    content_limit = int(chunk_size_bytes * 0.95)

    groups: dict[str, list[dict]] = {}
    for f in files:
        safe = _safe_group_name(f["group"])
        groups.setdefault(safe, []).append(f)

    results = []
    for group_name, file_list in groups.items():
        batch: list[dict] = []        # each: {"name","text","link","file_id"}
        batch_size = 0
        batch_words = 0
        part = 1

        def flush(b, p):
            fname = f"{group_name}_Part{p}.txt"
            fpath = os.path.join(output_dir, fname)
            h = _write_chunk(fpath, group_name, p, b)
            ids = [it["file_id"] for it in b if it.get("file_id")]
            results.append({"filename": fname, "path": fpath, "hash": h, "drive_file_ids": ids})

        for fdict in file_list:
            fpath = fdict["path"]
            fname = fdict["name"]
            file_id = fdict.get("drive_file_id")
            link = drive_link(file_id)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read()
            text = _normalize(raw)
            if not text:
                continue

            # A file that on its own blows the byte OR word budget must be split.
            if _byte_size(text) > chunk_size_bytes or _word_count(text) > max_words:
                if batch:
                    flush(batch, part)
                    batch, batch_size, batch_words, part = [], 0, 0, part + 1
                # Split the normalized text first, then inject markers per piece so
                # a split never cuts through a marker line.
                for idx, piece in enumerate(_split_by_limits(text, content_limit, max_words)):
                    pname = f"{fname} (Split {idx+1})"
                    section = _with_source_markers(piece, pname, link)
                    out_fname = f"{group_name}_Part{part}.txt"
                    out_path = os.path.join(output_dir, out_fname)
                    h = _write_chunk(out_path, group_name, part,
                                     [{"name": pname, "text": section, "link": link, "file_id": file_id}])
                    results.append({"filename": out_fname, "path": out_path, "hash": h,
                                    "drive_file_ids": [file_id] if file_id else []})
                    part += 1
            else:
                section = _with_source_markers(text, fname, link)
                size = _byte_size(section)
                words = _word_count(section)
                if batch and (batch_size + size > chunk_size_bytes or batch_words + words > max_words):
                    flush(batch, part)
                    batch, batch_size, batch_words, part = [], 0, 0, part + 1
                batch.append({"name": fname, "text": section, "link": link, "file_id": file_id})
                batch_size += size
                batch_words += words

        if batch:
            flush(batch, part)

    return results
