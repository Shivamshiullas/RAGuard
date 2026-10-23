"""RAGuard - Streamlit entry point.  Run:  streamlit run app.py   (RAGUARD_STAGE=1|2|3)"""
from __future__ import annotations

import logging

import streamlit as st

from ui import assistant, dashboard, datalab, evaluation, library, reliability
from ui.common import apply_theme, get_adaption, get_rag, pill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="RAGuard", page_icon="🛡️", layout="wide")
apply_theme()

rag = get_rag()
s = rag.s
status = rag.system_status()

with st.sidebar:
    st.markdown("### 🛡️ RAGuard")
    st.caption("Your academic documents. Clear answers. Verifiable evidence.")
    names = {1: "Basic RAG", 2: "Multimodal", 3: "Fault tolerance"}
    pills = [pill(f"Stage {s.stage} · {names[s.stage]}", "info"),
             pill("ChromaDB online", "ok") if status["chroma"] == "online" else pill("ChromaDB offline", "bad"),
             pill("LLM ready" if status["llm_enabled"] else "LLM unavailable", "ok" if status["llm_enabled"] else "bad")]
    if s.on("bm25"):
        pills.append(pill(f"BM25 · {status['bm25_chunks']} chunks", "ok"))
    if s.on("ocr"):
        pills.append(pill("OCR on" if status["ocr"] else "OCR off", "ok" if status["ocr"] else "warn"))
    if s.on("vision"):
        pills.append(pill("Vision on" if status["vision"] else "Vision off", "ok" if status["vision"] else "warn"))
    if s.on("extras"):
        ad = get_adaption().status()
        pills.append(pill("Adaption: " + ("connected" if ad.connected else "configured" if ad.configured else "not configured"),
                          "ok" if ad.connected else "info" if ad.configured else "warn"))
    if status["faults"]:
        pills.append(pill(f"{len(status['faults'])} simulated fault(s)", "sim"))
    st.markdown("".join(pills), unsafe_allow_html=True)
    st.caption(status["llm"])
    if not status.get("embedder_loaded", True):
        st.error("Embedding model not loaded. Run `python scripts/download_models.py`, then restart.")

pages = []
if s.stage >= 3:
    pages.append(st.Page(dashboard.render, title="Dashboard", icon="📊", url_path="dashboard"))
pages += [
    st.Page(library.render, title="Document Library", icon="📚", url_path="library", default=s.stage < 3),
    st.Page(assistant.render, title="AI Assistant", icon="💬", url_path="assistant"),
]
if s.on("fault_injection"):
    pages.append(st.Page(reliability.render, title="Reliability Demo", icon="🛠️", url_path="reliability"))
if s.on("extras"):
    pages += [st.Page(datalab.render, title="Academic Data Lab", icon="🧪", url_path="datalab"),
              st.Page(evaluation.render, title="Evaluation", icon="📈", url_path="evaluation")]
st.navigation(pages).run()
