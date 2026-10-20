-- SLEWCIS Phase 1 core schema.
-- Earth observation data is written by the ingest jobs (service role, bypasses RLS).
-- Field, telemetry and governance tables follow the PRD's least-privilege rules.

create extension if not exists postgis with schema extensions;

-- ---------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------

create type public.app_role as enum (
  'admin', 'state_officer', 'hub_coordinator', 'enumerator',
  'researcher', 'partner_analyst', 'telemetry_viewer'
);

create table public.user_roles (
  user_id uuid not null references auth.users (id) on delete cascade,
  role public.app_role not null,
  granted_at timestamptz not null default now(),
  primary key (user_id, role)
);

create function public.has_role(r public.app_role)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.user_roles
    where user_id = (select auth.uid()) and role in (r, 'admin')
  );
$$;

-- ---------------------------------------------------------------------------
-- Reference geography
-- ---------------------------------------------------------------------------

create table public.pilot_areas (
  id text primary key,
  name_en text not null,
  name_ar text not null,
  -- Bounding box used to clip EO products, before buffer.
  min_lon double precision not null,
  min_lat double precision not null,
  max_lon double precision not null,
  max_lat double precision not null,
  buffer_deg double precision not null default 0.25,
  boundary extensions.geometry (multipolygon, 4326),
  boundary_source text,
  active boolean not null default true
);

create table public.monitoring_points (
  id uuid primary key default gen_random_uuid(),
  area_id text not null references public.pilot_areas (id),
  name text not null,
  hub text,
  geom extensions.geometry (point, 4326) not null,
  active boolean not null default true,
  created_at timestamptz not null default now()
);

create table public.water_points (
  id uuid primary key default gen_random_uuid(),
  area_id text not null references public.pilot_areas (id),
  name text,
  kind text not null check (kind in ('borehole', 'hafir', 'well', 'dam', 'river', 'pond', 'other')),
  geom extensions.geometry (point, 4326) not null,
  created_at timestamptz not null default now()
);

create table public.corridors (
  id uuid primary key default gen_random_uuid(),
  area_id text not null references public.pilot_areas (id),
  name text not null,
  status text not null check (status in ('formal', 'historical', 'observed')),
  season text check (season in ('dry', 'wet', 'both')),
  geom extensions.geometry (multilinestring, 4326) not null,
  source text,
  valid_from date,
  valid_to date,
  created_at timestamptz not null default now()
);

create index on public.monitoring_points using gist (geom);
create index on public.water_points using gist (geom);
create index on public.corridors using gist (geom);

-- ---------------------------------------------------------------------------
-- Earth observation registry, runs and observations
-- ---------------------------------------------------------------------------

create table public.data_sources (
  key text primary key,
  name text not null,
  variable text not null,
  provider text not null,
  product text not null,
  product_version text,
  spatial_resolution text,
  cadence text not null check (cadence in ('daily', '8-day', '16-day', 'monthly', 'annual', 'static')),
  period text,
  access_method text not null,
  auth text not null check (auth in ('earthdata', 'cds', 'none')),
  url text not null,
  role text not null default 'primary' check (role in ('primary', 'fallback', 'reference', 'historical')),
  enabled boolean not null default true,
  validation_status text not null default 'unvalidated'
    check (validation_status in ('unvalidated', 'in_review', 'validated', 'rejected')),
  confidence text check (confidence in ('low', 'medium', 'high')),
  notes text
);

create table public.dataset_versions (
  id bigint generated always as identity primary key,
  source_key text not null references public.data_sources (key),
  product_version text not null,
  created_at timestamptz not null default now(),
  unique (source_key, product_version)
);

create table public.ingest_runs (
  id bigint generated always as identity primary key,
  source_key text not null references public.data_sources (key),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  status text not null default 'running' check (status in ('running', 'success', 'partial', 'failed', 'skipped')),
  dates_requested int not null default 0,
  rows_written int not null default 0,
  error text,
  runner text
);

create index on public.ingest_runs (source_key, started_at desc);

create table public.eo_observations (
  id bigint generated always as identity primary key,
  source_key text not null references public.data_sources (key),
  area_id text not null references public.pilot_areas (id),
  dataset_version_id bigint references public.dataset_versions (id),
  run_id bigint references public.ingest_runs (id) on delete set null,
  obs_date date not null,
  period_end date,
  variable text not null,
  stat text not null check (stat in ('mean', 'min', 'max', 'sum', 'fraction', 'valid_fraction')),
  value double precision,
  unit text not null,
  retrieved_at timestamptz not null default now(),
  processing jsonb not null default '{}'::jsonb,
  unique (source_key, area_id, variable, stat, obs_date)
);

create index on public.eo_observations (area_id, variable, obs_date desc);
create index on public.eo_observations (dataset_version_id);
create index on public.eo_observations (run_id);

-- Latest state per source, for the dashboard and pipeline health checks.
create view public.source_status
with (security_invoker = true)
as
select
  s.key,
  s.name,
  s.variable,
  s.role,
  s.enabled,
  s.cadence,
  s.validation_status,
  (select max(o.obs_date) from public.eo_observations o where o.source_key = s.key) as last_obs_date,
  r.status as last_run_status,
  r.finished_at as last_run_at,
  r.error as last_run_error
from public.data_sources s
left join lateral (
  select status, finished_at, error from public.ingest_runs
  where source_key = s.key order by started_at desc limit 1
) r on true;

-- ---------------------------------------------------------------------------
-- Field observations
-- ---------------------------------------------------------------------------

create table public.flow_counts (
  id uuid primary key default gen_random_uuid(),
  monitoring_point_id uuid not null references public.monitoring_points (id),
  enumerator_id uuid not null default auth.uid() references auth.users (id),
  observed_at timestamptz not null,
  species text not null check (species in ('cattle', 'sheep', 'goats', 'camels', 'other')),
  head_count int not null check (head_count between 1 and 100000),
  direction text check (direction in ('north', 'south', 'east', 'west', 'stationary')),
  flagged_outlier boolean not null default false,
  client_id text unique, -- offline submission id, makes sync idempotent
  synced_at timestamptz not null default now(),
  notes text
);

create table public.field_checks (
  id uuid primary key default gen_random_uuid(),
  area_id text not null references public.pilot_areas (id),
  enumerator_id uuid not null default auth.uid() references auth.users (id),
  observed_at timestamptz not null,
  geom extensions.geometry (point, 4326) not null,
  pasture_condition smallint check (pasture_condition between 1 and 5),
  water_condition smallint check (water_condition between 1 and 5),
  route_condition text check (route_condition in ('open', 'restricted', 'blocked')),
  photo_path text,
  client_id text unique,
  synced_at timestamptz not null default now(),
  notes text
);

create index on public.flow_counts (monitoring_point_id, observed_at desc);
create index on public.flow_counts (enumerator_id);
create index on public.field_checks using gist (geom);
create index on public.field_checks (enumerator_id);

-- ---------------------------------------------------------------------------
-- Sentinel telemetry and consent
-- ---------------------------------------------------------------------------

create table public.consent_records (
  id uuid primary key default gen_random_uuid(),
  owner_ref text not null, -- pseudonymous owner reference, not identity
  scope text not null check (scope in ('individual', 'community')),
  witnessed_by text,
  granted_at timestamptz not null default now(),
  withdrawn_at timestamptz
);

create table public.devices (
  id text primary key, -- supplier device id
  supplier text not null,
  consent_id uuid not null references public.consent_records (id),
  species text,
  last_fix_at timestamptz,
  battery_pct smallint,
  fix_success_rate real
);

create table public.telemetry_positions (
  id bigint generated always as identity primary key,
  device_id text not null references public.devices (id),
  fixed_at timestamptz not null,
  geom extensions.geometry (point, 4326) not null,
  received_at timestamptz not null default now(),
  unique (device_id, fixed_at)
);

create index on public.devices (consent_id);
create index on public.telemetry_positions using gist (geom);

-- No consent, no storage.
create function public.require_active_consent()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if not exists (
    select 1 from public.devices d
    join public.consent_records c on c.id = d.consent_id
    where d.id = new.device_id and c.withdrawn_at is null
  ) then
    raise exception 'No active consent for device %', new.device_id;
  end if;
  return new;
end;
$$;

create trigger telemetry_requires_consent
before insert on public.telemetry_positions
for each row execute function public.require_active_consent();

-- ---------------------------------------------------------------------------
-- Science outputs, thresholds and alerts
-- ---------------------------------------------------------------------------

create table public.science_outputs (
  id bigint generated always as identity primary key,
  area_id text not null references public.pilot_areas (id),
  model_name text not null,
  model_version text not null,
  input_dataset_versions bigint[] not null default '{}',
  indicator text not null,
  obs_date date not null,
  value double precision,
  confidence text check (confidence in ('low', 'medium', 'high')),
  uncertainty double precision,
  run_at timestamptz not null default now(),
  published boolean not null default false
);

create index on public.science_outputs (area_id, indicator, obs_date desc);

create table public.alert_thresholds (
  id bigint generated always as identity primary key,
  area_id text not null references public.pilot_areas (id),
  hazard text not null check (hazard in ('pasture_stress', 'water_stress', 'drought', 'heavy_rain')),
  tier text not null check (tier in ('watch', 'warning', 'severe')),
  rule jsonb not null,
  owner text not null, -- e.g. USU, ministry
  approved_at timestamptz,
  unique (area_id, hazard, tier)
);

create table public.alerts (
  id uuid primary key default gen_random_uuid(),
  area_id text not null references public.pilot_areas (id),
  threshold_id bigint references public.alert_thresholds (id),
  hazard text not null,
  tier text not null check (tier in ('watch', 'warning', 'severe')),
  triggering_indicators jsonb not null,
  confidence text check (confidence in ('low', 'medium', 'high')),
  issued_at timestamptz not null default now(),
  status text not null default 'open' check (status in ('open', 'verified', 'dismissed', 'escalated'))
);

create table public.alert_status_log (
  id bigint generated always as identity primary key,
  alert_id uuid not null references public.alerts (id) on delete cascade,
  status text not null check (status in ('verified', 'dismissed', 'escalated')),
  changed_by uuid not null default auth.uid() references auth.users (id),
  changed_at timestamptz not null default now(),
  note text
);

create index on public.alerts (area_id, issued_at desc);
create index on public.alerts (threshold_id);
create index on public.alert_status_log (alert_id);
create index on public.alert_status_log (changed_by);

-- Keep alerts.status in step with its log.
create function public.apply_alert_status()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  update public.alerts set status = new.status where id = new.alert_id;
  return new;
end;
$$;

create trigger alert_status_applied
after insert on public.alert_status_log
for each row execute function public.apply_alert_status();

-- ---------------------------------------------------------------------------
-- Audit
-- ---------------------------------------------------------------------------

create table public.audit_log (
  id bigint generated always as identity primary key,
  actor uuid,
  action text not null,
  target text not null,
  detail jsonb not null default '{}'::jsonb,
  at timestamptz not null default now()
);

-- Raw positions are read through this function so every access is logged.
create function public.read_positions(p_device text, p_from timestamptz, p_to timestamptz)
returns table (fixed_at timestamptz, lon double precision, lat double precision)
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.has_role('telemetry_viewer') then
    raise exception 'Not permitted';
  end if;
  insert into public.audit_log (actor, action, target, detail)
  values ((select auth.uid()), 'read_positions', p_device,
          jsonb_build_object('from', p_from, 'to', p_to));
  return query
    select t.fixed_at, extensions.st_x(t.geom), extensions.st_y(t.geom)
    from public.telemetry_positions t
    where t.device_id = p_device and t.fixed_at between p_from and p_to
    order by t.fixed_at;
end;
$$;

-- ---------------------------------------------------------------------------
-- Phase 2 reservations (no policies: locked until designed with FAO)
-- ---------------------------------------------------------------------------

create table public.animal_health_events (
  id uuid primary key default gen_random_uuid(),
  area_id text references public.pilot_areas (id),
  reported_at timestamptz not null,
  detail jsonb not null default '{}'::jsonb
);

create table public.vaccinations (
  id uuid primary key default gen_random_uuid(),
  area_id text references public.pilot_areas (id),
  administered_on date not null,
  detail jsonb not null default '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

alter table public.user_roles enable row level security;
alter table public.pilot_areas enable row level security;
alter table public.monitoring_points enable row level security;
alter table public.water_points enable row level security;
alter table public.corridors enable row level security;
alter table public.data_sources enable row level security;
alter table public.dataset_versions enable row level security;
alter table public.ingest_runs enable row level security;
alter table public.eo_observations enable row level security;
alter table public.flow_counts enable row level security;
alter table public.field_checks enable row level security;
alter table public.consent_records enable row level security;
alter table public.devices enable row level security;
alter table public.telemetry_positions enable row level security;
alter table public.science_outputs enable row level security;
alter table public.alert_thresholds enable row level security;
alter table public.alerts enable row level security;
alter table public.alert_status_log enable row level security;
alter table public.audit_log enable row level security;
alter table public.animal_health_events enable row level security;
alter table public.vaccinations enable row level security;

-- Public, aggregated products: readable without sign-in.
create policy "public read" on public.pilot_areas for select to anon, authenticated using (true);
create policy "public read" on public.data_sources for select to anon, authenticated using (true);
create policy "public read" on public.dataset_versions for select to anon, authenticated using (true);
create policy "public read" on public.ingest_runs for select to anon, authenticated using (true);
create policy "public read" on public.eo_observations for select to anon, authenticated using (true);
create policy "public read" on public.science_outputs for select to anon, authenticated using (published);

-- Signed-in users.
create policy "own roles" on public.user_roles for select to authenticated
  using (user_id = (select auth.uid()) or (select public.has_role('admin')));
create policy "admin manages roles" on public.user_roles for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));

create policy "read" on public.monitoring_points for select to authenticated using (true);
create policy "read" on public.water_points for select to authenticated using (true);
create policy "read" on public.corridors for select to authenticated using (true);
create policy "admin writes" on public.monitoring_points for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));
create policy "admin writes" on public.water_points for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));
create policy "admin writes" on public.corridors for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));

create policy "field staff submit" on public.flow_counts for insert to authenticated
  with check (enumerator_id = (select auth.uid())
    and ((select public.has_role('enumerator')) or (select public.has_role('hub_coordinator'))));
create policy "read" on public.flow_counts for select to authenticated
  using (enumerator_id = (select auth.uid())
    or (select public.has_role('hub_coordinator'))
    or (select public.has_role('state_officer'))
    or (select public.has_role('researcher')));
create policy "field staff submit" on public.field_checks for insert to authenticated
  with check (enumerator_id = (select auth.uid())
    and ((select public.has_role('enumerator')) or (select public.has_role('hub_coordinator'))));
create policy "read" on public.field_checks for select to authenticated
  using (enumerator_id = (select auth.uid())
    or (select public.has_role('hub_coordinator'))
    or (select public.has_role('state_officer'))
    or (select public.has_role('researcher')));

create policy "telemetry roles" on public.consent_records for select to authenticated
  using ((select public.has_role('telemetry_viewer')));
create policy "admin manages" on public.consent_records for all to authenticated
  using ((select public.has_role('admin'))) with check ((select public.has_role('admin')));
create policy "telemetry roles" on public.devices for select to authenticated
  using ((select public.has_role('telemetry_viewer')));
-- telemetry_positions: no select policy; read through read_positions() only.

create policy "read" on public.alert_thresholds for select to authenticated using (true);
create policy "read" on public.alerts for select to authenticated using (true);
create policy "read" on public.alert_status_log for select to authenticated using (true);
create policy "custodians log" on public.alert_status_log for insert to authenticated
  with check (changed_by = (select auth.uid())
    and ((select public.has_role('hub_coordinator')) or (select public.has_role('state_officer'))));

create policy "admin reads" on public.audit_log for select to authenticated
  using ((select public.has_role('admin')));

revoke execute on function public.require_active_consent() from public, anon, authenticated;
revoke execute on function public.apply_alert_status() from public, anon, authenticated;
revoke execute on function public.read_positions(text, timestamptz, timestamptz) from public, anon;
