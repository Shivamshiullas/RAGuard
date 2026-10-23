"""Integration with Adaption's Adaptive Data platform (https://docs.adaptionlabs.ai).

Every method calls the real Adaption API through the official ``adaption`` SDK and logs the
outcome to ``data/adaption/operations.jsonl``. Nothing here is mocked: if the SDK, the API
key or network access is missing, methods raise AdaptionNotAvailable with the reason.
"""
from __future__ import annotations

import gzip
import io
import json
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings


class AdaptionNotAvailable(RuntimeError):
    pass


@dataclass
class AdaptionStatus:
    installed: bool
    configured: bool
    connected: bool | None  # None = not tested
    message: str


def _jsonable(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump(exclude_none=True, mode="json")
    return obj


class AdaptionService:
    COLUMN_MAPPING = {"prompt": "prompt", "completion": "completion", "context": ["context"]}

    def __init__(self, s: Settings):
        self.s = s
        self.dir = s.adaption_dir
        self.log_path = self.dir / "operations.jsonl"
        self._client = None
        self._last_check: tuple[float, AdaptionStatus] | None = None

    # Connection -------------------------------------------------------------------------
    def _sdk(self):
        try:
            import adaption
        except ImportError as e:
            raise AdaptionNotAvailable("The 'adaption' Python package is not installed (pip install adaption).") from e
        return adaption

    def client(self):
        adaption = self._sdk()
        if not self.s.adaption_api_key:
            raise AdaptionNotAvailable("ADAPTION_API_KEY is not set. Add it to .env to enable Adaption operations.")
        if self._client is None:
            kwargs: dict[str, Any] = {"api_key": self.s.adaption_api_key, "timeout": 60.0, "max_retries": 2}
            if self.s.adaption_base_url:
                kwargs["base_url"] = self.s.adaption_base_url
            self._client = adaption.Adaption(**kwargs)
        return self._client

    def status(self, test_connection: bool = False) -> AdaptionStatus:
        try:
            self._sdk()
        except AdaptionNotAvailable as e:
            return AdaptionStatus(False, False, None, str(e))
        if not self.s.adaption_api_key:
            return AdaptionStatus(True, False, None, "SDK installed; ADAPTION_API_KEY not set.")
        if not test_connection:
            if self._last_check:
                return self._last_check[1]
            return AdaptionStatus(True, True, None, "API key configured; connection not tested yet.")
        try:
            page = self.client().datasets.list(limit=1)
            n = len(getattr(page, "data", []) or [])
            st = AdaptionStatus(True, True, True, f"Connected to Adaption API (listed {n} dataset(s)).")
            self._log("connection_test", ok=True)
        except Exception as e:
            st = AdaptionStatus(True, True, False, self.explain(e))
            self._log("connection_test", ok=False, error=self.explain(e))
        self._last_check = (time.time(), st)
        return st

    def explain(self, e: Exception) -> str:
        name = type(e).__name__
        hints = {
            "AuthenticationError": "Adaption rejected the API key (401). Check ADAPTION_API_KEY.",
            "PermissionDeniedError": "This API key does not have access to that operation (403).",
            "RateLimitError": "Adaption rate limit reached (429). Wait and retry.",
            "APIConnectionError": "Could not reach the Adaption API (network error).",
            "APITimeoutError": "The Adaption API timed out.",
            "NotFoundError": "Adaption could not find that dataset (404).",
            "UnprocessableEntityError": "Adaption rejected the request parameters (422).",
            "BadRequestError": "Adaption rejected the request (400).",
        }
        detail = str(e)[:300]
        return f"{hints.get(name, name)} {detail}".strip()

    # Operation log ----------------------------------------------------------------------
    def _log(self, op: str, ok: bool, **fields: Any) -> dict[str, Any]:
        entry = {"ts": time.time(), "op": op, "ok": ok, "source": "adaption_api", **fields}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry

    def operations(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(l) for l in reversed(lines) if l.strip()]

    # Dataset workflow -------------------------------------------------------------------
    def upload(self, rows: list[dict[str, Any]], name: str, wait_s: float = 180) -> dict[str, Any]:
        if not rows:
            raise ValueError("No rows to upload (all records rejected?).")
        path = self.dir / f"{name}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        c = self.client()
        try:
            up = c.datasets.upload_file(str(path), name=name)
            dataset_id = up.dataset_id
            deadline = time.monotonic() + wait_s
            status = None
            while time.monotonic() < deadline:
                status = c.datasets.get_status(dataset_id)
                if status.status == "failed":
                    msg = getattr(status.error_data, "message", None) or "unknown error"
                    raise RuntimeError(f"Adaption ingestion failed: {msg}")
                if status.row_count is not None:
                    break
                time.sleep(3)
            result = {"dataset_id": dataset_id, "status": getattr(status, "status", up.status),
                      "row_count": getattr(status, "row_count", None), "uploaded_rows": len(rows)}
            self._log("upload", ok=True, name=name, **result)
            return result
        except Exception as e:
            self._log("upload", ok=False, name=name, error=self.explain(e))
            raise

    def estimate(self, dataset_id: str, max_rows: int | None = None) -> dict[str, Any]:
        try:
            est = self.client().datasets.adapt(dataset_id, column_mapping=self.COLUMN_MAPPING,
                                               job_specification={"max_rows": max_rows or self.s.adaption_max_rows},
                                               estimate=True)
            result = {"dataset_id": dataset_id, "estimated_credits": est.estimated_credits_consumed,
                      "estimated_minutes": est.estimated_minutes}
            self._log("estimate", ok=True, **result)
            return result
        except Exception as e:
            self._log("estimate", ok=False, dataset_id=dataset_id, error=self.explain(e))
            raise

    def adapt(self, dataset_id: str, max_rows: int | None = None) -> dict[str, Any]:
        """Starts a real (credit-consuming) Adaptive Data run."""
        try:
            run = self.client().datasets.adapt(dataset_id, column_mapping=self.COLUMN_MAPPING,
                                               job_specification={"max_rows": max_rows or self.s.adaption_max_rows})
            result = {"dataset_id": dataset_id, "run_id": run.run_id, "estimated_minutes": run.estimated_minutes,
                      "estimated_credits": run.estimated_credits_consumed}
            self._log("adapt_started", ok=True, **result)
            return result
        except Exception as e:
            self._log("adapt_started", ok=False, dataset_id=dataset_id, error=self.explain(e))
            raise

    def job_status(self, dataset_id: str) -> dict[str, Any]:
        try:
            st = self.client().datasets.get_status(dataset_id)
            result = {"dataset_id": dataset_id, "status": st.status, "row_count": st.row_count,
                      "progress": _jsonable(st.progress),
                      "error": _jsonable(st.error_data) if st.error_data else None}
            self._log("status", ok=True, **result)
            return result
        except Exception as e:
            self._log("status", ok=False, dataset_id=dataset_id, error=self.explain(e))
            raise

    def evaluation(self, dataset_id: str) -> dict[str, Any]:
        """Adaption's own dataset-quality evaluation (score/grade before and after adaptation)."""
        try:
            ev = self.client().datasets.get_evaluation(dataset_id)
            q = ev.quality
            result = {"dataset_id": dataset_id, "status": ev.status,
                      "quality": _jsonable(q) if q else None}
            self._log("evaluation", ok=True, **result)
            return result
        except Exception as e:
            self._log("evaluation", ok=False, dataset_id=dataset_id, error=self.explain(e))
            raise

    def download(self, dataset_id: str) -> list[dict[str, Any]]:
        try:
            resp = self.client().datasets.download(dataset_id, file_format="jsonl")
            raw = resp.read() if hasattr(resp, "read") else resp.content
            rows = self._parse_download(raw)
            out = self.dir / f"adapted_{dataset_id}.jsonl"
            out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            self._log("download", ok=True, dataset_id=dataset_id, rows=len(rows), path=str(out))
            return rows
        except Exception as e:
            self._log("download", ok=False, dataset_id=dataset_id, error=self.explain(e))
            raise

    @staticmethod
    def _parse_download(raw: bytes) -> list[dict[str, Any]]:
        texts: list[str] = []
        if raw[:2] == b"\x1f\x8b":  # gzip, possibly a tar archive of shards
            try:
                with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
                    for m in tar.getmembers():
                        if m.isfile() and m.name.endswith((".jsonl", ".json")):
                            texts.append(tar.extractfile(m).read().decode("utf-8"))
            except tarfile.TarError:
                texts.append(gzip.decompress(raw).decode("utf-8"))
        else:
            texts.append(raw.decode("utf-8"))
        rows: list[dict[str, Any]] = []
        for t in texts:
            t = t.strip()
            if t.startswith("["):
                rows.extend(json.loads(t))
            else:
                rows.extend(json.loads(l) for l in t.splitlines() if l.strip())
        return rows


def match_adapted_rows(adapted: list[dict[str, Any]], originals: dict[str, Any]) -> tuple[list[tuple[Any, str]], int]:
    """Pair adapted prompts with their original record (for source pages), using record_id.

    Returns ([(original_record, adapted_prompt)], unmatched_count). Rows that cannot be joined
    are reported, never guessed.
    """
    pairs, unmatched = [], 0
    for row in adapted:
        rid = row.get("record_id")
        prompt = row.get("prompt") or row.get("adapted_prompt") or row.get("question")
        if rid in originals and prompt:
            pairs.append((originals[rid], str(prompt)))
        else:
            unmatched += 1
    return pairs, unmatched
