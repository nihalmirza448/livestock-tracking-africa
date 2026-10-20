-- Core livestock tracking schema. Every row is owned by the user who created it.

create table public.herds (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  name text not null,
  location text,
  created_at timestamptz not null default now()
);

create table public.animals (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  herd_id uuid references public.herds (id) on delete set null,
  tag_number text not null,
  species text not null,
  breed text,
  sex text check (sex in ('male', 'female')),
  birth_date date,
  status text not null default 'active' check (status in ('active', 'sold', 'deceased')),
  created_at timestamptz not null default now(),
  unique (owner_id, tag_number)
);

create table public.health_records (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  animal_id uuid not null references public.animals (id) on delete cascade,
  recorded_on date not null default current_date,
  kind text not null, -- e.g. vaccination, treatment, checkup
  notes text,
  created_at timestamptz not null default now()
);

create table public.weight_records (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid() references auth.users (id) on delete cascade,
  animal_id uuid not null references public.animals (id) on delete cascade,
  recorded_on date not null default current_date,
  weight_kg numeric(7, 2) not null check (weight_kg > 0),
  created_at timestamptz not null default now()
);

create index on public.herds (owner_id);
create index on public.animals (owner_id);
create index on public.animals (herd_id);
create index on public.health_records (animal_id);
create index on public.weight_records (animal_id);

-- Row Level Security: users only see and modify their own rows.
do $$
declare t text;
begin
  foreach t in array array['herds', 'animals', 'health_records', 'weight_records'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy "owner access" on public.%I for all to authenticated
         using ((select auth.uid()) = owner_id)
         with check ((select auth.uid()) = owner_id)', t);
  end loop;
end $$;
