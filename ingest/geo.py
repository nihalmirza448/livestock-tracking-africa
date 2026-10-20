"""Clip gridded data to the pilot area and reduce it to area statistics."""

import numpy as np


def bounds(area):
    b = area["buffer_deg"]
    return (area["min_lon"] - b, area["min_lat"] - b, area["max_lon"] + b, area["max_lat"] + b)


def grid_stats(values, lats, lons, area, scale=1.0, offset=0.0, valid_range=None, fill=None):
    """Area statistics for a 2-D field on a lat/lon grid.

    values has shape (len(lats), len(lons)). lons may be 0..360. The mean is
    weighted by cos(latitude) so cells are counted by area.
    """
    west, south, east, north = bounds(area)
    lons = np.where(np.asarray(lons) > 180, np.asarray(lons) - 360, lons)
    lat_mask = (np.asarray(lats) >= south) & (np.asarray(lats) <= north)
    lon_mask = (lons >= west) & (lons <= east)
    sub = np.asarray(values, dtype="float64")[np.ix_(lat_mask, lon_mask)]
    sub_lats = np.asarray(lats)[lat_mask]
    return masked_stats(sub, np.broadcast_to(sub_lats[:, None], sub.shape), scale, offset, valid_range, fill)


def masked_stats(raw, lat_grid, scale=1.0, offset=0.0, valid_range=None, fill=None):
    raw = np.asarray(raw, dtype="float64")
    valid = np.isfinite(raw)
    if fill is not None:
        valid &= raw != fill
    if valid_range is not None:
        valid &= (raw >= valid_range[0]) & (raw <= valid_range[1])
    total = raw.size
    if total == 0:
        raise ValueError("Pilot area does not overlap the grid")
    if not valid.any():
        return {"mean": None, "min": None, "max": None, "valid_fraction": 0.0}
    v = raw[valid] * scale + offset
    w = np.cos(np.deg2rad(np.asarray(lat_grid)[valid]))
    return {
        "mean": float(np.average(v, weights=w)),
        "min": float(v.min()),
        "max": float(v.max()),
        "valid_fraction": float(valid.sum() / total),
    }


def rows_from_stats(stats, obs_date, variable, unit, processing, period_end=None):
    out = []
    for stat, value in stats.items():
        out.append({
            "obs_date": obs_date.isoformat(),
            "period_end": period_end.isoformat() if period_end else None,
            "variable": variable,
            "stat": stat,
            "value": value,
            "unit": "fraction" if stat == "valid_fraction" else unit,
            "processing": processing,
        })
    return out


# MODIS sinusoidal grid (tiles are 10° x 10° at the equator).
SIN_R = 6371007.181
SIN_TILE = 1111950.5197665233
SIN_X0 = -20015109.355798
SIN_Y0 = 10007554.677899


def sinusoidal_latlon(h, v, size):
    """Pixel-centre latitude/longitude grids for MODIS tile hHHvVV of size x size pixels."""
    px = SIN_TILE / size
    x = SIN_X0 + h * SIN_TILE + (np.arange(size) + 0.5) * px
    y = SIN_Y0 - v * SIN_TILE - (np.arange(size) + 0.5) * px
    xx, yy = np.meshgrid(x, y)
    lat = np.rad2deg(yy / SIN_R)
    with np.errstate(divide="ignore", invalid="ignore"):
        lon = np.rad2deg(xx / (SIN_R * np.cos(np.deg2rad(lat))))
    return lat, lon


# ---------------------------------------------------------------------------
# Grids for the map: one regular lat/lon raster per (source, variable, date),
# rows running north to south, columns west to east.
# ---------------------------------------------------------------------------

def regular_grid(values, lats, lons, area, scale=1.0, offset=0.0, valid_range=None, fill=None):
    """Clip a regular lat/lon field to the area box at native resolution."""
    west, south, east, north = bounds(area)
    lats = np.asarray(lats, dtype="float64")
    lons = np.asarray(lons, dtype="float64")
    values = np.asarray(values, dtype="float64")
    lons = np.where(lons > 180, lons - 360, lons)
    order = np.argsort(lons)
    lons, values = lons[order], values[:, order]
    if lats[0] < lats[-1]:
        lats, values = lats[::-1], values[::-1]
    lat_mask = (lats >= south) & (lats <= north)
    lon_mask = (lons >= west) & (lons <= east)
    sub = values[np.ix_(lat_mask, lon_mask)]
    if sub.size == 0:
        raise ValueError("Pilot area does not overlap the grid")
    sub_lats, sub_lons = lats[lat_mask], lons[lon_mask]
    valid = np.isfinite(sub)
    if fill is not None:
        valid &= sub != fill
    if valid_range is not None:
        valid &= (sub >= valid_range[0]) & (sub <= valid_range[1])
    out = np.where(valid, sub * scale + offset, np.nan)
    dy = abs(float(lats[1] - lats[0]))
    dx = abs(float(lons[1] - lons[0]))
    return {"nx": int(len(sub_lons)), "ny": int(len(sub_lats)),
            "west": float(sub_lons[0] - dx / 2), "south": float(sub_lats[-1] - dy / 2),
            "dx": dx, "dy": dy, "values": out}


class BinGrid:
    """Average arbitrary (value, lat, lon) samples into a fixed-resolution grid over the area.

    Used for products whose native grid is not lat/lon (MODIS sinusoidal tiles) or is
    far finer than needed (30 m ASTER). Samples outside the box are ignored.
    """

    def __init__(self, area, res=0.05):
        west, south, east, north = bounds(area)
        self.west, self.south, self.res = west, south, res
        self.nx = int(round((east - west) / res))
        self.ny = int(round((north - south) / res))
        self.north = south + self.ny * res
        self.sum = np.zeros(self.nx * self.ny)
        self.cnt = np.zeros(self.nx * self.ny)

    def add(self, values, lats, lons):
        """values, lats, lons broadcast to one shape; NaN values are skipped."""
        shape = np.shape(values)
        v = np.asarray(values, dtype="float64").ravel()
        la = np.broadcast_to(np.asarray(lats, dtype="float64"), shape).ravel()
        lo = np.broadcast_to(np.asarray(lons, dtype="float64"), shape).ravel()
        col = np.floor((lo - self.west) / self.res).astype("int64")
        row = np.floor((self.north - la) / self.res).astype("int64")
        inside = np.isfinite(v) & (col >= 0) & (col < self.nx) & (row >= 0) & (row < self.ny)
        idx = row[inside] * self.nx + col[inside]
        np.add.at(self.sum, idx, v[inside])
        np.add.at(self.cnt, idx, 1)

    def grid(self):
        with np.errstate(invalid="ignore", divide="ignore"):
            vals = self.sum / self.cnt
        vals[self.cnt == 0] = np.nan
        return {"nx": self.nx, "ny": self.ny, "west": self.west, "south": self.south,
                "dx": self.res, "dy": self.res, "values": vals.reshape(self.ny, self.nx)}


def window_grid(data, transform, nodata, area, **kw):
    """Grid dict for a rasterio window read (data is the window's 2-D array)."""
    rows = np.arange(data.shape[0]) + 0.5
    cols = np.arange(data.shape[1]) + 0.5
    lats = transform.f + rows * transform.e
    lons = transform.c + cols * transform.a
    return regular_grid(data, lats, lons, area, fill=nodata, **kw)


def grid_row(grid, obs_date, variable, unit, period_end=None, decimals=4):
    """Serialisable eo_grids row. The runner strips the _grid marker."""
    vals = np.asarray(grid["values"], dtype="float64").ravel()
    return {
        "_grid": True,
        "obs_date": obs_date.isoformat(),
        "period_end": period_end.isoformat() if period_end else None,
        "variable": variable,
        "unit": unit,
        "nx": grid["nx"], "ny": grid["ny"],
        "west": round(grid["west"], 6), "south": round(grid["south"], 6),
        "dx": round(grid["dx"], 6), "dy": round(grid["dy"], 6),
        "values": [None if not np.isfinite(v) else round(float(v), decimals) for v in vals],
    }
