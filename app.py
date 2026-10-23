"""RAGuard - Streamlit entry point.  Run:  streamlit run app.py"""
from __future__ import annotations

import logging

import streamlit as st

from ui import assistant, dashboard, datalab, evaluation, library, reliability
from ui.common import apply_theme, get_adaption, get_rag, pill

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="RAGuard", page_icon="🛡️", layout="wide")
apply_theme()

rag = get_rag()
status = rag.system_status()

with st.sidebar:
    st.markdown("### 🛡️ RAGuard")
    st.caption("Your academic documents. Clear answers. Verifiable evidence.")
    pills = [
        pill("ChromaDB online", "ok") if status["chroma"] == "online" else pill("ChromaDB offline", "bad"),
        pill(f"BM25 · {status['bm25_chunks']} chunks", "ok"),
        pill("LLM: " + ("on" if status["llm_enabled"] else "off"), "ok" if status["llm_enabled"] else "warn"),
        pill("OCR on" if status["ocr"] else "OCR off", "ok" if status["ocr"] else "warn"),
        pill("Vision on" if status["vision"] else "Vision off", "ok" if status["vision"] else "warn"),
    ]
    ad = get_adaption().status()
    pills.append(pill("Adaption: " + ("connected" if ad.connected else "configured" if ad.configured else "not configured"),
                      "ok" if ad.connected else "info" if ad.configured else "warn"))
    if status["faults"]:
        pills.append(pill(f"{len(status['faults'])} simulated fault(s)", "sim"))
    st.markdown("".join(pills), unsafe_allow_html=True)
    st.caption(status["llm"])

pages = [
    st.Page(dashboard.render, title="Dashboard", icon="📊", url_path="dashboard", default=True),
    st.Page(library.render, title="Document Library", icon="📚", url_path="library"),
    st.Page(assistant.render, title="AI Assistant", icon="💬", url_path="assistant"),
    st.Page(datalab.render, title="Academic Data Lab", icon="🧪", url_path="datalab"),
    st.Page(reliability.render, title="Reliability Demo", icon="🛠️", url_path="reliability"),
    st.Page(evaluation.render, title="Evaluation", icon="📈", url_path="evaluation"),
]
st.navigation(pages).run()
