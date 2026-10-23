"""Fault-tolerant retrieval controller.

Order of operations for every query:
  1. Validate the query and the index manifest (embedding model / dimension must match).
  2. Embed the query and search ChromaDB, each under a timeout with bounded retries.
  3. Always search the independent BM25 index as well.
  4. If the vector path failed technically -> keyword fallback.
     If it returned nothing or only weak matches -> widen top-k and fuse with BM25.
  5. For visual questions, add the visual records of the best-matching pages.
  6. Apply the relevance gate and decide whether the evidence is sufficient.
Every step is recorded as a RecoveryEvent so the UI and logs show what happened.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import random
import time
from typing import Callable, TypeVar

from .config import Settings
from .faults import SimulatedFault, faults
from .indexes import BM25Store, ChromaStore, Embedder, IndexMismatch
from .models import Candidate, Chunk, RecoveryEvent, RetrievalResult
from .registry import Registry
from .text import content_terms, is_visual_query, term_coverage

log = logging.getLogger(__name__)
T = TypeVar("T")

_pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="raguard-io")
# Errors that will not go away by retrying: bad input, wrong index configuration.
NON_RETRYABLE = (ValueError, TypeError, KeyError, IndexMismatch)


class DeadlineExceeded(TimeoutError):
    pass


def call_with_retry(fn: Callable[[], T], *, stage: str, timeout_s: float, attempts: int, backoff_s: float,
                    deadline: float, events: list[RecoveryEvent], fault_flags: tuple[str, ...] = (),
                    on_retry: Callable[[], None] | None = None) -> T:
    """Run ``fn`` with a per-attempt timeout, exponential backoff with jitter, and an overall deadline."""
    last: BaseException | None = None
    for attempt in range(attempts + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0.05:
            raise DeadlineExceeded(f"request deadline reached before {stage} attempt {attempt + 1}")
        t0 = time.monotonic()
        simulated = any(faults.is_on(f) for f in fault_flags)
        future = _pool.submit(fn)
        try:
            result = future.result(timeout=min(timeout_s, remaining))
            if attempt:
                events.append(RecoveryEvent(stage, "ok", f"succeeded on attempt {attempt + 1}",
                                            (time.monotonic() - t0) * 1000, simulated))
            return result
        except cf.TimeoutError:
            future.cancel()
            last = TimeoutError(f"{stage} timed out after {min(timeout_s, remaining):.1f}s")
        except NON_RETRYABLE as e:
            events.append(RecoveryEvent(stage, "failed", f"{type(e).__name__}: {e} (not retried)",
                                        (time.monotonic() - t0) * 1000, simulated))
            raise
        except Exception as e:
            last = e
            simulated = simulated or isinstance(e, SimulatedFault)
        ms = (time.monotonic() - t0) * 1000
        if attempt < attempts:
            events.append(RecoveryEvent(stage, "retry", f"attempt {attempt + 1} failed: {last}", ms, simulated))
            if on_retry:
                on_retry()
            sleep = backoff_s * (2 ** attempt) * (0.5 + random.random())
            time.sleep(max(0.0, min(sleep, deadline - time.monotonic() - 0.1)))
        else:
            events.append(RecoveryEvent(stage, "failed", f"gave up after {attempts + 1} attempts: {last}", ms, simulated))
    assert last is not None
    raise last


def rrf(rank_lists: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion: robust to the different score scales of BM25 and cosine similarity."""
    scores: dict[str, float] = {}
    for ranking in rank_lists:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return scores


class RetrievalController:
    def __init__(self, s: Settings, registry: Registry, embedder: Embedder, chroma: ChromaStore, bm25: BM25Store):
        self.s, self.registry, self.embedder, self.chroma, self.bm25 = s, registry, embedder, chroma, bm25

    # Manifest ---------------------------------------------------------------------------
    def check_manifest(self) -> tuple[bool, str]:
        m = self.registry.manifest()
        if not m:
            return True, "no manifest yet (empty index)"
        if m.get("embedder") != self.embedder.name:
            return False, (f"index was built with '{m.get('embedder')}' but the configured model is "
                           f"'{self.embedder.name}'; vector search disabled until the index is rebuilt")
        return True, f"index manifest matches ({m.get('embedder')}, dim {m.get('dimension')})"

    # Main entry -------------------------------------------------------------------------
    def retrieve(self, query: str, doc_ids: list[str] | None = None, k: int | None = None) -> RetrievalResult:
        t_start = time.monotonic()
        deadline = t_start + self.s.request_deadline_s
        k = k or self.s.top_k
        events: list[RecoveryEvent] = []
        query = (query or "").strip()
        if not query:
            return RetrievalResult(query, [], [RecoveryEvent("validation", "failed", "empty question")],
                                   "none", False, "The question is empty.")
        if len(query) > 2000:
            query = query[:2000]
            events.append(RecoveryEvent("validation", "weak", "question truncated to 2000 characters"))

        chunk_map = {c.chunk_id: c for c in self.bm25._chunks}
        allowed = set(doc_ids) if doc_ids else None

        # 1. manifest
        vector_allowed, msg = self.check_manifest()
        events.append(RecoveryEvent("manifest", "ok" if vector_allowed else "failed", msg))

        # 2. vector path
        vector_hits: list[tuple[str, float]] | None = None
        vector_error: str | None = None
        if vector_allowed:
            try:
                t0 = time.monotonic()
                qvec = call_with_retry(lambda: self.embedder.embed_query(query), stage="embed",
                                       timeout_s=self.s.embed_timeout_s, attempts=self.s.retry_attempts,
                                       backoff_s=self.s.backoff_base_s, deadline=deadline, events=events,
                                       fault_flags=("embedding_down", "embedding_slow"))
                events.append(RecoveryEvent("embed", "ok", f"query embedded with {self.embedder.name}",
                                            (time.monotonic() - t0) * 1000))
                t0 = time.monotonic()
                vector_hits = call_with_retry(lambda: self._vector_query(qvec, k, doc_ids), stage="vector",
                                              timeout_s=self.s.vector_timeout_s, attempts=self.s.retry_attempts,
                                              backoff_s=self.s.backoff_base_s, deadline=deadline, events=events,
                                              fault_flags=("chroma_down",), on_retry=self.chroma.reset_connection)
                events.append(RecoveryEvent("vector", "ok", f"ChromaDB returned {len(vector_hits)} candidates",
                                            (time.monotonic() - t0) * 1000))
            except Exception as e:
                vector_error = f"{type(e).__name__}: {e}"
                vector_hits = None

        # 3. keyword path (independent of ChromaDB)
        t0 = time.monotonic()
        try:
            keyword_hits = self.bm25.search(query, k * 2, doc_ids)
            events.append(RecoveryEvent("keyword", "ok", f"BM25 returned {len(keyword_hits)} candidates",
                                        (time.monotonic() - t0) * 1000))
        except Exception as e:  # pragma: no cover - BM25 is in-process
            keyword_hits = []
            events.append(RecoveryEvent("keyword", "failed", f"{type(e).__name__}: {e}"))

        # Simulated "bad but technically successful" vector results
        if vector_hits is not None and faults.is_on("vector_empty"):
            vector_hits = []
            events.append(RecoveryEvent("vector", "weak", "vector search returned no results", simulated=True))
        if vector_hits is not None and faults.is_on("vector_irrelevant"):
            pool = [c.chunk_id for c in chunk_map.values() if allowed is None or c.doc_id in allowed]
            random.shuffle(pool)
            vector_hits = [(cid, 0.12) for cid in pool[:k]]
            events.append(RecoveryEvent("vector", "weak", "vector search returned unrelated chunks", simulated=True))

        # 4. routing decision
        if vector_hits is None:
            mode = "keyword_fallback"
            sim = any(e.simulated for e in events if e.stage in {"embed", "vector"})
            events.append(RecoveryEvent("vector", "fallback",
                                        f"vector path unavailable ({vector_error or 'disabled'}); "
                                        "switched to the independent BM25 index", simulated=sim))
            vector_hits = []
        else:
            best = max((sc for _, sc in vector_hits), default=0.0)
            if best < self.s.vector_min_similarity:
                mode = "hybrid_recovery"
                sim = faults.is_on("vector_empty") or faults.is_on("vector_irrelevant")
                events.append(RecoveryEvent("relevance", "weak",
                                            f"best vector similarity {best:.2f} is below {self.s.vector_min_similarity:.2f}; "
                                            "fusing with keyword results", simulated=sim))
                if not sim and vector_hits:
                    try:
                        wider = self._vector_query_safe(query, k * 2, doc_ids)
                        if wider:
                            vector_hits = wider
                            events.append(RecoveryEvent("vector", "ok", f"widened vector search to top-{k * 2}"))
                    except Exception:
                        pass
            else:
                mode = "hybrid"

        # 5. fuse candidates
        vec_rank = [cid for cid, _ in vector_hits if cid in chunk_map]
        kw_rank = [c.chunk_id for c, _ in keyword_hits]
        fused = rrf([vec_rank, kw_rank] if vec_rank else [kw_rank])
        vec_sim = dict(vector_hits)
        kw_score = {c.chunk_id: sc for c, sc in keyword_hits}
        cands: dict[str, Candidate] = {}
        for cid, score in fused.items():
            chunk = chunk_map.get(cid)
            if chunk is None or (allowed and chunk.doc_id not in allowed):
                continue
            found = (["vector"] if cid in vec_sim else []) + (["keyword"] if cid in kw_score else [])
            cands[cid] = Candidate(chunk, score, vec_sim.get(cid), kw_score.get(cid),
                                   term_coverage(query, chunk.text), found)

        # 6. visual evidence
        visual = is_visual_query(query)
        if visual:
            top_pages = {(c.chunk.doc_id, c.chunk.page) for c in sorted(cands.values(), key=lambda c: -c.score)[:k]}
            added = 0
            for chunk in chunk_map.values():
                if chunk.kind == "visual" and (chunk.doc_id, chunk.page) in top_pages and chunk.chunk_id not in cands:
                    best = max((c.score for c in cands.values() if (c.chunk.doc_id, c.chunk.page) == (chunk.doc_id, chunk.page)), default=0)
                    cands[chunk.chunk_id] = Candidate(chunk, best * 0.99, None, None,
                                                      term_coverage(query, chunk.text), ["visual"])
                    added += 1
            has_visual = any(c.chunk.kind == "visual" for c in cands.values())
            events.append(RecoveryEvent("visual", "ok" if has_visual else "weak",
                                        f"added {added} page-image records from matching pages" if has_visual else
                                        "visual question, but no figure/scanned-page record matched; answer will rely on text"))

        ranked = sorted(cands.values(), key=lambda c: c.score, reverse=True)[: max(k, 8)]

        # 7. relevance gate + sufficiency
        for c in ranked:
            c.relevant = self._is_relevant(c)
        evidence = [c for c in ranked if c.relevant]
        sufficient, reason = self._sufficiency(query, evidence)
        events.append(RecoveryEvent("relevance", "ok" if sufficient else "abstain", reason))
        return RetrievalResult(query, ranked, events, mode if ranked else "none", sufficient, reason, visual,
                               (time.monotonic() - t_start) * 1000)

    # Helpers ----------------------------------------------------------------------------
    def _vector_query(self, qvec: list[float], k: int, doc_ids: list[str] | None) -> list[tuple[str, float]]:
        try:
            return self.chroma.query(qvec, k, doc_ids)
        except Exception as e:
            if "dimension" in str(e).lower():
                raise IndexMismatch(str(e)) from e
            raise

    def _vector_query_safe(self, query: str, k: int, doc_ids: list[str] | None):
        return self.chroma.query(self.embedder.embed_query(query), k, doc_ids)

    def _is_relevant(self, c: Candidate) -> bool:
        if c.chunk.kind == "visual" and "visual" in c.found_by:
            return True  # attached because its page already matched
        sim_ok = c.vector_similarity is not None and c.vector_similarity >= self.s.vector_min_similarity
        cov_ok = c.term_coverage >= self.s.min_term_coverage
        # A strong semantic match counts on its own; a weaker one needs keyword agreement.
        if c.vector_similarity is not None and c.vector_similarity >= self.s.vector_min_similarity + 0.15:
            return True
        return (sim_ok and c.term_coverage >= 0.25) or cov_ok

    def _sufficiency(self, query: str, evidence: list[Candidate]) -> tuple[bool, str]:
        if not content_terms(query):
            return False, "The question has no searchable terms."
        if not evidence:
            return False, "No retrieved passage passed the relevance check."
        best_cov = max(c.term_coverage for c in evidence)
        best_sim = max((c.vector_similarity or 0.0) for c in evidence)
        score = max(best_cov, best_sim)
        if score < self.s.sufficiency_min_score:
            return False, f"Best evidence is weak (coverage {best_cov:.2f}, similarity {best_sim:.2f})."
        return True, f"{len(evidence)} relevant passages (best coverage {best_cov:.2f}, similarity {best_sim:.2f})."
