-- Gridded values for the map: one raster per (source, variable, date), stored as a
-- row-major array with rows running north to south. Coarse products keep their
-- native cells; fine or non-lat/lon products are averaged onto a 0.05° grid.

create table public.eo_grids (
  id bigint generated always as identity primary key,
  source_key text not null references public.data_sources (key),
  area_id text not null references public.pilot_areas (id),
  dataset_version_id bigint references public.dataset_versions (id),
  run_id bigint references public.ingest_runs (id) on delete set null,
  obs_date date not null,
  period_end date,
  variable text not null,
  unit text not null,
  nx int not null,
  ny int not null,
  west double precision not null,
  south double precision not null,
  dx double precision not null,
  dy double precision not null,
  values real[] not null,
  retrieved_at timestamptz not null default now(),
  unique (source_key, area_id, variable, obs_date)
);

create index on public.eo_grids (area_id, variable, obs_date desc);
create index on public.eo_grids (dataset_version_id);
create index on public.eo_grids (run_id);

alter table public.eo_grids enable row level security;
create policy "public read" on public.eo_grids for select to anon, authenticated using (true);

-- Official admin boundary as GeoJSON for the map (PostGIS geometry stays for analysis).
alter table public.pilot_areas add column boundary_geojson jsonb;
