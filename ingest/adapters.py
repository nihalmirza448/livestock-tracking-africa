"""One adapter per data source.

Each adapter yields (obs_date, rows) pairs for dates not already stored. Rows
are area statistics; the runner adds source, area, version and run ids.
Adding a source means adding an adapter here and a row in data_sources.
"""

import glob
import os
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from .geo import bounds, grid_stats, masked_stats, rows_from_stats, sinusoidal_latlon


# ---------------------------------------------------------------------------
# NASA Earthdata helpers
# ---------------------------------------------------------------------------

def _search(source, area, since, until):
    import earthaccess

    # Searching needs no login; logging in first attaches a token, and a bad
    # token makes CMR answer with a bare internal error.
    try:
        return earthaccess.search_data(
            short_name=source["product"],
            version=source["product_version"],
            temporal=(since.isoformat(), until.isoformat()),
            bounding_box=bounds(area),
        )
    except Exception as e:
        raise RuntimeError(f"CMR search for {source['product']} v{source['product_version']} failed: {e}") from e


_logged_in = False


def _login():
    global _logged_in
    if not _logged_in:
        import earthaccess

        auth = earthaccess.login(strategy="environment")
        if not auth or not auth.authenticated:
            raise RuntimeError("Earthdata login failed: check EARTHDATA_USERNAME / EARTHDATA_PASSWORD")
        _logged_in = True


def _granule_dates(g):
    rng = g["umm"]["TemporalExtent"]["RangeDateTime"]
    start = datetime.fromisoformat(rng["BeginningDateTime"].replace("Z", "+00:00")).date()
    end = rng.get("EndingDateTime")
    end = datetime.fromisoformat(end.replace("Z", "+00:00")).date() if end else None
    return start, end


def _download(granules, workdir):
    import earthaccess

    _login()
    paths = earthaccess.download(granules, workdir, show_progress=False)
    if len(paths) < len(granules):
        raise RuntimeError(
            f"Downloaded {len(paths)} of {len(granules)} files. If this is GES DISC data, approve "
            "'NASA GESDISC DATA ARCHIVE' under Authorized Apps in your Earthdata profile."
        )
    return paths


def _provenance(source, g=None, steps=()):
    p = {"product": source["product"], "version": source["product_version"], "steps": list(steps)}
    if g is not None:
        p["granule"] = g["meta"]["native-id"] if "meta" in g else None
    return p


def _remove(paths):
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# GPM IMERG daily precipitation
# ---------------------------------------------------------------------------

def gpm_imerg(source, area, since, until, skip, workdir):
    import xarray as xr

    for g in _search(source, area, since, until):
        d, _ = _granule_dates(g)
        if d in skip:
            continue
        paths = _download([g], workdir)
        try:
            with xr.open_dataset(paths[0]) as ds:
                da = ds["precipitation"].isel(time=0).transpose("lat", "lon")
                stats = grid_stats(da.values, da["lat"].values, da["lon"].values, area)
        finally:
            _remove(paths)
        stats.pop("min")
        yield d, rows_from_stats(stats, d, "precipitation", "mm/day",
                                 _provenance(source, g, ["clip bbox+buffer", "cos-lat weighted mean"]))


# ---------------------------------------------------------------------------
# CHIRPS daily precipitation (public cloud-optimised GeoTIFFs)
# ---------------------------------------------------------------------------

CHIRPS_URL = "/vsicurl/https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/cogs/p05/{y}/chirps-v2.0.{y}.{m:02d}.{d:02d}.cog"


def chirps(source, area, since, until, skip, workdir):
    import rasterio
    from rasterio.errors import RasterioIOError
    from rasterio.windows import from_bounds

    import requests

    west, south, east, north = bounds(area)
    found = missing = 0
    last_missing = None
    d = since
    while d <= until:
        if d not in skip:
            url = CHIRPS_URL.format(y=d.year, m=d.month, d=d.day)
            try:
                with rasterio.open(url) as src:
                    win = from_bounds(west, south, east, north, src.transform).round_offsets().round_lengths()
                    data = src.read(1, window=win)
                    rows_idx = np.arange(win.row_off, win.row_off + win.height) + 0.5
                    lats = src.transform.f + rows_idx * src.transform.e
                    stats = masked_stats(data, np.broadcast_to(lats[:, None], data.shape), fill=src.nodata)
            except RasterioIOError:
                missing += 1
                last_missing = url
                d += timedelta(days=1)
                continue  # not published yet
            found += 1
            stats.pop("min")
            yield d, rows_from_stats(stats, d, "precipitation", "mm/day", {
                "product": source["product"], "version": source["product_version"],
                "url": url.removeprefix("/vsicurl/"),
                "steps": ["window read bbox+buffer", "cos-lat weighted mean"],
            })
        d += timedelta(days=1)
    if missing and not found:
        # Every day missing means the path is wrong or the product stopped, not latency.
        http = last_missing.removeprefix("/vsicurl/")
        status = requests.head(http, timeout=30, allow_redirects=True).status_code if http.startswith("http") else "n/a"
        raise RuntimeError(f"No CHIRPS files for {since}..{until}; last tried {http} -> HTTP {status}")


# ---------------------------------------------------------------------------
# GLDAS-2.2 CLSM daily: soil moisture, groundwater, air temperature
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

    for g in _search(source, area, since, until):
        d, _ = _granule_dates(g)
        if d in skip:
            continue
        paths = _download([g], workdir)
        rows = []
        try:
            with xr.open_dataset(paths[0]) as ds:
                for nc_var, var, unit, offset in GLDAS_VARS:
                    da = ds[nc_var].isel(time=0)
                    stats = grid_stats(da.values, da["lat"].values, da["lon"].values, area, offset=offset)
                    rows += rows_from_stats(stats, d, var, unit,
                                            _provenance(source, g, ["clip bbox+buffer", "cos-lat weighted mean"]))
        finally:
            _remove(paths)
        yield d, rows


# ---------------------------------------------------------------------------
# GRACE/GRACE-FO mascons: one granule holds every month
# ---------------------------------------------------------------------------

def grace_mascon(source, area, since, until, skip, workdir):
    import xarray as xr

    granules = _search(source, area, date(2002, 4, 1), until)
    if not granules:
        return
    paths = _download(granules[-1:], workdir)
    try:
        with xr.open_dataset(paths[0]) as ds:
            da = ds["lwe_thickness"]
            for i, t in enumerate(da["time"].values):
                d = np.datetime64(t, "D").astype(object)
                if d < since or d in skip:
                    continue
                stats = grid_stats(da.isel(time=i).values, da["lat"].values, da["lon"].values, area)
                yield d, rows_from_stats(stats, d, "water_storage_anomaly", "cm",
                                         _provenance(source, granules[-1], ["clip bbox+buffer", "cos-lat weighted mean"]))
    finally:
        _remove(paths)


# ---------------------------------------------------------------------------
# MODIS (HDF4)
# ---------------------------------------------------------------------------

def modis_ndvi(source, area, since, until, skip, workdir):
    from pyhdf.SD import SD, SDC

    lats = 90 - 0.025 - 0.05 * np.arange(3600)
    lons = -180 + 0.025 + 0.05 * np.arange(7200)
    for g in _search(source, area, since, until):
        d, end = _granule_dates(g)
        if d in skip:
            continue
        paths = _download([g], workdir)
        try:
            hdf = SD(paths[0], SDC.READ)
            raw = hdf.select("CMG 0.05 Deg 16 days NDVI")[:]
            hdf.end()
        finally:
            _remove(paths)
        stats = grid_stats(raw, lats, lons, area, scale=1e-4, valid_range=(-2000, 10000))
        yield d, rows_from_stats(stats, d, "ndvi", "index",
                                 _provenance(source, g, ["clip bbox+buffer", "scale 1e-4", "cos-lat weighted mean"]),
                                 period_end=end)


def modis_et(source, area, since, until, skip, workdir):
    from pyhdf.SD import SD, SDC

    west, south, east, north = bounds(area)
    by_date = defaultdict(list)
    for g in _search(source, area, since, until):
        d, end = _granule_dates(g)
        if d not in skip:
            by_date[(d, end)].append(g)

    for (d, end), granules in sorted(by_date.items()):
        paths = _download(granules, workdir)
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
                                                            "cos-lat weighted mean"]) | {"tiles": len(paths)},
                                 period_end=end)


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
    import rasterio
    from rasterio.windows import from_bounds

    if ASTER_DATE in skip:
        return
    west, south, east, north = bounds(area)
    import earthaccess

    granules = earthaccess.search_data(short_name=source["product"], version=source["product_version"],
                                       bounding_box=(west, south, east, north))
    acc = _Accumulator()
    for g in granules:
        paths = _download([g], workdir)
        try:
            for p in paths:
                if not p.endswith("_dem.tif"):
                    continue
                with rasterio.open(p) as src:
                    b = src.bounds
                    win = from_bounds(max(west, b.left), max(south, b.bottom), min(east, b.right),
                                      min(north, b.top), src.transform).round_offsets().round_lengths()
                    data = src.read(1, window=win)
                    rows_idx = np.arange(win.row_off, win.row_off + win.height) + 0.5
                    lats = np.broadcast_to((src.transform.f + rows_idx * src.transform.e)[:, None], data.shape)
                    acc.add(data, lats, data != src.nodata if src.nodata is not None else np.ones_like(data, bool))
        finally:
            _remove(paths)
    yield ASTER_DATE, rows_from_stats(acc.stats(), ASTER_DATE, "elevation", "m",
                                      _provenance(source, None, ["mosaic 1° tiles", "clip bbox+buffer",
                                                                 "cos-lat weighted mean"]) | {"tiles": len(granules)})


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
    import requests
    from rasterio.windows import from_bounds

    if HWSD_DATE in skip:
        return
    url = os.environ.get("HWSD_URL", HWSD_URL)
    target = os.path.join(workdir, "hwsd.zip")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(target, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    try:
        with zipfile.ZipFile(target) as z:
            bil = next(n for n in z.namelist() if n.lower().endswith(".bil"))
        west, south, east, north = bounds(area)
        with rasterio.open(f"/vsizip/{target}/{bil}") as src:
            win = from_bounds(west, south, east, north, src.transform).round_offsets().round_lengths()
            data = src.read(1, window=win)
            rows_idx = np.arange(win.row_off, win.row_off + win.height) + 0.5
            lats = np.broadcast_to((src.transform.f + rows_idx * src.transform.e)[:, None], data.shape)
            nodata = src.nodata
        yield HWSD_DATE, _class_fractions(data, lats, HWSD_DATE, "smu",
                                          {"product": "HWSD", "version": "2.0", "url": url,
                                           "steps": ["window read bbox+buffer", "top-20 soil mapping unit fractions"]},
                                          top=20, ignore=(nodata,) if nodata is not None else ())
    finally:
        _remove([target])


# Source key -> (adapter, lookback days, needs Earthdata login)
ADAPTERS = {
    "gpm_imerg": (gpm_imerg, 10, True),
    "chirps": (chirps, 75, False),
    "gldas_clsm": (gldas_clsm, 180, True),
    "grace_mascon": (grace_mascon, 365, True),
    "modis_ndvi": (modis_ndvi, 64, True),
    "modis_et": (modis_et, 48, True),
    "aster_dem": (aster_dem, 0, True),
    "cci_landcover": (cci_landcover, 0, False),
    "hwsd": (hwsd, 0, False),
}
