# Failsafe demo set

One upload set that triggers failsafes in **both** agents, with every recovery outcome.

1. Create a new project.
2. Upload everything in `documents\` as **PDF documents**.
3. Upload everything in `maps\` as **GIS / map files**.
4. Click **Run analysis job**.

## Expected Failsafe status

The job ends **PARTIAL**: the good files still produce all 6 cases.

**PDF Agent (PyMuPDF): Failsafe Triggered: YES (3), Partially recovered**

| Input | Trigger | Reason | Fallback used | Recovery |
|---|---|---|---|---|
| `1_corridor_dossier.pdf` | none | Clean text PDF | n/a | n/a |
| `2_scanned_notice.pdf` | `OCR_USED` | No selectable text on page 1 | Page read by OCR (RapidOCR) | Succeeded |
| `3_inspection_report_with_blank_page.pdf` | `PAGES_UNREADABLE` | Page 2 is a blank scan, unreadable even by OCR | Page skipped, page 1 used | Partial |
| `4_password_protected.pdf` | `PDF_ENCRYPTED` | Password-protected | No retry; file quarantined | Failed |

**GIS Agent: Failsafe Triggered: YES (3), Partially recovered**

| Input | Trigger | Reason | Fallback used | Recovery |
|---|---|---|---|---|
| `1_parcels_two_broken.geojson` | `GEOMETRY_INVALID` | 2 self-intersecting parcels | Bad features quarantined, 7 valid kept | Partial |
| `2_parcel_sketch.png` | `NO_GEOREFERENCE` | Picture with no coordinates | Kept as visual reference only | Partial |
| `3_shapefile_missing_prj.zip` | `CRS_MISSING` | No `.prj`, coordinate system unknown | No retry; file quarantined | Failed |

## Retry failsafes

Retries need a temporary outage, which a file cannot cause. Add one to `landiq\backend\.env`, restart the backend, and run a job:

| `.env` line | Card shows |
|---|---|
| `FAULTS=pdf_flaky` | PDF: `TRANSIENT_ERROR`, retried, **succeeded on attempt 2 of 3** |
| `FAULTS=pdf_transient` | PDF: `TRANSIENT_ERROR`, 3 attempts all failed, **Failed** |
| `FAULTS=map_transient` | GIS: same, for maps |
| `FAULTS=map_agent` | GIS: `AGENT_CRASH`, crash isolated, PDF results kept |

Remove the line (or set `FAULTS=`) and restart to return to normal.

## Clean comparison

Upload only `documents\1_corridor_dossier.pdf` and `..\gis\3_corridor_layers.gpkg`. Both cards then show **Failsafe Triggered: NO.**
