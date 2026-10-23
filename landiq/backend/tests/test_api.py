"""HTTP API contract, demo data integrity and upload validation."""

from __future__ import annotations

import time

import pytest
from conftest import DOSSIER, make_pdf, parcels_geojson
from fastapi.testclient import TestClient

from landiq.api import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client) -> str:
    return client.post("/api/v1/projects", json={"name": "Corridor X", "corridor_id": "CX-1"}).json()["project_id"]


def _wait(client, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["state"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_end_to_end_over_http(client, project):
    up = client.post(f"/api/v1/projects/{project}/documents", files={"file": ("d.pdf", make_pdf([DOSSIER]), "application/pdf")})
    assert up.status_code == 201 and up.json()["status"] == "STORED"
    client.post(f"/api/v1/projects/{project}/maps", files={"file": ("p.geojson", parcels_geojson())})
    res = client.post(f"/api/v1/projects/{project}/analysis-jobs")
    assert res.status_code == 202 and res.json()["state"] == "QUEUED"
    job = _wait(client, res.json()["job_id"])
    assert job["state"] == "SUCCEEDED" and job["prediction_readiness"] == "NOT_READY"

    results = client.get(f"/api/v1/jobs/{job['job_id']}/results").json()
    assert results["complete"] and len(results["cases"]) == 2
    cases = client.get(f"/api/v1/projects/{project}/cases").json()
    detail = client.get(f"/api/v1/cases/{cases[0]['case_id']}").json()
    fact_ids = {fid for fv in detail["case"]["fields"].values() for fid in fv["facts"]}
    assert fact_ids <= set(detail["facts"])  # every cited fact resolves to provenance
    fc = client.get(f"/api/v1/projects/{project}/map-features").json()
    assert fc["type"] == "FeatureCollection" and len(fc["features"]) == 3 and not fc["synthetic"]

    ans = client.post(f"/api/v1/cases/{project}.0472/ask", json={"question": "What is the legal status?"}).json()
    assert ans["status"] == "ANSWERED" and ans["evidence"][0]["page"] == 1

    # Same inputs -> same job (idempotent).
    again = client.post(f"/api/v1/projects/{project}/analysis-jobs").json()
    assert again["job_id"] == job["job_id"]


def test_upload_validation_errors(client, project):
    assert client.post(f"/api/v1/projects/{project}/documents", files={"file": ("x.txt", b"hello")}).status_code == 415
    assert client.post(f"/api/v1/projects/{project}/documents", files={"file": ("x.pdf", b"")}).status_code == 400
    assert client.post(f"/api/v1/projects/{project}/maps", files={"file": ("x.exe", b"MZ")}).status_code == 415
    assert client.post(f"/api/v1/projects/{project}/maps", files={"file": ("x.zip", b"nope")}).status_code == 415
    assert client.post("/api/v1/projects/nope/documents", files={"file": ("x.pdf", b"%PDF")}).status_code == 404
    assert client.post(f"/api/v1/projects/{project}/analysis-jobs").status_code == 400  # nothing uploaded


def test_oversized_upload_is_413(client, project, monkeypatch):
    from landiq.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pdf_mb", 0)
    assert client.post(f"/api/v1/projects/{project}/documents",
                       files={"file": ("d.pdf", make_pdf([DOSSIER]))}).status_code == 413


def test_duplicate_upload_is_idempotent(client, project):
    data = make_pdf([DOSSIER])
    a = client.post(f"/api/v1/projects/{project}/documents", files={"file": ("d.pdf", data)}).json()
    b = client.post(f"/api/v1/projects/{project}/documents", files={"file": ("again.pdf", data)}).json()
    assert b["status"] == "DUPLICATE" and b["id"] == a["id"]


def test_failed_processing_is_reported_in_job_status_not_http(client, project):
    client.post(f"/api/v1/projects/{project}/documents", files={"file": ("bad.pdf", b"%PDF-1.4 corrupted")})
    res = client.post(f"/api/v1/projects/{project}/analysis-jobs")
    assert res.status_code == 202
    job = _wait(client, res.json()["job_id"])
    assert job["state"] == "FAILED" and job["pdf_agent"]["errors"][0]["code"] == "PDF_CORRUPT" and job["remediation"]


def test_demo_counts_are_consistent_and_labelled(client):
    summary = client.get("/api/v1/projects/demo-dme-pkg4/summary").json()
    cases = client.get("/api/v1/projects/demo-dme-pkg4/cases").json()
    assert summary["total"] == len(cases) == 840
    for risk in ("HIGH", "MEDIUM", "LOW"):
        assert summary["counts"][risk] == sum(1 for c in cases if c["illustrative"]["riskCategory"] == risk)
    assert summary["counts"] == {"HIGH": 28, "MEDIUM": 162, "LOW": 650}
    assert all(c["is_synthetic"] and c["prediction"]["status"] == "DEMO_ONLY"
               and c["prediction"]["delay_probability"] is None for c in cases)
    assert cases[0]["case_ref"] == "#0472" and cases[0]["illustrative"]["delayProbability"] == 82
    assert "Illustrative" in summary["label"]
    assert client.get("/api/v1/projects/demo-dme-pkg4/map-features").json()["synthetic"] is True


def test_demo_is_read_only(client):
    assert client.post("/api/v1/projects/demo-dme-pkg4/documents",
                       files={"file": ("d.pdf", make_pdf([DOSSIER]))}).status_code == 400
    assert client.post("/api/v1/cases/demo-dme-pkg4.0472/ask", json={"question": "legal status?"}).status_code == 400


def test_action_workflow_is_recorded_only(client, project):
    client.post(f"/api/v1/projects/{project}/documents", files={"file": ("d.pdf", make_pdf([DOSSIER]))})
    _wait(client, client.post(f"/api/v1/projects/{project}/analysis-jobs").json()["job_id"])
    action = client.get(f"/api/v1/cases/{project}.0472").json()["case"]["actions"][0]
    res = client.post(f"/api/v1/actions/{action['action_id']}/workflow", json={"status": "ESCALATED"}).json()
    assert "No message or order is sent" in res["note"]
    again = client.get(f"/api/v1/cases/{project}.0472").json()["case"]["actions"]
    assert next(a for a in again if a["action_id"] == action["action_id"])["workflow_status"] == "ESCALATED"


def test_health_reports_prediction_not_ready(client):
    body = client.get("/api/v1/health").json()
    assert body["prediction"]["status"] == "NOT_READY"
