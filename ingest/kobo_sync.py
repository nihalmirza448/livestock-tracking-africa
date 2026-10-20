"""Pull enumerator submissions from KoboToolbox into flow_counts and field_checks.

Forms live in forms/. Submissions are idempotent on Kobo's _uuid (client_id).
Enumerators are matched to platform users through enumerator_accounts; unmatched
submissions are kept but flagged pending_review rather than dropped.
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

KOBO_URL = os.environ.get("KOBO_URL", "https://kf.kobotoolbox.org").rstrip("/")


def _headers():
    return {"Authorization": f"Token {os.environ['KOBO_TOKEN']}", "Accept": "application/json"}


def fetch(asset, since):
    """All submissions of a form newer than `since` (ISO string or None)."""
    params = {"format": "json", "limit": 1000}
    if since:
        params["query"] = json.dumps({"_submission_time": {"$gt": since}})
    url = f"{KOBO_URL}/api/v2/assets/{asset}/data/"
    out = []
    while url:
        r = requests.get(url, params=params, headers=_headers(), timeout=120)
        r.raise_for_status()
        body = r.json()
        out += body.get("results", [])
        url, params = body.get("next"), None
    return out


def _point(geo):
    """Kobo geopoint 'lat lon alt acc' -> (lon, lat) or None."""
    try:
        lat, lon = (float(v) for v in geo.split()[:2])
        return lon, lat
    except (AttributeError, ValueError):
        return None


def _when(sub, field):
    return sub.get(field) or sub.get("_submission_time")


def map_flow(sub, points_by_code, users):
    code = sub.get("monitoring_point")
    mp = points_by_code.get(code)
    if not mp:
        return None, f"unknown monitoring point code {code!r}"
    user = users.get(sub.get("_submitted_by"))
    return {
        "client_id": sub["_uuid"],
        "monitoring_point_id": mp,
        "enumerator_id": user,
        "kobo_username": sub.get("_submitted_by"),
        "pending_review": user is None,
        "source": "kobo",
        "observed_at": _when(sub, "observed_at"),
        "species": sub.get("species"),
        "head_count": int(sub["head_count"]),
        "direction": sub.get("direction"),
        "notes": sub.get("notes"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }, None


def map_check(sub, area_id, users):
    pt = _point(sub.get("location"))
    if not pt:
        return None, "missing GPS"
    user = users.get(sub.get("_submitted_by"))
    return {
        "client_id": sub["_uuid"],
        "area_id": area_id,
        "enumerator_id": user,
        "kobo_username": sub.get("_submitted_by"),
        "pending_review": user is None,
        "source": "kobo",
        "observed_at": _when(sub, "observed_at"),
        "geom": f"SRID=4326;POINT({pt[0]} {pt[1]})",
        "pasture_condition": int(sub["pasture_condition"]) if sub.get("pasture_condition") else None,
        "water_condition": int(sub["water_condition"]) if sub.get("water_condition") else None,
        "route_condition": sub.get("route_condition"),
        "notes": sub.get("notes"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }, None


def photo_for(sub, store):
    """Copy the submission's photo into Supabase Storage; return its path."""
    att = next((a for a in sub.get("_attachments", []) if a.get("mimetype", "").startswith("image/")), None)
    if not att:
        return None
    r = requests.get(att["download_url"], headers=_headers(), timeout=300)
    r.raise_for_status()
    name = os.path.basename(att.get("filename", "photo.jpg"))
    return store.upload_photo(f"{sub['_uuid']}/{name}", r.content, att.get("mimetype", "image/jpeg"))


def main(store, area_id="south_kordofan"):
    if not os.environ.get("KOBO_TOKEN"):
        print("KOBO_TOKEN not set; nothing to sync")
        return 0
    flow_asset, check_asset = os.environ.get("KOBO_FLOW_ASSET"), os.environ.get("KOBO_CHECK_ASSET")
    users = store.enumerator_accounts()
    points = {p["code"]: p["id"] for p in store.monitoring_points(area_id) if p.get("code")}
    problems = []

    if flow_asset:
        since = store.get_cursor("kobo_flow")
        subs = fetch(flow_asset, since)
        rows = []
        for sub in subs:
            row, why = map_flow(sub, points, users)
            if row:
                rows.append(row)
            else:
                problems.append(f"flow {sub['_uuid']}: {why}")
        store.upsert_rows("flow_counts", rows)
        if subs:
            store.set_cursor("kobo_flow", max(s["_submission_time"] for s in subs))
        print(f"flow counts: {len(rows)} synced, {len(subs) - len(rows)} skipped")

    if check_asset:
        since = store.get_cursor("kobo_check")
        subs = fetch(check_asset, since)
        rows = []
        for sub in subs:
            row, why = map_check(sub, area_id, users)
            if row:
                try:
                    row["photo_path"] = photo_for(sub, store)
                except Exception as e:  # a lost photo should not lose the observation
                    problems.append(f"check {sub['_uuid']}: photo failed: {e}")
                rows.append(row)
            else:
                problems.append(f"check {sub['_uuid']}: {why}")
        store.upsert_rows("field_checks", rows)
        if subs:
            store.set_cursor("kobo_check", max(s["_submission_time"] for s in subs))
        print(f"field checks: {len(rows)} synced, {len(subs) - len(rows)} skipped")

    for p in problems:
        print("WARN", p, file=sys.stderr)
    return 0
