"""Phase 10: HTTP API used by the frontend."""

from __future__ import annotations

import time

import pytest
from conftest import CAMPUS_TEXT, make_pdf, text_image
from fastapi.testclient import TestClient

from college_rag.api import app, settings


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin(client):
    token = client.post("/api/admin/login", json={"username": settings.admin_username, "password": settings.admin_password}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def wait_indexed(client, admin, doc_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = next(d for d in client.get("/api/documents", headers=admin).json() if d["id"] == doc_id)
        if doc["versions"][-1]["stage"] in ("indexed", "failed"):
            return doc
        time.sleep(0.2)
    raise AssertionError("document was not processed in time")


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] in ("ok", "degraded") and "kbGeneration" in body


def test_login_rejects_bad_credentials(client):
    assert client.post("/api/admin/login", json={"username": "admin", "password": "nope"}).status_code == 401


def test_document_routes_require_admin(client):
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/documents", files={"file": ("a.txt", b"x")}, data={"title": "t", "category": "c"}).status_code == 401


def test_upload_index_and_chat_end_to_end(client, admin):
    res = client.post(
        "/api/documents", headers=admin,
        files={"file": ("campus.txt", CAMPUS_TEXT.encode(), "text/plain")},
        data={"title": "Campus Information", "category": "Campus & facilities", "academicYear": "2026-27"},
    )
    assert res.status_code == 202
    doc = res.json()
    assert doc["title"] == "Campus Information" and doc["versions"][0]["fileKind"] == "txt"
    doc = wait_indexed(client, admin, doc["id"])
    assert doc["versions"][-1]["stage"] == "indexed" and doc["academicYear"] == "2026-27"

    chat = client.post("/api/chat", data={"message": "Where is the campus located?"}).json()
    assert chat["status"] == "success" and chat["route"] == "college_specific"
    assert chat["sources"][0]["filename"] == "campus.txt" and chat["sources"][0]["page"] == 1
    assert chat["requestId"] and chat["tasks"] == {"completed": 1, "total": 1, "items": chat["tasks"]["items"]}
    assert chat["recovery"] == {"attempted": False, "method": None, "status": "not_needed"}

    # Deactivate -> no evidence; reactivate -> answer again.
    client.post(f"/api/documents/{doc['id']}/active", headers=admin, json={"active": False})
    assert client.post("/api/chat", data={"message": "Where is the campus located?"}).json()["status"] == "no_evidence"
    client.post(f"/api/documents/{doc['id']}/active", headers=admin, json={"active": True})
    assert client.post("/api/chat", data={"message": "Where is the campus located?"}).json()["status"] == "success"


def test_new_version_and_duplicate_via_api(client, admin):
    pdf = make_pdf(["Semester 5 tuition fee is Rs. 64,500."])
    doc = client.post("/api/documents", headers=admin, files={"file": ("fees.pdf", pdf, "application/pdf")},
                      data={"title": "Fees", "category": "Fees"}).json()
    wait_indexed(client, admin, doc["id"])
    dup = client.post("/api/documents", headers=admin, files={"file": ("again.pdf", pdf, "application/pdf")},
                      data={"title": "Fees", "category": "Fees"})
    assert dup.status_code == 409
    v2 = client.post("/api/documents", headers=admin,
                     files={"file": ("fees2.pdf", make_pdf(["Semester 5 tuition fee is Rs. 66,000."]), "application/pdf")},
                     data={"title": "Fees", "category": "Fees", "replacesId": doc["id"]}).json()
    assert v2["id"] == doc["id"] and len(v2["versions"]) == 2
    assert wait_indexed(client, admin, doc["id"])["versions"][-1]["stage"] == "indexed"


def test_invalid_upload_returns_message(client, admin):
    res = client.post("/api/documents", headers=admin, files={"file": ("x.exe", b"MZ")},
                      data={"title": "Bad", "category": "Other"})
    assert res.status_code == 400 and "Unsupported file type" in res.json()["detail"]


def test_chat_validation(client):
    assert client.post("/api/chat", data={"message": "  "}).status_code == 400
    assert client.post("/api/chat", data={"message": "x" * 2001}).status_code == 400
    bad = client.post("/api/chat", data={"message": "what is this"}, files={"image": ("a.png", b"not an image", "image/png")})
    assert bad.status_code == 400 and "PNG or JPG" in bad.json()["detail"]


def test_chat_with_image(client, admin):
    doc = client.post("/api/documents", headers=admin, files={"file": ("campus.txt", CAMPUS_TEXT.encode())},
                      data={"title": "Campus", "category": "Campus & facilities"}).json()
    wait_indexed(client, admin, doc["id"])
    res = client.post("/api/chat", data={"message": "what is this about?"},
                      files={"image": ("shot.png", text_image("Library opening hours on weekdays"), "image/png")})
    body = res.json()
    assert res.status_code == 200 and "image_agent" in body["agents"] and body["sources"]


def test_greeting_via_api(client):
    body = client.post("/api/chat", data={"message": "hi"}).json()
    assert body["status"] == "general" and body["sources"] == [] and body["tasks"]["total"] == 0
