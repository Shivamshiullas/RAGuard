from __future__ import annotations

import datetime as dt
import json

import pandas as pd
import streamlit as st

from raguard.faults import LABELS

from .common import card, get_evaluator, get_rag, get_store, hero, pill, simulated_banner

METRICS = [
    ("retrieval_hit_rate", "Retrieval hit rate", "%", "Answerable questions whose source page is in the top-k."),
    ("mrr", "MRR", "", "Mean reciprocal rank of the source page."),
    ("citation_correctness", "Citation correctness", "%", "Answered questions citing the source page (needs an LLM)."),
    ("evidence_support", "Evidence support", "%", "Answers with no validation warnings (needs an LLM)."),
    ("correct_abstention", "Correct abstention", "%", "Unanswerable questions RAGuard declined."),
    ("false_abstention", "False abstention", "%", "Answerable questions RAGuard declined (lower is better)."),
    ("latency_p50_ms", "Latency p50", " ms", ""),
    ("latency_p95_ms", "Latency p95", " ms", ""),
]


def _fmt(v, unit: str) -> str:
    return "n/a" if v is None else f"{v}{unit}"


def render() -> None:
    rag = get_rag()
    ev = get_evaluator()
    hero("Evaluation", "Measured, not claimed: run RAGuard against a dataset under normal and simulated-failure "
                       "conditions. Every number below comes from an actual run.")
    simulated_banner()
    datasets = [d["name"] for d in get_store().list()]
    if not datasets:
        st.info("Create or import a dataset in the **Academic Data Lab** first (the golden test set is a good start).")
        return

    with st.form("run"):
        c1, c2 = st.columns([2, 1])
        name = c1.selectbox("Dataset", datasets)
        k = c2.number_input("k (top-k for hit rate)", 1, 20, rag.s.top_k)
        c3, c4 = st.columns(2)
        conditions = c3.multiselect("Conditions", ["normal"] + [f for f in LABELS if f != "llm_down"],
                                    default=["normal", "chroma_down"],
                                    format_func=lambda f: "Normal" if f == "normal" else f"{LABELS[f]} (simulated)")
        with_llm = c4.toggle("Generate answers with the language model", value=False, disabled=not rag.llm.enabled,
                             help="Off: retrieval-only (fast, free). On: full answers, citation and support checks.")
        include_unreviewed = st.toggle("Include records that failed automatic checks", value=False)
        go = st.form_submit_button("Run evaluation", type="primary")

    if go:
        records = get_store().load(name)
        if not include_unreviewed:
            records = [r for r in records if r.review_status in {"auto_validated", "human_reviewed"}]
        if not records:
            st.warning("No records to evaluate with the current filters.")
        for cond in conditions:
            bar = st.progress(0.0, text=f"{cond}: 0/{len(records)}")
            flags = {} if cond == "normal" else {cond: True}
            run = ev.run(records, name, cond if cond == "normal" else f"{LABELS[cond]} (simulated)", flags, with_llm, int(k),
                         progress=lambda i, n, b=bar, c=cond: b.progress(i / n, text=f"{c}: {i}/{n}"))
            bar.empty()
            st.success(f"{run.label}: {run.metrics['n_total']} records evaluated.")

    runs = ev.list_runs()
    if not runs:
        return
    st.divider()
    st.subheader("Results")
    latest = runs[0]
    m = latest["metrics"]
    st.markdown(pill(latest["label"], "sim" if latest["config"].get("faults") else "ok") +
                pill(f"dataset {latest['dataset']}", "info") + pill(f"n = {m['n_total']}", "info") +
                pill(latest["config"]["llm"], "info"), unsafe_allow_html=True)
    cols = st.columns(4)
    for i, (key, label, unit, help_) in enumerate(METRICS):
        cols[i % 4].markdown(card(label, _fmt(m.get(key), unit), help_), unsafe_allow_html=True)
        if i % 4 == 3:
            cols = st.columns(4)
    for lim in latest.get("limitations", []):
        st.caption(f"Limitation: {lim}")

    st.markdown("#### Compare runs")
    table = pd.DataFrame([{
        "run": f"{dt.datetime.fromtimestamp(r['created_at']):%d %b %H:%M:%S}",
        "condition": r["label"], "dataset": r["dataset"], "n": r["metrics"]["n_total"],
        "hit rate %": r["metrics"]["retrieval_hit_rate"], "MRR": r["metrics"]["mrr"],
        "citation %": r["metrics"]["citation_correctness"], "support %": r["metrics"]["evidence_support"],
        "correct abstain %": r["metrics"]["correct_abstention"], "false abstain %": r["metrics"]["false_abstention"],
        "recovered": r["metrics"]["recovered_requests"], "p95 ms": r["metrics"]["latency_p95_ms"],
        "answers": "LLM" if r["config"]["llm"] != "none (retrieval only)" else "retrieval only",
    } for r in runs[:30]])
    st.dataframe(table, width="stretch", hide_index=True)

    adapted = [d for d in get_store().list() if d.get("adapted_from")]
    if adapted:
        st.caption("Adaption comparison: run the same conditions on a dataset and its `_adapted` version. Both share "
                   "the same source pages, so their hit rates are directly comparable.")

    with st.expander("Per-question outcomes (latest run)"):
        out = pd.DataFrame(latest["outcomes"])
        if not out.empty:
            out = out[["question", "question_type", "answerable", "source", "hit_rank", "abstained", "status", "mode",
                       "recovered", "latency_ms", "error"]]
            st.dataframe(out, width="stretch", hide_index=True)
        st.download_button("Download run JSON", json.dumps(latest, indent=2, default=str),
                           f"raguard_eval_{latest['run_id']}.json", "application/json")
