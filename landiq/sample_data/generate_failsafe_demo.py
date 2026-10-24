"""One upload set that triggers failsafes in both agents, with every recovery outcome.

Run:  python landiq/sample_data/generate_failsafe_demo.py   -> writes landiq/sample_data/failsafe_demo/
Upload everything in documents/ as PDFs and everything in maps/ as GIS files into one
new project, then run an analysis job. See failsafe_demo/README.md for the expected result.
Requires generate.py, generate_gis.py and generate_bad_inputs.py to have been run first.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
OUT = HERE / "failsafe_demo"


def mixed_pages_pdf(path: Path) -> None:
    """Page 1 has text; page 2 is a blank scan that even OCR cannot read."""
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 800), (
        "SITE INSPECTION REPORT\n"
        "Case ID: #0618\n"
        "Village: Dharuhera, District: Rewari\n"
        "Approval status: Cleared\n"
        "Page 2 (attached site photograph) follows."), fontsize=11)
    blank = pymupdf.open()
    blank.new_page().draw_rect(pymupdf.Rect(80, 80, 515, 760), color=(0.85, 0.85, 0.85), width=1)
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842),
                                stream=blank[0].get_pixmap(dpi=100).tobytes("jpeg", jpg_quality=60))
    doc.save(path)


def partly_broken_geojson(path: Path) -> None:
    """Valid parcels and alignment, plus two parcels with self-intersecting geometry."""
    fc = json.loads((HERE / "gis" / "1_corridor_parcels.geojson").read_text(encoding="utf-8"))
    fc["features"] += [
        {"type": "Feature", "properties": {"parcel_id": "P-BAD-01", "survey_no": "999/1"},
         "geometry": {"type": "Polygon", "coordinates": [[[76.68, 28.21], [76.684, 28.214], [76.684, 28.21],
                                                          [76.68, 28.214], [76.68, 28.21]]]}},
        {"type": "Feature", "properties": {"parcel_id": "P-BAD-02", "survey_no": "999/2"},
         "geometry": {"type": "Polygon", "coordinates": [[[76.69, 28.22], [76.694, 28.224], [76.694, 28.22],
                                                          [76.69, 28.224], [76.69, 28.22]]]}},
    ]
    path.write_text(json.dumps(fc, indent=1), encoding="utf-8")


def main() -> None:
    docs, maps = OUT / "documents", OUT / "maps"
    for folder in (docs, maps):  # keep README.md
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)

    shutil.copy(HERE / "corridor_dossier.pdf", docs / "1_corridor_dossier.pdf")  # clean: no failsafe
    shutil.copy(HERE / "scanned_notice.pdf", docs / "2_scanned_notice.pdf")  # OCR_USED -> succeeded
    mixed_pages_pdf(docs / "3_inspection_report_with_blank_page.pdf")  # PAGES_UNREADABLE -> partial
    shutil.copy(HERE / "bad_inputs" / "doc_password_protected.pdf", docs / "4_password_protected.pdf")  # failed

    partly_broken_geojson(maps / "1_parcels_two_broken.geojson")  # GEOMETRY_INVALID -> partial
    shutil.copy(HERE / "gis" / "5_parcel_sketch_unreferenced.png", maps / "2_parcel_sketch.png")  # partial
    shutil.copy(HERE / "bad_inputs" / "map_shapefile_missing_prj.zip", maps / "3_shapefile_missing_prj.zip")  # failed
    print(f"Failsafe demo set written to {OUT}")


if __name__ == "__main__":
    main()
