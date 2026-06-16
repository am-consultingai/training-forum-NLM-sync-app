import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.database import get_connection

router = APIRouter(prefix="/api/files", tags=["files"])


def _folder_status(node: dict) -> str:
    """Derive a folder's aggregate status from its descendants."""
    statuses = set()
    def _collect(n):
        for child in n["children"]:
            if child["is_folder"]:
                _collect(child)
            else:
                s = child.get("status", {})
                statuses.add(s.get("processing", "pending"))
    _collect(node)
    if not statuses:
        return "pending"
    if any(s in ("downloading", "extracting", "transcribing") for s in statuses):
        return "active"
    if "failed" in statuses:
        return "failed"
    if all(s in ("done", "skipped") for s in statuses):
        return "done"
    return "pending"


def _build_tree(rows: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for row in rows:
        node = {
            "id": row["id"],
            "name": row["name"],
            "drive_path": row["drive_path"],
            "is_folder": bool(row["is_folder"]),
            "parent_id": row["parent_id"],
            "children": [],
        }
        if not row["is_folder"]:
            node["relevance"] = row.get("relevance") or "relevant"
            node["status"] = {
                "download": row["download_status"] or "pending",
                "processing": row["processing_status"] or "pending",
                "processing_type": row["processing_type"],
                "progress": row["processing_progress"],
                "chunking": row["chunking_status"] or "pending",
                "error": row["processing_error"] or row["download_error"],
            }
        by_id[row["id"]] = node

    roots = []
    for node in by_id.values():
        parent_id = node.pop("parent_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            roots.append(node)

    # Annotate folders with aggregate status after tree is built
    def _annotate_folders(nodes):
        for node in nodes:
            if node["is_folder"]:
                _annotate_folders(node["children"])
                node["folder_status"] = _folder_status(node)
    _annotate_folders(roots)

    return roots


@router.get("")
def get_file_tree():
    conn = get_connection()
    rows = conn.execute(
        """SELECT df.id, df.name, df.mime_type, df.drive_path, df.parent_id, df.is_folder,
                  df.relevance,
                  fp.download_status, fp.download_error, fp.processing_status,
                  fp.processing_type, fp.processing_progress, fp.processing_error,
                  fp.chunking_status
           FROM drive_files df
           LEFT JOIN file_processing fp ON fp.drive_file_id = df.id
           ORDER BY df.drive_path"""
    ).fetchall()
    conn.close()
    return _build_tree([dict(r) for r in rows])


@router.get("/{file_id}")
def get_file_detail(file_id: str):
    conn = get_connection()
    row = conn.execute(
        """SELECT df.*, fp.*
           FROM drive_files df
           LEFT JOIN file_processing fp ON fp.drive_file_id = df.id
           WHERE df.id = ?""",
        (file_id,),
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    return dict(row)


class FlagRequest(BaseModel):
    relevance: str  # 'relevant' | 'not_relevant'


@router.patch("/{file_id}/flag")
def set_file_flag(file_id: str, body: FlagRequest):
    if body.relevance not in ("relevant", "not_relevant"):
        raise HTTPException(status_code=400, detail="relevance must be 'relevant' or 'not_relevant'")

    conn = get_connection()
    row = conn.execute("SELECT id FROM drive_files WHERE id=?", (file_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="File not found")

    conn.execute("UPDATE drive_files SET relevance=? WHERE id=?", (body.relevance, file_id))

    # Mark any chunks containing this file as needing regeneration
    chunks = conn.execute("SELECT id, source_files FROM chunks").fetchall()
    for chunk in chunks:
        sources = json.loads(chunk["source_files"] or "[]")
        if file_id in sources:
            conn.execute(
                "UPDATE chunks SET content_hash=NULL, upload_status='pending', updated_at=datetime('now') WHERE id=?",
                (chunk["id"],),
            )

    # Mark file for re-chunking on next sync
    conn.execute(
        "UPDATE file_processing SET chunking_status='pending' WHERE drive_file_id=?",
        (file_id,),
    )
    conn.commit()
    conn.close()
    return {"id": file_id, "relevance": body.relevance}
