"""Regression for v1.1.8: chunk upload must be idempotent by name (no duplicate
Majors_Part5.txt across machines), plus the dedup + relevance helpers."""
from backend.services.drive_upload import (
    dedupe_by_name,
    reconcile_chunks_by_name,
    relevance_from_props,
    update_app_properties,
    upload_text_file,
)
from fake_drive import FakeDrive


def _tmpfile(tmp_path, text="hello"):
    p = tmp_path / "chunk.txt"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_upload_is_idempotent_by_name(tmp_path):
    """A second machine that doesn't know the Drive ID must UPDATE the existing
    file, not create a duplicate with the same name."""
    svc = FakeDrive()
    f = _tmpfile(tmp_path)
    id1, created1 = upload_text_file(svc, f, "PARENT", name="Majors_Part5.txt")
    id2, created2 = upload_text_file(svc, f, "PARENT", name="Majors_Part5.txt")  # no id known
    assert id1 == id2
    assert created1 is True       # first call made a new Drive file
    assert created2 is False      # second call updated it in place — no new source
    assert svc.live_named("Majors_Part5.txt") == 1


def test_upload_respects_explicit_existing_id(tmp_path):
    svc = FakeDrive()
    f = _tmpfile(tmp_path)
    id1, _ = upload_text_file(svc, f, "PARENT", name="a.txt")
    id2, created2 = upload_text_file(svc, f, "PARENT", name="a.txt", existing_drive_id=id1)
    assert id2 == id1
    assert created2 is False
    assert len(svc.store) == 1


def test_upload_creates_distinct_files_for_distinct_names(tmp_path):
    svc = FakeDrive()
    f = _tmpfile(tmp_path)
    a, ca = upload_text_file(svc, f, "PARENT", name="Majors_Part1.txt")
    b, cb = upload_text_file(svc, f, "PARENT", name="Majors_Part2.txt")
    assert a != b
    assert ca is True and cb is True
    assert len(svc.store) == 2


def test_dedupe_by_name_keeps_newest():
    files = [
        {"id": "old", "name": "A", "modifiedTime": "2026-01-01T00:00:00Z"},
        {"id": "new", "name": "A", "modifiedTime": "2026-02-01T00:00:00Z"},
        {"id": "b", "name": "B", "modifiedTime": "2026-01-01T00:00:00Z"},
    ]
    id_by_name, to_trash = dedupe_by_name(files)
    assert id_by_name["A"] == "new"
    assert id_by_name["B"] == "b"
    assert to_trash == [("A", "old")]


def test_dedupe_by_name_no_duplicates():
    files = [{"id": "x", "name": "A", "modifiedTime": "2026-01-01T00:00:00Z"}]
    id_by_name, to_trash = dedupe_by_name(files)
    assert id_by_name == {"A": "x"}
    assert to_trash == []


def test_reconcile_chunks_by_name_adopts_not_rebuilds():
    """A chunk another machine (re)created has a DIFFERENT Drive ID for the same
    name. We must adopt that ID, not flag it missing and rebuild/re-upload."""
    tracked = [
        ("AI_Part1.txt", "old_id_a"),       # present under a new id -> adopt
        ("Majors_Part1.txt", "same_id_m"),  # present, same id -> no-op
        ("Gone_Part1.txt", "old_id_g"),     # name absent entirely -> rebuild
    ]
    present_by_name = {"AI_Part1.txt": "new_id_a", "Majors_Part1.txt": "same_id_m"}
    adopt, missing = reconcile_chunks_by_name(tracked, present_by_name)
    assert adopt == [("AI_Part1.txt", "new_id_a")]
    assert missing == ["Gone_Part1.txt"]


def test_reconcile_chunks_all_present_no_rebuild():
    """The reported bug: every tracked chunk exists by name (even if its ID changed),
    so NOTHING is missing — an idle sync must not rebuild."""
    tracked = [("AI_Part1.txt", "stale1"), ("Majors_Part1.txt", "stale2")]
    present_by_name = {"AI_Part1.txt": "newA", "Majors_Part1.txt": "newM"}
    adopt, missing = reconcile_chunks_by_name(tracked, present_by_name)
    assert missing == []                      # no rebuild
    assert sorted(adopt) == [("AI_Part1.txt", "newA"), ("Majors_Part1.txt", "newM")]


def test_relevance_from_props():
    assert relevance_from_props({"relevance": "not_relevant"}) == "not_relevant"
    assert relevance_from_props({"relevance": "relevant"}) == "relevant"
    assert relevance_from_props({}) is None          # legacy extract: don't force a value
    assert relevance_from_props(None) is None
    assert relevance_from_props({"relevance": "bogus"}) is None
