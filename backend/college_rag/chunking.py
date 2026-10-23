"""Heading/paragraph-aware chunking.

Chunks never cross a page boundary, so every chunk has one exact page to cite.
Token counts are approximated from words (about 0.75 words per token).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extraction import PageText

WORDS_PER_TOKEN = 0.75
_HEADING = re.compile(
    r"^(#{1,6}\s|\d+(\.\d+)*[.)]?\s+[A-Z]|(Unit|Section|Chapter|Part|Annexure)\s+\w+|[A-Z][A-Z0-9 &/,:()'-]{3,80}$)"
)


@dataclass
class Chunk:
    page: int
    ordinal: int
    text: str


def is_heading(line: str) -> bool:
    return len(line) < 100 and bool(_HEADING.match(line))


def paragraphs(text: str) -> list[str]:
    """Split a page into paragraphs; headings become their own paragraphs."""
    blocks: list[str] = []
    current: list[str] = []

    def close() -> None:
        if current:
            blocks.append(" ".join(current))
            current.clear()

    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            close()
        elif is_heading(line):
            close()
            blocks.append(line)
        else:
            current.append(line)
    close()
    return blocks


def chunk_pages(pages: list[PageText], chunk_tokens: int = 500, overlap_tokens: int = 75) -> list[Chunk]:
    max_words = max(50, int(chunk_tokens * WORDS_PER_TOKEN))
    overlap_words = min(max_words // 2, max(0, int(overlap_tokens * WORDS_PER_TOKEN)))
    chunks: list[Chunk] = []

    for page in pages:
        parts: list[str] = []  # paragraphs in the current chunk
        size = 0
        fresh = 0  # words added since the overlap was carried over

        def flush() -> None:
            nonlocal parts, size, fresh
            if fresh:
                chunks.append(Chunk(page.page, len(chunks), "\n".join(parts)))
                tail = " ".join(parts).split()[-overlap_words:] if overlap_words else []
                parts = [" ".join(tail)] if tail else []
                size = len(tail)
            fresh = 0

        for para in paragraphs(page.text):
            words = para.split()
            if is_heading(para) and size > max_words // 2:
                flush()
                parts, size = [], 0  # a new section starts clean
            while words:
                room = max_words - size
                if room <= 0:
                    flush()
                    continue
                piece = words[:room]
                words = words[room:]
                parts.append(" ".join(piece))
                size += len(piece)
                fresh += len(piece)
        flush()

    return chunks
