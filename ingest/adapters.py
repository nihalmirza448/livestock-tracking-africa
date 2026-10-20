"""One adapter per data source.

Each adapter yields (obs_date, rows) pairs for dates not already stored. Rows
are area statistics; the runner adds source, area, version and run ids.
Adding a source means adding an adapter here and a row in data_sources.

NASA daily products are found through the archives' own listings (see direct.py)
because the CMR search service has been unreliable. GRACE still uses CMR.
"""

import glob
import os
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from . import direct
from .geo import bounds, grid_stats, masked_stats, rows_from_stats, sinusoidal_latlon


def _provenance(source, url=None, steps=(), **extra):
    p = {"product": source["product"], "version": source["product_version"], "steps": list(steps)}
    if url:
        p["url"] = url
    return p | extra


def _remove(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def _window_stats(path_or_url, box, **kw):
    """Area statistics for one band of a GeoTIFF/COG restricted to box."""
    import rasterio
    from rasterio.windows import from_bounds

    west, south, east, north = box
    with rasterio.open(path_or_url) as src:
        b = src.bounds
        win = from_bounds(max(west, b.left), max(south, b.bottom), min(east, b.right), min(north, b.top),
                          src.transform).round_offsets().round_lengths()
        data = src.read(1, window=win)
        rows_idx = np.arange(win.row_off, win.row_off + win.height) + 0.5
        lats = np.broadcast_to((src.transform.f + rows_idx * src.transform.e)[:, None], data.shape)
        return masked_stats(data, lats, fill=src.nodata, **kw), data, lats, src.nodata


# ---------------------------------------------------------------------------
# GPM IMERG Late daily precipitation (GES DISC)
# ---------------------------------------------------------------------------

def gpm_imerg(source, area, since, until, skip, workdir):
    import xarray as xr

    for d, url in direct.gesdisc_files("GPM_3IMERGDL", since, until):
        if d in skip:
            continue
        path = direct.download(url, os.path.join(workdir, os.path.basename(url)))
        try:
            with xr.open_dataset(path) as ds:
                da = ds["precipitation"].isel(time=0).transpose("lat", "lon")
                stats = grid_stats(da.values, da["lat"].values, da["lon"].values, area)
        finally:
            _remove([path])
        stats.pop("min")
        yield d, rows_from_stats(stats, d, "precipitation", "mm/day",
                                 _provenance(source, url, ["clip bbox+buffer", "cos-lat weighted mean"]))


# ---------------------------------------------------------------------------
# CHIRPS v3 daily precipitation (public COG/GeoTIFF; final preferred, prelim recent)
# ---------------------------------------------------------------------------

def chirps3(source, area, since, until, skip, workdir):
    files = direct.chirps3_files(since, until)
    if not files:
        raise RuntimeError(f"No CHIRPS v3 daily files found for {since}..{until} under {direct.CHIRPS3}")
    for d in sorted(files):
        if d in skip:
            continue
        url, kind = files[d]
        stats, *_ = _window_stats("/vsicurl/" + url, bounds(area))
        stats.pop("min")
        yield d, rows_from_stats(stats, d, "precipitation", "mm/day",
                                 _provenance(source, url, ["window read bbox+buffer", "cos-lat weighted mean"],
                                             release=kind))


# Legacy CHIRPS v2.0 (discontinued in favour of v3; kept for backfills of old years)
CHIRPS_URL = "/vsicurl/https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/cogs/p05/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.cog"


def chirps(source, area, since, until, skip, workdir):
    from rasterio.errors import RasterioIOError

    found = 0
    d = since
    while d <= until:
        if d not in skip:
            url = CHIRPS_URL.format(y=d.year, m=d.month, d=d.day)
            try:
                stats, *_ = _window_stats(url, bounds(area))
            except RasterioIOError:
                d += timedelta(days=1)
                continue
            found += 1
            stats.pop("min")
            yield d, rows_from_stats(stats, d, "precipitation", "mm/day",
                                     _provenance(source, url.removeprefix("/vsicurl/"),
                                                 ["window read bbox+buffer", "cos-lat weighted mean"]))
        d += timedelta(days=1)
    if not found and since < until - timedelta(days=7):
        raise RuntimeError(f"No CHIRPS v2 files for {since}..{until}; v2 is discontinued, use chirps3")


# ---------------------------------------------------------------------------
# GLDAS-2.2 CLSM daily: soil moisture, groundwater, air temperature (GES DISC)
# ---------------------------------------------------------------------------

GLDAS_VARS = [
    # (netCDF variable, stored variable, unit, offset)
    ("SoilMoist_S_tavg", "soil_moisture_surface", "kg/m2", 0.0),
    ("SoilMoist_RZ_tavg", "soil_moisture_rootzone", "kg/m2", 0.0),
    ("GWS_tavg", "groundwater_storage", "mm", 0.0),
    ("Tair_f_tavg", "air_temperature", "degC", -273.15),
]


def gldas_clsm(source, area, since, until, skip, workdir):
    import xarray as xr

    for d, url in direct.gesdisc_files("GLDAS_CLSM025_DA1_D", since, until):
        if d in skip:
            continue
        path = direct.download(url, os.path.join(workdir, os.path.basename(url)))
        rows = []
        try:
            with xr.open_dataset(path) as ds:
                for nc_var, var, unit, offset in GLDAS_VARS:
                    da = ds[nc_var].isel(time=0)
                    stats = grid_stats(da.values, da["lat"].values, da["lon"].values, area, offset=offset)
                    rows += rows_from_stats(stats, d, var, unit,
                                            _provenance(source, url, ["clip bbox+buffer", "cos-lat weighted mean"]))
        finally:
            _remove([path])
        yield d, rows


# ---------------------------------------------------------------------------
# GRACE/GRACE-FO mascons: one granule holds every month (CMR + earthaccess)
# ---------------------------------------------------------------------------

def _cmr_search(source, area, since, until):
    import time

    import earthaccess

    for attempt in range(4):
        try:
            return earthaccess.search_data(short_name=source["product"], version=source["product_version"],
                                           temporal=(since.isoformat(), until.isoformat()),
                                           bounding_box=bounds(area))
        except Exception as e:
            if attempt == 3:
                raise RuntimeError(f"CMR search for {source['product']} failed (NASA CMR outage?): {e}") from e
            time.sleep(10 * 2**attempt)


def grace_mascon(source, area, since, until, skip, workdir):
    import earthaccess
    import xarray as xr

    granules = _cmr_search(source, area, date(2002, 4, 1), until)
    if not granules:
        return
    direct.token()  # logs in through earthaccess as a side effect
    paths = earthaccess.download(granules[-1:], workdir, show_progress=False)
    try:
        with xr.open_dataset(paths[0]) as ds:
            da = ds["lwe_thickness"]
            for i, t in enumerate(da["time"].values):
                d = np.datetime64(t, "D").astype(object)
                if d < since or d in skip:
                    continue
                stats = grid_stats(da.isel(time=i).values, da["lat"].values, da["lon"].values, area)
                yield d, rows_from_stats(stats, d, "water_storage_anomaly", "cm",
                                         _provenance(source, None, ["clip bbox+buffer", "cos-lat weighted mean"],
                                                     granule=os.path.basename(paths[0])))
    finally:
        _remove(paths)


# ---------------------------------------------------------------------------
# MODIS via LAADS (HDF4)
# ---------------------------------------------------------------------------

def _laads_dates(product, since, until, skip):
    for year in range(since.year, until.year + 1):
        for doy in direct.laads_days(product, year):
            d = direct.doy_to_date(year, doy)
            if since <= d <= until and d not in skip:
                yield d, year, doy


def modis_ndvi(source, area, since, until, skip, workdir):
    from pyhdf.SD import SD, SDC

    lats = 90 - 0.025 - 0.05 * np.arange(3600)
    lons = -180 + 0.025 + 0.05 * np.arange(7200)
    for d, year, doy in _laads_dates("MOD13C1", since, until, skip):
        urls = direct.laads_files("MOD13C1", year, doy)
        if not urls:
            continue
        path = direct.download(urls[0], os.path.join(workdir, os.path.basename(urls[0])))
        try:
            hdf = SD(path, SDC.READ)
            raw = hdf.select("CMG 0.05 Deg 16 days NDVI")[:]
            hdf.end()
        finally:
            _remove([path])
        stats = grid_stats(raw, lats, lons, area, scale=1e-4, valid_range=(-2000, 10000))
        yield d, rows_from_stats(stats, d, "ndvi", "index",
                                 _provenance(source, urls[0], ["clip bbox+buffer", "scale 1e-4", "cos-lat weighted mean"]),
                                 period_end=d + timedelta(days=15))


def modis_et(source, area, since, until, skip, workdir):
    from pyhdf.SD import SD, SDC

    west, south, east, north = bounds(area)
    tiles = direct.modis_tiles((west, south, east, north))
    for d, year, doy in _laads_dates("MOD16A2", since, until, skip):
        urls = direct.laads_files("MOD16A2", year, doy, tiles)
        if not urls:
            continue
        paths = [direct.download(u, os.path.join(workdir, os.path.basename(u))) for u in urls]
        values, lat_parts = [], []
        try:
            for p in paths:
                m = re.search(r"\.h(\d\d)v(\d\d)\.", os.path.basename(p))
                hdf = SD(p, SDC.READ)
                raw = hdf.select("ET_500m")[:]
                hdf.end()
                lat, lon = sinusoidal_latlon(int(m.group(1)), int(m.group(2)), raw.shape[0])
                inside = (lat >= south) & (lat <= north) & (lon >= west) & (lon <= east)
                values.append(raw[inside])
                lat_parts.append(lat[inside])
        finally:
            _remove(paths)
        stats = masked_stats(np.concatenate(values), np.concatenate(lat_parts), scale=0.1, valid_range=(0, 32700))
        yield d, rows_from_stats(stats, d, "evapotranspiration", "mm/8-day",
                                 _provenance(source, None, ["mosaic tiles", "clip bbox+buffer", "scale 0.1",
                                                            "cos-lat weighted mean"], tiles=tiles),
                                 period_end=d + timedelta(days=7))


# ---------------------------------------------------------------------------
# Static and annual reference layers
# ---------------------------------------------------------------------------

class _Accumulator:
    """Running weighted mean/min/max so large mosaics never sit in memory at once."""

    def __init__(self):
        self.wsum = self.vsum = 0.0
        self.n_valid = self.n_total = 0
        self.vmin, self.vmax = np.inf, -np.inf

    def add(self, values, lats, valid):
        self.n_total += values.size
        v, w = values[valid].astype("float64"), np.cos(np.deg2rad(lats[valid]))
        if v.size:
            self.vsum += float((v * w).sum())
            self.wsum += float(w.sum())
            self.vmin, self.vmax = min(self.vmin, v.min()), max(self.vmax, v.max())
            self.n_valid += v.size

    def stats(self):
        if not self.n_valid:
            return {"mean": None, "min": None, "max": None, "valid_fraction": 0.0}
        return {"mean": self.vsum / self.wsum, "min": float(self.vmin), "max": float(self.vmax),
                "valid_fraction": self.n_valid / self.n_total}


ASTER_DATE = date(2019, 8, 5)  # ASTGTM v003 release


def aster_dem(source, area, since, until, skip, workdir):
    if ASTER_DATE in skip:
        return
    box = bounds(area)
    acc = _Accumulator()
    n = 0
    for url in direct.aster_tiles(box):
        path = direct.download(url, os.path.join(workdir, os.path.basename(url)))
        if path is None:
            continue  # tile does not exist (sea)
        try:
            _, data, lats, nodata = _window_stats(path, box)
            acc.add(data, lats, data != nodata if nodata is not None else np.ones_like(data, bool))
            n += 1
        finally:
            _remove([path])
    yield ASTER_DATE, rows_from_stats(acc.stats(), ASTER_DATE, "elevation", "m",
                                      _provenance(source, None, ["mosaic 1° tiles", "clip bbox+buffer",
                                                                 "cos-lat weighted mean"], tiles=n))


def _class_fractions(classes, lats, d, variable_prefix, provenance, top=None, ignore=()):
    w = np.cos(np.deg2rad(lats)).ravel()
    c = classes.ravel()
    keep = ~np.isin(c, ignore)
    totals = {}
    uniq, inv = np.unique(c[keep], return_inverse=True)
    sums = np.bincount(inv, weights=w[keep])
    frac = sums / sums.sum()
    order = np.argsort(frac)[::-1][:top] if top else np.argsort(frac)[::-1]
    for i in order:
        totals[int(uniq[i])] = float(frac[i])
    return [{
        "obs_date": d.isoformat(), "period_end": None, "variable": f"{variable_prefix}_{cls}",
        "stat": "fraction", "value": value, "unit": "fraction", "processing": provenance,
    } for cls, value in totals.items()]


CCI_FIRST_YEAR, CCI_LAST_YEAR = 2016, 2022


def cci_landcover(source, area, since, until, skip, workdir):
    import cdsapi
    import xarray as xr

    years = [y for y in range(CCI_FIRST_YEAR, CCI_LAST_YEAR + 1) if date(y, 1, 1) not in skip]
    if not years:
        return
    year = years[-1]  # one year per run keeps the job inside its time limit
    west, south, east, north = bounds(area)
    client = cdsapi.Client(url="https://cds.climate.copernicus.eu/api", key=os.environ["CDS_API_KEY"])
    target = os.path.join(workdir, f"lc_{year}.zip")
    client.retrieve("satellite-land-cover", {
        "variable": "all", "year": [str(year)], "version": ["v2_1_1"],
        "area": [north, west, south, east],
    }, target)
    with zipfile.ZipFile(target) as z:
        z.extractall(workdir)
    nc = sorted(glob.glob(os.path.join(workdir, "*LC*.nc")))[-1]
    try:
        with xr.open_dataset(nc) as ds:
            da = ds["lccs_class"].isel(time=0)
            da = da.sel(lat=slice(north, south), lon=slice(west, east))
            lats = np.broadcast_to(da["lat"].values[:, None], da.shape)
            d = date(year, 1, 1)
            yield d, _class_fractions(da.values, lats, d, "lc_class",
                                      {"product": source["product"], "version": "v2_1_1", "year": year,
                                       "steps": ["CDS area subset", "cos-lat weighted class fractions"]},
                                      ignore=(0,))
    finally:
        _remove([target, nc])


HWSD_URL = "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/HWSD/HWSD2_RASTER.zip"
HWSD_DATE = date(2023, 1, 1)  # HWSD v2.0 release year


def hwsd(source, area, since, until, skip, workdir):
    import rasterio

    if HWSD_DATE in skip:
        return
    url = os.environ.get("HWSD_URL", HWSD_URL)
    target = direct.download(url, os.path.join(workdir, "hwsd.zip"), nasa=False)
    try:
        with zipfile.ZipFile(target) as z:
            bil = next(n for n in z.namelist() if n.lower().endswith(".bil"))
        _, data, lats, nodata = _window_stats(f"/vsizip/{target}/{bil}", bounds(area))
        yield HWSD_DATE, _class_fractions(data, lats, HWSD_DATE, "smu",
                                          {"product": "HWSD", "version": "2.0", "url": url,
                                           "steps": ["window read bbox+buffer", "top-20 soil mapping unit fractions"]},
                                          top=20, ignore=(nodata,) if nodata is not None else ())
    finally:
        _remove([target])


# Source key -> (adapter, lookback days, needs Earthdata login)
ADAPTERS = {
    "gpm_imerg": (gpm_imerg, 10, True),
    "chirps3": (chirps3, 400, False),
    "chirps": (chirps, 75, False),
    "gldas_clsm": (gldas_clsm, 180, True),
    "grace_mascon": (grace_mascon, 365, True),
    "modis_ndvi": (modis_ndvi, 64, True),
    "modis_et": (modis_et, 48, True),
    "aster_dem": (aster_dem, 0, True),
    "cci_landcover": (cci_landcover, 0, False),
    "hwsd": (hwsd, 0, False),
}
