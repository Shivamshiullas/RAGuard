from __future__ import annotations

import datetime as dt

import streamlit as st

from .common import card, get_adaption, get_evaluator, get_rag, get_store, hero, pill, simulated_banner


def _when(ts: float | None) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d %b %H:%M") if ts else "-"


def render() -> None:
    rag = get_rag()
    hero("RAGuard", "Ask your academic documents anything, with page-level citations, and an honest answer "
                    "when the evidence isn't there.")
    simulated_banner()
    s = rag.system_status()
    docs = rag.documents()
    ready = [d for d in docs if d.get("status") == "ready"]
    datasets = get_store().list()
    runs = get_evaluator().list_runs()

    c = st.columns(4)
    c[0].markdown(card("Documents", str(len(ready)), f"{sum(d.get('pages', 0) for d in ready)} pages indexed"), unsafe_allow_html=True)
    c[1].markdown(card("Indexed chunks", str(s["registry_chunks"]),
                       f"{sum(len(d.get('ocr_pages') or []) for d in ready)} OCR pages · "
                       f"{sum(len(d.get('visual_pages') or []) for d in ready)} visual pages"), unsafe_allow_html=True)
    c[2].markdown(card("Datasets", str(len(datasets)), f"{sum(d.get('records', 0) for d in datasets)} QA records"), unsafe_allow_html=True)
    last = runs[0]["metrics"] if runs else None
    c[3].markdown(card("Last eval hit rate", f"{last['retrieval_hit_rate']}%" if last and last.get("retrieval_hit_rate") is not None else "-",
                       f"{runs[0]['label']} · n={last['n_total']}" if last else "no evaluation run yet"), unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Recent uploads")
        if not docs:
            st.info("No documents yet. Add academic PDFs in the **Document Library** (or load the sample set).")
        for d in docs[:6]:
            kind = {"ready": "ok", "processing": "info", "failed": "bad", "rejected": "bad"}.get(d.get("status"), "info")
            st.markdown(f"**{d.get('filename')}** {pill(d.get('status', '?'), kind)} "
                        f"<span class='rg-muted'>{d.get('pages', '-')} pages · {d.get('chunks', '-')} chunks · "
                        f"{_when(d.get('uploaded_at'))}</span>", unsafe_allow_html=True)
    with right:
        st.subheader("System status")
        rows = [
            ("Vector store", f"ChromaDB {s['chroma']} · {s['chroma_chunks'] if s['chroma_chunks'] is not None else '?'} vectors", s["chroma"] == "online"),
            ("Keyword fallback", f"BM25 in-memory index · {s['bm25_chunks']} chunks", s["bm25_chunks"] > 0 or not ready),
            ("Index manifest", s["manifest"], s["manifest_ok"]),
            ("Vector/registry sync", "in sync" if s["in_sync"] else "out of sync - rebuild from the Library page", s["in_sync"]),
            ("Embeddings", s["embedder"], True),
            ("Language model", s["llm"], s["llm_enabled"]),
            ("OCR", s["ocr_message"], s["ocr"]),
            ("Adaption", get_adaption().status().message, get_adaption().status().configured),
        ]
        for name, detail, ok in rows:
            st.markdown(f"{pill('●', 'ok' if ok else 'warn')} **{name}** <span class='rg-muted'>{detail}</span>",
                        unsafe_allow_html=True)

    st.divider()
    st.markdown("#### How RAGuard answers")
    st.markdown(
        "1. **Retrieve** with ChromaDB (semantic) *and* an independent BM25 index (keywords), fused by rank.\n"
        "2. **Recover** from failures: timeouts, bounded retries with backoff, and keyword fallback if the vector store "
        "or embedding model is down.\n"
        "3. **Gate** the evidence: passages must actually match the question; otherwise RAGuard abstains.\n"
        "4. **Answer** only from evidence, with `[E#]` citations validated against the retrieved chunks.\n"
        "5. **Measure** it: the Data Lab builds a quality-checked QA dataset, and the Evaluation page reports real metrics.")
