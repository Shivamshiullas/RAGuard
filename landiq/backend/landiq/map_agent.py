"""Map Intelligence Agent.

Vector GIS (GeoJSON, zipped Shapefile, GeoPackage, KML):
- read every layer, require a known CRS (GeoJSON/KML default to WGS84 by spec;
  a Shapefile without .prj or a layer without CRS is rejected, never guessed)
- validate each geometry; invalid features are quarantined (excluded, counted, reported)
- reproject to EPSG:4326 for Leaflet; compute areas and distances in a local UTM CRS
- read parcel/case/survey/zone attributes into facts with map provenance
- relate parcels to a corridor alignment only when the layer actually contains one

Map images and map PDFs carry no georeference: they are stored as visual
references only. No features, no spatial relationships, no parcel claims.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from . import faults
from .config import get_settings
from .pdf_agent import PermanentAgentError, normalize_case_ref, normalize_survey
from .schemas import AgentState, ErrorInfo, Fact, MapFeature, MapProvenance, MapResult, ValidationStatus

log = logging.getLogger(__name__)

VECTOR_EXT = {".geojson", ".json", ".zip", ".gpkg", ".kml", ".shp"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
PDF_EXT = {".pdf"}
SUPPORTED_EXT = VECTOR_EXT | IMAGE_EXT | PDF_EXT

ATTR_KEYS = {
    "parcel_id": ("parcel_id", "parcelid", "parcel", "parcel_no", "pid", "plot_id", "plotid"),
    "case_id": ("case_id", "caseid", "case", "case_no", "case_ref", "caseref"),
    "survey": ("survey_no", "survey_nos", "survey", "sy_no", "syno", "khasra", "khasra_no"),
    "zone": ("zone", "zone_name"),
    "role": ("role", "type", "kind", "layer_type", "feature_type", "class"),
    "village": ("village", "village_name"),
    "district": ("district",),
}
ALIGNMENT_WORDS = re.compile(r"align|corridor|centerline|centreline|chainage|row|right.of.way", re.I)


def _attr(props: dict[str, Any], key: str) -> Any:
    lowered = {k.lower(): v for k, v in props.items()}
    for name in ATTR_KEYS[key]:
        value = lowered.get(name)
        if value not in (None, "") and str(value).lower() not in ("nan", "none", "null"):
            return value
    return None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return None if value != value else value  # NaN -> None
    return str(value)


def _read_layers(path: Path, ext: str) -> list[tuple[str, Any]]:
    """Return [(layer_name, GeoDataFrame)]. Raises PermanentAgentError on unreadable input."""
    import geopandas as gpd
    import pyogrio

    work_dir: Path | None = None
    try:
        source = path
        if ext == ".zip":
            work_dir = Path(tempfile.mkdtemp(prefix="landiq_shp_"))
            with zipfile.ZipFile(path) as zf:
                names = [n for n in zf.namelist() if not n.endswith("/")]
                if any(n.startswith("/") or ".." in Path(n).parts for n in names):
                    raise PermanentAgentError("MAP_INVALID_ARCHIVE", "The archive contains unsafe paths.",
                                              "Zip only the shapefile parts (.shp, .shx, .dbf, .prj).")
                total = sum(zf.getinfo(n).file_size for n in names)
                if total > get_settings().max_map_mb * 1024 * 1024 * 4:
                    raise PermanentAgentError("MAP_TOO_LARGE", "The archive expands beyond the size limit.")
                zf.extractall(work_dir)
            shps = list(work_dir.rglob("*.shp"))
            if len(shps) != 1:
                raise PermanentAgentError("MAP_INVALID_ARCHIVE", "The zip must contain exactly one .shp file.",
                                          "Zip one shapefile with its .shx, .dbf and .prj files.")
            source = shps[0]
            missing = [s for s in (".shx", ".dbf") if not source.with_suffix(s).exists()]
            if missing:
                raise PermanentAgentError("MAP_INVALID_ARCHIVE", f"The shapefile is missing {', '.join(missing)}.")
            if not source.with_suffix(".prj").exists():
                raise PermanentAgentError("CRS_MISSING", "The shapefile has no .prj file, so its coordinate system is unknown.",
                                          "Include the .prj file. LANDIQ does not guess coordinate systems.")
        try:
            layers = [name for name, _ in pyogrio.list_layers(source)]
        except Exception:  # noqa: BLE001
            raise PermanentAgentError("MAP_UNREADABLE", "The map file could not be read as GIS data.",
                                      "Check the file is valid GeoJSON, Shapefile (zipped), GeoPackage or KML.") from None
        out = []
        for layer in layers:
            try:
                gdf = gpd.read_file(source, layer=layer)
            except Exception:  # noqa: BLE001
                raise PermanentAgentError("MAP_UNREADABLE", f"Layer '{layer}' could not be read.") from None
            out.append((str(layer), gdf))
        return out
    finally:
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)


def _unreferenced(map_id: str, filename: str, ext: str) -> MapResult:
    kind = "pdf_unreferenced" if ext in PDF_EXT else "raster_unreferenced"
    return MapResult(
        map_id=map_id, filename=filename, state=AgentState.SUCCEEDED, input_type=kind, spatial_analysis="UNAVAILABLE",
        warnings=["This map has no georeference. It is stored as a visual reference only; no parcel geometry, "
                  "intersections or distances are derived from it."],
    )


def process_map(map_id: str, filename: str, path: Path) -> MapResult:
    faults.check("map_agent")
    if faults.is_active("map_transient"):
        raise faults.InjectedTransientFault("injected transient map fault")
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise PermanentAgentError("MAP_UNSUPPORTED", "Unsupported map format.",
                                  "Upload GeoJSON, zipped Shapefile, GeoPackage, KML, or a PNG/JPG/PDF map image.")
    if ext in IMAGE_EXT or ext in PDF_EXT:
        return _unreferenced(map_id, filename, ext)
    if ext == ".shp":
        raise PermanentAgentError("MAP_INVALID_ARCHIVE", "A bare .shp file cannot be read without its sidecar files.",
                                  "Zip the .shp, .shx, .dbf and .prj files together and upload the zip.")

    layers = _read_layers(path, ext)
    features: list[MapFeature] = []
    facts: list[Fact] = []
    warnings: list[str] = []
    invalid = 0
    source_crs: str | None = None
    bounds: list[float] | None = None
    total = 0

    for layer, gdf in layers:
        total += len(gdf)
        if total > settings.max_features:
            raise PermanentAgentError("MAP_TOO_LARGE", f"The map has more than {settings.max_features} features.",
                                      "Split the map into smaller files.")
        if gdf.crs is None:
            if ext in (".geojson", ".json", ".kml"):
                gdf = gdf.set_crs("EPSG:4326")
                warnings.append(f"Layer '{layer}' declares no CRS; WGS84 assumed as required by the {ext[1:].upper()} format.")
            else:
                raise PermanentAgentError("CRS_MISSING", f"Layer '{layer}' has no coordinate reference system.",
                                          "Assign a CRS in your GIS tool and export again.")
        source_crs = gdf.crs.to_string()
        try:
            wgs = gdf.to_crs("EPSG:4326")
        except Exception:  # noqa: BLE001
            raise PermanentAgentError("CRS_INVALID", f"Layer '{layer}' could not be transformed to WGS84.",
                                      "Check the layer's coordinate reference system.") from None

        geoms = wgs.geometry
        finite = geoms[geoms.notna() & ~geoms.is_empty]
        if len(finite):
            minx, miny, maxx, maxy = finite.total_bounds
            if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
                raise PermanentAgentError("CRS_INVALID", f"Layer '{layer}' has coordinates outside valid longitude/latitude.",
                                          "The declared CRS does not match the coordinates. Fix the CRS and export again.")
            b = [float(minx), float(miny), float(maxx), float(maxy)]
            bounds = b if bounds is None else [min(bounds[0], b[0]), min(bounds[1], b[1]), max(bounds[2], b[2]), max(bounds[3], b[3])]

        try:
            metric = gdf.to_crs(wgs.estimate_utm_crs()) if len(finite) else None
        except Exception:  # noqa: BLE001
            metric = None

        layer_features: list[MapFeature] = []
        for idx in range(len(wgs)):
            from shapely.geometry import mapping
            from shapely.validation import explain_validity

            geom = wgs.geometry.iloc[idx]
            props = {str(k): _json_safe(v) for k, v in wgs.iloc[idx].drop(labels="geometry").items()}
            feature_id = f"{map_id}-{re.sub(r'[^A-Za-z0-9]+', '_', layer)}-{idx}"
            if geom is None or geom.is_empty:
                invalid += 1
                warnings.append(f"Feature {feature_id} has no geometry and was quarantined.")
                continue
            if not geom.is_valid:
                invalid += 1
                warnings.append(f"Feature {feature_id} has invalid geometry ({explain_validity(geom)}) and was quarantined.")
                continue

            role_attr = str(_attr(props, "role") or "")
            gtype = geom.geom_type
            if "Line" in gtype and (ALIGNMENT_WORDS.search(role_attr) or ALIGNMENT_WORDS.search(layer)
                                    or ALIGNMENT_WORDS.search(str(props.get("name", "")))):
                role = "alignment"
            elif "Polygon" in gtype:
                role = "parcel"
            else:
                role = "other"
            case_raw = _attr(props, "case_id")
            case_digits = re.search(r"\d{3,5}", str(case_raw)) if case_raw is not None else None
            survey_raw = _attr(props, "survey")
            parcel = _attr(props, "parcel_id")
            area = None
            if role == "parcel" and metric is not None:
                area = round(float(metric.geometry.iloc[idx].area) / 10_000, 4)
            layer_features.append(MapFeature(
                feature_id=feature_id, map_id=map_id, layer=layer, geometry_type=gtype,
                geometry=_round_geojson(mapping(geom)), parcel_id=str(parcel).strip() if parcel is not None else None,
                case_id=normalize_case_ref(case_digits.group(0)) if case_digits else None,
                survey_numbers=normalize_survey(str(survey_raw)) if survey_raw is not None else [],
                zone=str(_attr(props, "zone")) if _attr(props, "zone") is not None else None,
                role=role, area_hectares=area, attributes=props,
            ))

        # Spatial relationships only when this layer set contains an alignment.
        alignments = [f for f in layer_features if f.role == "alignment"]
        if metric is not None and alignments:
            from shapely.ops import unary_union

            idx_of = {f.feature_id: int(f.feature_id.rsplit("-", 1)[1]) for f in layer_features}
            align_geom = unary_union([metric.geometry.iloc[idx_of[a.feature_id]] for a in alignments])
            for f in layer_features:
                if f.role == "parcel":
                    g = metric.geometry.iloc[idx_of[f.feature_id]]
                    f.distance_to_alignment_m = round(float(g.distance(align_geom)), 2)
                    f.intersects_alignment = bool(g.intersects(align_geom))
        features.extend(layer_features)

    # Cross-layer alignment (e.g. GeoPackage with separate parcel and alignment layers).
    if any(f.role == "alignment" for f in features) and any(f.role == "parcel" and f.distance_to_alignment_m is None
                                                           for f in features):
        _relate_across_layers(features)

    for f in features:
        prov = MapProvenance(map_id=map_id, filename=filename, layer=f.layer, feature_id=f.feature_id, crs=source_crs)
        if f.case_id:
            facts.append(_fact(f, "case_id", f.case_id, f.case_id, prov, "gis:attribute"))
        if f.parcel_id:
            facts.append(_fact(f, "parcel_id", f.parcel_id, f.parcel_id, prov, "gis:attribute"))
        for sn in f.survey_numbers:
            facts.append(_fact(f, "survey_numbers", sn, sn, prov, "gis:attribute"))
        if f.area_hectares is not None:
            facts.append(_fact(f, "area_hectares", f"{f.area_hectares} ha (computed)", f.area_hectares, prov, "gis:spatial"))
        for key in ("village", "district"):
            val = _attr(f.attributes, key)
            if val is not None:
                facts.append(_fact(f, key, str(val), str(val).strip().title(), prov, "gis:attribute"))

    valid = len(features)
    if valid == 0:
        state = AgentState.FAILED
        error = ErrorInfo(code="GEOMETRY_INVALID" if invalid else "MAP_EMPTY", stage="map_agent",
                          message="No valid features were found in the map." if invalid else "The map has no features.",
                          remediation="Repair the geometries in your GIS tool and upload again.")
    else:
        state = AgentState.PARTIAL if invalid else AgentState.SUCCEEDED
        error = None
    if valid and not any(f.role == "alignment" for f in features):
        warnings.append("No corridor alignment found; distance/intersection with the alignment were not computed.")
    return MapResult(
        map_id=map_id, filename=filename, state=state, input_type="vector", source_crs=source_crs,
        output_crs="EPSG:4326" if features else None, layers=[name for name, _ in layers], feature_count=valid,
        invalid_feature_count=invalid, features=features, facts=facts, bounds=bounds,
        spatial_analysis="COMPUTED" if features else "UNAVAILABLE", warnings=warnings[:50], error=error,
    )


def _relate_across_layers(features: list[MapFeature]) -> None:
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.ops import unary_union

    gdf = gpd.GeoDataFrame({"fid": [f.feature_id for f in features]},
                           geometry=[shape(f.geometry) for f in features], crs="EPSG:4326")
    metric = gdf.to_crs(gdf.estimate_utm_crs())
    geom_of = dict(zip(gdf["fid"], metric.geometry))
    align = unary_union([geom_of[f.feature_id] for f in features if f.role == "alignment"])
    for f in features:
        if f.role == "parcel" and f.distance_to_alignment_m is None:
            g = geom_of[f.feature_id]
            f.distance_to_alignment_m = round(float(g.distance(align)), 2)
            f.intersects_alignment = bool(g.intersects(align))


def _fact(f: MapFeature, field: str, value: str, normalized, prov: MapProvenance, method: str) -> Fact:
    return Fact(fact_id=f"F-{f.feature_id}-{field}-{normalized}"[:120], field=field, value=str(value),
                normalized_value=normalized, case_id=f.case_id, parcel_id=f.parcel_id, extraction_method=method,
                validation_status=ValidationStatus.VALIDATED, provenance=prov)


def _round_geojson(geom: dict) -> dict:
    def r(c):
        if isinstance(c, (list, tuple)):
            return [r(x) for x in c]
        return round(float(c), 7)

    return {"type": geom["type"], "coordinates": r(geom["coordinates"])}
