from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import fitz
import streamlit as st

from raguard.config import ROOT

from raguard.ingestion import supported_types

from .common import get_rag, hero, pill, simulated_banner, strip_context

SAMPLE_DIR = ROOT / "sample_docs"


def _ingest(rag, items: list[tuple[str, bytes]]) -> None:
    progress = st.progress(0.0, text="Processing…")
    for i, (name, data) in enumerate(items, start=1):
        progress.progress((i - 1) / len(items), text=f"Processing {name} ({i}/{len(items)})…")
        out = rag.ingest(name, data)
        if out.ok:
            st.success(f"**{out.filename}**: {out.message}")
        else:
            st.error(f"**{out.filename}**: {out.message}")
        for w in out.warnings:
            st.warning(f"{out.filename}: {w}")
    progress.progress(1.0, text="Done")


@st.cache_data(show_spinner=False, max_entries=64)
def _page_png(path: str, page: int) -> bytes:
    with fitz.open(path) as doc:
        return doc[page - 1].get_pixmap(dpi=90).tobytes("png")


def render() -> None:
    rag = get_rag()
    hero("Document Library", "Upload syllabi, regulations, notices and handbooks. Each page is extracted, "
                             "OCR'd if scanned, and indexed for semantic and keyword search.")
    simulated_banner()

    up_col, sample_col = st.columns([3, 1])
    with up_col:
        types = sorted(t.strip(".") for t in supported_types(rag.s))
        files = st.file_uploader(f"Upload academic documents ({', '.join(t.upper() for t in types)}, "
                                 f"max {rag.s.max_upload_mb} MB each)", type=types, accept_multiple_files=True)
        if files and st.button(f"Process {len(files)} file(s)", type="primary"):
            _ingest(rag, [(f.name, f.getvalue()) for f in files])
    with sample_col:
        st.markdown("**Sample set**")
        st.caption("Synthetic documents from a fictional institute: regulations, a syllabus and an admission "
                   "notice. Some pages are scanned or visual; they are only indexed from Stage 2 on.")
        if st.button("Load sample documents"):
            if not list(SAMPLE_DIR.glob("*.pdf")):
                subprocess.run([sys.executable, str(ROOT / "scripts" / "make_sample_docs.py"), str(SAMPLE_DIR)], check=True)
            _ingest(rag, [(p.name, p.read_bytes()) for p in sorted(SAMPLE_DIR.glob("*.pdf"))])

    st.divider()
    docs = rag.documents()
    head, tools = st.columns([3, 2])
    head.subheader(f"Library ({len(docs)})")
    with tools:
        if rag.s.on("fallbacks") and st.button("Rebuild vector index from source", help="Re-embeds every chunk from the local chunk store. "
                     "Use after a ChromaDB outage, corruption or an embedding-model change."):
            with st.spinner("Re-embedding all chunks…"):
                st.info(rag.rebuild_vector_index())
    h = rag.index_health()
    st.markdown(pill(f"ChromaDB: {h['chroma']} ({h['chroma_chunks'] if h['chroma_chunks'] is not None else '?'} vectors)",
                     "ok" if h["chroma"] == "online" else "bad") +
                (pill(f"BM25: {h['bm25_chunks']} chunks", "ok") if rag.s.on("bm25") else "") +
                pill("indexes in sync" if h["in_sync"] else "indexes out of sync", "ok" if h["in_sync"] else "warn"),
                unsafe_allow_html=True)

    if not docs:
        st.info("The library is empty.")
        return
    for d in docs:
        status = d.get("status", "?")
        kind = {"ready": "ok", "processing": "info", "failed": "bad", "rejected": "bad"}.get(status, "info")
        extras = []
        if d.get("ocr_pages"):
            extras.append(pill(f"OCR p.{', '.join(map(str, d['ocr_pages']))}", "info"))
        if d.get("visual_pages"):
            extras.append(pill(f"visuals p.{', '.join(map(str, d['visual_pages']))}", "info"))
        if status == "ready" and not d.get("vector_indexed", True):
            extras.append(pill("keyword-only (vector indexing failed)", "warn"))
        with st.expander(f"{d.get('filename')}  ·  {status}  ·  {d.get('pages', '-')} pages  ·  {d.get('chunks', '-')} chunks"):
            st.markdown(pill(status, kind) + "".join(extras), unsafe_allow_html=True)
            if d.get("error"):
                st.error(d["error"])
            for w in d.get("warnings") or []:
                st.warning(w)
            if status == "ready":
                path = d.get("path")
                tab_prev, tab_chunks = st.tabs(["Preview", "Extracted chunks"])
                with tab_prev:
                    if path and Path(path).exists() and path.lower().endswith(".pdf"):
                        page = st.number_input("Page", 1, max(1, d.get("pages", 1)), 1, key=f"pg_{d['doc_id']}")
                        st.image(_page_png(path, int(page)), width=520)
                    elif path and Path(path).exists():
                        st.image(path, width=520)
                with tab_chunks:
                    for c in rag.registry.load_chunks(d["doc_id"])[:40]:
                        st.markdown(f"**p.{c.page} · {c.kind}** <span class='rg-muted'>{c.chunk_id}</span>",
                                    unsafe_allow_html=True)
                        st.text(strip_context(c.text)[:600])
            if st.button("Remove document", key=f"del_{d['doc_id']}"):
                st.success(rag.delete(d["doc_id"]))
                st.rerun()
