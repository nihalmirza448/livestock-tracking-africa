"""Thin PostgREST client for writing ingest results to Supabase.

Uses the project's secret key, which bypasses RLS. Only run this from trusted
infrastructure (GitHub Actions secrets), never from the browser.
"""

import os
import time
from datetime import date, datetime, timezone

import requests


class Store:
    def __init__(self):
        self.base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
        key = os.environ["SUPABASE_SECRET_KEY"]
        self.session = requests.Session()
        self.session.headers.update({"apikey": key, "Content-Type": "application/json"})

    def _req(self, method, path, **kw):
        # Writes are idempotent upserts, so retrying a timed-out request is safe.
        for attempt in range(4):
            try:
                r = self.session.request(method, f"{self.base}/{path}", timeout=120, **kw)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise
                time.sleep(5 * 2**attempt)
                continue
            if r.status_code >= 500 and attempt < 3:
                time.sleep(5 * 2**attempt)
                continue
            if not r.ok:
                raise RuntimeError(f"{method} {path} -> {r.status_code}: {r.text[:500]}")
            return r.json() if r.content else None

    def area(self, area_id):
        rows = self._req("GET", "pilot_areas", params={"id": f"eq.{area_id}", "select": "*"})
        if not rows:
            raise RuntimeError(f"Unknown pilot area {area_id}")
        return rows[0]

    def source(self, key):
        rows = self._req("GET", "data_sources", params={"key": f"eq.{key}", "select": "*"})
        if not rows:
            raise RuntimeError(f"Unknown data source {key}")
        return rows[0]

    def dataset_version(self, source_key, product_version):
        rows = self._req(
            "POST", "dataset_versions",
            params={"on_conflict": "source_key,product_version"},
            headers={"Prefer": "return=representation,resolution=merge-duplicates"},
            json={"source_key": source_key, "product_version": product_version},
        )
        return rows[0]["id"]

    def stored_dates(self, source_key, area_id, since, table="eo_observations"):
        rows = self._req("GET", table, params={
            "select": "obs_date",
            "source_key": f"eq.{source_key}",
            "area_id": f"eq.{area_id}",
            "obs_date": f"gte.{since.isoformat()}",
        })
        return {date.fromisoformat(r["obs_date"]) for r in rows}

    def start_run(self, source_key, runner):
        rows = self._req(
            "POST", "ingest_runs",
            headers={"Prefer": "return=representation"},
            json={"source_key": source_key, "runner": runner},
        )
        return rows[0]["id"]

    def finish_run(self, run_id, status, dates_requested, rows_written, error=None):
        self._req("PATCH", "ingest_runs", params={"id": f"eq.{run_id}"}, json={
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "dates_requested": dates_requested,
            "rows_written": rows_written,
            "error": error[:2000] if error else None,
        })

    def write_grids(self, rows):
        if not rows:
            return 0
        self._req(
            "POST", "eo_grids",
            params={"on_conflict": "source_key,area_id,variable,obs_date"},
            headers={"Prefer": "resolution=merge-duplicates"},
            json=rows,
        )
        return len(rows)

    def water_points(self, area_id):
        return self._req("GET", "water_points_ll", params={"area_id": f"eq.{area_id}", "select": "id,lon,lat,kind,name"})

    def upsert_water_points(self, rows):
        self._req("POST", "water_points", params={"on_conflict": "osm_id"},
                  headers={"Prefer": "resolution=merge-duplicates"}, json=rows)

    def write_water_obs(self, rows):
        if not rows:
            return 0
        self._req("POST", "water_point_observations",
                  params={"on_conflict": "water_point_id,source_key,obs_date"},
                  headers={"Prefer": "resolution=merge-duplicates"}, json=rows)
        return len(rows)

    def monitoring_points(self, area_id):
        return self._req("GET", "monitoring_points", params={"area_id": f"eq.{area_id}", "select": "id,code,name"})

    def enumerator_accounts(self):
        rows = self._req("GET", "enumerator_accounts", params={"select": "kobo_username,user_id"})
        return {r["kobo_username"]: r["user_id"] for r in rows}

    def get_cursor(self, key):
        rows = self._req("GET", "sync_cursors", params={"key": f"eq.{key}", "select": "value"})
        return rows[0]["value"] if rows else None

    def set_cursor(self, key, value):
        self._req("POST", "sync_cursors", params={"on_conflict": "key"},
                  headers={"Prefer": "resolution=merge-duplicates"}, json={"key": key, "value": value})

    def upsert_rows(self, table, rows):
        if rows:
            self._req("POST", table, params={"on_conflict": "client_id"},
                      headers={"Prefer": "resolution=merge-duplicates"}, json=rows)
        return len(rows)

    def upload_photo(self, path, content, mimetype):
        """Store a field photo in the private field-photos bucket; returns the object path."""
        url = os.environ["SUPABASE_URL"].rstrip("/") + f"/storage/v1/object/field-photos/{path}"
        key = os.environ["SUPABASE_SECRET_KEY"]
        r = requests.post(url, data=content, timeout=300,
                          headers={"apikey": key, "Authorization": f"Bearer {key}",
                                   "Content-Type": mimetype, "x-upsert": "true"})
        if not r.ok:
            raise RuntimeError(f"photo upload -> {r.status_code}: {r.text[:300]}")
        return f"field-photos/{path}"

    def update_area(self, area_id, fields):
        self._req("PATCH", "pilot_areas", params={"id": f"eq.{area_id}"}, json=fields)

    def write_observations(self, rows):
        if not rows:
            return 0
        self._req(
            "POST", "eo_observations",
            params={"on_conflict": "source_key,area_id,variable,stat,obs_date"},
            headers={"Prefer": "resolution=merge-duplicates"},
            json=rows,
        )
        return len(rows)
