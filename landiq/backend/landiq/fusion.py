"""Evidence fusion: turns validated facts and map features into cases.

Rules:
- join only on verified identifiers (case refs, exact parcel IDs, exact survey numbers)
- a survey number / parcel that points at several cases is NOT merged; it becomes
  an UnresolvedMatch and the user is asked which case it belongs to
- disagreeing VALIDATED values for a field are kept as a Conflict (value stays null)
- facts with no case stay unattached; missing fields stay UNKNOWN
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .actions import recommend
from .prediction import predict
from .schemas import (
    Case, Conflict, Fact, FieldValue, MapFeature, MapProvenance, Prediction, PredictionStatus, UnresolvedMatch,
    ValidationStatus,
)

MULTI_VALUE = {"survey_numbers", "parcel_id", "notification_date", "hearing_date", "deadline_date"}
NUMERIC = {"area_hectares", "compensation_amount_cr", "compensation_disbursed_pct", "rr_progress_pct", "project_progress_pct"}
CORE_STATUS = ("legal_status", "compensation_status", "clearance_status")
NUMERIC_TOLERANCE = 0.02


def case_uid(project_id: str, case_ref: str) -> str:
    return f"{project_id}.{case_ref.lstrip('#')}"


def _source(f: Fact) -> str:
    p = f.provenance
    if isinstance(p, MapProvenance):
        return f"{p.filename} · {p.layer} · {p.feature_id}"
    return f"{p.filename} p.{p.page}"


def _match_id(kind: str, key: str, candidates: list[str]) -> str:
    return "M-" + hashlib.sha1(f"{kind}|{key}|{'|'.join(sorted(candidates))}".encode()).hexdigest()[:12]


def _same_within(a, b, tol: float) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b), 1e-9)


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= NUMERIC_TOLERANCE * max(abs(a), abs(b), 1e-9)
    return str(a).strip().lower() == str(b).strip().lower()


def fuse(project_id: str, corridor_id: str | None, facts: list[Fact], features: list[MapFeature],
         resolutions: dict[str, str | None]) -> tuple[list[Case], list[Conflict], list[UnresolvedMatch], list[str]]:
    warnings: list[str] = []
    refs = sorted({str(f.normalized_value) for f in facts
                   if f.field == "case_id" and f.normalized_value and not isinstance(f.provenance, MapProvenance)})
    by_case: dict[str, list[Fact]] = defaultdict(list)
    unattached = 0
    for f in facts:
        if isinstance(f.provenance, MapProvenance):
            continue  # map facts follow their feature's verified case (below)
        if f.case_id:
            by_case[f.case_id].append(f)
        elif f.field != "case_id":
            unattached += 1

    # Index document survey numbers / parcel IDs -> cases, to place map features without a case attribute.
    doc_key_cases: dict[tuple[str, str], set[str]] = defaultdict(set)
    for ref, fs in by_case.items():
        for f in fs:
            if f.field in ("survey_numbers", "parcel_id") and f.provenance.kind == "document":
                doc_key_cases[(f.field, str(f.normalized_value).upper())].add(ref)

    matches: list[UnresolvedMatch] = []
    feature_case: dict[str, str] = {}
    for feat in features:
        if feat.role != "parcel":
            continue
        keys = [("parcel_id", feat.parcel_id.upper())] if feat.parcel_id else []
        keys += [("survey_numbers", s.upper()) for s in feat.survey_numbers]
        doc_cases = set().union(*(doc_key_cases.get(k, set()) for k in keys)) if keys else set()
        if feat.case_id:
            if doc_cases and feat.case_id not in doc_cases:
                cands = sorted(doc_cases | {feat.case_id})
                mid = _match_id("parcel_to_case", feat.feature_id, cands)
                if mid in resolutions:
                    if resolutions[mid]:
                        feature_case[feat.feature_id] = resolutions[mid]
                    continue
                matches.append(UnresolvedMatch(
                    match_id=mid, kind="parcel_to_case", key=feat.feature_id, candidates=cands, source=feat.map_id,
                    question=(f"Map parcel {feat.parcel_id or feat.feature_id} is labelled {feat.case_id}, but its survey/parcel "
                              f"numbers appear in documents for {', '.join(sorted(doc_cases))}. Which case does it belong to?")))
                continue
            feature_case[feat.feature_id] = feat.case_id
        elif len(doc_cases) == 1:
            feature_case[feat.feature_id] = next(iter(doc_cases))
        elif len(doc_cases) > 1:
            cands = sorted(doc_cases)
            mid = _match_id("parcel_to_case", feat.feature_id, cands)
            if mid in resolutions:
                if resolutions[mid]:
                    feature_case[feat.feature_id] = resolutions[mid]
                continue
            matches.append(UnresolvedMatch(
                match_id=mid, kind="parcel_to_case", key=feat.feature_id, candidates=cands, source=feat.map_id,
                question=(f"Map parcel {feat.parcel_id or feat.feature_id} (survey {', '.join(feat.survey_numbers) or 'n/a'}) "
                          f"matches several cases: {', '.join(cands)}. Which case does it belong to?")))

    # Map facts follow their feature's verified case. Geometry-computed areas stay in
    # `spatial` (they measure the polygon, not the recorded acquisition area).
    feat_by_id = {f.feature_id: f for f in features}
    for f in facts:
        if (isinstance(f.provenance, MapProvenance) and f.provenance.feature_id in feature_case
                and f.extraction_method != "gis:spatial"):
            by_case[feature_case[f.provenance.feature_id]].append(f)
    all_refs = sorted(set(refs) | set(by_case) | set(feature_case.values()))

    cases: list[Case] = []
    conflicts: list[Conflict] = []
    for ref in all_refs:
        uid = case_uid(project_id, ref)
        fs = [f for f in by_case.get(ref, []) if f.field != "case_id"]
        grouped: dict[str, list[Fact]] = defaultdict(list)
        for f in fs:
            grouped[f.field].append(f)
        fields: dict[str, FieldValue] = {}
        case_conflicts: list[str] = []
        for name, group in grouped.items():
            if name in MULTI_VALUE:
                vals = sorted({str(f.normalized_value) for f in group})
                fields[name] = FieldValue(value=vals, status="KNOWN", facts=[f.fact_id for f in group])
                continue
            validated = [f for f in group if f.validation_status == ValidationStatus.VALIDATED]
            pool = validated or group
            distinct: list = []
            for f in pool:
                if not any(_same(f.normalized_value, d) for d in distinct):
                    distinct.append(f.normalized_value)
            if len(distinct) == 1:
                fields[name] = FieldValue(value=distinct[0], status="KNOWN" if validated else "UNVERIFIED",
                                          facts=[f.fact_id for f in pool])
            else:
                cid = "C-" + hashlib.sha1(f"{uid}|{name}".encode()).hexdigest()[:10]
                conflicts.append(Conflict(conflict_id=cid, case_id=uid, field=name, values=[
                    {"value": f.normalized_value, "fact_id": f.fact_id, "source": _source(f)} for f in pool]))
                case_conflicts.append(cid)
                fields[name] = FieldValue(value=None, status="CONFLICT", facts=[f.fact_id for f in pool],
                                          alternatives=distinct)
        for name in CORE_STATUS:
            fields.setdefault(name, FieldValue())

        linked = [feat_by_id[fid] for fid, r in feature_case.items() if r == ref and fid in feat_by_id]
        spatial: dict = {}
        case_warnings: list[str] = []
        if linked:
            spatial = {
                "features": len(linked),
                "area_hectares_computed": round(sum(f.area_hectares or 0 for f in linked), 4),
                "intersects_alignment": (any(f.intersects_alignment for f in linked)
                                         if any(f.intersects_alignment is not None for f in linked) else None),
                "min_distance_to_alignment_m": min((f.distance_to_alignment_m for f in linked
                                                    if f.distance_to_alignment_m is not None), default=None),
                "zone": next((f.zone for f in linked if f.zone), None),
            }
            recorded = fields.get("area_hectares")
            computed = spatial["area_hectares_computed"]
            if recorded and recorded.status == "KNOWN" and computed and not _same_within(recorded.value, computed, 0.10):
                case_warnings.append(f"Recorded area ({recorded.value} ha) differs from the mapped parcel area "
                                     f"({computed} ha) by more than 10%.")
        else:
            case_warnings.append("No validated map geometry is linked to this case; spatial conclusions are disabled.")
        known = sum(1 for n in CORE_STATUS if fields[n].status == "KNOWN")
        quality = "GOOD" if known == len(CORE_STATUS) and not case_conflicts else ("PARTIAL" if known or linked else "POOR")
        if case_conflicts:
            case_warnings.append(f"{len(case_conflicts)} field(s) have conflicting evidence and are left unresolved.")
        if any(fv.status == "UNVERIFIED" for fv in fields.values()):
            case_warnings.append("Some values were inferred from free text and are unverified.")

        case = Case(
            case_id=uid, case_ref=ref, project_id=project_id, corridor_id=corridor_id,
            parcel_ids=sorted({f.parcel_id for f in linked if f.parcel_id} |
                              set(fields.get("parcel_id", FieldValue(value=[])).value or [])),
            fields=fields, geometry_refs=[{"map_id": f.map_id, "feature_id": f.feature_id} for f in linked],
            spatial=spatial, conflicts=case_conflicts, data_quality=quality, warnings=case_warnings,
            prediction=Prediction(status=PredictionStatus.NOT_READY, reason="pending"),
        )
        case.prediction = predict(case)
        case.actions = recommend(case, {f.fact_id: f for f in fs}, linked)
        cases.append(case)

    if unattached:
        warnings.append(f"{unattached} document fact(s) could not be tied to a single case and were not merged.")
    return cases, conflicts, matches, warnings
