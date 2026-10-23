from __future__ import annotations

import streamlit as st

from .common import get_rag, hero, render_answer, simulated_banner

EXAMPLES = [
    "What are the attendance requirements for examination eligibility?",
    "What documents are required for admission?",
    "What is the project submission deadline?",
    "Explain the topics listed under Unit 3 of the syllabus.",
    "What does the grade distribution chart show?",
    "What is the hostel fee for international students?",
]


def render() -> None:
    rag = get_rag()
    hero("AI Assistant", "Answers come only from your documents, with page citations you can check. "
                         "If the evidence isn't there, RAGuard says so.")
    simulated_banner()
    docs = [d for d in rag.documents() if d.get("status") == "ready"]
    if not docs:
        st.info("Add documents in the **Document Library** first.")
        return

    names = {d["doc_id"]: d["filename"] for d in docs}
    selected = st.multiselect("Search in", options=list(names), format_func=names.get,
                              placeholder="All documents", help="Leave empty to search the whole library.")
    st.session_state.setdefault("chat", [])

    st.caption("Try:")
    cols = st.columns(3)
    clicked = None
    examples = [q for q in EXAMPLES if rag.s.on("vision") or "chart" not in q]
    for i, q in enumerate(examples):
        if cols[i % 3].button(q, key=f"ex{i}", width="stretch"):
            clicked = q

    for turn in st.session_state.chat:
        with st.chat_message("user"):
            st.markdown(turn["q"])
        with st.chat_message("assistant", avatar="🛡️"):
            render_answer(turn["res"])

    question = st.chat_input("Ask about your documents…") or clicked
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant", avatar="🛡️"):
            with st.spinner("Retrieving evidence and checking it…"):
                res = rag.ask(question, selected or None)
            render_answer(res)
        st.session_state.chat.append({"q": question, "res": res})

    if st.session_state.chat and st.button("Clear conversation"):
        st.session_state.chat = []
        st.rerun()
    st.caption("Each question is answered independently from the documents. RAGuard is not an official authority: "
               "confirm important decisions with your institution.")
