"""
Persistent user-settable configuration.

Stored in app_config.json at a STABLE, writable per-user location (the app home),
independent of the data folder — because one of the settings it holds is *where the
data folder is*, so it cannot live inside that folder. (The install dir is read-only,
so it cannot live there either.) Holds: data_root, the Drive folder IDs,
chunk_size_mb, ignore_extensions.

All local paths (database + downloads/ + mirror/ + chunks/) derive from a single
`data_root`, so relocating it moves everything (the app behaves like a new machine).
"""
import json
import os
import re
from typing import Optional

from backend import paths
from backend.config import settings

# Canonical config path: <app_home>/app_config.json (writable, survives reinstalls).
_APP_CONFIG_PATH = os.path.join(paths.app_home(), "app_config.json")
# Legacy locations, read (newest-first) only if the canonical file is absent — lets
# an existing dev checkout keep its data_root/folders after this move: the old repo
# root, then the old default-data-dir copy.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LEGACY_APP_CONFIG_PATHS = [
    os.path.join(_REPO_ROOT, "app_config.json"),
    os.path.join(os.path.abspath(settings.data_dir), "app_config.json"),
]

DEFAULT_DATA_ROOT = os.path.abspath(settings.data_dir)


def _read() -> dict:
    candidates = [_APP_CONFIG_PATH, *_LEGACY_APP_CONFIG_PATHS]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                continue
    return {}


def _write(data: dict):
    os.makedirs(os.path.dirname(os.path.abspath(_APP_CONFIG_PATH)), exist_ok=True)
    with open(_APP_CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Single data-root → derived local paths ────────────────────────────────────

def get_data_root() -> str:
    return _read().get("data_root") or DEFAULT_DATA_ROOT


def set_data_root(path: str) -> str:
    """Persist the data root and create its internal structure. Takes effect for the
    database on the next server restart (a live server holds the DB open)."""
    path = os.path.abspath(path)
    data = _read()
    data["data_root"] = path
    _write(data)
    ensure_data_dirs(path)
    return path


def get_db_path() -> str:
    return os.path.join(get_data_root(), "sync.db")


def get_downloads_dir() -> str:
    return os.path.join(get_data_root(), "downloads")


def get_mirror_dir() -> str:
    """Local copy of the extracted-text mirror (per-file .txt, mirroring the source)."""
    return os.path.join(get_data_root(), "mirror")


def get_chunks_dir() -> str:
    return os.path.join(get_data_root(), "chunks")


def data_rel(p: Optional[str]) -> Optional[str]:
    """Convert an absolute local path under the data root into a path RELATIVE to it,
    so the DB stays portable (the whole data folder can be moved/copied/swapped)."""
    if not p:
        return p
    try:
        return os.path.relpath(p, get_data_root())
    except ValueError:
        return p


def data_abs(p: Optional[str]) -> Optional[str]:
    """Resolve a data-root-relative path back to absolute for filesystem access.
    Absolute inputs (legacy rows) are returned unchanged."""
    if not p:
        return p
    return p if os.path.isabs(p) else os.path.join(get_data_root(), p)


def ensure_data_dirs(root: Optional[str] = None):
    root = root or get_data_root()
    for d in (root, os.path.join(root, "downloads"), os.path.join(root, "mirror"),
              os.path.join(root, "chunks")):
        os.makedirs(d, exist_ok=True)


def is_configured() -> bool:
    """Configured if the data root's parent exists (the leaf is auto-created)."""
    root = get_data_root()
    return os.path.exists(os.path.dirname(root) or "/")


# ── Chunk size ─────────────────────────────────────────────────────────────────

DEFAULT_CHUNK_SIZE_MB = 5.0


def get_chunk_size_mb() -> float:
    return float(_read().get("chunk_size_mb", DEFAULT_CHUNK_SIZE_MB))


def set_chunk_size_mb(mb: float) -> float:
    mb = max(1.0, min(mb, 200.0))
    data = _read()
    data["chunk_size_mb"] = mb
    _write(data)
    return mb


# ── Google Drive folders (source / chunks-output / mirror) ─────────────────────

_FOLDER_ID_RE = re.compile(r"/folders/([a-zA-Z0-9_-]+)")
_ID_PARAM_RE = re.compile(r"[?&]id=([a-zA-Z0-9_-]+)")


def parse_drive_folder_id(value: str) -> str:
    """Extract a Drive folder ID from a full Drive URL or a bare ID. '' if unparseable."""
    value = (value or "").strip()
    if not value:
        return ""
    m = _FOLDER_ID_RE.search(value) or _ID_PARAM_RE.search(value)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{25,}", value):
        return value
    return ""


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""


def get_effective_source_folder_id() -> str:
    return _read().get("source_drive_folder_id") or settings.source_drive_folder_id


def get_effective_output_folder_id() -> str:
    return _read().get("output_drive_folder_id") or settings.output_drive_folder_id


def get_effective_extracted_text_folder_id() -> str:
    return _read().get("extracted_text_drive_folder_id") or settings.extracted_text_drive_folder_id


def _set_folder(key: str, url_or_id: str) -> dict:
    fid = parse_drive_folder_id(url_or_id)
    if not fid:
        raise ValueError("Could not parse a Drive folder ID from the input")
    data = _read()
    data[key] = fid
    _write(data)
    return {"folder_id": fid, "url": folder_url(fid)}


def set_source_folder(url_or_id: str) -> dict:
    return _set_folder("source_drive_folder_id", url_or_id)


def set_output_folder(url_or_id: str) -> dict:
    return _set_folder("output_drive_folder_id", url_or_id)


def set_extracted_text_folder(url_or_id: str) -> dict:
    return _set_folder("extracted_text_drive_folder_id", url_or_id)


# ── Ignored file extensions ───────────────────────────────────────────────────

def get_ignore_extensions() -> list:
    """Lowercased extensions (each with a leading dot) to skip during processing."""
    return _read().get("ignore_extensions", [])


def set_ignore_extensions(exts) -> list:
    norm: list[str] = []
    for e in exts:
        e = (e or "").strip().lower()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        if e not in norm:
            norm.append(e)
    data = _read()
    data["ignore_extensions"] = norm
    _write(data)
    return norm
