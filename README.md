# SLEWCIS Phase 1 prototype

Sudan Livestock Early Warning, Climate Intelligence, Movement, Health and Extension System.
This prototype covers the PRD's data foundation: Earth observation ingest (P0-1), the
spatio-temporal store (P0-2) and a first conditions dashboard (P0-6). It also includes the
schema for field app data, telemetry with consent (P0-4), science outputs (P0-5), alerts
(P0-7) and governance (P0-8).

| Part | Where | Runs on |
| --- | --- | --- |
| Dashboard (Arabic first, English toggle) | `src/` | Vercel |
| Database schema and seed registry | `supabase/migrations/` | Supabase (Postgres + PostGIS) |
| EO ingest jobs | `ingest/` | GitHub Actions, daily at 02:00 UTC |

## Data sources

The registry lives in the `data_sources` table, and `/[lang]/sources` shows each source's
latest data and last run.

| Key | Product | Variables stored | Fetched from | Auth |
| --- | --- | --- | --- | --- |
| `gpm_imerg` | GPM IMERG Late daily (GPM_3IMERGDL v07) | precipitation | GES DISC directory listing | Earthdata |
| `chirps3` | CHIRPS v3.0 daily, `sat` disaggregation (fallback rainfall) | precipitation | CHC directory listing (final, then prelim) | none |
| `gldas_clsm` | GLDAS-2.2 CLSM daily (GLDAS_CLSM025_DA1_D) | surface and root-zone soil moisture, groundwater, total water storage, land surface temperature | GES DISC directory listing | Earthdata |
| `grace_mascon` | GRACE/GRACE-FO JPL mascon RL06.3 | water storage anomaly | CMR search + earthaccess | Earthdata |
| `modis_ndvi` | MOD13C1 v061 (0.05°, 16-day) | NDVI | LAADS archive listing | Earthdata |
| `modis_et` | MOD16A2 v061 (500 m, 8-day) | evapotranspiration | LAADS archive listing | Earthdata |
| `aster_dem` | ASTGTM v003 | elevation | LP DAAC cloud, deterministic tile URLs | Earthdata |
| `cci_landcover` | C3S/ESA CCI land cover v2.1.1 | land cover class fractions | Copernicus CDS API | CDS API key |
| `hwsd` | HWSD v2.0 raster | soil mapping unit fractions | FAO S3 | none |
| `s2_water` | Sentinel-2 L2A, MNDWI water mask (20 m → 60 m blocks) | surface water fraction per 0.05° cell and per water point (500 m) | Copernicus Data Space OData | CDSE login |
| `chirps` | CHIRPS v2.0 daily (discontinued Jan 2025; disabled) | precipitation | CHC | none |
| `cfsr` | CFSR (ended 2017; disabled) | — | — | — |

NASA's CMR search service has been returning server errors, so every daily NASA product is
located through the archive's own listing instead (`ingest/direct.py`). Only GRACE still
needs CMR. `python ingest/diagnose.py` (or the *Diagnose data servers* workflow) prints what
each server currently serves.

Every stored value is an area statistic (cos-latitude weighted mean, min, max, valid
fraction) for the pilot area plus its buffer. Each value records its dataset version, its
ingest run and the processing steps in `processing`.

Where the concept note's datasets are out of date, the replacements are: CFSR → still open
(GLDAS CLSM-DA carries no air temperature; land surface temperature is stored meanwhile), MODIS ET 2000–2010 → MOD16A2 v061, CCI 1992–2015 → C3S v2.1.1 (to 2022), and
HWSD v1.2 → v2.0. The HDX, GitHub, Jupyter, CUAHSI/HydroShare and Box links in the concept
note are places to publish results, not data sources, so they aren't ingested.

## Setup

1. **Earthdata.** Create a login at https://urs.earthdata.nasa.gov. Under *Applications →
   Authorized Apps*, approve **NASA GESDISC DATA ARCHIVE** (needed for GPM and GLDAS).
2. **GitHub secrets** (repo → Settings → Secrets and variables → Actions):
   - `SUPABASE_URL`: `https://nrfhearjgjdsunzjkzyr.supabase.co`
   - `SUPABASE_SECRET_KEY`: a secret key (`sb_secret_…`) from Supabase → Project Settings → API Keys
   - `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD`
   - `CDS_API_KEY` (optional, for land cover): from https://cds.climate.copernicus.eu after
     accepting the satellite-land-cover licence
   - `CDSE_USERNAME`, `CDSE_PASSWORD` (surface water): a free account at https://dataspace.copernicus.eu
   - `KOBO_URL`, `KOBO_TOKEN`, `KOBO_FLOW_ASSET`, `KOBO_CHECK_ASSET` (field forms): see below
3. **First run.** Actions → *EO ingest* → *Run workflow*. Leave *sources* blank for the daily
   set, or enter e.g. `aster_dem,hwsd,grace_mascon`. To backfill, set *since*, e.g. `2025-01-01`.

## Field data (enumerators)

Herd counts and site checks are collected with ODK Collect against two KoboToolbox forms in
`forms/` (`python forms/build_forms.py` regenerates them from the CSV sources; Arabic default,
English second; constraints mirror the database checks). To go live:

1. Create a free account at https://kf.kobotoolbox.org (or the humanitarian server), upload
   `forms/flow_count.xlsx` and `forms/field_check.xlsx`, deploy both.
2. Account → Security → create an API token. Add secrets `KOBO_TOKEN`, `KOBO_URL`
   (`https://kf.kobotoolbox.org`), `KOBO_FLOW_ASSET` and `KOBO_CHECK_ASSET` (the asset ids in
   each form's URL).
3. Enumerators install ODK Collect, connect it to the Kobo server with their account, and
   download the forms once; they then work fully offline and sync when in coverage.
4. `kobo_sync` runs hourly, upserting by submission UUID into `flow_counts` / `field_checks`
   and copying photos to the private `field-photos` bucket. Map each enumerator's Kobo username
   to a platform user in `enumerator_accounts`; unmapped submissions are kept flagged
   `pending_review`. The dashboard's *Field* page shows weekly aggregates only.

Water points start as a provisional OpenStreetMap seed (`python -m ingest.run --sources
water_points`); replace with the NIDAA/ministry list when available.

## Local development

```bash
cp .env.example .env.local   # fill in SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY
npm install && npm run dev   # http://localhost:3000 -> /ar

python -m venv .venv && .venv/bin/pip install -r ingest/requirements.txt
.venv/bin/python -m ingest.test_adapters                  # offline tests, no credentials
SUPABASE_URL=… SUPABASE_SECRET_KEY=… EARTHDATA_USERNAME=… EARTHDATA_PASSWORD=… \
  .venv/bin/python -m ingest.run --sources gpm_imerg
```

## Adding a source

Add an adapter in `ingest/adapters.py` that yields `(date, rows)` for dates not in `skip`.
Register it in `ADAPTERS`, insert a `data_sources` row, and add its key to the workflow
matrix. The core schema doesn't change.
