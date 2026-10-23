"""Synthetic demo corridor: one internally consistent, deterministic dataset.

Everything here is ILLUSTRATIVE. Cases are flagged is_synthetic, their
figures live only under `illustrative` (labelled), their predictions are
DEMO_ONLY with null numeric fields, and their geometries are invented. Every
count and percentage shown for the demo corridor is derived from these cases.

The eight hero cases (#0472 ...) come from the original LANDIQ prototype so
the screenshot story stays the same. The rest are generated with a fixed seed.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from .prediction import predict
from .runtime import get_repo
from .schemas import Case, FieldValue, MapFeature, Prediction, PredictionStatus, Project

DEMO_PROJECT_ID = "demo-dme-pkg4"
DEMO_MAP_ID = "demo-synthetic-map"
SEED = 2026
TOTAL = 840
TARGET = {"HIGH": 28, "MEDIUM": 162, "LOW": 650}  # sums to TOTAL
LABEL = "Illustrative Data: synthetic demo case, not real government records or model output."
HERO_FILE = Path(__file__).parent / "data" / "demo_hero_cases.json"

ZONES = ["Zone A", "Zone B", "Zone C", "Zone D", "Zone E"]
VILLAGES = ["Kishangarh Khurd", "Rampura Kalan", "Bilaspur Jagir", "Fatehpur Bir", "Manesar West", "Dharuhera South",
            "Bawal Greenfield", "Khori Kalan", "Jaitpur", "Nangal Pathani", "Masani", "Kasola"]
DISTRICTS = ["Rewari", "Gurugram Rural", "Gurugram", "Rewari / Gurugram Border"]
LEGAL = {"HIGH": ["Dispute", "In Court", "Dispute"], "MEDIUM": ["Clear", "Pending Settlement", "Dispute"], "LOW": ["Clear"]}
COMP = {"HIGH": ["Pending", "Disputed"], "MEDIUM": ["In Progress", "Pending"], "LOW": ["Disbursed", "In Progress"]}
APPR = {"HIGH": ["Delayed", "Pending"], "MEDIUM": ["Under Review", "Pending", "Cleared"], "LOW": ["Cleared"]}
ALIGN_START, ALIGN_END = (28.43, 76.99), (28.57, 77.18)  # lat, lng of the synthetic alignment


def _alignment_point(t: float) -> tuple[float, float]:
    return (ALIGN_START[0] + (ALIGN_END[0] - ALIGN_START[0]) * t, ALIGN_START[1] + (ALIGN_END[1] - ALIGN_START[1]) * t)


def _square(lat: float, lng: float, half: float = 0.0012) -> list[list[float]]:
    return [[lat + half, lng - half], [lat + half, lng + half], [lat - half, lng + half], [lat - half, lng - half]]


def _generated(rng: random.Random, number: int, risk: str) -> dict:
    t = rng.random()
    lat, lng = _alignment_point(t)
    lat += rng.uniform(-0.004, 0.004)
    lng += rng.uniform(-0.004, 0.004)
    prob = {"HIGH": rng.randint(60, 79), "MEDIUM": rng.randint(35, 59), "LOW": rng.randint(3, 34)}[risk]
    disb = {"HIGH": rng.randint(5, 45), "MEDIUM": rng.randint(40, 80), "LOW": rng.randint(85, 100)}[risk]
    km = 38 + t * 92
    legal = rng.choice(LEGAL[risk])
    comp = rng.choice(COMP[risk])
    appr = rng.choice(APPR[risk])
    return {
        "id": f"#{number:04d}", "zone": ZONES[min(4, int(t * 5))],
        "subDivision": f"Km {int(km)}+{rng.randint(0, 9)}00 to Km {int(km) + 1}+{rng.randint(0, 9)}00",
        "surveyNo": f"Sy. No. {rng.randint(10, 400)}/{rng.randint(1, 9)}", "villageName": rng.choice(VILLAGES),
        "district": rng.choice(DISTRICTS), "areaHectares": round(rng.uniform(2, 30), 1),
        "delayProbability": prob, "riskCategory": risk,
        "legalStatus": legal, "legalDetails": f"Synthetic record: legal status {legal.lower()}.",
        "compensationStatus": comp, "compensationDetails": f"Synthetic record: {disb}% of award disbursed.",
        "compensationDisbursedPercent": disb,
        "approvalStatus": appr, "approvalDetails": f"Synthetic record: clearances {appr.lower()}.",
        "rrProgress": {"HIGH": rng.randint(40, 70), "MEDIUM": rng.randint(60, 85), "LOW": rng.randint(85, 100)}[risk],
        "rrDetails": "Synthetic record.",
        "projectProgress": {"HIGH": rng.randint(50, 75), "MEDIUM": rng.randint(65, 88), "LOW": rng.randint(85, 99)}[risk],
        "estDelayDays": {"HIGH": rng.randint(70, 130), "MEDIUM": rng.randint(20, 65), "LOW": rng.randint(0, 15)}[risk],
        "shapContributions": [], "recommendations": [],
        "coordinates": [round(lat, 5), round(lng, 5)], "polygonCoords": _square(lat, lng),
    }


def build_cases() -> list[dict]:
    rng = random.Random(SEED)
    heroes = json.loads(HERO_FILE.read_text(encoding="utf-8"))
    used = {int(h["id"].lstrip("#")) for h in heroes}
    need = dict(TARGET)
    for h in heroes:
        need[h["riskCategory"]] -= 1
    numbers = [n for n in range(1, 2000) if n not in used]
    rng.shuffle(numbers)
    rows = list(heroes)
    for risk in ("HIGH", "MEDIUM", "LOW"):
        for _ in range(need[risk]):
            rows.append(_generated(rng, numbers.pop(), risk))
    for row in rows:
        # Hero SHAP values were placeholders in the prototype; keep them clearly labelled.
        row["shapLabel"] = "Illustrative placeholder attribution, not computed by a trained model."
        row["label"] = LABEL
    return sorted(rows, key=lambda r: -r["delayProbability"])


def summary(cases: list[Case]) -> dict:
    counts = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for c in cases:
        risk = (c.illustrative or {}).get("riskCategory")
        if risk in counts:
            counts[risk] += 1
    total = sum(counts.values())
    pct = {k: round(100 * v / total, 1) if total else 0 for k, v in counts.items()}
    # Six-month illustrative trend ending at today's counts (drift is synthetic).
    months = ["May 2026", "Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026", "Oct 2026"]
    trend = []
    for i, m in enumerate(months):
        back = len(months) - 1 - i
        high = max(0, counts["HIGH"] - round(back * 0.6 * math.sin(i + 1)))
        avg = round(sum((c.illustrative or {}).get("delayProbability", 0) for c in cases) / max(total, 1) - back * 0.5, 1)
        trend.append({"month": m, "highRisk": high, "avgDelayProb": avg})
    return {"total": total, "counts": counts, "percent": pct, "trend": trend, "label": LABEL}


def seed_demo(force: bool = False) -> int:
    """Create the demo project and its synthetic cases/features. Idempotent."""
    repo = get_repo()
    if repo.get_project(DEMO_PROJECT_ID) and repo.list_cases(DEMO_PROJECT_ID) and not force:
        return 0
    repo.put_project(Project(project_id=DEMO_PROJECT_ID, name="Delhi-Mumbai Express Corridor (Package 4)",
                             corridor_id="NHAI-DME-PKG4", is_demo=True,
                             description="Synthetic demo corridor. All figures are illustrative."))
    rows = build_cases()
    cases: list[Case] = []
    features: list[MapFeature] = []
    for row in rows:
        ref = row["id"]
        case = Case(
            case_id=f"{DEMO_PROJECT_ID}.{ref.lstrip('#')}", case_ref=ref, project_id=DEMO_PROJECT_ID,
            corridor_id="NHAI-DME-PKG4", is_synthetic=True, parcel_ids=[f"DEMO-P-{ref.lstrip('#')}"],
            fields={n: FieldValue() for n in ("legal_status", "compensation_status", "clearance_status")},
            geometry_refs=[{"map_id": DEMO_MAP_ID, "feature_id": f"{DEMO_MAP_ID}-{ref.lstrip('#')}"}],
            data_quality="POOR", warnings=[LABEL],
            prediction=Prediction(status=PredictionStatus.DEMO_ONLY, reason="pending"),
            illustrative=row,
        )
        case.prediction = predict(case)
        cases.append(case)
        ring = [[lng, lat] for lat, lng in row["polygonCoords"]]
        ring.append(ring[0])
        features.append(MapFeature(
            feature_id=f"{DEMO_MAP_ID}-{ref.lstrip('#')}", map_id=DEMO_MAP_ID, layer="synthetic_parcels",
            geometry_type="Polygon", geometry={"type": "Polygon", "coordinates": [ring]},
            parcel_id=f"DEMO-P-{ref.lstrip('#')}", case_id=ref, zone=row["zone"], role="parcel",
            attributes={"synthetic": True, "riskCategory": row["riskCategory"], "label": LABEL},
        ))
    line = [[ALIGN_START[1], ALIGN_START[0]], [ALIGN_END[1], ALIGN_END[0]]]
    features.append(MapFeature(feature_id=f"{DEMO_MAP_ID}-alignment", map_id=DEMO_MAP_ID, layer="synthetic_alignment",
                               geometry_type="LineString", geometry={"type": "LineString", "coordinates": line},
                               role="alignment", attributes={"synthetic": True, "label": LABEL}))
    repo.replace_project_cases(DEMO_PROJECT_ID, cases, [], [])
    repo.replace_features(DEMO_PROJECT_ID, DEMO_MAP_ID, features)
    return len(cases)
