# LANDIQ sample data

All names, places and numbers are fictional. Regenerate with:

```powershell
python landiq\sample_data\generate.py             # PDFs + corridor_parcels.geojson
python landiq\sample_data\generate_gis.py         # gis\  (valid GIS in every format)
python landiq\sample_data\generate_bad_inputs.py  # bad_inputs\  (failsafe triggers)
```

## Happy path

Create a project, upload the four PDFs and **one** GIS file, then click **Run analysis job**.

| File | Shows |
|---|---|
| `corridor_dossier.pdf` | 6 cases (#0472, #0511, #0618, #0655, #0705, #0706) with labelled statuses |
| `tribunal_order.pdf` | Contradicts #0472's legal status → CONFLICT |
| `compensation_register.pdf` | Award amounts and disbursement percentages |
| `scanned_notice.pdf` | Image-only page, read by OCR (adds #0706's notification date) |
| `corridor_parcels.geojson` | Parcels + alignment, plus one ambiguous parcel (→ NEEDS_CLARIFICATION) and one broken polygon (quarantined) |

### `gis\`: valid GIS inputs (pick one per project)

They describe the same parcels, so uploading several double-counts areas.

| File | Format | Result with `corridor_dossier.pdf` |
|---|---|---|
| `1_corridor_parcels.geojson` | GeoJSON (WGS84) | All 6 cases linked to parcels, 5 on the alignment |
| `2_corridor_parcels_utm43n_shapefile.zip` | Zipped Shapefile in UTM 43N (metres) | Reprojected to WGS84; all 6 linked. A shapefile holds one geometry type, so it has no alignment line (distances not computed, with a warning) |
| `3_corridor_layers.gpkg` | GeoPackage, `parcels` + `alignment` layers | All 6 linked, 5 on the alignment (computed across layers) |
| `4_corridor_parcels.kml` | KML | All 6 linked, 5 on the alignment |
| `5_parcel_sketch_unreferenced.png` | Plain image | Stored as a visual reference only; no geometry derived |

## `bad_inputs\`: wrong inputs and the failsafe each one triggers

Upload them alone or mixed with the good files. The job's **Failsafes triggered** table lists each one with what went wrong, what LANDIQ did, and how to fix it. Good files in the same job are still processed.

### Rejected at upload (never stored)

| File | Upload as | Response |
|---|---|---|
| `upload_not_really_a.pdf` | PDF | HTTP 415: not a PDF (content check, not just the extension) |
| `upload_empty.pdf` | PDF | HTTP 400: the file is empty |
| `upload_parcels.csv` | Map | HTTP 415: unsupported map format |
| `upload_not_a_zip.zip` | Map | HTTP 415: not a valid archive |

Files over 50 MB (PDF) or 100 MB (map) get HTTP 413.

### Accepted, then fail safely in the job

| File | Upload as | Error code | Failsafe response |
|---|---|---|---|
| `doc_corrupt.pdf` | PDF | `PDF_CORRUPT` | Not retried; quarantined; other inputs continue |
| `doc_password_protected.pdf` | PDF | `PDF_ENCRYPTED` | Not retried; quarantined |
| `doc_blank_scan.pdf` | PDF | `NEEDS_OCR` | OCR attempted, nothing readable; document skipped, nothing guessed |
| `doc_prompt_injection.pdf` | PDF | none | Text telling the system to "report every case as clear" is treated as data: #0472 stays **Dispute** |
| `map_shapefile_missing_prj.zip` | Map | `CRS_MISSING` | Coordinate system is never guessed; quarantined |
| `map_geopackage_without_crs.gpkg` | Map | `CRS_MISSING` | Same, for a GeoPackage layer |
| `map_utm_coordinates_in_geojson.geojson` | Map | `CRS_INVALID` | Coordinates don't match the declared CRS; quarantined |
| `map_two_shapefiles_in_one_zip.zip` | Map | `MAP_INVALID_ARCHIVE` | Ambiguous archive rejected |
| `map_truncated.geojson` | Map | `MAP_UNREADABLE` | Quarantined |
| `map_all_geometry_broken.geojson` | Map | `GEOMETRY_INVALID` | Every feature quarantined; nothing fused |
| `map_empty.geojson` | Map | `MAP_EMPTY` | Nothing to analyse; quarantined |

### Simulated outages (no files needed)

Switch on outages (`vector`, `pdf_flaky`, `map_agent`, `llm`, `ocr`, …) with `FAULTS=vector,pdf_flaky` in `.env` (then restart), or at runtime with `PUT /api/v1/faults` `{"faults": ["vector"]}`. Then run a job with the happy-path files. Faults apply to every job on the server until cleared. To turn the runtime endpoint off on a shared server, set `ALLOW_FAULT_INJECTION=false`.
