from __future__ import annotations

import pandas as pd
import streamlit as st

from raguard.faults import LABELS, faults

from .common import MODE_TEXT, get_rag, hero, pill, render_answer, render_trace, simulated_banner

DESCRIPTIONS = {
    "chroma_down": "Every ChromaDB call raises a connection error, like a crashed or unreachable server.",
    "embedding_down": "The embedding model raises on every call, so no query vector can be produced.",
    "embedding_slow": "The embedding call hangs past its timeout (tests timeouts and the request deadline).",
    "vector_empty": "ChromaDB responds, but with zero results.",
    "vector_irrelevant": "ChromaDB responds with random, unrelated chunks.",
    "llm_down": "The language model provider fails; RAGuard falls back to showing extracted evidence.",
}

SCENARIOS = [
    ("Normal operation", {}),
    ("ChromaDB outage", {"chroma_down": True}),
    ("Embedding model down", {"embedding_down": True}),
    ("Empty vector results", {"vector_empty": True}),
    ("Irrelevant vector results", {"vector_irrelevant": True}),
]


def render() -> None:
    rag = get_rag()
    hero("Reliability Demo", "Inject failures on purpose and watch RAGuard recover, or refuse to guess. "
                             "Every injected failure is labelled as simulated.")
    simulated_banner()
    if not rag.documents():
        st.info("Load documents in the **Document Library** first.")
        return

    st.subheader("1 · Side-by-side: normal vs. failure")
    q = st.text_input("Question", "What is the condonation fee for low attendance?")
    fault = st.selectbox("Failure to inject", [k for k in LABELS if k != "llm_down"], format_func=LABELS.get)
    st.caption(DESCRIPTIONS[fault])
    if st.button("Run comparison", type="primary"):
        left, right = st.columns(2)
        with left:
            st.markdown(f"#### Normal {pill('baseline', 'ok')}", unsafe_allow_html=True)
            with st.spinner("Running…"):
                res = rag.ask(q)
            render_answer(res)
        with right:
            st.markdown(f"#### {LABELS[fault]} {pill('SIMULATED', 'sim')}", unsafe_allow_html=True)
            with st.spinner("Running with injected failure…"):
                with faults.scoped(**{fault: True}):
                    res = rag.ask(q)
            render_answer(res)
            st.markdown("**What happened**")
            render_trace(res.all_events)

    st.divider()
    st.subheader("2 · Fault suite")
    st.caption("Runs each scenario on a few questions (retrieval only) and records whether evidence was still found.")
    qs = st.text_area("Questions (one per line)", "What minimum attendance is required?\n"
                      "When do the hostel gates close?\nWhat is the hostel fee for international students?").splitlines()
    if st.button("Run fault suite"):
        rows = []
        bar = st.progress(0.0)
        total = len(SCENARIOS) * len([x for x in qs if x.strip()])
        n = 0
        for name, flags in SCENARIOS:
            for question in [x.strip() for x in qs if x.strip()]:
                with faults.scoped(**flags):
                    r = rag.retrieve(question)
                n += 1
                bar.progress(n / total)
                rows.append({"scenario": name + (" (simulated)" if flags else ""), "question": question,
                             "path": MODE_TEXT.get(r.mode, (r.mode,))[0],
                             "outcome": "evidence found" if r.sufficient else "abstained",
                             "top source": f"{r.evidence[0].chunk.filename} p.{r.evidence[0].chunk.page}" if r.sufficient and r.evidence else "-",
                             "retries": sum(e.status == "retry" for e in r.events),
                             "latency ms": round(r.latency_ms)})
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Unanswerable questions should show 'abstained' in every scenario. Crashes would appear as errors; "
                   "none are expected.")

    st.divider()
    st.subheader("3 · Persistent fault switches")
    st.caption("Keep a failure active while you use the AI Assistant. A banner on every page shows that simulation is on.")
    cols = st.columns(3)
    for i, (key, label) in enumerate(LABELS.items()):
        on = cols[i % 3].toggle(label, value=faults.is_on(key), key=f"tg_{key}", help=DESCRIPTIONS[key])
        if on != faults.is_on(key):
            faults.set(**{key: on})
            st.rerun()
    if faults.any_active() and st.button("Turn off all simulated failures"):
        faults.clear()
        for key in LABELS:
            st.session_state[f"tg_{key}"] = False
        st.rerun()
    if rag.s.chroma_host:
        st.info(f"ChromaDB runs as a server at {rag.chroma.location}. For a real (not simulated) outage, stop that "
                "server: RAGuard takes the same recovery path.")
    else:
        st.caption("Tip: set CHROMA_HOST to run ChromaDB as a separate server (`chroma run --path data/chroma_server`); "
                   "you can then stop it for a real outage test.")
