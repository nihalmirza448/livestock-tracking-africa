"""Offline tests: each adapter is fed synthetic files in the real product format.

    python -m pytest ingest  (or)  python -m ingest.test_adapters
"""

import os
import tempfile
from datetime import date

import numpy as np

from . import adapters, run
from .geo import grid_stats, sinusoidal_latlon

AREA = {"id": "south_kordofan", "min_lon": 29.0, "min_lat": 9.3, "max_lon": 32.4, "max_lat": 12.7, "buffer_deg": 0.25}


def src(key, product="P", version="1", auth="earthdata"):
    return {"key": key, "product": product, "product_version": version, "enabled": True, "auth": auth}


def granule(start, end=None, name="g"):
    rng = {"BeginningDateTime": f"{start}T00:00:00Z"}
    if end:
        rng["EndingDateTime"] = f"{end}T23:59:59Z"
    return {"umm": {"TemporalExtent": {"RangeDateTime": rng}}, "meta": {"native-id": name}}


def fake_earthaccess(monkey_files):
    """Point the adapters' search/download at local files: {granule_name: path}."""
    granules = list(monkey_files)
    adapters._search = lambda source, area, since, until: [g for g, _ in granules]
    adapters._download = lambda gs, workdir: [p for g, p in granules if any(g is x for x in gs)]
    adapters._remove = lambda paths: None


def test_grid_stats_weights_and_clip():
    lats = np.arange(-89.5, 90, 1.0)
    lons = np.arange(0.5, 360, 1.0)  # 0..360 convention
    field = np.zeros((lats.size, lons.size))
    field[(lats > 9) & (lats < 13)][:, :] = 0
    lat_in = (lats >= 9.05) & (lats <= 12.95)
    lon_in = (lons >= 28.75) & (lons <= 32.65)
    field[np.ix_(lat_in, lon_in)] = 5.0
    s = grid_stats(field, lats, lons, AREA)
    assert abs(s["mean"] - 5.0) < 1e-9 and s["valid_fraction"] == 1.0


def test_sinusoidal_tile_h20v07_covers_south_kordofan():
    lat, lon = sinusoidal_latlon(20, 7, 2400)
    assert abs(lat[0, 0] - 20) < 0.01 and abs(lat[-1, 0] - 10) < 0.01
    inside = (lat > 10) & (lat < 12.7) & (lon > 29) & (lon < 32.4)
    assert inside.any()


def _nc(path, var, values, lats, lons, time="2026-10-18"):
    import xarray as xr

    xr.Dataset({var: (("time", "lat", "lon"), values[None])},
               coords={"time": [np.datetime64(time)], "lat": lats, "lon": lons}).to_netcdf(path)


def test_gpm_imerg():
    with tempfile.TemporaryDirectory() as d:
        import xarray as xr

        lats, lons = np.arange(-89.95, 90, 0.1), np.arange(-179.95, 180, 0.1)
        p = os.path.join(d, "imerg.nc4")
        # IMERG stores (time, lon, lat)
        xr.Dataset({"precipitation": (("time", "lon", "lat"), np.full((1, lons.size, lats.size), 3.0, "f4"))},
                   coords={"time": [np.datetime64("2026-10-18")], "lat": lats, "lon": lons}).to_netcdf(p)
        g = granule("2026-10-18")
        fake_earthaccess([(g, p)])
        out = list(adapters.gpm_imerg(src("gpm_imerg"), AREA, date(2026, 10, 10), date(2026, 10, 20), set(), d))
        assert len(out) == 1
        mean = next(r for r in out[0][1] if r["stat"] == "mean")
        assert abs(mean["value"] - 3.0) < 1e-6 and mean["unit"] == "mm/day"


def test_gldas_converts_temperature():
    with tempfile.TemporaryDirectory() as d:
        import xarray as xr

        lats, lons = np.arange(-59.875, 90, 0.25), np.arange(-179.875, 180, 0.25)
        shape = (1, lats.size, lons.size)
        ds = xr.Dataset({v: (("time", "lat", "lon"), np.full(shape, val, "f4")) for v, val in
                         [("SoilMoist_S_tavg", 10.0), ("SoilMoist_RZ_tavg", 200.0),
                          ("GWS_tavg", 500.0), ("Tair_f_tavg", 303.15)]},
                        coords={"time": [np.datetime64("2026-06-01")], "lat": lats, "lon": lons})
        p = os.path.join(d, "gldas.nc4")
        ds.to_netcdf(p)
        fake_earthaccess([(granule("2026-06-01"), p)])
        (_, rows), = adapters.gldas_clsm(src("gldas_clsm"), AREA, date(2026, 5, 1), date(2026, 7, 1), set(), d)
        t = next(r for r in rows if r["variable"] == "air_temperature" and r["stat"] == "mean")
        assert abs(t["value"] - 30.0) < 1e-4 and t["unit"] == "degC"


def test_grace_skips_stored_months():
    with tempfile.TemporaryDirectory() as d:
        import xarray as xr

        lats, lons = np.arange(-89.75, 90, 0.5), np.arange(0.25, 360, 0.5)
        times = np.array(["2026-07-16", "2026-08-16"], dtype="datetime64[ns]")
        p = os.path.join(d, "grace.nc")
        xr.Dataset({"lwe_thickness": (("time", "lat", "lon"), np.full((2, lats.size, lons.size), -4.0, "f4"))},
                   coords={"time": times, "lat": lats, "lon": lons}).to_netcdf(p)
        fake_earthaccess([(granule("2002-04-01"), p)])
        out = list(adapters.grace_mascon(src("grace_mascon"), AREA, date(2026, 1, 1), date(2026, 10, 1),
                                         {date(2026, 7, 16)}, d))
        assert [o[0] for o in out] == [date(2026, 8, 16)]


def _hdf4(path, name, data):
    from pyhdf.SD import SD, SDC

    hdf = SD(path, SDC.WRITE | SDC.CREATE)
    sds = hdf.create(name, SDC.INT16, data.shape)
    sds[:] = data
    sds.endaccess()
    hdf.end()


def test_modis_ndvi():
    with tempfile.TemporaryDirectory() as d:
        raw = np.full((3600, 7200), 4000, "i2")
        raw[1546, 4200] = -3000  # fill value inside the area is ignored
        p = os.path.join(d, "MOD13C1.A2026273.061.hdf")
        _hdf4(p, "CMG 0.05 Deg 16 days NDVI", raw)
        fake_earthaccess([(granule("2026-09-30", "2026-10-15"), p)])
        (_, rows), = adapters.modis_ndvi(src("modis_ndvi"), AREA, date(2026, 9, 1), date(2026, 10, 20), set(), d)
        mean = next(r for r in rows if r["stat"] == "mean")
        assert abs(mean["value"] - 0.4) < 1e-6 and mean["period_end"] == "2026-10-15"


def test_modis_et_mosaics_tiles():
    with tempfile.TemporaryDirectory() as d:
        files = []
        for tile, val in [("h20v07", 100), ("h20v08", 300)]:
            p = os.path.join(d, f"MOD16A2.A2026273.{tile}.061.hdf")
            raw = np.full((2400, 2400), val, "i2")
            raw[:10, :10] = 32767  # fill class
            _hdf4(p, "ET_500m", raw)
            files.append((granule("2026-09-30", "2026-10-07", tile), p))
        fake_earthaccess(files)
        (_, rows), = adapters.modis_et(src("modis_et"), AREA, date(2026, 9, 1), date(2026, 10, 20), set(), d)
        stats = {r["stat"]: r["value"] for r in rows}
        assert stats["min"] == 10.0 and stats["max"] == 30.0  # scaled by 0.1, both tiles present


def test_chirps_window_read():
    import rasterio
    from rasterio.transform import from_origin

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "chirps-v2.0.2026.10.01.tif")
        data = np.full((2000, 7200), 2.5, "f4")
        with rasterio.open(p, "w", driver="GTiff", width=7200, height=2000, count=1, dtype="float32",
                           crs="EPSG:4326", transform=from_origin(-180, 50, 0.05, 0.05), nodata=-9999) as dst:
            dst.write(data, 1)
        adapters.CHIRPS_URL = os.path.join(d, "chirps-v2.0.{y}.{m:02d}.{d:02d}.tif")
        out = list(adapters.chirps(src("chirps", auth="none"), AREA, date(2026, 10, 1), date(2026, 10, 2), set(), d))
        assert [o[0] for o in out] == [date(2026, 10, 1)]  # 2 Oct missing -> skipped, not failed
        assert abs(next(r for r in out[0][1] if r["stat"] == "mean")["value"] - 2.5) < 1e-6


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

    def stored_dates(self, key, area_id, since):
        return set()

    def write_observations(self, rows):
        self.rows += rows
        return len(rows)


def test_runner_records_partial_failure():
    def flaky(source, area, since, until, skip, workdir):
        yield date(2026, 10, 1), [{"obs_date": "2026-10-01", "variable": "v", "stat": "mean", "value": 1}]
        raise OSError("corrupt granule")

    run.ADAPTERS["flaky"] = (flaky, 5, False)
    store = FakeStore()
    assert run.run_source(store, "flaky", AREA, None, "test") is False
    status, requested, written, _ = store.runs[1]
    assert (status, requested, written) == ("partial", 1, 1)
    assert store.rows[0]["dataset_version_id"] == 7 and store.rows[0]["run_id"] == 1


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("ok", t.__name__)
