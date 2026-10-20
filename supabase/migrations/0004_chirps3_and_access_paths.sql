-- CHIRPS v2.0 is discontinued (CHC: "As of 2025.01 there is a new version, CHIRPS-v3");
-- 2026 v2 files are patchy and stop. Add v3 as the rainfall fallback and keep v2 as history.
-- Also record that NASA daily products are now fetched from the archives directly
-- (GES DISC listings, LAADS, LP DAAC cloud) because CMR search has been failing.

insert into public.data_sources
  (key, name, variable, provider, product, product_version, spatial_resolution, cadence, period,
   access_method, auth, url, role, enabled, notes)
values
  ('chirps3', 'CHIRPS v3.0 daily (sat)', 'precipitation', 'UCSB Climate Hazards Center',
   'CHIRPS-3.0 daily sat p05', '3.0', '0.05°', 'daily', '1998 – present', 'chc-https', 'none',
   'https://www.chc.ucsb.edu/data/chirps3', 'fallback', true,
   'Daily values disaggregated from CHIRPS3 pentads with IMERG Late. final/ preferred, prelim/ for recent days.');

update public.data_sources set
  role = 'historical', enabled = false,
  notes = 'Discontinued by CHC in favour of CHIRPS v3; 2026 files are incomplete. Kept for old-year backfills.'
where key = 'chirps';

update public.data_sources set access_method = 'gesdisc-https', notes = coalesce(notes, '') ||
  ' Fetched from GES DISC directory listings (file suffix currently V07C).'
where key = 'gpm_imerg';
update public.data_sources set access_method = 'gesdisc-https' where key = 'gldas_clsm';
update public.data_sources set access_method = 'laads-https' where key in ('modis_ndvi', 'modis_et');
update public.data_sources set access_method = 'lpdaac-cloud-https' where key = 'aster_dem';
update public.data_sources set access_method = 'earthaccess (CMR)' where key = 'grace_mascon';
