"""Sentinel-2 L2A surface water for the pilot area, via Copernicus Data Space (CDSE).

Water is where MNDWI = (B03 - B11) / (B03 + B11) > 0 on pixels the scene
classification (SCL) calls vegetation, bare, water or unclassified. The 20 m
bands are aggregated to 60 m blocks, then to the 0.05° map grid and to a
500 m buffer around each mapped water point.
"""

import os
import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import urljoin, urlparse

import numpy as np
import requests

from .geo import BinGrid, bounds, grid_row, masked_stats, rows_from_stats

ODATA = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD = "https://download.dataspace.copernicus.eu/odata/v1/Products({pid})"
TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
MAX_CLOUD = 60.0  # per-product cloud cover limit, percent
BLOCK = 3  # 20 m pixels per block edge -> 60 m
MIN_VALID_PIXELS = 4  # of 9 in a block
BUFFER_M = 500
SCL_VALID = (4, 5, 6, 7)  # vegetation, not vegetated, water, unclassified
UA = {"User-Agent": "slewcis-ingest/1.0"}

_tok = {"value": None, "at": 0.0}


def token():
    """CDSE access token; they expire after 10 minutes, so refresh at 8."""
    if _tok["value"] and time.time() - _tok["at"] < 480:
        return _tok["value"]
    u, p = os.environ.get("CDSE_USERNAME"), os.environ.get("CDSE_PASSWORD")
    if not (u and p):
        raise RuntimeError("CDSE_USERNAME / CDSE_PASSWORD not set")
    r = requests.post(TOKEN_URL, data={"client_id": "cdse-public", "grant_type": "password",
                                       "username": u, "password": p}, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"CDSE login failed ({r.status_code}): {r.text[:200]}")
    _tok.update(value=r.json()["access_token"], at=time.time())
    return _tok["value"]


def _get(url, stream=False, timeout=600):
    """GET following redirects by hand so the token survives the hop to the download host."""
    for _ in range(8):
        headers = dict(UA)
        if urlparse(url).hostname.endswith("dataspace.copernicus.eu"):
            headers["Authorization"] = f"Bearer {token()}"
        r = requests.get(url, headers=headers, stream=stream, timeout=timeout, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and "location" in r.headers:
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"Too many redirects fetching {url}")


def search(area, since, until):
    """L2A products intersecting the area in the date range, oldest first."""
    west, south, east, north = bounds(area)
    poly = f"POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))"
    flt = (
        "Collection/Name eq 'SENTINEL-2' and "
        "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and "
        "att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
        f"OData.CSC.Intersects(area=geography'SRID=4326;{poly}') and "
        f"ContentDate/Start ge {since.isoformat()}T00:00:00.000Z and "
        f"ContentDate/Start le {until.isoformat()}T23:59:59.000Z and "
        "Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and "
        f"att/OData.CSC.DoubleAttribute/Value le {MAX_CLOUD})"
    )
    items, url, params = [], ODATA, {"$filter": flt, "$top": 200, "$orderby": "ContentDate/Start asc"}
    while url:
        r = requests.get(url, params=params, headers=UA, timeout=120)
        r.raise_for_status()
        body = r.json()
        items += body.get("value", [])
        url, params = body.get("@odata.nextLink"), None
    return [i for i in items if i.get("Online", True)]


def _children(nodes_url):
    return _get(nodes_url, timeout=120).json().get("result", [])


def band_urls(product_id):
    """URLs of the 20 m B03, B11 and SCL files inside a product, by walking its node tree."""
    root = _children(DOWNLOAD.format(pid=product_id) + "/Nodes")
    safe = root[0]
    granule_dir = next(n for n in _children(safe["Nodes"]["uri"]) if n["Name"] == "GRANULE")
    granule = _children(granule_dir["Nodes"]["uri"])[0]
    img = next(n for n in _children(granule["Nodes"]["uri"]) if n["Name"] == "IMG_DATA")
    r20 = next(n for n in _children(img["Nodes"]["uri"]) if n["Name"] == "R20m")
    files = {n["Name"]: n["Nodes"]["uri"].removesuffix("/Nodes") + "/$value" for n in _children(r20["Nodes"]["uri"])}
    out = {}
    for band in ("B03", "B11", "SCL"):
        name = next((n for n in files if f"_{band}_20m" in n), None)
        if not name:
            raise RuntimeError(f"{band} 20 m file missing in product {product_id}")
        out[band] = files[name]
    return out


def download(url, dest):
    with _get(url, stream=True) as r:
        if "text/html" in r.headers.get("content-type", ""):
            raise RuntimeError(f"CDSE returned an HTML page for {url}")
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


def water_blocks(green, swir, scl):
    """60 m water fraction (NaN where too cloudy) from 20 m arrays."""
    g = green.astype("float32")
    s = swir.astype("float32")
    valid = np.isin(scl, SCL_VALID) & ((g + s) > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        water = valid & ((g - s) / (g + s) > 0)
    n = (g.shape[0] // BLOCK) * BLOCK
    m = (g.shape[1] // BLOCK) * BLOCK
    v = valid[:n, :m].reshape(n // BLOCK, BLOCK, m // BLOCK, BLOCK).sum(axis=(1, 3))
    w = water[:n, :m].reshape(n // BLOCK, BLOCK, m // BLOCK, BLOCK).sum(axis=(1, 3))
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = w / v
    frac[v < MIN_VALID_PIXELS] = np.nan
    return frac.astype("float32")


def block_lonlat(transform, crs, shape):
    """Centre lon/lat of each 60 m block for a tile with the given 20 m transform."""
    from rasterio.warp import transform as warp

    rows, cols = np.indices(shape)
    x = transform.c + (cols * BLOCK + BLOCK / 2) * transform.a
    y = transform.f + (rows * BLOCK + BLOCK / 2) * transform.e
    lon, lat = warp(crs, "EPSG:4326", x.ravel().tolist(), y.ravel().tolist())
    return np.asarray(lon).reshape(shape), np.asarray(lat).reshape(shape), x, y


def point_fraction(frac, x, y, px, py):
    """Mean water fraction and valid share of blocks within BUFFER_M of (px, py) in tile CRS."""
    inside = (x - px) ** 2 + (y - py) ** 2 <= BUFFER_M**2
    if not inside.any():
        return None
    vals = frac[inside]
    finite = np.isfinite(vals)
    if not finite.any():
        return (None, 0.0, int(inside.sum()))
    return (float(vals[finite].mean()), float(finite.mean()), int(inside.sum()))


def s2_water(source, area, since, until, skip, workdir, water_points=()):
    """Yield (date, rows) with an area grid, area stats and per-water-point fractions."""
    import rasterio
    from rasterio.warp import transform as warp

    by_date = defaultdict(list)
    for item in search(area, since, until):
        d = datetime.fromisoformat(item["ContentDate"]["Start"].replace("Z", "+00:00")).date()
        if d not in skip:
            by_date[d].append(item)

    for d in sorted(by_date):
        bins = BinGrid(area)
        acc = {wp["id"]: [0.0, 0.0, 0] for wp in water_points}  # sum(frac*n), sum(valid*n), n
        for item in by_date[d]:
            urls = band_urls(item["Id"])
            paths = {b: download(u, os.path.join(workdir, f"{item['Id']}_{b}.jp2")) for b, u in urls.items()}
            try:
                with rasterio.open(paths["B03"]) as g, rasterio.open(paths["B11"]) as s, rasterio.open(paths["SCL"]) as c:
                    frac = water_blocks(g.read(1), s.read(1), c.read(1))
                    tr, crs = g.transform, g.crs
            finally:
                for p in paths.values():
                    try:
                        os.remove(p)
                    except OSError:
                        pass
            lon, lat, x, y = block_lonlat(tr, crs, frac.shape)
            bins.add(frac, lat, lon)
            if water_points:
                xs, ys = warp("EPSG:4326", crs, [wp["lon"] for wp in water_points], [wp["lat"] for wp in water_points])
                for wp, px, py in zip(water_points, xs, ys):
                    res = point_fraction(frac, x, y, px, py)
                    if res and res[0] is not None:
                        f, valid, n = res
                        a = acc[wp["id"]]
                        a[0] += f * n
                        a[1] += valid * n
                        a[2] += n
        grid = bins.grid()
        lat_rows = bins.north - (np.arange(bins.ny) + 0.5) * bins.res
        stats = masked_stats(grid["values"], np.broadcast_to(lat_rows[:, None], grid["values"].shape))
        rows = rows_from_stats(stats, d, "surface_water_fraction", "fraction", {
            "product": "S2MSI2A", "products": [i["Name"] for i in by_date[d]],
            "steps": ["MNDWI>0 on SCL-valid pixels", "60 m blocks", "0.05° bin mean"],
        })
        rows.append(grid_row(grid, d, "surface_water_fraction", "fraction"))
        for wp_id, (fs, vs, n) in acc.items():
            if n:
                rows.append({"_wp": True, "water_point_id": wp_id, "obs_date": d.isoformat(),
                             "water_fraction": round(fs / n, 4), "valid_fraction": round(vs / n, 4)})
        yield d, rows
