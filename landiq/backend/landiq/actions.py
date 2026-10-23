"""Evidence-backed recommended actions for human review.

Each action is triggered by a KNOWN (or explicitly conflicting) case field and
cites the facts behind it. Actions are suggestions with a suggested owner role;
LANDIQ never executes them and none is a legal determination.
"""

from __future__ import annotations

import hashlib

from .schemas import Action, Case, DocumentProvenance, EvidenceRef, Fact, MapFeature, MapProvenance

RULES = [
    # (field, trigger values, priority, title, rationale, owner)
    ("legal_status", {"DISPUTE", "IN_COURT"}, "HIGH", "Review the pending legal dispute",
     "Source records show an unresolved legal dispute or court proceeding affecting possession.",
     "Competent Authority for Land Acquisition (CALA) with the legal cell"),
    ("legal_status", {"PENDING_SETTLEMENT"}, "MEDIUM", "Track the settlement / mediation process",
     "Records indicate a settlement or mediation route is in progress.", "CALA / District Revenue Officer"),
    ("compensation_status", {"DISPUTED"}, "HIGH", "Review the disputed compensation award",
     "Landowners have contested or appealed the compensation award.", "Special Land Acquisition Officer (SLAO)"),
    ("compensation_status", {"PENDING"}, "HIGH", "Review pending compensation disbursement",
     "Compensation is recorded as pending, which commonly blocks site handover.", "Special Land Acquisition Officer (SLAO)"),
    ("compensation_status", {"IN_PROGRESS"}, "MONITOR", "Monitor remaining compensation disbursement",
     "Compensation disbursement is partially complete.", "SLAO desk"),
    ("clearance_status", {"DELAYED", "PENDING"}, "MEDIUM", "Expedite the pending statutory clearance",
     "A required approval or clearance is recorded as pending or delayed.", "Project Director, PIU, with the clearing department"),
    ("clearance_status", {"UNDER_REVIEW"}, "MONITOR", "Follow up on the clearance under review",
     "A clearance is under review.", "Project Director, PIU"),
    ("rr_status", {"PENDING", "IN_PROGRESS"}, "MONITOR", "Coordinate rehabilitation & resettlement (R&R) delivery",
     "R&R is recorded as not yet complete.", "R&R Commissioner / Administrator"),
]


def _ref(f: Fact) -> EvidenceRef:
    p = f.provenance
    if isinstance(p, DocumentProvenance):
        return EvidenceRef(fact_id=f.fact_id, document_id=p.document_id, page=p.page, snippet=p.snippet)
    assert isinstance(p, MapProvenance)
    return EvidenceRef(fact_id=f.fact_id, map_id=p.map_id, feature_id=p.feature_id)


def _id(case_id: str, title: str) -> str:
    return "A-" + hashlib.sha1(f"{case_id}|{title}".encode()).hexdigest()[:12]


def recommend(case: Case, facts: dict[str, Fact], features: list[MapFeature]) -> list[Action]:
    actions: list[Action] = []
    for field, triggers, priority, title, rationale, owner in RULES:
        fv = case.fields.get(field)
        if fv is None or fv.status != "KNOWN" or fv.value not in triggers:
            continue
        refs = [_ref(facts[fid]) for fid in fv.facts if fid in facts][:5]
        if not refs:
            continue  # never recommend without evidence
        actions.append(Action(action_id=_id(case.case_id, title), case_id=case.case_id, title=title,
                              rationale=rationale, evidence=refs, suggested_owner=owner, priority=priority))

    conflicting = [n for n, fv in case.fields.items() if fv.status == "CONFLICT"]
    if conflicting:
        refs = [_ref(facts[fid]) for n in conflicting for fid in case.fields[n].facts if fid in facts][:6]
        title = "Reconcile conflicting records: " + ", ".join(n.replace("_", " ") for n in conflicting)
        actions.append(Action(action_id=_id(case.case_id, title), case_id=case.case_id, title=title,
                              rationale="Sources disagree; LANDIQ does not pick a value. Verify against the original records.",
                              evidence=refs, suggested_owner="Case officer / data steward", priority="HIGH"))

    if case.spatial.get("intersects_alignment") and features:
        parcel = next((f for f in features if f.intersects_alignment), None)
        if parcel is not None:
            title = "Confirm acquisition status of the parcel on the alignment"
            actions.append(Action(
                action_id=_id(case.case_id, title), case_id=case.case_id, title=title,
                rationale="The validated parcel geometry intersects the corridor alignment.",
                evidence=[EvidenceRef(map_id=parcel.map_id, feature_id=parcel.feature_id)],
                suggested_owner="Project Director, PIU / survey team", priority="MEDIUM"))
    order = {"HIGH": 0, "MEDIUM": 1, "MONITOR": 2}
    return sorted(actions, key=lambda a: order[a.priority])
