"""Load the fictional sample documents through the normal ingestion pipeline.

    python -m college_rag.seed            (from the backend folder)

Files already uploaded (same content hash) are skipped, so it is safe to rerun.
"""

from __future__ import annotations

import json
import sys

from .config import BACKEND_DIR, configure_logging, get_settings
from .ingestion import UploadMetadata, UploadRejected, upload_document
from .runtime import get_store

SAMPLES = BACKEND_DIR / "sample_docs"


def main() -> int:
    configure_logging(get_settings())
    manifest = json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))
    for item in manifest:
        path = SAMPLES / item["file"]
        meta = UploadMetadata(
            title=item["title"], category=item["category"], semester=item.get("semester"),
            academic_year=item.get("academicYear"), effective_date=item.get("effectiveDate"),
        )
        try:
            doc_id, version = upload_document(path.name, path.read_bytes(), meta, run_async=False)
        except UploadRejected as exc:
            print(f"skip  {path.name}: {exc}")
            continue
        row = get_store().get_version(doc_id, version)
        detail = f"{row.chunk_count} chunks" + (", OCR" if row.ocr_required else "") if row.stage == "indexed" else row.error
        print(f"{row.stage:7} {path.name}: {detail}")
    print(f"Knowledge-base generation: {get_store().kb_generation()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
