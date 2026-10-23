from __future__ import annotations

import datetime as dt
import time

import pandas as pd
import streamlit as st

from raguard.adaption_client import AdaptionNotAvailable, match_adapted_rows
from raguard.config import ROOT
from raguard.datalab import (QUESTION_TYPES, REVIEW_STATES, DatasetGenerator, QARecord, check_quality, load_golden,
                             to_adaption_rows, to_csv, to_jsonl)

from .common import get_adaption, get_rag, get_store, hero, pill, simulated_banner, strip_context

STATUS_KIND = {"ai_generated": "warn", "auto_validated": "info", "human_reviewed": "ok", "rejected": "bad"}


def _save(name: str, records: list[QARecord], **meta) -> None:
    get_store().save(name, records, **meta)


def _generate_section(rag) -> None:
    docs = [d for d in rag.documents() if d.get("status") == "ready"]
    if not docs:
        st.info("Add documents in the Document Library to generate a dataset.")
        return
    names = {d["doc_id"]: d["filename"] for d in docs}
    with st.form("gen"):
        c1, c2 = st.columns(2)
        chosen = c1.multiselect("Source documents", list(names), default=list(names), format_func=names.get)
        ds_name = c2.text_input("Dataset name", f"academic_qa_{dt.datetime.now():%Y%m%d_%H%M}")
        c3, c4, c5, c6 = st.columns(4)
        per_chunk = c3.number_input("Questions per passage", 1, 4, 2)
        max_chunks = c4.number_input("Passages to sample", 2, 60, 12)
        n_unans = c5.number_input("Unanswerable questions", 0, 20, 4)
        n_comp = c6.number_input("Comparative questions", 0, 10, 2)
        c7, c8 = st.columns(2)
        use_llm = c7.toggle("Use language model", value=rag.llm.enabled, disabled=not rag.llm.enabled,
                            help="Without a model, questions are template-generated and marked as such.")
        malayalam = c8.toggle("Add Malayalam variants (needs a language model)", value=False, disabled=not rag.llm.enabled)
        go = st.form_submit_button("Generate dataset", type="primary")
    if go:
        chunks = [c for c in rag.registry.all_chunks() if c.doc_id in set(chosen)]
        with st.spinner("Generating question-answer pairs…"):
            gen = DatasetGenerator(rag.llm, rag.retrieve)
            records, notes = gen.generate(chunks, int(per_chunk), int(n_unans), int(n_comp), malayalam, use_llm,
                                          int(max_chunks))
        with st.spinner("Running quality checks…"):
            summary = check_quality(records, rag.registry.chunk_by_id(), rag.retrieve)
        _save(ds_name, records, quality=summary, source_docs=[names[d] for d in chosen])
        st.session_state["dataset"] = ds_name.replace(" ", "_")
        st.success(f"Created **{ds_name}** with {len(records)} records: {summary['auto_validated']} passed automatic "
                   f"checks, {summary['needs_review']} need review.")
        for n in notes:
            st.caption(f"ℹ {n}")

    st.caption("Or start from the hand-written test set for the sample documents:")
    if st.button("Import golden test set (24 human-written questions)"):
        recs, skipped = load_golden(ROOT / "evaluation" / "golden_questions.json", rag.registry.all_chunks())
        if recs:
            summary = check_quality(recs, rag.registry.chunk_by_id(), rag.retrieve)
            _save("golden_set", recs, quality=summary, source="evaluation/golden_questions.json")
            st.session_state["dataset"] = "golden_set"
            st.success(f"Imported {len(recs)} human-reviewed records.")
        if skipped:
            st.warning(f"{len(skipped)} question(s) skipped because their document is not in the library.")


def _inspect_section(rag, name: str, records: list[QARecord]) -> None:
    meta = get_store().meta(name)
    by_status = {s: sum(r.review_status == s for r in records) for s in REVIEW_STATES}
    st.markdown("".join(pill(f"{s.replace('_', ' ')}: {n}", STATUS_KIND[s]) for s, n in by_status.items()) +
                pill(f"{sum(r.language == 'ml' for r in records)} Malayalam", "info"), unsafe_allow_html=True)
    q = meta.get("quality") or {}
    if q:
        st.caption(f"Last quality check: {q.get('duplicates', 0)} duplicates · {q.get('inconsistent', 0)} inconsistent · "
                   f"{q.get('unsupported', 0)} unsupported · {q.get('untraceable', 0)} untraceable · "
                   f"{q.get('missing_fields', 0)} missing fields · {q.get('answerability_mismatch', 0)} answerability mismatches")

    f1, f2, f3 = st.columns(3)
    fs = f1.multiselect("Status", REVIEW_STATES, placeholder="All statuses")
    ft = f2.multiselect("Type", QUESTION_TYPES, placeholder="All types")
    issues_only = f3.toggle("Only records with issues")
    view = [r for r in records if (not fs or r.review_status in fs) and (not ft or r.question_type in ft)
            and (not issues_only or r.quality_issues)]
    df = pd.DataFrame([{"id": r.record_id, "status": r.review_status, "type": r.question_type, "lang": r.language,
                        "question": r.question, "answer": r.answer,
                        "source": f"{r.source_filename} p.{r.source_page}" if r.answerable else "(unanswerable)",
                        "generator": r.generator, "issues": "; ".join(r.quality_issues)} for r in view])
    st.dataframe(df, width="stretch", hide_index=True, height=320)

    if not view:
        return
    rid = st.selectbox("Inspect record", [r.record_id for r in view],
                       format_func=lambda i: next(f"{r.record_id} · {r.question[:80]}" for r in view if r.record_id == i))
    rec = next(r for r in records if r.record_id == rid)
    c1, c2 = st.columns([3, 2])
    with c1:
        new_q = st.text_area("Question", rec.question, key=f"q_{rid}")
        new_a = st.text_area("Answer", rec.answer, key=f"a_{rid}")
        note = st.text_input("Reviewer note", rec.reviewer_note, key=f"n_{rid}")
        b1, b2, b3 = st.columns(3)
        if b1.button("Approve", key=f"ok_{rid}", type="primary"):
            rec.question, rec.answer, rec.reviewer_note, rec.review_status = new_q, new_a, note, "human_reviewed"
            _save(name, records)
            st.rerun()
        if b2.button("Reject", key=f"rej_{rid}"):
            rec.reviewer_note, rec.review_status = note, "rejected"
            _save(name, records)
            st.rerun()
        if b3.button("Save edit only", key=f"ed_{rid}"):
            rec.question, rec.answer, rec.reviewer_note = new_q, new_a, note
            _save(name, records)
            st.rerun()
    with c2:
        st.markdown(pill(rec.review_status, STATUS_KIND[rec.review_status]) + pill(rec.question_type, "info") +
                    pill(rec.generator, "info"), unsafe_allow_html=True)
        for i in rec.quality_issues:
            st.caption(f"⚠ {i}")
        if rec.answerable:
            st.markdown(f"**Evidence** · {rec.source_filename} p.{rec.source_page}")
            st.markdown(f'<div class="rg-evidence">{strip_context(rec.source_passage)[:1200]}</div>', unsafe_allow_html=True)
        else:
            st.caption("Unanswerable by design: RAGuard should abstain on this question.")

    if st.button("Re-run quality checks on this dataset"):
        with st.spinner("Checking…"):
            summary = check_quality(records, rag.registry.chunk_by_id(), rag.retrieve)
        _save(name, records, quality=summary)
        st.rerun()

    st.markdown("**Export**")
    e1, e2, e3, e4 = st.columns(4)
    e1.download_button("JSONL", to_jsonl(records), f"{name}.jsonl", "application/json")
    e2.download_button("CSV", to_csv(records), f"{name}.csv", "text/csv")
    approved = [r for r in records if r.review_status in {"auto_validated", "human_reviewed"}]
    e3.download_button(f"Validated only ({len(approved)})", to_jsonl(approved), f"{name}_validated.jsonl", "application/json")
    if e4.button("Delete dataset"):
        get_store().delete(name)
        st.session_state.pop("dataset", None)
        st.rerun()


def _adaption_section(rag, name: str, records: list[QARecord]) -> None:
    svc = get_adaption()
    store = get_store()
    meta = store.meta(name)
    status = svc.status()
    kind = "ok" if status.connected else "info" if status.configured else "warn"
    st.markdown(pill("LIVE · Adaption API" if status.configured else "Adaption not configured", kind) +
                f" <span class='rg-muted'>{status.message}</span>", unsafe_allow_html=True)
    if not status.configured:
        st.info("Set `ADAPTION_API_KEY` in `.env` and restart to enable these steps. Everything else in RAGuard works "
                "without it. No Adaption result is ever simulated: without a key these steps simply don't run.")
        return
    if st.button("Test connection"):
        st.write(svc.status(test_connection=True).message)

    rows = to_adaption_rows([r for r in records if r.review_status in {"auto_validated", "human_reviewed"}])
    st.caption(f"{len(rows)} validated/reviewed records will be sent as prompt / completion / context rows "
               "(rejected and failing records are excluded).")
    ad_id = meta.get("adaption_dataset_id")

    try:
        c1, c2, c3 = st.columns(3)
        if c1.button("1 · Upload to Adaption", disabled=not rows):
            with st.spinner("Uploading and waiting for Adaption to ingest…"):
                res = svc.upload(rows, f"raguard_{name}")
            store.update_meta(name, adaption_dataset_id=res["dataset_id"], adaption_uploaded_at=time.time())
            st.success(f"Uploaded: Adaption dataset `{res['dataset_id']}` ({res['row_count']} rows ingested).")
            ad_id = res["dataset_id"]
        if ad_id:
            st.caption(f"Adaption dataset id: `{ad_id}`")
            if c2.button("2 · Estimate adaptation cost"):
                est = svc.estimate(ad_id, len(rows))
                store.update_meta(name, adaption_estimate=est)
                st.info(f"Estimated credits: **{est['estimated_credits']}**, about {est['estimated_minutes']} min.")
            est = store.meta(name).get("adaption_estimate")
            confirm = st.checkbox(f"I understand this starts a real Adaptive Data run that consumes credits"
                                  f"{f' (estimate: {est['estimated_credits']})' if est else ''}.")
            if c3.button("3 · Start adaptation", disabled=not confirm):
                run = svc.adapt(ad_id, len(rows))
                store.update_meta(name, adaption_run=run)
                st.success(f"Adaptive Data run started: `{run['run_id']}`.")

            d1, d2, d3 = st.columns(3)
            if d1.button("Check status"):
                st.json(svc.job_status(ad_id))
            if d2.button("Fetch Adaption quality evaluation"):
                ev = svc.evaluation(ad_id)
                store.update_meta(name, adaption_evaluation=ev)
                q = ev.get("quality") or {}
                if q:
                    st.success(f"Adaption quality score: {q.get('score_before')} → {q.get('score_after')} "
                               f"(grade {q.get('grade_before')} → {q.get('grade_after')}, "
                               f"{q.get('improvement_percent')}% improvement) - as reported by Adaption.")
                else:
                    st.info(f"Evaluation status: {ev.get('status')} (no quality metrics yet).")
            if d3.button("Download adapted dataset"):
                adapted = svc.download(ad_id)
                originals = {r.record_id: r for r in records}
                pairs, unmatched = match_adapted_rows(adapted, originals)
                new = []
                for orig, prompt in pairs:
                    rec = QARecord(**{**orig.to_dict(), "record_id": f"{orig.record_id}-ad", "question": prompt,
                                      "parent_record_id": orig.record_id, "generator": "adaption",
                                      "review_status": "ai_generated", "quality_issues": []})
                    new.append(rec)
                if new:
                    summary = check_quality(new, rag.registry.chunk_by_id(), rag.retrieve)
                    store.save(f"{name}_adapted", new, quality=summary, adapted_from=name, adaption_dataset_id=ad_id)
                    st.success(f"Saved {len(new)} adapted records as dataset **{name}_adapted**. "
                               "Compare them against the original on the Evaluation page.")
                if unmatched:
                    st.warning(f"{unmatched} adapted row(s) could not be matched to an original record by record_id "
                               "and were not imported (their source pages are unknown).")
    except AdaptionNotAvailable as e:
        st.error(str(e))
    except Exception as e:
        st.error(svc.explain(e))

    ops = svc.operations(20)
    if ops:
        with st.expander("Adaption operation log (real API calls)"):
            st.dataframe(pd.DataFrame([{"time": dt.datetime.fromtimestamp(o["ts"]).strftime("%H:%M:%S"), "operation": o["op"],
                                        "ok": o["ok"], "dataset": o.get("dataset_id", ""),
                                        "detail": o.get("error") or {k: v for k, v in o.items()
                                                                     if k not in {"ts", "op", "ok", "source", "dataset_id"}}}
                                       for o in ops]), width="stretch", hide_index=True)


def render() -> None:
    rag = get_rag()
    hero("Academic Data Lab", "Turn your documents into a traceable, quality-checked question-answer dataset, "
                              "refine it with Adaption, and use it to measure RAGuard.")
    simulated_banner()
    tab_gen, tab_inspect, tab_ad = st.tabs(["Generate", "Inspect & review", "Adaption"])
    with tab_gen:
        _generate_section(rag)
    datasets = [d["name"] for d in get_store().list()]
    current = st.session_state.get("dataset")
    with tab_inspect:
        if not datasets:
            st.info("No datasets yet.")
        else:
            name = st.selectbox("Dataset", datasets, index=datasets.index(current) if current in datasets else 0, key="ds_inspect")
            st.session_state["dataset"] = name
            _inspect_section(rag, name, get_store().load(name))
    with tab_ad:
        if not datasets:
            st.info("Create a dataset first.")
        else:
            name = st.selectbox("Dataset", datasets, index=datasets.index(current) if current in datasets else 0, key="ds_ad")
            _adaption_section(rag, name, get_store().load(name))
