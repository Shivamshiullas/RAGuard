import fitz
import pytest

from raguard.ingestion import UploadRejected, validate_upload


def _chunks(rag, filename):
    return [c for c in rag.registry.all_chunks() if c.filename == filename]


def test_page_numbers_and_metadata(rag1):
    reg = _chunks(rag1, "Academic_Regulations_2026.pdf")
    assert {c.page for c in reg} == {1, 2, 3}
    for c in reg:
        assert c.doc_id and c.chunk_id.startswith(f"{c.doc_id}:p{c.page}:") and c.filename
    att = [c for c in reg if "75% attendance" in c.text]
    assert att and all(c.page == 1 for c in att)


def test_heading_aware_chunking(rag1):
    syl = _chunks(rag1, "CS201_Data_Structures_Syllabus.pdf")
    unit3 = [c for c in syl if "Unit 3: Trees" in c.text]
    assert len(unit3) == 1
    assert "Unit 4" not in unit3[0].text  # a heading starts a new chunk
    assert "| Unit 3: Trees]" in unit3[0].text.splitlines()[0]  # context line carries the heading


def test_table_kept_whole_in_one_chunk(rag1):
    reg = _chunks(rag1, "Academic_Regulations_2026.pdf")
    rows = ["Internal test 1", "Internal test 2", "Assignments / quizzes", "End-semester examination"]
    holders = [c for c in reg if "|Internal test 1|15|Week 6|" in c.text]
    assert len(holders) == 1, "table must live in exactly one chunk"
    assert all(r in holders[0].text for r in rows)
    assert "|Component|Marks|Conducted in|" in holders[0].text  # bold header keeps its spaces
    others = [c for c in reg if c is not holders[0]]
    assert not any("|Internal test 1|" in c.text for c in others)


def test_long_text_is_split_with_overlap(s1, tmp_path):
    from raguard.ingestion import PDFParser

    doc = fitz.open()
    page = doc.new_page()
    para = " ".join(f"Rule {i} says students must follow procedure number {i}." for i in range(60))
    page.insert_textbox(fitz.Rect(50, 50, 545, 800), para, fontsize=8)
    path = tmp_path / "long.pdf"
    doc.save(path)
    res = PDFParser(s1).parse(path, "d", "long.pdf", "v")
    bodies = [c.text.split("\n", 1)[1] for c in res.chunks]
    assert len(bodies) >= 2
    assert all(len(b) <= s1.chunk_chars + s1.chunk_overlap + 50 for b in bodies)
    tail = bodies[0][-60:].split(". ")[-1][:20]
    assert tail and tail in bodies[1]  # consecutive chunks overlap


def test_running_header_removed(rag1):
    assert not any("Northfield Institute" in c.text for c in _chunks(rag1, "Academic_Regulations_2026.pdf"))


def test_scanned_page_skipped_with_warning(rag1):
    notice = next(d for d in rag1.documents() if d["filename"] == "Admission_Notice_2026.pdf")
    assert any("Stage 2" in w for w in notice["warnings"])
    assert {c.page for c in _chunks(rag1, "Admission_Notice_2026.pdf")} == {1}


@pytest.mark.parametrize("name,data,msg", [
    ("notes.docx", b"PK\x03\x04", "Unsupported"),
    ("fake.pdf", b"hello", "not a valid PDF"),
    ("empty.pdf", b"", "empty"),
    ("scan.png", b"\x89PNG\r\n", "Stage 2"),
])
def test_invalid_uploads_rejected(s1, name, data, msg):
    with pytest.raises(UploadRejected, match=msg):
        validate_upload(name, data, s1)


def test_oversized_upload_rejected(s1):
    with pytest.raises(UploadRejected, match="larger than"):
        validate_upload("big.pdf", b"%PDF" + b"0" * (s1.max_upload_mb * 1024 * 1024 + 1), s1)


def test_password_protected_pdf_rejected(rag1):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "secret syllabus")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    out = rag1.ingest("locked.pdf", data)
    assert not out.ok and "password" in out.message.lower()


def test_page_limit(rag1, s1, monkeypatch):
    from dataclasses import replace

    from raguard.ingestion import PDFParser

    doc = fitz.open()
    for _ in range(3):
        doc.new_page().insert_text((72, 72), "page text that is long enough to count as text")
    path = s1.uploads_dir / "three.pdf"
    doc.save(path)
    with pytest.raises(UploadRejected, match="limit is 2"):
        PDFParser(replace(s1, max_pages=2)).parse(path, "x", "three.pdf", "v")


def test_duplicate_upload_not_reindexed(rag1, sample_dir):
    before = rag1.chroma.count()
    out = rag1.ingest("renamed_copy.pdf", (sample_dir / "Academic_Regulations_2026.pdf").read_bytes())
    assert out.ok and "Already" in out.message
    assert rag1.chroma.count() == before


def test_delete_removes_document(rag1):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Temporary notice: the canteen is open from 8 AM to 6 PM on weekdays.")
    out = rag1.ingest("temp_notice.pdf", doc.tobytes())
    assert out.ok and rag1.chroma.ids_for(out.doc_id)
    rag1.delete(out.doc_id)
    assert rag1.registry.get(out.doc_id) is None and not rag1.chroma.ids_for(out.doc_id)
