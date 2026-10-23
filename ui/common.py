"""Shared UI pieces: cached services, theme CSS, status badges and evidence rendering."""
from __future__ import annotations

import html
import re
from pathlib import Path

import streamlit as st

from raguard.adaption_client import AdaptionService
from raguard.answering import render_citations, strip_context
from raguard.config import get_settings
from raguard.datalab import DatasetStore
from raguard.evaluation import Evaluator
from raguard.faults import LABELS, faults
from raguard.models import AnswerResult, RecoveryEvent
from raguard.service import RAGuard

CSS = """
<style>
:root { --navy:#132A4A; --navy2:#1E3A64; --teal:#0E8A8A; --muted:#5B6B82; --line:#DDE5EF; --soft:#F1F5FA; }
.block-container { padding-top: 2.2rem; max-width: 1180px; }
h1, h2, h3 { color: var(--navy); letter-spacing: -0.01em; }
.rg-hero { background: linear-gradient(120deg, #132A4A 0%, #1E3A64 60%, #0E6F78 100%); color: #fff;
  border-radius: 14px; padding: 26px 30px; margin-bottom: 18px; }
.rg-hero h1 { color: #fff; margin: 0 0 4px 0; font-size: 1.9rem; }
.rg-hero p { color: #CFE3F0; margin: 0; font-size: 1.02rem; }
.rg-card { border: 1px solid var(--line); border-radius: 12px; padding: 16px 18px; background: #fff; height: 100%; }
.rg-card .label { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }
.rg-card .value { color: var(--navy); font-size: 1.7rem; font-weight: 700; margin-top: 2px; }
.rg-card .sub { color: var(--muted); font-size: .85rem; }
.rg-pill { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .78rem; font-weight: 600;
  margin: 0 6px 6px 0; border: 1px solid transparent; }
.rg-ok { background:#E6F5EF; color:#11683F; border-color:#BFE6D3; }
.rg-warn { background:#FFF5E1; color:#8A5A00; border-color:#F3DDA8; }
.rg-bad { background:#FDECEC; color:#A12A2A; border-color:#F3C4C4; }
.rg-info { background:#E7F1FA; color:#1E3A64; border-color:#C9DDF0; }
.rg-sim { background:#F3E8FF; color:#5B2A91; border-color:#DCC6F5; }
.rg-evidence { border-left: 3px solid var(--teal); background: var(--soft); padding: 10px 14px; border-radius: 0 8px 8px 0;
  margin: 6px 0 10px 0; font-size: .92rem; color: #22324A; white-space: pre-wrap; }
.rg-evidence .src { font-weight: 700; color: var(--navy2); font-size: .82rem; margin-bottom: 4px; }
.rg-trace { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .8rem; }
.rg-banner-sim { background:#F3E8FF; border:1px solid #DCC6F5; color:#4B2380; padding:10px 14px; border-radius:10px; margin-bottom:12px; }
.rg-muted { color: var(--muted); font-size: .88rem; }
</style>
"""


def apply_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading RAGuard (embedding model, indexes)…")
def get_rag() -> RAGuard:
    rag = RAGuard()
    rag.warm_up()
    return rag


@st.cache_resource
def get_adaption() -> AdaptionService:
    return AdaptionService(get_settings())


def get_store() -> DatasetStore:
    return DatasetStore(get_settings())


def get_evaluator() -> Evaluator:
    return Evaluator(get_rag(), get_settings().eval_dir)


def pill(text: str, kind: str = "info") -> str:
    return f'<span class="rg-pill rg-{kind}">{html.escape(text)}</span>'


def card(label: str, value: str, sub: str = "") -> str:
    return (f'<div class="rg-card"><div class="label">{html.escape(label)}</div>'
            f'<div class="value">{html.escape(str(value))}</div><div class="sub">{html.escape(sub)}</div></div>')


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="rg-hero"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>',
                unsafe_allow_html=True)


def simulated_banner() -> None:
    active = faults.flags.active()
    if active:
        names = ", ".join(LABELS[a] for a in active)
        st.markdown(f'<div class="rg-banner-sim"><b>Simulation mode.</b> These failures are being injected on '
                    f'purpose for the reliability demo: {html.escape(names)}. Turn them off on the Reliability Demo page.</div>',
                    unsafe_allow_html=True)


STATUS_KIND = {"ok": "ok", "retry": "warn", "failed": "bad", "fallback": "warn", "skipped": "info",
               "weak": "warn", "abstain": "bad"}
STATUS_ICON = {"ok": "✓", "retry": "↻", "failed": "✗", "fallback": "⤳", "skipped": "–", "weak": "!", "abstain": "⊘"}


def render_trace(events: list[RecoveryEvent]) -> None:
    rows = []
    for e in events:
        sim = pill("SIMULATED", "sim") if e.simulated else ""
        ms = f"{e.latency_ms:.0f} ms" if e.latency_ms else ""
        rows.append(f'<div class="rg-trace">{pill(STATUS_ICON.get(e.status, "") + " " + e.status, STATUS_KIND.get(e.status, "info"))}'
                    f'<b>{html.escape(e.stage)}</b> · {html.escape(e.detail)} <span class="rg-muted">{ms}</span> {sim}</div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


MODE_TEXT = {"vector": ("Vector search (top-k)", "info"),
             "hybrid": ("Hybrid retrieval (vector + keyword)", "ok"),
             "hybrid_recovery": ("Recovered: weak vector results fused with keyword search", "warn"),
             "keyword_fallback": ("Recovered: vector search unavailable, used independent BM25 index", "warn"),
             "none": ("No evidence retrieved", "bad")}
ANSWER_STATUS = {"answered": ("Grounded answer", "ok"),
                 "extractive": ("Evidence only · no language model used", "info"),
                 "unverified": ("Unverified · model gave no valid citations", "bad"),
                 "abstained": ("Abstained · insufficient evidence", "bad"),
                 "error": ("Error", "bad")}


def source_label(i: int, ch) -> str:
    return f"[{ch.filename}, p.{ch.page}]"


def render_evidence(cands, numbered: bool = True, show_images: bool = True) -> None:
    for i, c in enumerate(cands, start=1):
        ch = c.chunk
        kind = {"table": "table", "figure": "page image", "ocr": "OCR"}.get(ch.kind, "text")
        tag = f"{source_label(i, ch)} · " if numbered else f"{html.escape(ch.filename)} · page {ch.page} · "
        scores = []
        if c.vector_similarity is not None:
            scores.append(f"similarity {c.vector_similarity:.2f}")
        if c.keyword_score is not None:
            scores.append(f"BM25 {c.keyword_score:.1f}")
        if c.keyword_score is not None or "keyword" in c.found_by:
            scores.append(f"term coverage {c.term_coverage:.2f}")
        st.markdown(f'<div class="rg-evidence"><div class="src">{html.escape(tag)}{kind} '
                    f'<span class="rg-muted">({", ".join(scores)}; found by {", ".join(c.found_by) or "-"})</span></div>'
                    f'{html.escape(strip_context(ch.text)[:1200])}</div>', unsafe_allow_html=True)
        if show_images and ch.image_path and ch.kind in {"figure", "table", "ocr"} and Path(ch.image_path).exists():
            with st.expander(f"View page {ch.page} image"):
                st.image(ch.image_path, width="stretch")


def render_answer(res: AnswerResult) -> None:
    s = get_rag().s
    label, kind = ANSWER_STATUS.get(res.status, (res.status, "info"))
    if res.status == "answered" and s.on("answer_checks"):
        label = "Grounded answer · citations verified"
    mlabel, mkind = MODE_TEXT.get(res.retrieval.mode, (res.retrieval.mode, "info"))
    badges = pill(label, kind) + pill(mlabel, mkind)
    if res.retrieval.simulated or any(e.simulated for e in res.llm_events):
        badges += pill("simulated failure active", "sim")
    if res.used_images:
        badges += pill(f"{len(res.used_images)} page image(s) sent to vision model", "info")
    st.markdown(badges, unsafe_allow_html=True)
    text = render_citations(res.text, res.cited)
    text = re.sub(r"(?m)^(Interpretation:)", r"****", text)
    text = re.sub(r"(?m)^(Conflict:)", r"⚠️ ****", text)
    st.markdown(text)
    for w in res.warnings:
        st.caption(f"⚠ {w}")
    if res.cited:
        with st.expander(f"Sources ({len(res.cited)})", expanded=res.status != "abstained"):
            render_evidence(res.cited)
    title = "Recovery events" if s.on("fallbacks") else "Details"
    with st.expander(title):
        st.caption(f"Total {res.latency_ms:.0f} ms · retrieval {res.retrieval.latency_ms:.0f} ms · model: {res.provider}")
        render_trace(res.all_events)
        if res.status == "abstained" and res.retrieval.candidates:
            st.markdown("**Closest passages (did not pass the relevance check):**")
            render_evidence(res.retrieval.candidates[:3], numbered=False, show_images=False)
