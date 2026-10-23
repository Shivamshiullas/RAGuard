"""Small text helpers shared by BM25, the relevance gate, validation and dataset checks."""
from __future__ import annotations

import re

STOPWORDS = frozenset("""
a about above after again all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has
have having he her here hers him his how i if in into is it its itself just me more most my no
nor not now of off on once only or other our out over own same she should so some such than
that the their them then there these they this those through to too under until up very was we
were what when where which while who whom why will with would you your yours please tell explain
give list show describe document documents page pages according mentioned say says said state
stated per regarding
""".split())

_WORD = re.compile(r"[a-z0-9][a-z0-9\-']*", re.IGNORECASE)
_NUMBER = re.compile(r"\b\d+(?:[.,:/-]\d+)*%?")


def stem(word: str) -> str:
    """Deliberately light stemming so 'requirements' matches 'requirement'."""
    for suffix in ("ments", "ment", "ings", "ing", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w.lower().strip("-'")) for w in _WORD.findall(text or "")]


def content_terms(text: str) -> list[str]:
    seen: list[str] = []
    for t in tokenize(text):
        if len(t) > 1 and t not in STOPWORDS and t not in seen:
            seen.append(t)
    return seen


def term_coverage(query: str, passage: str) -> float:
    """Share of the query's content words that appear in the passage."""
    q = content_terms(query)
    if not q:
        return 0.0
    p = set(tokenize(passage))
    return sum(1 for t in q if t in p) / len(q)


def overlap_ratio(claim: str, passage: str) -> float:
    """Share of the claim's content words found in the passage (claim support proxy)."""
    c = content_terms(claim)
    if not c:
        return 1.0
    p = set(tokenize(passage))
    return sum(1 for t in c if t in p) / len(c)


def jaccard(a: str, b: str) -> float:
    sa, sb = set(content_terms(a)), set(content_terms(b))
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / max(1, len(sa | sb))


def numbers(text: str) -> set[str]:
    return {n.rstrip(".,") for n in _NUMBER.findall(text or "")}


def normalize(text: str) -> str:
    return " ".join(tokenize(text))


VISUAL_HINTS = frozenset(tokenize(
    "chart graph figure diagram image picture photo table plot scanned scan screenshot visual "
    "illustration flowchart drawing map bar pie axis"
))


def is_visual_query(query: str) -> bool:
    return any(t in VISUAL_HINTS for t in tokenize(query))
