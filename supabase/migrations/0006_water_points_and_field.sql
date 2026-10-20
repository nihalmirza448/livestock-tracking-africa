-- Surface water at water points (Sentinel-2) and enumerator field data via KoboToolbox.

-- Water points: provisional OSM seed, lon/lat view for ingest and the map, public read.
alter table public.water_points add column source text, add column osm_id bigint unique, add column name_ar text;
create view public.water_points_ll with (security_invoker = true) as
  select id, area_id, name, name_ar, kind, source, extensions.st_x(geom) as lon, extensions.st_y(geom) as lat
  from public.water_points;
-- The earlier authenticated-only "read" policy stays; this adds anonymous read for the map.
create policy "public read" on public.water_points for select to anon, authenticated using (true);

create table public.water_point_observations (
  id bigint generated always as identity primary key,
  water_point_id uuid not null references public.water_points (id) on delete cascade,
  source_key text not null references public.data_sources (key),
  obs_date date not null,
  water_fraction real,
  valid_fraction real,
  run_id bigint references public.ingest_runs (id) on delete set null,
  unique (water_point_id, source_key, obs_date)
);
create index wpo_point_date on public.water_point_observations (water_point_id, obs_date desc);
create index wpo_run on public.water_point_observations (run_id);
alter table public.water_point_observations enable row level security;
create policy "public read" on public.water_point_observations for select to anon, authenticated using (true);

alter table public.data_sources drop constraint data_sources_auth_check;
alter table public.data_sources add constraint data_sources_auth_check check (auth in ('earthdata', 'cds', 'cdse', 'kobo', 'none'));
insert into public.data_sources (key, name, variable, provider, product, product_version, spatial_resolution, cadence, period, access_method, auth, url, role, enabled, notes)
values ('s2_water', 'Sentinel-2 surface water (MNDWI)', 'surface water fraction', 'ESA / Copernicus Data Space', 'S2MSI2A', 'L2A',
        '20 m (stored at 60 m / 0.05°)', 'daily', '2017 – present', 'cdse-odata', 'cdse', 'https://dataspace.copernicus.eu/', 'primary', true,
        'Water where MNDWI > 0 on cloud-free pixels (SCL mask). Each tile revisits every 5 days; coverage per date is partial.');

-- Field data from KoboToolbox forms (forms/*.xlsx), synced by ingest/kobo_sync.py.
alter table public.monitoring_points add column code text unique, add column source text;
alter table public.flow_counts alter column enumerator_id drop not null,
  add column kobo_username text, add column pending_review boolean not null default false,
  add column source text not null default 'app';
alter table public.field_checks alter column enumerator_id drop not null,
  add column kobo_username text, add column pending_review boolean not null default false,
  add column source text not null default 'app';

create table public.enumerator_accounts (
  kobo_username text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  created_at timestamptz not null default now()
);
alter table public.enumerator_accounts enable row level security;
create policy "admin manages" on public.enumerator_accounts for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));

create table public.sync_cursors (key text primary key, value text not null, updated_at timestamptz not null default now());
alter table public.sync_cursors enable row level security;

insert into storage.buckets (id, name, public) values ('field-photos', 'field-photos', false);

-- Public, aggregated views (owner rights on purpose: they expose weekly sums and rounded
-- positions only, never enumerators or photos). PRD P0-6: aggregated by default.
create view public.flow_summary as
  select mp.id as monitoring_point_id, mp.name, mp.code,
         extensions.st_x(mp.geom) as lon, extensions.st_y(mp.geom) as lat,
         fc.species, date_trunc('week', fc.observed_at)::date as week,
         sum(fc.head_count)::bigint as head_count, count(*)::int as submissions
  from public.flow_counts fc join public.monitoring_points mp on mp.id = fc.monitoring_point_id
  where not fc.pending_review
  group by 1, 2, 3, 4, 5, 6, 7;
grant select on public.flow_summary to anon, authenticated;

create view public.field_check_summary as
  select area_id, observed_at::date as obs_date,
         round(extensions.st_x(geom)::numeric, 2) as lon, round(extensions.st_y(geom)::numeric, 2) as lat,
         pasture_condition, water_condition, route_condition
  from public.field_checks where not pending_review;
grant select on public.field_check_summary to anon, authenticated;

-- Provisional monitoring points (towns on the main corridors) until NIDAA defines the network.
insert into public.monitoring_points (area_id, code, name, hub, geom, source) values
  ('south_kordofan', 'KAD', 'Kadugli', 'Kadugli', 'SRID=4326;POINT(29.718 11.013)', 'provisional'),
  ('south_kordofan', 'DIL', 'Dilling', 'Dilling', 'SRID=4326;POINT(29.650 12.050)', 'provisional'),
  ('south_kordofan', 'RAS', 'Rashad', 'Rashad', 'SRID=4326;POINT(31.052 11.868)', 'provisional'),
  ('south_kordofan', 'ABJ', 'Abu Jubayha', 'Abu Jubayha', 'SRID=4326;POINT(31.228 11.457)', 'provisional'),
  ('south_kordofan', 'TAL', 'Talodi', 'Talodi', 'SRID=4326;POINT(30.383 10.633)', 'provisional'),
  ('south_kordofan', 'LAG', 'Lagawa', 'Lagawa', 'SRID=4326;POINT(29.133 11.400)', 'provisional'),
  ('south_kordofan', 'ABB', 'Al Abbasiya', 'Rashad', 'SRID=4326;POINT(31.293 12.173)', 'provisional');
