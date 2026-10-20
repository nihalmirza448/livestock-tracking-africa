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

from .adapters import ADAPTERS
from .store import Store


def run_source(store, key, area, since_override, runner):
    source = store.source(key)
    adapter, lookback, needs_earthdata = ADAPTERS[key]
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
        if needs_earthdata:
            import earthaccess

            earthaccess.login(strategy="environment")
        version_id = store.dataset_version(key, source["product_version"])
        skip = store.stored_dates(key, area["id"], since)
        with tempfile.TemporaryDirectory() as workdir:
            stream = adapter(source, area, since, until, skip, workdir)
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
                for r in rows:
                    r.update(source_key=key, area_id=area["id"], dataset_version_id=version_id, run_id=run_id)
                written += store.write_observations(rows)
                print(f"[{key}] {d}: {len(rows)} rows")
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
    unknown = set(keys) - set(ADAPTERS)
    if unknown:
        sys.exit(f"Unknown sources: {', '.join(sorted(unknown))}")

    store = Store()
    area = store.area(args.area)
    runner = os.environ.get("GITHUB_RUN_ID", "local")
    ok = [run_source(store, k, area, args.since, runner) for k in keys]
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
