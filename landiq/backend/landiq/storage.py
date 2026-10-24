"""Persistence behind a small repository interface.

The local prototype uses SQLite (WAL) plus files on disk. Every method speaks
in schema objects or plain values, so a PostgreSQL/PostGIS implementation can
replace `SqliteRepository` without touching agents or the orchestrator.

The `chunks_fts` table is the lexical index (exact case IDs, survey numbers,
dates, amounts). It lives in SQLite and is independent of the vector store.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .schemas import (
    Case, Conflict, Fact, Job, JobState, MapFeature, Project, UnresolvedMatch, utcnow,
)

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS projects (project_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS inputs (
    input_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, filename TEXT NOT NULL,
    sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL,
    detail TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS inputs_by_project ON inputs(project_id, kind);
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL, body TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    job_id TEXT NOT NULL, stage TEXT NOT NULL, input_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (job_id, stage, input_id)
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, document_id TEXT NOT NULL, filename TEXT NOT NULL,
    page INTEGER NOT NULL, text TEXT NOT NULL, case_ids TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED, project_id UNINDEXED, text, case_ids, tokenize='unicode61 tokenchars ''#/'''
);
CREATE TABLE IF NOT EXISTS facts (fact_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, source_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS features (
    feature_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, map_id TEXT NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conflicts (conflict_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS matches (match_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS resolutions (
    match_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, case_id TEXT, resolved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_workflow (action_id TEXT PRIMARY KEY, status TEXT NOT NULL, updated_at TEXT NOT NULL);
"""


class InputRow:
    def __init__(self, row: sqlite3.Row):
        self.input_id: str = row["input_id"]
        self.project_id: str = row["project_id"]
        self.kind: str = row["kind"]
        self.filename: str = row["filename"]
        self.sha256: str = row["sha256"]
        self.size_bytes: int = row["size_bytes"]
        self.path = Path(row["path"])
        self.status: str = row["status"]
        self.detail: str | None = row["detail"]
        self.created_at: str = row["created_at"]


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted tokens."""
    tokens = re.findall(r"[#\w][\w/.#-]*", text.lower())
    tokens = [t.strip(".") for t in tokens if len(t.strip(".")) > 1][:32]
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in tokens)


class SqliteRepository:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        with self._conn() as conn:
            conn.executescript(SCHEMA)

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

    # -- projects -------------------------------------------------------------

    def put_project(self, project: Project) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO projects VALUES (?,?)", (project.project_id, project.model_dump_json()))

    def get_project(self, project_id: str) -> Project | None:
        with self._conn() as c:
            row = c.execute("SELECT body FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return Project.model_validate_json(row[0]) if row else None

    def list_projects(self) -> list[Project]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM projects").fetchall()
        return sorted((Project.model_validate_json(r[0]) for r in rows), key=lambda p: (not p.is_demo, p.created_at))

    # -- uploaded inputs --------------------------------------------------------

    def add_input(self, input_id: str, project_id: str, kind: str, filename: str, sha256: str, size: int,
                  path: Path, status: str, detail: str | None = None) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO inputs VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (input_id, project_id, kind, filename, sha256, size, str(path), status, detail, utcnow()))

    def get_input(self, input_id: str) -> InputRow | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM inputs WHERE input_id=?", (input_id,)).fetchone()
        return InputRow(row) if row else None

    def find_input_by_hash(self, project_id: str, kind: str, sha256: str) -> InputRow | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM inputs WHERE project_id=? AND kind=? AND sha256=? AND status='STORED'",
                            (project_id, kind, sha256)).fetchone()
        return InputRow(row) if row else None

    def list_inputs(self, project_id: str, kind: str | None = None) -> list[InputRow]:
        with self._conn() as c:
            if kind:
                rows = c.execute("SELECT * FROM inputs WHERE project_id=? AND kind=? ORDER BY created_at",
                                 (project_id, kind)).fetchall()
            else:
                rows = c.execute("SELECT * FROM inputs WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
        return [InputRow(r) for r in rows]

    def set_input_status(self, input_id: str, status: str, detail: str | None, path: Path | None = None) -> None:
        with self._conn() as c:
            if path is not None:
                c.execute("UPDATE inputs SET status=?, detail=?, path=? WHERE input_id=?", (status, detail, str(path), input_id))
            else:
                c.execute("UPDATE inputs SET status=?, detail=? WHERE input_id=?", (status, detail, input_id))

    # -- jobs and checkpoints ------------------------------------------------------

    def create_job(self, job: Job) -> Job:
        """Idempotent: an existing job with the same key is returned instead."""
        with self._conn() as c:
            row = c.execute("SELECT body FROM jobs WHERE idempotency_key=?", (job.idempotency_key,)).fetchone()
            if row:
                return Job.model_validate_json(row[0])
            c.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?)",
                      (job.job_id, job.project_id, job.idempotency_key, job.state.value, job.model_dump_json(), job.updated_at))
        return job

    def save_job(self, job: Job) -> None:
        job.updated_at = utcnow()
        with self._conn() as c:
            c.execute("UPDATE jobs SET state=?, body=?, updated_at=? WHERE job_id=?",
                      (job.state.value, job.model_dump_json(), job.updated_at, job.job_id))

    def get_job(self, job_id: str) -> Job | None:
        with self._conn() as c:
            row = c.execute("SELECT body FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return Job.model_validate_json(row[0]) if row else None

    def list_jobs(self, project_id: str | None = None, states: list[JobState] | None = None) -> list[Job]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM jobs ORDER BY updated_at DESC").fetchall()
        jobs = [Job.model_validate_json(r[0]) for r in rows]
        if project_id:
            jobs = [j for j in jobs if j.project_id == project_id]
        if states:
            jobs = [j for j in jobs if j.state in states]
        return jobs

    def put_checkpoint(self, job_id: str, stage: str, input_id: str, body: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?)", (job_id, stage, input_id, body, utcnow()))

    def get_checkpoint(self, job_id: str, stage: str, input_id: str) -> str | None:
        with self._conn() as c:
            row = c.execute("SELECT body FROM checkpoints WHERE job_id=? AND stage=? AND input_id=?",
                            (job_id, stage, input_id)).fetchone()
        return row[0] if row else None

    # -- chunks (lexical index) -----------------------------------------------------

    def replace_chunks(self, project_id: str, document_id: str, rows: list[dict]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
            c.execute("DELETE FROM chunks_fts WHERE chunk_id IN (SELECT chunk_id FROM chunks_fts WHERE chunk_id LIKE ?)",
                      (f"{document_id}-%",))
            for r in rows:
                case_ids = " ".join(r["case_ids"])
                c.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?,?)",
                          (r["chunk_id"], project_id, document_id, r["filename"], r["page"], r["text"], json.dumps(r["case_ids"])))
                c.execute("INSERT INTO chunks_fts VALUES (?,?,?,?)", (r["chunk_id"], project_id, r["text"], case_ids))

    def get_chunks(self, chunk_ids: list[str]) -> dict[str, dict]:
        if not chunk_ids:
            return {}
        with self._conn() as c:
            marks = ",".join("?" * len(chunk_ids))
            rows = c.execute(f"SELECT * FROM chunks WHERE chunk_id IN ({marks})", chunk_ids).fetchall()
        return {r["chunk_id"]: {**dict(r), "case_ids": json.loads(r["case_ids"])} for r in rows}

    def lexical_search(self, project_id: str, query: str, k: int, document_ids: list[str] | None = None,
                       case_ref: str | None = None) -> list[tuple[str, float]]:
        q = fts_query(query)
        if not q:
            return []
        with self._conn() as c:
            rows = c.execute(
                "SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts WHERE chunks_fts MATCH ? AND project_id=? "
                "ORDER BY score LIMIT ?", (q, project_id, k * 4),
            ).fetchall()
        hits = [(r[0], -float(r[1])) for r in rows]
        if document_ids or case_ref:
            meta = self.get_chunks([h[0] for h in hits])
            hits = [h for h in hits if (not document_ids or meta[h[0]]["document_id"] in document_ids)
                    and (not case_ref or case_ref in meta[h[0]]["case_ids"])]
        return hits[:k]

    def chunk_count(self, project_id: str) -> int:
        with self._conn() as c:
            return int(c.execute("SELECT COUNT(*) FROM chunks WHERE project_id=?", (project_id,)).fetchone()[0])

    # -- facts, features, cases, conflicts, matches ----------------------------------

    def replace_facts(self, project_id: str, source_id: str, facts: list[Fact]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM facts WHERE source_id=?", (source_id,))
            c.executemany("INSERT OR REPLACE INTO facts VALUES (?,?,?,?)",
                          [(f.fact_id, project_id, source_id, f.model_dump_json()) for f in facts])

    def list_facts(self, project_id: str) -> list[Fact]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM facts WHERE project_id=?", (project_id,)).fetchall()
        return [Fact.model_validate_json(r[0]) for r in rows]

    def replace_features(self, project_id: str, map_id: str, features: list[MapFeature]) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM features WHERE map_id=?", (map_id,))
            c.executemany("INSERT INTO features VALUES (?,?,?,?)",
                          [(f.feature_id, project_id, map_id, f.model_dump_json()) for f in features])

    def list_features(self, project_id: str) -> list[MapFeature]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM features WHERE project_id=?", (project_id,)).fetchall()
        return [MapFeature.model_validate_json(r[0]) for r in rows]

    def replace_project_cases(self, project_id: str, cases: list[Case], conflicts: list[Conflict],
                              matches: list[UnresolvedMatch]) -> None:
        """Fusion output for a project is written atomically."""
        with self._conn() as c:
            for table in ("cases", "conflicts", "matches"):
                c.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
            c.executemany("INSERT INTO cases VALUES (?,?,?)", [(x.case_id, project_id, x.model_dump_json()) for x in cases])
            c.executemany("INSERT INTO conflicts VALUES (?,?,?)",
                          [(x.conflict_id, project_id, x.model_dump_json()) for x in conflicts])
            c.executemany("INSERT INTO matches VALUES (?,?,?)", [(x.match_id, project_id, x.model_dump_json()) for x in matches])

    def list_cases(self, project_id: str) -> list[Case]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM cases WHERE project_id=?", (project_id,)).fetchall()
        return [self._with_workflow(Case.model_validate_json(r[0])) for r in rows]

    def rescore_cases(self, predict) -> int:
        """Re-run `predict` on stored uploaded cases (e.g. after the scorer changed)."""
        with self._conn() as c:
            rows = c.execute("SELECT case_id, body FROM cases").fetchall()
            updates = []
            for case_id, body in rows:
                case = Case.model_validate_json(body)
                if case.is_synthetic:
                    continue
                prediction = predict(case)
                if prediction.model_dump(exclude={"generated_at"}) != case.prediction.model_dump(exclude={"generated_at"}):
                    case.prediction = prediction
                    updates.append((case.model_dump_json(), case_id))
            c.executemany("UPDATE cases SET body=? WHERE case_id=?", updates)
        return len(updates)

    def get_case(self, case_id: str) -> Case | None:
        with self._conn() as c:
            row = c.execute("SELECT body FROM cases WHERE case_id=?", (case_id,)).fetchone()
        return self._with_workflow(Case.model_validate_json(row[0])) if row else None

    def list_conflicts(self, project_id: str) -> list[Conflict]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM conflicts WHERE project_id=?", (project_id,)).fetchall()
        return [Conflict.model_validate_json(r[0]) for r in rows]

    def list_matches(self, project_id: str) -> list[UnresolvedMatch]:
        with self._conn() as c:
            rows = c.execute("SELECT body FROM matches WHERE project_id=?", (project_id,)).fetchall()
        return [UnresolvedMatch.model_validate_json(r[0]) for r in rows]

    # -- human answers to ambiguous matches ------------------------------------------

    def put_resolution(self, project_id: str, match_id: str, case_id: str | None) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO resolutions VALUES (?,?,?,?)", (match_id, project_id, case_id, utcnow()))

    def list_resolutions(self, project_id: str) -> dict[str, str | None]:
        with self._conn() as c:
            rows = c.execute("SELECT match_id, case_id FROM resolutions WHERE project_id=?", (project_id,)).fetchall()
        return {r[0]: r[1] for r in rows}

    # -- human workflow on recommended actions ------------------------------------

    def set_action_status(self, action_id: str, status: str) -> None:
        with self._conn() as c:
            c.execute("INSERT OR REPLACE INTO action_workflow VALUES (?,?,?)", (action_id, status, utcnow()))

    def _with_workflow(self, case: Case) -> Case:
        if not case.actions:
            return case
        with self._conn() as c:
            marks = ",".join("?" * len(case.actions))
            rows = dict(c.execute(f"SELECT action_id, status FROM action_workflow WHERE action_id IN ({marks})",
                                  [a.action_id for a in case.actions]).fetchall())
        for a in case.actions:
            if a.action_id in rows:
                a.workflow_status = rows[a.action_id]
        return case
