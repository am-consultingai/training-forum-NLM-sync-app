"""Regression for v1.1.8: chunk packing must be identical on every machine.

The bug: extracts were packed into Group_PartN.txt in DB-row order, which differs
per machine, so the same sources produced a different number of parts (8 vs 13)
with different content — causing duplicate/divergent chunks on Drive."""
import random

from backend.services.chunker import build_chunks


def _make_files(tmp_path, n):
    src = tmp_path / "src"
    src.mkdir()
    files = []
    for i in range(n):
        p = src / f"f{i:02d}.txt"
        # Varying sizes so bin-packing boundaries are genuinely order-sensitive.
        p.write_text(("word%d " % i) * (30000 + i * 4000), encoding="utf-8")
        files.append({
            "name": f"f{i:02d}.txt", "path": str(p), "group": "Majors",
            "drive_file_id": f"id{i}", "drive_path": f"Majors/f{i:02d}.txt",
        })
    return files


def _signature(files, outdir):
    outdir.mkdir()
    result = build_chunks(files, str(outdir), chunk_size_bytes=1024 * 1024)
    return sorted((c["filename"], c["hash"]) for c in result)


def test_chunking_is_order_independent(tmp_path):
    files = _make_files(tmp_path, 12)
    ordered = _signature(list(files), tmp_path / "a")
    shuffled = list(files)
    random.Random(13).shuffle(shuffled)
    reshuffled = _signature(shuffled, tmp_path / "b")
    assert ordered == reshuffled, "shuffled input produced a different chunk set"
    assert len(ordered) > 1, "test should span multiple parts to be meaningful"


def test_chunking_is_stable_across_repeats(tmp_path):
    files = _make_files(tmp_path, 6)
    assert _signature(files, tmp_path / "x") == _signature(files, tmp_path / "y")
