"""SQLite metadata store: documents, versions, the extracted-text cache,
the knowledge-base generation counter and the negative-result cache.

The chunk table is the local text cache that BM25 searches. It is independent
of ChromaDB, so keyword retrieval keeps working when the vector store fails.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    semester TEXT,
    academic_year TEXT,
    effective_date TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    doc_id TEXT NOT NULL REFERENCES documents(id),
    version INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    file_kind TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    uploaded_at REAL NOT NULL,
    stage TEXT NOT NULL,
    failed_at TEXT,
    error TEXT,
    ocr_required INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    indexed_at REAL,
    PRIMARY KEY (doc_id, version)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    page INTEGER NOT NULL,
    ordinal INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_by_version ON chunks(doc_id, version);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS negative_cache (
    cache_key TEXT PRIMARY KEY,
    normalized_query TEXT NOT NULL,
    generation INTEGER NOT NULL,
    created_at REAL NOT NULL
);
"""

TERMINAL_STAGES = {"indexed", "failed"}


@dataclass
class DocumentRow:
    id: str
    title: str
    category: str
    semester: str | None
    academic_year: str | None
    effective_date: str | None
    active: bool
    created_at: float


@dataclass
class VersionRow:
    doc_id: str
    version: int
    file_name: str
    file_kind: str
    size_bytes: int
    sha256: str
    stored_path: str
    uploaded_at: float
    stage: str
    failed_at: str | None
    error: str | None
    ocr_required: bool
    chunk_count: int
    indexed_at: float | None

    @property
    def key(self) -> str:
        return version_key(self.doc_id, self.version)


@dataclass
class ChunkRow:
    chunk_id: str
    doc_id: str
    version: int
    page: int
    ordinal: int
    text: str


def version_key(doc_id: str, version: int) -> str:
    return f"{doc_id}:v{version}"


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('kb_generation', '0')")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # -- documents ------------------------------------------------------------

    def create_document(self, doc: DocumentRow) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?)",
                (doc.id, doc.title, doc.category, doc.semester, doc.academic_year, doc.effective_date,
                 int(doc.active), doc.created_at),
            )

    def update_document_metadata(self, doc_id: str, **fields: object) -> None:
        allowed = {"title", "category", "semester", "academic_year", "effective_date", "active"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        with self._conn() as conn:
            conn.execute(
                f"UPDATE documents SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                (*[int(v) if isinstance(v, bool) else v for v in sets.values()], doc_id),
            )

    def get_document(self, doc_id: str) -> DocumentRow | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return _doc(row) if row else None

    def list_documents(self) -> list[DocumentRow]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [_doc(r) for r in rows]

    # -- versions ---------------------------------------------------------------

    def add_version(self, v: VersionRow) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (v.doc_id, v.version, v.file_name, v.file_kind, v.size_bytes, v.sha256, v.stored_path,
                 v.uploaded_at, v.stage, v.failed_at, v.error, int(v.ocr_required), v.chunk_count, v.indexed_at),
            )

    def update_version(self, doc_id: str, version: int, **fields: object) -> None:
        allowed = {"stage", "failed_at", "error", "ocr_required", "chunk_count", "indexed_at"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        with self._conn() as conn:
            conn.execute(
                f"UPDATE versions SET {', '.join(f'{k}=?' for k in sets)} WHERE doc_id=? AND version=?",
                (*[int(v) if isinstance(v, bool) else v for v in sets.values()], doc_id, version),
            )

    def versions(self, doc_id: str) -> list[VersionRow]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM versions WHERE doc_id=? ORDER BY version", (doc_id,)).fetchall()
        return [_version(r) for r in rows]

    def get_version(self, doc_id: str, version: int) -> VersionRow | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM versions WHERE doc_id=? AND version=?", (doc_id, version)).fetchone()
        return _version(row) if row else None

    def find_version_by_hash(self, sha256: str) -> VersionRow | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM versions WHERE sha256=? AND stage != 'failed' ORDER BY uploaded_at DESC", (sha256,)
            ).fetchone()
        return _version(row) if row else None

    def mark_interrupted(self) -> int:
        """After a restart, versions left mid-pipeline can never finish; mark them failed."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE versions SET failed_at=stage, stage='failed', "
                "error='Processing was interrupted by a server restart. Click Reprocess.' "
                "WHERE stage NOT IN ('indexed', 'failed')"
            )
            return cur.rowcount

    def searchable_versions(self) -> dict[str, tuple[DocumentRow, VersionRow]]:
        """For each active document, its newest successfully indexed version."""
        result: dict[str, tuple[DocumentRow, VersionRow]] = {}
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT d.*, v.* FROM documents d
                JOIN versions v ON v.doc_id = d.id
                WHERE d.active = 1 AND v.stage = 'indexed'
                  AND v.version = (SELECT MAX(version) FROM versions WHERE doc_id = d.id AND stage = 'indexed')
                """
            ).fetchall()
        for row in rows:
            doc = DocumentRow(row[0], row[1], row[2], row[3], row[4], row[5], bool(row[6]), row[7])
            version = _version(row, offset=8)
            result[version.key] = (doc, version)
        return result

    # -- chunk text cache -------------------------------------------------------

    def replace_chunks(self, doc_id: str, version: int, chunks: list[ChunkRow]) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM chunks WHERE doc_id=? AND version=?", (doc_id, version))
            conn.executemany(
                "INSERT INTO chunks VALUES (?,?,?,?,?,?)",
                [(c.chunk_id, c.doc_id, c.version, c.page, c.ordinal, c.text) for c in chunks],
            )

    def chunks_for_versions(self, keys: set[str]) -> list[ChunkRow]:
        if not keys:
            return []
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM chunks ORDER BY doc_id, version, ordinal").fetchall()
        return [ChunkRow(*r) for r in rows if version_key(r["doc_id"], r["version"]) in keys]

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, ChunkRow]:
        if not chunk_ids:
            return {}
        with self._conn() as conn:
            marks = ",".join("?" * len(chunk_ids))
            rows = conn.execute(f"SELECT * FROM chunks WHERE chunk_id IN ({marks})", chunk_ids).fetchall()
        return {r["chunk_id"]: ChunkRow(*r) for r in rows}

    # -- knowledge-base generation and negative cache ---------------------------

    def kb_generation(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT value FROM meta WHERE key='kb_generation'").fetchone()[0])

    def bump_generation(self) -> int:
        """Called after every successful index/replace/activate/deactivate.
        Old negative-cache entries stop matching and are purged."""
        with self._conn() as conn:
            conn.execute("UPDATE meta SET value = CAST(value AS INTEGER) + 1 WHERE key='kb_generation'")
            gen = int(conn.execute("SELECT value FROM meta WHERE key='kb_generation'").fetchone()[0])
            conn.execute("DELETE FROM negative_cache WHERE generation < ?", (gen,))
            return gen

    def negative_get(self, cache_key: str) -> tuple[int, float] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT generation, created_at FROM negative_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
        return (row[0], row[1]) if row else None

    def negative_put(self, cache_key: str, normalized_query: str, generation: int) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO negative_cache VALUES (?,?,?,?)",
                (cache_key, normalized_query, generation, time.time()),
            )

    def negative_delete(self, cache_key: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM negative_cache WHERE cache_key=?", (cache_key,))

    def negative_count(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM negative_cache").fetchone()[0])


def _doc(row: sqlite3.Row) -> DocumentRow:
    return DocumentRow(
        id=row["id"], title=row["title"], category=row["category"], semester=row["semester"],
        academic_year=row["academic_year"], effective_date=row["effective_date"], active=bool(row["active"]),
        created_at=row["created_at"],
    )


def _version(row: sqlite3.Row, offset: int = 0) -> VersionRow:
    r = tuple(row)[offset:]
    return VersionRow(
        doc_id=r[0], version=r[1], file_name=r[2], file_kind=r[3], size_bytes=r[4], sha256=r[5], stored_path=r[6],
        uploaded_at=r[7], stage=r[8], failed_at=r[9], error=r[10], ocr_required=bool(r[11]), chunk_count=r[12],
        indexed_at=r[13],
    )
