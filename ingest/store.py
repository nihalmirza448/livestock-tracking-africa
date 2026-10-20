"""Thin PostgREST client for writing ingest results to Supabase.

Uses the project's secret key, which bypasses RLS. Only run this from trusted
infrastructure (GitHub Actions secrets), never from the browser.
"""

import os
from datetime import date, datetime, timezone

import requests


class Store:
    def __init__(self):
        self.base = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
        key = os.environ["SUPABASE_SECRET_KEY"]
        self.session = requests.Session()
        self.session.headers.update({"apikey": key, "Content-Type": "application/json"})

    def _req(self, method, path, **kw):
        r = self.session.request(method, f"{self.base}/{path}", timeout=60, **kw)
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

    def stored_dates(self, source_key, area_id, since):
        rows = self._req("GET", "eo_observations", params={
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
