"""Generate a synthetic sample corridor that exercises every LANDIQ pipeline path.

Run from anywhere:  python landiq/sample_data/generate.py
Writes PDFs and GeoJSON next to this script. All names, places and numbers are fictional.
"""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent

DOSSIER_PAGES = [
    """REWARI BYPASS CORRIDOR - PACKAGE 2
LAND ACQUISITION CASE DOSSIER
Compiled by the District Land Acquisition Office, October 2026.
This dossier summarises the status of every acquisition case on the corridor.
Each section below covers exactly one case.""",
    """Case ID: #0472
Village: Kishangarh Khurd, District: Rewari
Parcel ID: P-0472-A
Survey No. 142/3A, 142/3B and 143/1 covering 17.3 ha.
Legal status: Dispute - title partition suit pending before District Revenue Tribunal.
Compensation status: Pending
Award of Rs. 14.85 Cr notified on 12.03.2026.
Only 28% of the compensation has been disbursed so far.
Approval status: Delayed (Stage-II forest clearance pending for 95 days)
R&R progress stands at 63% with 14 families awaiting transit allowance.
Next hearing listed on 18.11.2026 before the Tribunal.

Case ID: #0511
Village: Rampura Kalan, District: Rewari
Survey No. 88/1, 88/4 covering 17.3 ha.
Legal status: No pending litigation; title verified.
Compensation status: Disputed - 18 landowners appealed the award.
Award of Rs. 9.20 Cr notified on 03.02.2026.
Approval status: Cleared
R&R status: Completed""",
    """Case ID: #0618
Village: Dharuhera, District: Rewari
Parcel ID: P-0618-A
Survey No. 210/2 covering 17.3 ha.
Legal status: Clear
Compensation status: Fully disbursed
Compensation award of Rs. 6.40 Cr; 100% paid to all 22 landowners.
Approval status: Cleared
R&R status: Completed
Project progress: 88% of civil works completed.

Case ID: #0655
Village: Bawal, District: Rewari
Parcel ID: P-0655-A
Survey No. 45/7 covering 25 ha.
A writ petition challenging the acquisition notification is pending in the High Court.
The compensation award is still awaiting approval from the state committee.
Deadline for filing objections: 30.11.2026.""",
    """Case ID: #0705
Village: Khol, District: Rewari
Survey No. 301/2, 301/5 covering 17.3 ha.
Legal status: Pending settlement through Lok Adalat mediation.
Compensation status: In progress - partially disbursed.
Approval status: Under review
R&R status: In progress

Case ID: #0706
Village: Khol, District: Rewari
Survey No. 301/2, 302/1
Legal status: Clear
Compensation status: Pending
Approval status: Pending
R&R status: Not started""",
]

TRIBUNAL_ORDER = """ORDER OF THE DISTRICT REVENUE TRIBUNAL, REWARI
Dated 02.04.2026

Case ID: #0472
In the matter of the partition suit concerning Survey No. 142/3A and 142/3B.
Legal status: Clear - the partition suit was withdrawn by all parties on 02.04.2026.
The Tribunal records that no further proceedings remain pending."""

COMPENSATION_REGISTER = """COMPENSATION DISBURSEMENT REGISTER - PACKAGE 2
Prepared by the Land Acquisition Collector, September 2026.

Case ID: #0511
Award of Rs. 9.20 Cr; 40% disbursed to landowners who did not appeal.
Compensation status: Disputed - appeal pending before the Reference Court.

Case ID: #0705
Compensation award of Rs. 3.75 Cr; 55% paid as of 15.09.2026.

Case ID: #0655
Compensation award of Rs. 11.10 Cr has not yet been disbursed."""

SCANNED_NOTICE = """GAZETTE NOTIFICATION (SCANNED COPY)
Case ID: #0706
Village: Khol, District: Rewari
Notification under Section 11 published on 14.08.2026.
Approval status: Pending"""


def write_pdf(name: str, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=10)
    doc.save(OUT / name)


def write_scanned_pdf(name: str, text: str) -> None:
    """Image-only PDF (no selectable text): the PDF agent has to read it with OCR."""
    src = pymupdf.open()
    src.new_page().insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=12)
    jpeg = src[0].get_pixmap(dpi=150).tobytes("jpeg", jpg_quality=70)
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=jpeg)
    doc.save(OUT / name)


def square(lng: float, lat: float, d: float = 0.004) -> dict:
    return {"type": "Polygon", "coordinates": [[[lng, lat], [lng + d, lat], [lng + d, lat + d], [lng, lat + d], [lng, lat]]]}


def feature(props: dict, geometry: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": geometry}


def write_geojson() -> None:
    features = [
        feature({"name": "Rewari Bypass alignment", "role": "alignment"},
                {"type": "LineString", "coordinates": [[76.60, 28.18], [76.63, 28.19], [76.66, 28.20], [76.69, 28.21]]}),
        # Labelled with a case ID, crossed by the alignment.
        feature({"parcel_id": "P-0472-A", "case_id": "#0472", "survey_no": "142/3A", "zone": "Zone A",
                 "village": "Kishangarh Khurd"}, square(76.610, 28.181)),
        # No case ID: joined to #0511 through its survey number.
        feature({"parcel_id": "P-0511-A", "survey_no": "88/1", "zone": "Zone A"}, square(76.625, 28.187)),
        feature({"parcel_id": "P-0618-A", "case_id": "#0618", "survey_no": "210/2", "zone": "Zone B"},
                square(76.640, 28.192)),
        # Away from the alignment; recorded 25 ha vs ~17 ha mapped -> area-mismatch warning.
        feature({"parcel_id": "P-0655-A", "case_id": "#0655", "survey_no": "45/7", "zone": "Zone B"},
                square(76.650, 28.230)),
        # Survey 301/2 appears in both #0705 and #0706 -> ambiguous match, job NEEDS_CLARIFICATION.
        feature({"parcel_id": "P-KHOL-301", "survey_no": "301/2", "zone": "Zone C"}, square(76.670, 28.201)),
        # Self-intersecting "bow-tie" polygon -> quarantined as invalid geometry.
        feature({"parcel_id": "P-BAD-01", "survey_no": "999/9"},
                {"type": "Polygon", "coordinates": [[[76.68, 28.21], [76.684, 28.214], [76.684, 28.21],
                                                     [76.68, 28.214], [76.68, 28.21]]]}),
    ]
    (OUT / "corridor_parcels.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features},
                                                             indent=1))


def main() -> None:
    write_pdf("corridor_dossier.pdf", DOSSIER_PAGES)
    write_pdf("tribunal_order.pdf", [TRIBUNAL_ORDER])
    write_pdf("compensation_register.pdf", [COMPENSATION_REGISTER])
    write_scanned_pdf("scanned_notice.pdf", SCANNED_NOTICE)
    write_geojson()
    print(f"Sample data written to {OUT}")


if __name__ == "__main__":
    main()
