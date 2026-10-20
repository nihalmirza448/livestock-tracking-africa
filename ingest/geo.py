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
