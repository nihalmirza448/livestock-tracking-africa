"""Load the official pilot-area boundary from geoBoundaries (gbOpen, CC-BY)."""

import requests

GB_API = "https://www.geoboundaries.org/api/current/gbOpen/SDN/ADM1/"
NAMES = {"south_kordofan": ("south kordofan", "southern kordofan", "janub kurdufan", "south kurdufan")}


def main(store, area_id="south_kordofan"):
    meta = requests.get(GB_API, timeout=60)
    meta.raise_for_status()
    meta = meta.json()
    gj = requests.get(meta["gjDownloadURL"], timeout=300)
    gj.raise_for_status()
    features = gj.json()["features"]
    wanted = NAMES[area_id]
    match = [f for f in features if f["properties"].get("shapeName", "").strip().lower() in wanted]
    if not match:
        names = sorted(f["properties"].get("shapeName", "") for f in features)
        print(f"No feature named {wanted}; available: {names}")
        return 1
    feat = match[0]
    feat["properties"] = {k: feat["properties"].get(k) for k in ("shapeName", "shapeISO", "shapeID", "shapeGroup")}
    store.update_area(area_id, {
        "boundary_geojson": feat,
        "boundary_source": f"geoBoundaries gbOpen SDN ADM1 {meta.get('boundaryYearRepresented', '')} "
                           f"({meta.get('boundarySource', 'unknown source')}), {meta.get('boundaryLicense', '')}".strip(),
    })
    n = sum(len(r) for poly in (feat["geometry"]["coordinates"] if feat["geometry"]["type"] == "MultiPolygon"
            else [feat["geometry"]["coordinates"]]) for r in poly)
    print(f"Stored boundary for {area_id}: {feat['properties']['shapeName']}, {n} vertices")
    return 0
