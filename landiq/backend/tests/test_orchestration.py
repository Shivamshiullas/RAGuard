"""Orchestration, fault tolerance, failsafe gates, fusion and recovery."""

from __future__ import annotations

from conftest import DOSSIER, add_input, feature, geojson, make_pdf, make_scanned_pdf, new_project, parcels_geojson, run, square

from landiq import faults, orchestrator, pdf_agent
from landiq.config import get_settings
from landiq.runtime import get_repo
from landiq.schemas import AgentState, JobIn, JobState, PredictionStatus, StageState


def _setup(pdf: bytes | None = None, gis: bytes | None = None) -> str:
    pid = new_project()
    if pdf is not None:
        add_input(pid, "document", "dossier.pdf", pdf)
    if gis is not None:
        add_input(pid, "map", "parcels.geojson", gis)
    return pid


def _case(pid: str, ref: str):
    return get_repo().get_case(f"{pid}.{ref.lstrip('#')}")


# --- Happy path ------------------------------------------------------------------


def test_full_pipeline_succeeds_with_traceable_cases():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    job = run(pid)
    assert job.state == JobState.SUCCEEDED
    assert job.pdf_agent.state == AgentState.SUCCEEDED and job.map_agent.state == AgentState.SUCCEEDED
    assert job.pdf_agent.checkpoint and job.map_agent.checkpoint and job.fusion.checkpoint
    assert job.retrieval.state == StageState.SUCCEEDED
    assert job.prediction_readiness == PredictionStatus.NOT_READY
    assert [a.action for a in job.audit] == ["START", "RUN_AGENTS", "CHECK_RETRIEVAL", "FUSE", "CHECK_PREDICTION", "FINALIZE"]

    c472 = _case(pid, "#0472")
    assert c472.fields["legal_status"].value == "DISPUTE" and c472.fields["legal_status"].status == "KNOWN"
    assert c472.spatial["intersects_alignment"] is True and c472.geometry_refs
    assert c472.prediction.status == PredictionStatus.NOT_READY and c472.prediction.delay_probability is None
    assert all(a.evidence and a.requires_human_review for a in c472.actions)
    # Parcel without a case attribute joined to #0511 through an exact survey-number match.
    c511 = _case(pid, "#0511")
    assert any(r["feature_id"].endswith("-1") for r in c511.geometry_refs)
    assert c511.fields["clearance_status"].status == "UNKNOWN" and c511.fields["clearance_status"].value is None


def test_job_creation_is_idempotent():
    pid = _setup(make_pdf([DOSSIER]))
    first, created1 = orchestrator.create_job(pid, JobIn(), None)
    second, created2 = orchestrator.create_job(pid, JobIn(), None)
    assert created1 and not created2 and first.job_id == second.job_id


# --- Independent agents / partial results ----------------------------------------


def test_pdf_agent_failure_keeps_map_results():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    with faults.injected("pdf_agent"):
        job = run(pid)
    assert job.state == JobState.PARTIAL and job.pdf_agent.state == AgentState.FAILED
    assert job.map_agent.state == AgentState.SUCCEEDED and len(get_repo().list_features(pid)) == 3
    c472 = _case(pid, "#0472")
    assert c472.geometry_refs and c472.fields["legal_status"].status == "UNKNOWN"  # no invented document facts
    assert "Document analysis did not complete" in job.remediation


def test_map_agent_failure_keeps_pdf_results_and_disables_spatial():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    with faults.injected("map_agent"):
        job = run(pid)
    assert job.state == JobState.PARTIAL and job.map_agent.state == AgentState.FAILED
    assert job.pdf_agent.state == AgentState.SUCCEEDED
    c472 = _case(pid, "#0472")
    assert c472.fields["legal_status"].value == "DISPUTE"
    assert c472.spatial == {} and any("spatial conclusions are disabled" in w for w in c472.warnings)
    assert not any("alignment" in a.title for a in c472.actions)


def test_needs_ocr_pdf_with_valid_map_is_partial():
    pid = _setup(make_scanned_pdf(), parcels_geojson())
    job = run(pid)
    assert job.pdf_agent.state == AgentState.NEEDS_OCR and job.state == JobState.PARTIAL
    assert any(e.code == "NEEDS_OCR" for e in job.pdf_agent.errors)


def test_all_inputs_invalid_is_safe_failure_with_remediation():
    pid = new_project()
    add_input(pid, "document", "broken.pdf", b"%PDF-1.7 broken")
    add_input(pid, "map", "broken.geojson", b"{not json")
    job = run(pid)
    assert job.state == JobState.FAILED and job.remediation and "start a new job" in job.remediation
    assert {i.status for i in get_repo().list_inputs(pid)} == {"QUARANTINED"}
    assert get_repo().list_cases(pid) == []


# --- Retries, timeouts, invalid output ------------------------------------------------


def test_transient_failure_is_retried_then_succeeds():
    pid = _setup(make_pdf([DOSSIER]))
    with faults.injected("pdf_flaky"):
        job = run(pid)
    assert job.state == JobState.SUCCEEDED and job.pdf_agent.attempts == 2
    assert any("retrying" in w for w in job.pdf_agent.warnings)


def test_transient_failures_stop_at_attempt_limit():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    with faults.injected("pdf_transient"):
        job = run(pid)
    assert job.pdf_agent.attempts == get_settings().agent_max_attempts
    assert job.pdf_agent.errors[-1].code == "TRANSIENT_ERROR" and job.pdf_agent.errors[-1].transient
    assert job.state == JobState.PARTIAL  # map results still delivered


def test_permanent_failure_is_not_retried_and_is_quarantined():
    pid = new_project()
    doc = add_input(pid, "document", "broken.pdf", b"%PDF-1.7 broken")
    add_input(pid, "map", "p.geojson", parcels_geojson())
    job = run(pid)
    assert job.pdf_agent.attempts == 1 and job.pdf_agent.errors[0].code == "PDF_CORRUPT"
    row = get_repo().get_input(doc)
    assert row.status == "QUARANTINED" and "quarantine" in str(row.path)


def test_agent_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(get_settings(), "agent_timeout_s", 0.3)
    monkeypatch.setattr(get_settings(), "agent_max_attempts", 2)
    pid = _setup(make_pdf([DOSSIER]))
    with faults.injected("pdf_timeout"):
        job = run(pid)
    assert job.pdf_agent.attempts == 2 and job.pdf_agent.errors[-1].code == "AGENT_TIMEOUT"
    assert job.state == JobState.FAILED


def test_invalid_agent_output_never_reaches_fusion():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    with faults.injected("pdf_invalid_output"):
        job = run(pid)
    assert job.pdf_agent.state == AgentState.FAILED
    assert job.pdf_agent.errors[-1].code == "AGENT_OUTPUT_INVALID"
    assert not any(f.provenance.kind == "document" for f in get_repo().list_facts(pid))
    assert _case(pid, "#0472").fields["legal_status"].status == "UNKNOWN"


def test_invalid_map_output_is_rejected():
    pid = _setup(None, parcels_geojson())
    with faults.injected("map_invalid_output"):
        job = run(pid)
    assert job.map_agent.state == AgentState.FAILED and get_repo().list_features(pid) == []


def test_fusion_failure_keeps_agent_results():
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    with faults.injected("fusion"):
        job = run(pid)
    assert job.state == JobState.PARTIAL and job.fusion.state == StageState.FAILED
    results = orchestrator.job_results(job)
    assert results.pdf.documents[0].facts and results.map.maps[0].features and results.cases == []


def test_step_budget_stops_safely(monkeypatch):
    monkeypatch.setattr(get_settings(), "job_max_steps", 2)
    pid = _setup(make_pdf([DOSSIER]))
    job, _ = orchestrator.create_job(pid, JobIn(), None)
    job = orchestrator.run_job(job.job_id)
    assert job.state == JobState.PARTIAL and job.steps_used == 2
    assert any(a.action == "STOP_BUDGET" for a in job.audit)


# --- Checkpoints and restart recovery -----------------------------------------------------


def test_restart_resumes_from_checkpoints(monkeypatch):
    pid = _setup(make_pdf([DOSSIER]), parcels_geojson())
    job = run(pid)
    # Simulate a crash after the agents finished: job left RUNNING in storage.
    job.state = JobState.RUNNING
    get_repo().save_job(job)

    calls = []
    real = pdf_agent.extract_document

    def counting(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    monkeypatch.setattr(orchestrator, "extract_document", counting)
    from landiq import runtime

    runtime.reset()  # new process: fresh repository object on the same files
    runner = orchestrator.JobRunner(1)
    assert runner.resume_pending() == 1
    runner._pool.shutdown(wait=True)
    resumed = get_repo().get_job(job.job_id)
    assert resumed.state == JobState.SUCCEEDED and resumed.resumed_count == 1
    assert calls == []  # the PDF was not processed again
    assert _case(pid, "#0472").fields["legal_status"].value == "DISPUTE"


# --- Conflicts and ambiguous matches -----------------------------------------------------


def test_conflicting_sources_are_preserved_not_resolved():
    pid = new_project()
    add_input(pid, "document", "a.pdf", make_pdf(["Case ID: #0472\nLegal status: Dispute pending in tribunal"]))
    add_input(pid, "document", "b.pdf", make_pdf(["Case ID: #0472\nLegal status: Clear, title verified"]))
    job = run(pid)
    case = _case(pid, "#0472")
    field = case.fields["legal_status"]
    assert field.status == "CONFLICT" and field.value is None and set(field.alternatives) == {"DISPUTE", "CLEAR"}
    conflict = get_repo().list_conflicts(pid)[0]
    assert conflict.status == "INVESTIGATED" and "human review" in conflict.note.lower()
    assert any(a.action == "INVESTIGATE_CONFLICT" for a in job.audit)
    assert any("Reconcile conflicting records" in a.title for a in case.actions)


def test_ambiguous_parcel_match_requests_clarification():
    pid = new_project()
    add_input(pid, "document", "a.pdf", make_pdf(["Case ID: #0101\nSurvey No. 55/1\nLegal status: Clear",
                                                   "Case ID: #0202\nSurvey No. 55/1\nLegal status: Dispute"]))
    add_input(pid, "map", "p.geojson", geojson([feature({"parcel_id": "PX", "survey_no": "55/1"}, square(77.0, 28.5))]))
    job = run(pid)
    assert job.state == JobState.NEEDS_CLARIFICATION and len(job.clarifications) == 1
    match = job.clarifications[0]
    assert match.candidates == ["#0101", "#0202"]
    assert not _case(pid, "#0101").geometry_refs and not _case(pid, "#0202").geometry_refs  # not merged

    get_repo().put_resolution(pid, match.match_id, "#0202")
    remaining = orchestrator.refuse_project(pid)
    assert remaining == [] and _case(pid, "#0202").geometry_refs
    assert get_repo().get_job(job.job_id).state == JobState.SUCCEEDED


def test_pages_with_text_but_no_facts_are_reextracted():
    pid = _setup(make_pdf(["General notes about the corridor survey programme and its timeline.", DOSSIER]))
    job = run(pid)
    assert any(a.action == "REEXTRACT_PAGES" for a in job.audit)
