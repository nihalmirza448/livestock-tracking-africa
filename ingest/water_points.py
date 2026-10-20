"""Provisional water points for the pilot area from OpenStreetMap (Overpass).

A list from NIDAA or the ministry should replace this; rows are tagged
source='osm_provisional' so they can be told apart and removed.
"""

import requests

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]

KIND_BY_TAG = [
    (("man_made", "water_well"), "well"),
    (("man_made", "reservoir"), "dam"),
    (("landuse", "reservoir"), "dam"),
    (("waterway", "dam"), "dam"),
    (("amenity", "water_point"), "borehole"),
    (("water", "river"), "river"),
    (("water", "reservoir"), "dam"),
    (("water", "pond"), "pond"),
    (("natural", "water"), "pond"),
]


def classify(tags):
    for (k, v), kind in KIND_BY_TAG:
        if tags.get(k) == v:
            return kind
    return "other"


def main(store, area_id="south_kordofan"):
    area = store.area(area_id)
    s, w, n, e = area["min_lat"], area["min_lon"], area["max_lat"], area["max_lon"]
    bbox = f"{s},{w},{n},{e}"
    query = f"""
    [out:json][timeout:180];
    (
      node["natural"="water"]({bbox}); way["natural"="water"]({bbox});
      way["man_made"="reservoir"]({bbox}); way["landuse"="reservoir"]({bbox});
      node["man_made"="water_well"]({bbox}); node["amenity"="water_point"]({bbox});
      way["waterway"="dam"]({bbox});
    );
    out center;
    """
    errors = []
    for url in OVERPASS:
        r = requests.post(url, data={"data": query}, timeout=300,
                          headers={"User-Agent": "slewcis-ingest/1.0 (water point seed)"})
        if r.ok:
            break
        errors.append(f"{url} -> {r.status_code}: {r.text[:300]}")
    else:
        raise RuntimeError("Overpass failed: " + " | ".join(errors))
    rows = []
    for el in r.json().get("elements", []):
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        tags = el.get("tags", {})
        rows.append({
            "area_id": area_id,
            "osm_id": el["id"] * (1 if el["type"] == "node" else -1),  # ways negative to avoid id clashes
            "name": tags.get("name:en") or tags.get("name"),
            "name_ar": tags.get("name:ar"),
            "kind": classify(tags),
            "geom": f"SRID=4326;POINT({lon} {lat})",
            "source": "osm_provisional",
        })
    if not rows:
        print("Overpass returned no water features for the pilot box")
        return 1
    store.upsert_water_points(rows)
    kinds = {}
    for row in rows:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    print(f"Upserted {len(rows)} provisional water points: {kinds}")
    return 0
