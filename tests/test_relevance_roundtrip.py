"""Regression for v1.1.9 (edge case #4): the "ignore" (relevance) flag must travel
with the extract on Drive so a fresh machine doesn't re-add an ignored file to a
chunk. The flag rides in the extract's appProperties; a toggle merges into them
without clobbering the source provenance."""
from backend.services.drive_upload import (
    relevance_from_props,
    update_app_properties,
    upload_text_file,
)
from fake_drive import FakeDrive


def _extract(tmp_path):
    p = tmp_path / "e.txt"
    p.write_text("some extracted text", encoding="utf-8")
    return str(p)


def test_relevance_is_stamped_on_upload(tmp_path):
    svc = FakeDrive()
    fid = upload_text_file(
        svc, _extract(tmp_path), "MIRROR", name="e.txt",
        app_properties={"source_id": "S1", "source_md5": "abc", "relevance": "not_relevant"},
    )
    stored = svc.store[fid]["appProperties"]
    # What a fresh machine reads back off the extract during hydration:
    assert relevance_from_props(stored) == "not_relevant"
    assert stored["source_id"] == "S1"


def test_relevance_toggle_merges_without_losing_provenance(tmp_path):
    svc = FakeDrive()
    fid = upload_text_file(
        svc, _extract(tmp_path), "MIRROR", name="e.txt",
        app_properties={"source_id": "S1", "source_md5": "abc", "relevance": "not_relevant"},
    )
    # User flips it back to relevant on some machine -> metadata-only push:
    update_app_properties(svc, fid, {"relevance": "relevant"})
    stored = svc.store[fid]["appProperties"]
    assert relevance_from_props(stored) == "relevant"
    assert stored["source_id"] == "S1"   # provenance preserved by the merge
    assert stored["source_md5"] == "abc"
