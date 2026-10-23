import pytest

from raguard.ingestion import UploadRejected, validate_upload


def _doc(rag, name):
    return next(d for d in rag.documents() if d["filename"] == name)


def test_page_mapping_preserved(rag):
    chunks = rag.registry.all_chunks()
    reg = [c for c in chunks if c.filename == "Academic_Regulations_2026.pdf"]
    assert {c.page for c in reg} == {1, 2, 3}
    attendance = [c for c in reg if "75% attendance" in c.text]
    assert attendance and all(c.page == 1 for c in attendance)
    assert all(c.chunk_id.startswith(c.doc_id) for c in chunks)


def test_scanned_page_is_ocrd(rag):
    from raguard.ingestion import ocr_status

    if not ocr_status()[0]:
        pytest.skip("OCR engine not installed")
    notice = _doc(rag, "Admission_Notice_2026.pdf")
    assert 2 in notice["ocr_pages"]
    ocr_text = " ".join(c.text for c in rag.registry.load_chunks(notice["doc_id"]) if c.page == 2)
    assert "9:30" in ocr_text or "Hostel" in ocr_text


def test_visual_pages_and_tables_detected(rag):
    reg = _doc(rag, "Academic_Regulations_2026.pdf")
    assert 3 in reg["visual_pages"]  # bar chart
    kinds = {c.kind for c in rag.registry.load_chunks(reg["doc_id"])}
    assert "visual" in kinds


def test_running_header_removed(rag):
    texts = [c.text for c in rag.registry.all_chunks() if c.filename == "Academic_Regulations_2026.pdf"]
    assert not any("Northfield Institute" in t for t in texts)


@pytest.mark.parametrize("name,data,msg", [
    ("notes.docx", b"PK\x03\x04", "Unsupported"),
    ("fake.pdf", b"hello", "not a valid PDF"),
    ("empty.pdf", b"", "empty"),
    ("pic.png", b"GIF89a", "not a valid PNG"),
])
def test_invalid_uploads_rejected(rag, name, data, msg):
    with pytest.raises(UploadRejected, match=msg):
        validate_upload(name, data, rag.s)


def test_reupload_is_idempotent(rag, sample_dir):
    before = len(rag.registry.all_chunks())
    out = rag.ingest("Academic_Regulations_2026.pdf", (sample_dir / "Academic_Regulations_2026.pdf").read_bytes())
    assert out.ok and "Already" in out.message
    assert len(rag.registry.all_chunks()) == before


def test_delete_removes_everything(rag, sample_dir):
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Temporary notice about the canteen timings: 8 AM to 6 PM.")
    data = doc.tobytes()
    out = rag.ingest("temp_notice.pdf", data)
    assert out.ok
    assert rag.chroma.ids_for(out.doc_id)
    rag.delete(out.doc_id)
    assert rag.registry.get(out.doc_id) is None
    assert not rag.chroma.ids_for(out.doc_id)
    assert all(c.doc_id != out.doc_id for c in rag.bm25.chunks)
