-- Pilot area and the data source registry from the concept note (Table 1) and PRD P0-1.

insert into public.pilot_areas (id, name_en, name_ar, min_lon, min_lat, max_lon, max_lat, buffer_deg, boundary_source)
values ('south_kordofan', 'South Kordofan', 'جنوب كردفان', 29.0, 9.3, 32.4, 12.7, 0.25,
        'Approximate bounding box. Replace with the OCHA COD-AB admin1 boundary from HDX.');

insert into public.data_sources
  (key, name, variable, provider, product, product_version, spatial_resolution, cadence, period,
   access_method, auth, url, role, enabled, notes)
values
  ('gpm_imerg', 'GPM IMERG Late daily', 'precipitation', 'NASA GES DISC', 'GPM_3IMERGDL', '07',
   '0.1°', 'daily', '2000 – present', 'earthaccess', 'earthdata',
   'https://gpm.nasa.gov/data/directory', 'primary', true,
   'Late run (~14 h latency). Final run replaces it after ~3.5 months.'),
  ('chirps', 'CHIRPS v2.0 daily', 'precipitation', 'UCSB Climate Hazards Center', 'CHIRPS-2.0 global_daily p05', '2.0',
   '0.05°', 'daily', '1981 – present', 'http-cog', 'none',
   'https://data.chc.ucsb.edu/products/CHIRPS-2.0/', 'fallback', true,
   'Rainfall fallback named in the PRD. Not in the concept note table.'),
  ('gldas_clsm', 'GLDAS-2.2 CLSM daily (GRACE-DA)', 'soil moisture, groundwater, air temperature', 'NASA GES DISC',
   'GLDAS_CLSM025_DA1_D', '2.2', '0.25°', 'daily', '2003 – present', 'earthaccess', 'earthdata',
   'https://ldas.gsfc.nasa.gov/gldas/GLDASoutput.php', 'primary', true,
   'Also supplies air temperature as the current replacement for CFSR.'),
  ('grace_mascon', 'GRACE/GRACE-FO JPL mascon', 'terrestrial water storage', 'NASA PO.DAAC',
   'TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4', 'RL06.3v04', '0.5° (3° mascons)', 'monthly', '2002 – present',
   'earthaccess', 'earthdata', 'https://grace.jpl.nasa.gov/data/get-data/', 'primary', true, null),
  ('modis_ndvi', 'MODIS Terra vegetation indices', 'NDVI', 'NASA LP DAAC', 'MOD13C1', '061',
   '0.05°', '16-day', '2000 – present', 'earthaccess', 'earthdata',
   'https://modis.gsfc.nasa.gov/data/dataprod/mod13.php', 'primary', true, null),
  ('modis_et', 'MODIS Terra evapotranspiration', 'evapotranspiration', 'NASA LP DAAC', 'MOD16A2', '061',
   '500 m', '8-day', '2000 – present', 'earthaccess', 'earthdata',
   'https://modis.gsfc.nasa.gov/data/dataprod/mod16.php', 'primary', true,
   'Collection 6.1 replaces the 2000–2010 period listed in the concept note.'),
  ('aster_dem', 'ASTER Global DEM v3', 'elevation', 'NASA LP DAAC', 'ASTGTM', '003',
   '30 m', 'static', '2000 – 2013', 'earthaccess', 'earthdata',
   'https://lpdaac.usgs.gov/products/astgtmv003/', 'reference', true, null),
  ('cci_landcover', 'ESA CCI / C3S land cover', 'land cover', 'Copernicus Climate Data Store',
   'satellite-land-cover', 'v2.1.1', '300 m', 'annual', '1992 – 2022', 'cdsapi', 'cds',
   'http://maps.elie.ucl.ac.be/CCI/viewer/', 'reference', true,
   'C3S v2.1.1 extends the 1992–2015 CCI V2 series in the concept note. Needs a CDS API key.'),
  ('hwsd', 'Harmonized World Soil Database', 'soil mapping units', 'FAO / IIASA', 'HWSD', '2.0',
   '1 km', 'static', 'n/a', 'http-zip', 'none',
   'http://www.fao.org/soils-portal/soil-survey/soil-maps-and-databases/harmonized-world-soil-database-v12/en/',
   'reference', true, 'v2.0 raster replaces the v1.2 named in the concept note.'),
  ('cfsr', 'Climate Forecast System Reanalysis', 'air temperature', 'NCAR / NOAA', 'CFSR', 'v1',
   '0.5°', 'daily', '1979 – 2017', 'manual', 'none',
   'https://climatedataguide.ucar.edu/climate-data/climate-forecast-system-reanalysis-cfsr', 'historical', false,
   'Stopped in 2017. Current temperature comes from GLDAS; CFSR is for historical SWAT calibration only.');
