# 🎬 LANDIQ — SIH 2026 Demo Video Script
### Duration: 3 min 30 sec | Format: Screen Recording + Voiceover

---

## PRE-RECORDING SETUP CHECKLIST
- [ ] Browser open at **http://localhost:5173** — Dashboard visible
- [ ] Browser set to **1920×1080**, **Full Screen (F11)**
- [ ] Zoom browser to **90%** for best UI density
- [ ] **Click "SIH 2026 Pitch Mode"** once — note the tour panel but **close it immediately** for the recording (use it manually)
- [ ] Microphone tested, quiet room
- [ ] Recommended screen recorder: OBS Studio or Loom

---

## 🎙️ NARRATION + SCREEN ACTION — TIMED BREAKDOWN

---

### ⏱️ SEGMENT 1 — THE PROBLEM (0:00 – 0:30)
> **On screen:** Dashboard loaded, no interaction yet. Let the UI breathe.

**[Narration — speak slowly & clearly]**

> *"India builds 30+ km of national highway every day. But beneath every construction milestone lies a silent bottleneck — land acquisition.*
>
> *Across 1,240 parcels on a single highway corridor, project directors have no real-time way to know — which parcels will turn into legal disputes, which compensation files are stuck, which government approvals are overdue.*
>
> *The result? Thousands of crores locked. Projects delayed by months or years.*
>
> *We built LANDIQ — a predictive analytics system that flags land acquisition delays before they happen."*

---

### ⏱️ SEGMENT 2 — DASHBOARD OVERVIEW (0:30 – 1:00)
> **On screen:**
> 1. Slowly pan the cursor over the **4 KPI Cards**
> 2. Hover over the **Donut Chart** to show the 72/25/3% breakdown tooltip
> 3. Hover over the **Risk Trend Line Chart** — last few points

**[Narration]**

> *"The LANDIQ dashboard gives the Project Director a real-time corridor health view.*
>
> *Out of 1,240 acquisition parcels on NH-XXX — 37 are predicted High Risk.*
>
> *The system continuously monitors risk trends — and you can see here, the average delay probability has been slowly creeping up over the last 6 months.*
>
> *Those 37 cases? Let's find out who they are."*

> 👉 **Click "VIEW HIGH-RISK CASES"**

---

### ⏱️ SEGMENT 3 — HIGH-RISK PRIORITIZED QUEUE (1:00 – 1:25)
> **On screen:**
> 1. Table loads with HIGH RISK filter active
> 2. Hover briefly over row `#0511` and `#0732`
> 3. Move cursor to `#0472` row — pause 1 second

**[Narration]**

> *"Instead of a project director manually reviewing thousands of files, LANDIQ presents a ranked queue of high-risk acquisition bottlenecks.*
>
> *Each row shows the delay probability, legal status, compensation status, and approvals — at a glance.*
>
> *Case #0472 in Zone A has an 82% predicted delay probability. Let's dig in."*

> 👉 **Click on Case #0472 row**

---

### ⏱️ SEGMENT 4 — CASE DETAILS HERO PAGE (1:25 – 2:00)
> **On screen:**
> 1. Watch the **82% counter animate up** from 0
> 2. Pan over the **5 status cards** — Legal → Compensation → Approval → R&R → Project Progress
> 3. Scroll down slowly to the **SHAP Horizontal Contribution Chart**

**[Narration]**

> *"This is Case #0472 — 18 hectares in Zone A of Kishangarh Khurd, Rewari District.*
>
> *The model predicts an 82% probability of acquisition delay — which translates to approximately 140 additional days of construction hold-up.*
>
> *Looking at the live status indicators — there's an active title dispute at the District Revenue Tribunal. Only 28% of the ₹14.85 crore compensation has been disbursed. And the Stage-2 Forest Clearance has been pending for over 95 days.*
>
> *But here's the critical question — why exactly is this case high risk? Our system tells you."*

> 👉 **Click "SHAP Explainability" button (top right)**

---

### ⏱️ SEGMENT 5 — EXPLAINABILITY (2:00 – 2:35)
> **On screen:**
> 1. Risk Explanation page loads
> 2. Pan over the **Waterfall Summary callout box**
> 3. Slowly scroll through the **4 attribution cards**
> 4. Hover over the ML Architecture panel at the bottom

**[Narration]**

> *"Black-box AI is unacceptable in government decision-making. LANDIQ uses SHAP — SHapley Additive exPlanations — to explain every single prediction.*
>
> *The model moved from a baseline probability of 24% — all the way to 82% — because of these specific, traceable factors.*
>
> *The ongoing legal dispute contributes +0.31 to the risk score. Pending compensation adds +0.22. The forest clearance delay adds +0.16.*
>
> *Every IAS officer, district collector, and PIU director can now see exactly which file to pick up first.*
>
> *The primary model — a Random Forest Classifier — achieves a ROC-AUC of 89.2%, significantly outperforming the logistic regression baseline at 74.1%.*
>
> *Now — what do we actually do about it?"*

> 👉 **Click "View Prescriptive Actions"**

---

### ⏱️ SEGMENT 6 — RECOMMENDED ACTIONS + SIMULATION (2:35 – 3:05)
> **On screen:**
> 1. Scroll through the **4 Action Cards** quickly
> 2. Click **"MARK FOR REVIEW"** on the first card — watch status flip
> 3. Click **"ESCALATE TO AUTHORITY"** on the second card
> 4. Click **"Simulate Mitigation"** — watch probability drop from 82% to ~38%

**[Narration]**

> *"LANDIQ doesn't just predict — it prescribes.*
>
> *For Case #0472, the system generates 4 prioritized statutory interventions: initiating a Lok Adalat fast-track review, releasing the uncontested share of compensation under Section 77(2) of the RFCTLARR Act, escalating forest clearance through PM GatiShakti — and deploying an R&R liaison officer.*
>
> *A project director can mark interventions in the workflow — and watch what happens.*
>
> *When these mitigations are simulated — the predicted delay probability drops from 82% — HIGH RISK — all the way down to 38% — MEDIUM RISK.*
>
> *That's the power of early action. Now let's see where this case sits on the ground."*

> 👉 **Click "Open Parcel-Level GIS Map"**

---

### ⏱️ SEGMENT 7 — GIS MAP (3:05 – 3:25)
> **On screen:**
> 1. GIS Map loads with highway corridor and color-coded parcels
> 2. Click the **Zone A Focus** button to center on the cluster
> 3. Click the **#0472 parcel polygon** — popup shows
> 4. Hover over the risk hotspot callout badge (top right of map)

**[Narration]**

> *"The GIS Spatial Intelligence module renders every acquisition parcel as a vector polygon — color-coded by delay risk.*
>
> *Here in Zone A, you can clearly see a spatial cluster of HIGH-RISK parcels around Km 42+350 — that's exactly where Case #0472 and its adjacent contested parcels sit.*
>
> *A field team can immediately pinpoint the geographic obstruction blocking the highway alignment — and coordinate a ground inspection.*
>
> *This is the complete closed loop — from raw data, to prediction, to explanation, to recommended action, to spatial location."*

---

### ⏱️ SEGMENT 8 — CLOSING STATEMENT (3:25 – 3:45)
> **On screen:** Navigate back to **Dashboard** — let the full UI show one final time.

**[Narration]**

> *"LANDIQ is built on a proven technical stack — React and FastAPI frontend-backend, PostgreSQL with PostGIS for spatial land records, Scikit-learn Random Forest as the core model, and SHAP for full explainability.*
>
> *It is designed to integrate with existing government systems — DILRMP for digitized land records, PM GatiShakti APIs, and NHAI CMIS — to serve Project Directors, District Collectors, Competent Authority Land Acquisition officers, and senior MoRTH officials.*
>
> *LANDIQ transforms land acquisition from a reactive, file-driven process — into a proactive, data-driven early warning system.*
>
> *Thank you."*

---

## 📋 QUICK REFERENCE — CLICK SEQUENCE SUMMARY

```
1. Dashboard loads (don't click anything — narrate)
2. Hover KPI cards → Hover Donut chart
3. Click "VIEW HIGH-RISK CASES"
4. Click Row: Case #0472
5. Watch 82% counter animate
6. Pan over 5 status cards + SHAP chart
7. Click "SHAP Explainability" (top right)
8. Pan through 4 attribution cards
9. Click "View Prescriptive Actions"
10. Click "MARK FOR REVIEW" (Card 1)
11. Click "Simulate Mitigation" → watch 82% → 38% drop
12. Click "Open Parcel-Level GIS Map"
13. Click Zone A button → Click #0472 parcel polygon
14. Navigate back to Dashboard → closing shot
```

---

## 🎥 PRODUCTION TIPS

| Tip | Recommendation |
| :--- | :--- |
| **Screen recorder** | OBS Studio (free) or Loom for quick export |
| **Narration pace** | Speak at ~130 words/min — slightly slower than natural pace |
| **Mouse movement** | Move slowly and deliberately — avoid rapid cursor flicks |
| **Transitions** | Add 0.5s fade-in between major page transitions in editing |
| **Background music** | Optional: subtle ambient/corporate track at 10-15% volume |
| **Editing tool** | CapCut (free, quick export) or Adobe Premiere |
| **Text overlays** | Add section title cards: e.g., *"STEP 4: Explainability (SHAP)"* |
| **Export format** | MP4, 1920×1080, 60fps, H.264 |

---

> **Total Estimated Duration:** ~3 min 30 sec
> **Tone:** Confident, crisp, problem-first, non-technical for judges

