"""Fixtures: isolated storage per test, a scriptable fake LLM and input builders."""

from __future__ import annotations

import io
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from landiq import config, faults, llm, orchestrator, runtime  # noqa: E402
from landiq.llm import LLMClient, LLMUnavailable  # noqa: E402
from landiq.schemas import JobIn  # noqa: E402


class FakeLLM(LLMClient):
    """mode: cite | insufficient | uncited | bad_citation | conflict | down"""

    def __init__(self):
        self.mode = "cite"
        self.prompts: list[str] = []

    def generate_json(self, prompt, model, system=None):
        self.prompts.append(prompt)
        if self.mode == "down":
            raise LLMUnavailable("fake outage")
        first = re.search(r"\[E1\] \(.*?\)\n<<<\n(.*?)\n>>>", prompt, re.S)
        text = first.group(1)[:120] if first else ""
        data = {
            "cite": {"answer": f"{text} [E1]"},
            "insufficient": {"answer": "Not in the evidence.", "insufficient_evidence": True},
            "uncited": {"answer": "The compensation is Rs. 99 Cr."},
            "bad_citation": {"answer": f"{text} [E42]"},
            "conflict": {"answer": "One record says X [E1], another Y [E2].", "conflict": True},
        }[self.mode]
        return model.model_validate(data)

    def health(self):
        return {"fake": True}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("FAULTS", "")
    monkeypatch.setenv("RETRY_BASE_DELAY_S", "0.01")
    monkeypatch.setenv("RETRY_MAX_DELAY_S", "0.05")
    monkeypatch.setenv("MODEL_PATH", "")
    # Strict defaults for the existing gate tests; the scorecard and OCR have their own tests.
    monkeypatch.setenv("RISK_SCORER", "off")
    monkeypatch.setenv("OCR_ENGINES", "")
    config.get_settings.cache_clear()
    runtime.reset()
    faults.configure("")
    fake = FakeLLM()
    llm.set_llm(fake)
    yield fake
    llm.set_llm(None)
    runtime.reset()
    config.get_settings.cache_clear()


@pytest.fixture
def fake_llm(isolated) -> FakeLLM:
    return isolated


# ---------------------------------------------------------------------------
# Input builders
# ---------------------------------------------------------------------------

DOSSIER = """LAND ACQUISITION CASE DOSSIER - NHAI-DME-PKG4
Case ID: #0472
Village: Kishangarh Khurd, District: Rewari
Survey No. 142/3A, 142/3B and 143/1 covering 18.4 ha.
Legal status: Dispute - title partition suit pending before District Revenue Tribunal.
Compensation status: Pending
Award of Rs. 14.85 Cr notified on 12.03.2025; 28% of the award disbursed so far.
Approval status: Delayed (Stage-II forest clearance pending for 95 days)
R&R progress stands at 63% with 14 families awaiting transit allowance.
Project progress: 71% of civil subgrade completed.

Case ID: #0511
Village: Rampura Kalan, District: Rewari
Survey No. 88/1, 88/4
Legal status: No pending litigation; title verified.
Compensation status: Disputed - 18 landowners appealed the award."""


def make_pdf(pages: list[str]) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 800), text, fontsize=10)
    return doc.tobytes()


def make_scanned_pdf() -> bytes:
    import pymupdf

    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 545, 800), DOSSIER, fontsize=10)
    png = p.get_pixmap(dpi=72).tobytes("png")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=png)
    return doc.tobytes()


def feature(props: dict, geometry: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": geometry}


def square(lng: float, lat: float, d: float = 0.005) -> dict:
    return {"type": "Polygon", "coordinates": [[[lng, lat], [lng + d, lat], [lng + d, lat + d], [lng, lat + d], [lng, lat]]]}


ALIGNMENT = feature({"name": "DME alignment", "role": "alignment"},
                    {"type": "LineString", "coordinates": [[77.0, 28.45], [77.05, 28.47], [77.1, 28.5]]})


def geojson(features: list[dict]) -> bytes:
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def parcels_geojson() -> bytes:
    return geojson([
        feature({"parcel_id": "P-0472-A", "case_id": "#0472", "survey_no": "142/3A", "zone": "Zone A"},
                square(77.02, 28.455)),
        feature({"parcel_id": "P-X", "survey_no": "88/1"}, square(77.06, 28.477)),
        ALIGNMENT,
    ])


def shapefile_zip(include_prj: bool = True) -> bytes:
    import tempfile

    import geopandas as gpd

    tmp = Path(tempfile.mkdtemp())
    gdf = gpd.read_file(io.BytesIO(parcels_geojson())).iloc[:2].to_crs("EPSG:32643")
    gdf.to_file(tmp / "p.shp")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            if ext == ".prj" and not include_prj:
                continue
            z.write(tmp / f"p{ext}", f"p{ext}")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Job helpers (synchronous, no background runner)
# ---------------------------------------------------------------------------


def new_project(name: str = "Test corridor") -> str:
    import uuid

    from landiq.schemas import Project

    pid = "prj_" + uuid.uuid4().hex[:8]
    runtime.get_repo().put_project(Project(project_id=pid, name=name, corridor_id="TEST-1"))
    return pid


def add_input(project_id: str, kind: str, filename: str, data: bytes) -> str:
    import hashlib
    import uuid

    settings = config.get_settings()
    input_id = ("doc_" if kind == "document" else "map_") + uuid.uuid4().hex[:10]
    path = settings.uploads_dir / f"{input_id}{Path(filename).suffix}"
    path.write_bytes(data)
    runtime.get_repo().add_input(input_id, project_id, kind, filename, hashlib.sha256(data).hexdigest(), len(data),
                                 path, "STORED")
    return input_id


def run(project_id: str, **kwargs):
    job, _ = orchestrator.create_job(project_id, JobIn(**kwargs), None)
    return orchestrator.run_job(job.job_id)
