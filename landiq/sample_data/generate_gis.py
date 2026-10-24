"""Valid GIS inputs in every supported format, matching the cases in corridor_dossier.pdf.

Run:  python landiq/sample_data/generate_gis.py   -> writes landiq/sample_data/gis/
Upload ONE of these per project together with the PDFs (they describe the same parcels,
so uploading several would double-count parcel areas). All data is fictional.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Polygon, box

OUT = Path(__file__).resolve().parent / "gis"

ALIGNMENT = LineString([(76.60, 28.18), (76.63, 28.19), (76.66, 28.20), (76.69, 28.21)])
PARCELS = [  # (props, lng, lat) of the south-west corner of a ~17 ha square
    ({"parcel_id": "P-0472-A", "case_id": "#0472", "survey_no": "142/3A", "zone": "Zone A", "village": "Kishangarh Khurd"},
     76.610, 28.181),
    ({"parcel_id": "P-0511-A", "case_id": None, "survey_no": "88/1", "zone": "Zone A", "village": "Rampura Kalan"},
     76.625, 28.187),
    ({"parcel_id": "P-0618-A", "case_id": "#0618", "survey_no": "210/2", "zone": "Zone B", "village": "Dharuhera"},
     76.640, 28.192),
    ({"parcel_id": "P-0655-A", "case_id": "#0655", "survey_no": "45/7", "zone": "Zone B", "village": "Bawal"},
     76.650, 28.230),
    ({"parcel_id": "P-0705-A", "case_id": "#0705", "survey_no": "301/5", "zone": "Zone C", "village": "Khol"},
     76.670, 28.201),
    ({"parcel_id": "P-0706-A", "case_id": "#0706", "survey_no": "302/1", "zone": "Zone C", "village": "Khol"},
     76.676, 28.205),
]


def parcels_gdf() -> gpd.GeoDataFrame:
    rows = [{**props, "geometry": box(x, y, x + 0.004, y + 0.004)} for props, x, y in PARCELS]
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def alignment_gdf() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame([{"name": "Rewari Bypass alignment", "role": "alignment", "geometry": ALIGNMENT}],
                            crs="EPSG:4326")


def write_geojson() -> None:
    combined = gpd.GeoDataFrame(list(parcels_gdf().to_dict("records")) + list(alignment_gdf().to_dict("records")),
                                crs="EPSG:4326")
    (OUT / "1_corridor_parcels.geojson").write_text(combined.to_json(drop_id=True, indent=1), encoding="utf-8")


def write_shapefile_zip() -> None:
    """Zipped Shapefile in UTM zone 43N (metres), to show reprojection to WGS84."""
    tmp = Path(tempfile.mkdtemp())
    try:
        utm = gpd.GeoDataFrame(list(parcels_gdf().to_dict("records")) + list(alignment_gdf().to_dict("records")),
                               crs="EPSG:4326").to_crs("EPSG:32643")
        # Shapefiles keep one geometry type per file: parcels here, the alignment in the GeoPackage example.
        utm[utm.geometry.geom_type == "Polygon"].to_file(tmp / "corridor_parcels_utm43n.shp")
        with zipfile.ZipFile(OUT / "2_corridor_parcels_utm43n_shapefile.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for part in sorted(tmp.iterdir()):
                zf.write(part, part.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def write_geopackage() -> None:
    """Two layers: parcels and the alignment (spatial relations are computed across layers)."""
    path = OUT / "3_corridor_layers.gpkg"
    path.unlink(missing_ok=True)
    parcels_gdf().to_file(path, layer="parcels", driver="GPKG")
    alignment_gdf().to_file(path, layer="alignment", driver="GPKG")


def write_kml() -> None:
    combined = gpd.GeoDataFrame(list(parcels_gdf().to_dict("records")) + list(alignment_gdf().to_dict("records")),
                                crs="EPSG:4326")
    combined["Name"] = combined["parcel_id"].fillna(combined["name"])
    path = OUT / "4_corridor_parcels.kml"
    path.unlink(missing_ok=True)
    combined.to_file(path, driver="KML")


def write_map_image() -> None:
    """A plain picture of the map: no georeference, so it is kept as a visual reference only."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=600, height=400)

    def xy(lng: float, lat: float) -> pymupdf.Point:
        return pymupdf.Point(40 + (lng - 76.60) * 5500, 360 - (lat - 28.175) * 5500)

    for props, x, y in PARCELS:
        page.draw_rect(pymupdf.Rect(xy(x, y + 0.004), xy(x + 0.004, y)), color=(0.1, 0.3, 0.7), fill=(0.8, 0.88, 1))
        page.insert_text(xy(x, y + 0.0045), props["parcel_id"], fontsize=7)
    pts = [xy(*c) for c in ALIGNMENT.coords]
    for a, b in zip(pts, pts[1:]):
        page.draw_line(a, b, color=(0.85, 0.1, 0.1), width=2)
    page.insert_text(pymupdf.Point(40, 30), "Rewari Bypass - parcel sketch (not to scale)", fontsize=12)
    page.get_pixmap(dpi=110).save(OUT / "5_parcel_sketch_unreferenced.png")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    write_geojson()
    write_shapefile_zip()
    write_geopackage()
    write_kml()
    write_map_image()
    print(f"GIS samples written to {OUT}")


if __name__ == "__main__":
    main()
