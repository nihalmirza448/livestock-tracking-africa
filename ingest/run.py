"""Run ingest for one or more sources.

    python -m ingest.run                      # every enabled source
    python -m ingest.run --sources gpm_imerg  # one source
    python -m ingest.run --since 2026-01-01   # backfill from a date

Exits non-zero if any source failed, so the scheduler reports it.
"""

import argparse
import os
import sys
import tempfile
import traceback
from datetime import date, timedelta

from .adapters import ADAPTERS, GRID_SOURCES
from .store import Store


def run_source(store, key, area, since_override, runner):
    source = store.source(key)
    adapter, lookback, _ = ADAPTERS[key]
    run_id = store.start_run(key, runner)
    until = date.today()
    since = since_override or (until - timedelta(days=lookback) if lookback else date(1990, 1, 1))
    requested = written = failures = 0
    last_error = None
    try:
        if not source["enabled"]:
            store.finish_run(run_id, "skipped", 0, 0, "Source disabled in data_sources")
            return True
        if source["auth"] == "cds" and not os.environ.get("CDS_API_KEY"):
            store.finish_run(run_id, "skipped", 0, 0, "CDS_API_KEY not configured")
            return True
        if source["auth"] == "cdse" and not (os.environ.get("CDSE_USERNAME") and os.environ.get("CDSE_PASSWORD")):
            store.finish_run(run_id, "skipped", 0, 0, "CDSE_USERNAME / CDSE_PASSWORD not configured")
            return True
        version_id = store.dataset_version(key, source["product_version"])
        # Sources that produce map grids are complete only when the grid exists.
        skip = store.stored_dates(key, area["id"], since,
                                  table="eo_grids" if key in GRID_SOURCES else "eo_observations")
        extra = {"water_points": store.water_points(area["id"])} if key == "s2_water" else {}
        with tempfile.TemporaryDirectory() as workdir:
            stream = adapter(source, area, since, until, skip, workdir, **extra)
            while True:
                try:
                    d, rows = next(stream)
                except StopIteration:
                    break
                except Exception as e:
                    # The adapter stops at its first error. Rows already written
                    # are kept, and missing dates are retried on the next run.
                    failures += 1
                    last_error = f"{type(e).__name__}: {e}"
                    print(f"[{key}] {traceback.format_exc()}", file=sys.stderr)
                    break
                requested += 1
                obs, grids, wps = [], [], []
                for r in rows:
                    if r.pop("_grid", False):
                        grids.append(r)
                    elif r.pop("_wp", False):
                        wps.append(r)
                        r.update(source_key=key, run_id=run_id)
                        continue
                    else:
                        obs.append(r)
                    r.update(source_key=key, area_id=area["id"], dataset_version_id=version_id, run_id=run_id)
                written += store.write_observations(obs) + store.write_grids(grids) + store.write_water_obs(wps)
                print(f"[{key}] {d}: {len(obs)} rows, {len(grids)} grids, {len(wps)} water points")
        if failures:
            status = "partial" if written else "failed"
        else:
            status = "success" if requested else "skipped"
        store.finish_run(run_id, status, requested, written, last_error)
        return failures == 0
    except Exception as e:
        traceback.print_exc()
        store.finish_run(run_id, "failed", requested, written, f"{type(e).__name__}: {e}")
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", help="comma-separated source keys (default: all)")
    p.add_argument("--area", default="south_kordofan")
    p.add_argument("--since", type=date.fromisoformat)
    args = p.parse_args()

    keys = args.sources.split(",") if args.sources else list(ADAPTERS)
    if keys == ["boundary"]:
        from .boundary import main as boundary_main

        sys.exit(boundary_main(Store(), args.area))
    if keys == ["kobo_sync"]:
        from .kobo_sync import main as kobo_main

        sys.exit(kobo_main(Store(), args.area))
    if keys == ["water_points"]:
        from .water_points import main as wp_main

        sys.exit(wp_main(Store(), args.area))
    unknown = set(keys) - set(ADAPTERS)
    if unknown:
        sys.exit(f"Unknown sources: {', '.join(sorted(unknown))}")

    required = ["SUPABASE_URL", "SUPABASE_SECRET_KEY"]
    if any(ADAPTERS[k][2] for k in keys):
        required += ["EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing settings: {', '.join(missing)}. Add them as GitHub Actions repository secrets.")

    store = Store()
    area = store.area(args.area)
    runner = os.environ.get("GITHUB_RUN_ID", "local")
    ok = [run_source(store, k, area, args.since, runner) for k in keys]
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
