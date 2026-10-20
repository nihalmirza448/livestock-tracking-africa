"""Offline tests: adapters are fed synthetic files in the real product formats,
with the archive listings and downloads stubbed out.

    python -m ingest.test_adapters
"""

import os
import shutil
import tempfile
from datetime import date

import numpy as np

from . import adapters, direct, run
from .geo import BinGrid, grid_row, grid_stats, regular_grid, sinusoidal_latlon

AREA = {"id": "south_kordofan", "min_lon": 29.0, "min_lat": 9.3, "max_lon": 32.4, "max_lat": 12.7, "buffer_deg": 0.25}
BOX = (28.75, 9.05, 32.65, 12.95)


def src(key, product="P", version="1", auth="earthdata"):
    return {"key": key, "product": product, "product_version": version, "enabled": True, "auth": auth}


def stub_downloads(files):
    """direct.download copies a local file instead of fetching: {url: local_path}."""
    def fake(url, dest, nasa=True):
        if url not in files:
            return None
        if os.path.abspath(files[url]) != os.path.abspath(dest):
            shutil.copy(files[url], dest)
        return dest
    direct.download = fake
    direct.download_modis = fake


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------

def test_grid_stats_weights_and_clip():
    lats = np.arange(-89.5, 90, 1.0)
    lons = np.arange(0.5, 360, 1.0)  # 0..360 convention
    field = np.zeros((lats.size, lons.size))
    lat_in = (lats >= 9.05) & (lats <= 12.95)
    lon_in = (lons >= 28.75) & (lons <= 32.65)
    field[np.ix_(lat_in, lon_in)] = 5.0
    s = grid_stats(field, lats, lons, AREA)
    assert abs(s["mean"] - 5.0) < 1e-9 and s["valid_fraction"] == 1.0


def test_regular_grid_flips_to_north_first_and_wraps_lons():
    lats = np.arange(-89.875, 90, 0.25)          # ascending, like GLDAS
    lons = np.arange(0.125, 360, 0.25)           # 0..360, like GRACE
    field = np.broadcast_to(lats[:, None], (lats.size, lons.size)).copy()  # value == latitude
    g = regular_grid(field, lats, lons, AREA)
    assert g["ny"] == 16 and g["nx"] == 16 and abs(g["dx"] - 0.25) < 1e-9
    assert g["values"][0, 0] > g["values"][-1, 0]              # first row is the northernmost
    assert abs(g["south"] - 9.0) < 1e-9 and abs(g["west"] - 28.75) < 1e-9


def test_bingrid_averages_samples_into_cells():
    b = BinGrid(AREA, res=0.05)
    assert (b.nx, b.ny) == (78, 78)
    b.add(np.array([10.0, 30.0, np.nan]), np.array([12.93, 12.92, 12.91]), np.array([28.76, 28.77, 28.78]))
    g = b.grid()
    assert abs(g["values"][0, 0] - 20.0) < 1e-9 and np.isnan(g["values"][1, 1])
    row = grid_row(g, date(2026, 1, 1), "x", "u")
    assert row["_grid"] and row["values"][0] == 20.0 and row["values"][1] is None and len(row["values"]) == 78 * 78


def test_adapters_emit_one_grid_per_variable():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "imerg.nc4")
        _nc_global(p, "precipitation", 3.0, 0.1, -90, lon_first=True)
        url = "https://x/2026/10/3B-DAY-L.MS.MRG.3IMERG.20261018-S000000-E235959.V07C.nc4"
        direct.gesdisc_files = lambda product, since, until: [(date(2026, 10, 18), url)]
        stub_downloads({url: p})
        (_, rows), = adapters.gpm_imerg(src("gpm_imerg"), AREA, date(2026, 10, 10), date(2026, 10, 20), set(), d)
        grids = [r for r in rows if r.get("_grid")]
        assert len(grids) == 1 and grids[0]["nx"] == 39 and grids[0]["ny"] == 39
        assert all(abs(v - 3.0) < 1e-6 for v in grids[0]["values"])


def test_modis_tiles_for_south_kordofan():
    tiles = direct.modis_tiles(BOX)
    assert "h20v07" in tiles and "h21v07" in tiles and "h20v08" in tiles
    assert len(tiles) <= 4
    lat, lon = sinusoidal_latlon(20, 7, 2400)
    assert abs(lat[0, 0] - 20) < 0.01 and abs(lat[-1, 0] - 10) < 0.01


def test_aster_tiles_cover_box():
    urls = direct.aster_tiles(BOX)
    assert len(urls) == 4 * 5
    assert any("N09E028" in u for u in urls) and any("N12E032" in u for u in urls)


def test_lpcloud_url_from_laads_name():
    u = direct.lpcloud_url("https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1/2026/241/MOD13C1.A2026241.061.2026258051816.hdf")
    assert u == ("https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MOD13C1.061/"
                 "MOD13C1.A2026241.061.2026258051816/MOD13C1.A2026241.061.2026258051816.hdf")


def test_gesdisc_date_regex():
    import re
    for name, want in [("3B-DAY-L.MS.MRG.3IMERG.20261018-S000000-E235959.V07C.nc4", "20261018"),
                       ("GLDAS_CLSM025_DA1_D.A20260801.022.nc4", "20260801")]:
        assert re.search(r"(?<!\d)(20\d{6})(?!\d)", name).group(1) == want


# ---------------------------------------------------------------------------
# netCDF products
# ---------------------------------------------------------------------------

def _nc_global(path, var, value, res, lats_from, lon_first=False, time="2026-10-18", extra=None):
    import xarray as xr

    lats = np.arange(lats_from + res / 2, 90, res)
    lons = np.arange(-180 + res / 2, 180, res)
    data = {var: (("time", "lon", "lat") if lon_first else ("time", "lat", "lon"),
                  np.full((1, lons.size, lats.size) if lon_first else (1, lats.size, lons.size), value, "f4"))}
    for v, val in (extra or {}).items():
        data[v] = (("time", "lat", "lon"), np.full((1, lats.size, lons.size), val, "f4"))
    xr.Dataset(data, coords={"time": [np.datetime64(time)], "lat": lats, "lon": lons}).to_netcdf(path)


def test_gpm_imerg_via_gesdisc_listing():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "imerg.nc4")
        _nc_global(p, "precipitation", 3.0, 0.1, -90, lon_first=True)
        url = "https://x/2026/10/3B-DAY-L.MS.MRG.3IMERG.20261018-S000000-E235959.V07C.nc4"
        direct.gesdisc_files = lambda product, since, until: [(date(2026, 10, 18), url)]
        stub_downloads({url: p})
        out = list(adapters.gpm_imerg(src("gpm_imerg"), AREA, date(2026, 10, 10), date(2026, 10, 20), set(), d))
        assert len(out) == 1 and out[0][0] == date(2026, 10, 18)
        mean = next(r for r in out[0][1] if r["stat"] == "mean")
        assert abs(mean["value"] - 3.0) < 1e-6 and mean["unit"] == "mm/day" and mean["processing"]["url"] == url


def test_gldas_converts_temperature_and_skips_stored():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "gldas.nc4")
        _nc_global(p, "SoilMoist_S_tavg", 10.0, 0.25, -60, time="2026-08-01",
                   extra={"SoilMoist_RZ_tavg": 200.0, "GWS_tavg": 500.0, "AvgSurfT_tavg": 303.15})
        u1, u2 = "https://x/2026/08/GLDAS_CLSM025_DA1_D.A20260801.022.nc4", "https://x/2026/08/GLDAS_CLSM025_DA1_D.A20260802.022.nc4"
        direct.gesdisc_files = lambda product, since, until: [(date(2026, 8, 1), u1), (date(2026, 8, 2), u2)]
        stub_downloads({u1: p, u2: p})
        out = list(adapters.gldas_clsm(src("gldas_clsm"), AREA, date(2026, 5, 1), date(2026, 9, 1), {date(2026, 8, 2)}, d))
        assert [o[0] for o in out] == [date(2026, 8, 1)]
        t = next(r for r in out[0][1] if r["variable"] == "surface_temperature" and r["stat"] == "mean")
        assert abs(t["value"] - 30.0) < 1e-4 and t["unit"] == "degC"
        assert not any(r["variable"] == "total_water_storage" for r in out[0][1])  # optional var absent -> skipped


# ---------------------------------------------------------------------------
# MODIS via LAADS
# ---------------------------------------------------------------------------

def _hdf4(path, name, data):
    from pyhdf.SD import SD, SDC

    hdf = SD(path, SDC.WRITE | SDC.CREATE)
    sds = hdf.create(name, SDC.INT16, data.shape)
    sds[:] = data
    sds.endaccess()
    hdf.end()


def test_modis_ndvi_via_laads():
    with tempfile.TemporaryDirectory() as d:
        raw = np.full((3600, 7200), 4000, "i2")
        raw[1546, 4200] = -3000  # fill value inside the area is ignored
        p = os.path.join(d, "MOD13C1.A2026257.061.2026278042210.hdf")
        _hdf4(p, "CMG 0.05 Deg 16 days NDVI", raw)
        url = "https://laads/MOD13C1/2026/257/MOD13C1.A2026257.061.2026278042210.hdf"
        direct.laads_days = lambda product, year: [241, 257, 273] if year == 2026 else []
        direct.laads_files = lambda product, year, doy, tiles=None: [url] if doy == 257 else ["https://laads/other.hdf"]
        stub_downloads({url: p, "https://laads/other.hdf": p})
        out = list(adapters.modis_ndvi(src("modis_ndvi"), AREA, date(2026, 9, 10), date(2026, 10, 20), {date(2026, 9, 30)}, d))
        assert [o[0] for o in out] == [date(2026, 9, 14)]  # doy 257; 273 skipped as stored; 241 before since
        mean = next(r for r in out[0][1] if r["stat"] == "mean")
        assert abs(mean["value"] - 0.4) < 1e-6 and mean["period_end"] == "2026-09-29"


def test_modis_et_mosaics_tiles():
    with tempfile.TemporaryDirectory() as d:
        files = {}
        for tile, val in [("h20v07", 100), ("h20v08", 300)]:
            p = os.path.join(d, f"MOD16A2.A2026257.{tile}.061.2026274160926.hdf")
            raw = np.full((2400, 2400), val, "i2")
            raw[:10, :10] = 32767  # fill class
            _hdf4(p, "ET_500m", raw)
            files[f"https://laads/MOD16A2/2026/257/{os.path.basename(p)}"] = p
        direct.laads_days = lambda product, year: [257]
        direct.laads_files = lambda product, year, doy, tiles=None: sorted(files)
        stub_downloads(files)
        (_, rows), = adapters.modis_et(src("modis_et"), AREA, date(2026, 9, 1), date(2026, 10, 20), set(), d)
        stats = {r["stat"]: r["value"] for r in rows if "stat" in r}
        assert stats["min"] == 10.0 and stats["max"] == 30.0  # scaled by 0.1, both tiles present
        assert rows[0]["period_end"] == "2026-09-21"


# ---------------------------------------------------------------------------
# CHIRPS v3 and ASTER (GeoTIFF window reads)
# ---------------------------------------------------------------------------

def _tif(path, value, width=7200, height=2000, origin=(-180, 50), res=0.05, nodata=-9999):
    import rasterio
    from rasterio.transform import from_origin

    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(*origin, res, res), nodata=nodata) as dst:
        dst.write(np.full((height, width), value, "float32"), 1)


def test_chirps3_prefers_final_over_prelim():
    with tempfile.TemporaryDirectory() as d:
        pf, pp = os.path.join(d, "final.tif"), os.path.join(d, "prelim.tif")
        _tif(pf, 2.5)
        _tif(pp, 9.0)
        d1, d2 = date(2026, 10, 1), date(2026, 10, 2)
        direct.chirps3_files = lambda since, until: {d1: (pf, "final"), d2: (pp, "prelim")}
        # /vsicurl/ prefix is harmless for local paths? No: strip it for the test by patching rasterio open path.
        import rasterio
        real_open = rasterio.open
        rasterio.open = lambda p, *a, **k: real_open(p.removeprefix("/vsicurl/"), *a, **k)
        try:
            out = list(adapters.chirps3(src("chirps3", auth="none"), AREA, d1, d2, set(), d))
        finally:
            rasterio.open = real_open
        assert [o[0] for o in out] == [d1, d2]
        means = {o[0]: next(r for r in o[1] if r["stat"] == "mean") for o in out}
        assert abs(means[d1]["value"] - 2.5) < 1e-6 and means[d1]["processing"]["release"] == "final"
        assert abs(means[d2]["value"] - 9.0) < 1e-6 and means[d2]["processing"]["release"] == "prelim"


def test_chirps3_fails_loudly_when_nothing_listed():
    direct.chirps3_files = lambda since, until: {}
    try:
        list(adapters.chirps3(src("chirps3", auth="none"), AREA, date(2026, 1, 1), date(2026, 2, 1), set(), "/tmp"))
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "No CHIRPS v3" in str(e)


def test_aster_mosaics_available_tiles():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, "fixture"))
        p = os.path.join(d, "fixture", "ASTGTMV003_N10E030_dem.tif")
        _tif(p, 500.0, width=3601, height=3601, origin=(30, 11), res=1 / 3600, nodata=-9999)
        urls = direct.aster_tiles(BOX)
        stub_downloads({u: p for u in urls if "N10E030" in u})  # every other tile 404s
        (_, rows), = adapters.aster_dem(src("aster_dem"), AREA, date(1990, 1, 1), date.today(), set(), d)
        stats = {r["stat"]: r["value"] for r in rows if "stat" in r}
        assert abs(stats["mean"] - 500.0) < 1e-6 and rows[0]["processing"]["tiles"] == 1


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

class FakeStore:
    def __init__(self):
        self.rows, self.runs = [], {}

    def source(self, key):
        return src(key, auth="none")

    def start_run(self, key, runner):
        self.runs[1] = None
        return 1

    def finish_run(self, run_id, status, requested, written, error=None):
        self.runs[run_id] = (status, requested, written, error)

    def dataset_version(self, key, version):
        return 7

    def stored_dates(self, key, area_id, since, table="eo_observations"):
        return set()

    def write_observations(self, rows):
        self.rows += rows
        return len(rows)

    def write_grids(self, rows):
        self.rows += rows
        return len(rows)

    def write_water_obs(self, rows):
        self.rows += rows
        return len(rows)

    def water_points(self, area_id):
        return []


def test_runner_records_partial_failure():
    def flaky(source, area, since, until, skip, workdir):
        yield date(2026, 10, 1), [{"obs_date": "2026-10-01", "variable": "v", "stat": "mean", "value": 1}]
        raise OSError("corrupt granule")

    run.ADAPTERS["flaky"] = (flaky, 5, False)
    store = FakeStore()
    assert run.run_source(store, "flaky", AREA, None, "test") is False
    status, requested, written, err = store.runs[1]
    assert (status, requested, written) == ("partial", 1, 1) and "corrupt granule" in err
    assert store.rows[0]["dataset_version_id"] == 7 and store.rows[0]["run_id"] == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)


# ---------------------------------------------------------------------------
# Sentinel-2 water and Kobo mapping
# ---------------------------------------------------------------------------

def test_water_blocks_mndwi_and_cloud_mask():
    from . import sentinel

    green = np.full((6, 6), 1000, "uint16")
    swir = np.full((6, 6), 2000, "uint16")       # dry everywhere
    swir[:3, :3] = 200                            # top-left block is water
    scl = np.full((6, 6), 4, "uint8")
    scl[3:, 3:] = 9                               # bottom-right block is cloud
    frac = sentinel.water_blocks(green, swir, scl)
    assert frac.shape == (2, 2)
    assert frac[0, 0] == 1.0 and frac[0, 1] == 0.0 and frac[1, 0] == 0.0 and np.isnan(frac[1, 1])


def test_point_fraction_buffer():
    from . import sentinel

    frac = np.array([[1.0, np.nan], [0.0, 0.0]], "float32")
    x = np.array([[0.0, 60.0], [0.0, 60.0]])
    y = np.array([[60.0, 60.0], [0.0, 0.0]])
    f, valid, n = sentinel.point_fraction(frac, x, y, 30.0, 30.0)
    assert n == 4 and abs(f - (1 / 3)) < 1e-6 and abs(valid - 0.75) < 1e-6
    assert sentinel.point_fraction(frac, x, y, 5000.0, 5000.0) is None


def test_kobo_flow_mapping_flags_unknown_user():
    from . import kobo_sync

    sub = {"_uuid": "u1", "_submitted_by": "ahmed", "_submission_time": "2026-10-20T08:00:00",
           "monitoring_point": "KAD", "species": "cattle", "head_count": "120", "direction": "south"}
    row, why = kobo_sync.map_flow(sub, {"KAD": "mp-1"}, {})
    assert why is None and row["client_id"] == "u1" and row["head_count"] == 120
    assert row["pending_review"] is True and row["enumerator_id"] is None
    row, why = kobo_sync.map_flow({**sub, "monitoring_point": "XXX"}, {"KAD": "mp-1"}, {})
    assert row is None and "XXX" in why
    chk, _ = kobo_sync.map_check({"_uuid": "u2", "_submitted_by": "ahmed", "location": "11.01 29.72 500 5",
                                  "pasture_condition": "3", "route_condition": "open"}, "south_kordofan", {"ahmed": "user-9"})
    assert chk["geom"] == "SRID=4326;POINT(29.72 11.01)" and chk["pending_review"] is False


def test_osm_kind_classification():
    from . import water_points

    assert water_points.classify({"man_made": "water_well"}) == "well"
    assert water_points.classify({"natural": "water", "water": "reservoir"}) == "dam"
    assert water_points.classify({"natural": "water"}) == "pond"
