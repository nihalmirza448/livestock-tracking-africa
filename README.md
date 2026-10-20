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

| Key | Product | Variables stored | Auth |
| --- | --- | --- | --- |
| `gpm_imerg` | GPM IMERG Late daily (GPM_3IMERGDL v07) | precipitation | Earthdata |
| `chirps` | CHIRPS v2.0 daily COGs (fallback rainfall) | precipitation | none |
| `gldas_clsm` | GLDAS-2.2 CLSM daily (GLDAS_CLSM025_DA1_D) | surface and root-zone soil moisture, groundwater, air temperature | Earthdata |
| `grace_mascon` | GRACE/GRACE-FO JPL mascon RL06.3 | water storage anomaly | Earthdata |
| `modis_ndvi` | MOD13C1 v061 (0.05°, 16-day) | NDVI | Earthdata |
| `modis_et` | MOD16A2 v061 (500 m, 8-day) | evapotranspiration | Earthdata |
| `aster_dem` | ASTGTM v003 | elevation | Earthdata |
| `cci_landcover` | C3S/ESA CCI land cover v2.1.1 | land cover class fractions | CDS API key |
| `hwsd` | HWSD v2.0 raster | soil mapping unit fractions | none |
| `cfsr` | CFSR (ended 2017) | registered only, disabled | — |

Every stored value is an area statistic (cos-latitude weighted mean, min, max, valid
fraction) for the pilot area plus its buffer. Each value records its dataset version, its
ingest run and the processing steps in `processing`.

Where the concept note's datasets are out of date, the replacements are: CFSR → GLDAS air
temperature, MODIS ET 2000–2010 → MOD16A2 v061, CCI 1992–2015 → C3S v2.1.1 (to 2022), and
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
3. **First run.** Actions → *EO ingest* → *Run workflow*. Leave *sources* blank for the daily
   set, or enter e.g. `aster_dem,hwsd,grace_mascon`. To backfill, set *since*, e.g. `2025-01-01`.

## Local development

```bash
cp .env.example .env.local   # fill in the two NEXT_PUBLIC_ values
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
