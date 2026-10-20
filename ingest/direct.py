"""Direct access to the data archives without NASA's CMR search service.

CMR's granule search has been returning 500s (even its /health endpoint). The
archives themselves publish listings (HTML at GES DISC, JSON at LAADS, plain
directories at CHC) and file names carry the date, so granules can be found
without CMR. NASA downloads authenticate with an Earthdata bearer token.
"""

import math
import os
import re
import time
from datetime import date, datetime, timedelta

import requests

UA = {"User-Agent": "slewcis-ingest/1.0"}
_session = None
_token = None


def _retry(fn, attempts=4):
    for i in range(attempts):
        try:
            return fn()
        except (requests.ConnectionError, requests.Timeout) as e:
            if i == attempts - 1:
                raise
            time.sleep(5 * 2**i)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code < 500 or i == attempts - 1:
                raise
            time.sleep(5 * 2**i)


def session():
    """requests session that follows the Earthdata (URS) redirect login."""
    global _session
    if _session is None:
        u, p = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
        if not (u and p):
            raise RuntimeError("EARTHDATA_USERNAME / EARTHDATA_PASSWORD not set")
        s = requests.Session()
        s.auth = (u, p)
        s.headers.update(UA)
        _session = s
    return _session


def token():
    """Earthdata bearer token, accepted by every NASA archive we use."""
    global _token
    if _token is None:
        import earthaccess

        auth = earthaccess.login(strategy="environment")
        if not auth or not auth.authenticated:
            raise RuntimeError("Earthdata login failed: check EARTHDATA_USERNAME / EARTHDATA_PASSWORD")
        _token = auth.token["access_token"]
    return _token


def list_dir(url, pattern, auth=False):
    """Sorted unique hrefs in an HTML directory listing that match pattern; [] on 404."""
    s = session() if auth else requests

    def get():
        r = s.get(url, timeout=120, headers=UA)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        names = set(re.findall(r'href="([^"?#/][^"?#]*)"', r.text))
        return sorted(n for n in names if re.search(pattern, n))

    return _retry(get)


def download(url, dest, nasa=True):
    """Stream url to dest. Fails loudly on an HTML login page instead of saving it."""
    headers = {**UA, **({"Authorization": f"Bearer {token()}"} if nasa else {})}

    def get():
        with requests.get(url, headers=headers, stream=True, timeout=900, allow_redirects=True) as r:
            if r.status_code == 404:
                return None
            r.raise_for_status()
            if "text/html" in r.headers.get("content-type", ""):
                raise RuntimeError(
                    f"{url} returned an HTML page, not data. The archive probably needs approval "
                    "under Authorized Apps in your Earthdata profile."
                )
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        return dest

    return _retry(get)


# ---------------------------------------------------------------------------
# GES DISC: <root>/<YYYY>/<MM>/<file>, with YYYYMMDD in the file name
# ---------------------------------------------------------------------------

GESDISC = {
    "GPM_3IMERGDL": "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/",
    "GLDAS_CLSM025_DA1_D": "https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_CLSM025_DA1_D.2.2/",
}


def months(since, until):
    y, m = since.year, since.month
    while (y, m) <= (until.year, until.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def gesdisc_files(product, since, until):
    """Yield (date, url) for daily files between since and until, oldest first."""
    root = GESDISC[product]
    for y, m in months(since, until):
        month_url = f"{root}{y}/{m:02d}/"
        for name in list_dir(month_url, r"\.nc4$", auth=True):
            md = re.search(r"(?<!\d)(20\d{6})(?!\d)", name)
            if not md:
                continue
            d = datetime.strptime(md.group(1), "%Y%m%d").date()
            if since <= d <= until:
                yield d, month_url + name


# ---------------------------------------------------------------------------
# LAADS: <root>/<product>/<YYYY>/<DDD>.json lists the day's files
# ---------------------------------------------------------------------------

LAADS = "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/"


def _laads_json(url):
    def get():
        r = requests.get(url, timeout=120, headers=UA)
        if r.status_code == 404:
            return []
        r.raise_for_status()
        payload = r.json()
        if isinstance(payload, dict):
            payload = payload.get("content") or payload.get("entries") or []
        return payload

    return _retry(get)


def laads_days(product, year):
    """Day-of-year folders that exist for product in year."""
    return sorted(int(e["name"]) for e in _laads_json(f"{LAADS}{product}/{year}.json") if e["name"].isdigit())


def laads_files(product, year, doy, tiles=None):
    names = [e["name"] for e in _laads_json(f"{LAADS}{product}/{year}/{doy:03d}.json") if e["name"].endswith(".hdf")]
    if tiles:
        names = [n for n in names if any(f".{t}." in n for t in tiles)]
    return [f"{LAADS}{product}/{year}/{doy:03d}/{n}" for n in sorted(names)]


def doy_to_date(year, doy):
    return date(year, 1, 1) + timedelta(days=doy - 1)


# MODIS sinusoidal tiling
_R, _T, _X0, _Y0 = 6371007.181, 1111950.5197665233, -20015109.355798, 10007554.677899


def modis_tiles(bounds, step=0.25):
    """Tile names (hHHvVV) that intersect a (west, south, east, north) box."""
    west, south, east, north = bounds
    tiles = set()
    lat = south
    while lat <= north + 1e-9:
        lon = west
        while lon <= east + 1e-9:
            x = _R * math.radians(lon) * math.cos(math.radians(lat))
            y = _R * math.radians(lat)
            tiles.add(f"h{int((x - _X0) // _T):02d}v{int((_Y0 - y) // _T):02d}")
            lon += step
        lat += step
    return sorted(tiles)


# ---------------------------------------------------------------------------
# LP DAAC cloud: ASTER GDEM tiles have deterministic names
# ---------------------------------------------------------------------------

ASTER_URL = "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ASTGTM.003/ASTGTMV003_{ns}{lat:02d}{ew}{lon:03d}_dem.tif"


def aster_tiles(bounds):
    west, south, east, north = bounds
    out = []
    for lat in range(math.floor(south), math.ceil(north)):
        for lon in range(math.floor(west), math.ceil(east)):
            out.append(ASTER_URL.format(ns="N" if lat >= 0 else "S", lat=abs(lat),
                                        ew="E" if lon >= 0 else "W", lon=abs(lon)))
    return out


# ---------------------------------------------------------------------------
# CHIRPS v3 daily (CHC, public): final/sat preferred, prelim/sat for recent days
# ---------------------------------------------------------------------------

CHIRPS3 = "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/"
# Candidate folders per year, tried in order; the first with dated files wins.
CHIRPS3_FINAL = ["final/sat/cogs/p05/{y}/", "final/sat/{y}/", "final/sat/p05/{y}/"]
CHIRPS3_PRELIM = ["prelim/sat/cogs/p05/{y}/", "prelim/sat/{y}/", "prelim/sat/p05/{y}/"]
_DATE_IN_NAME = re.compile(r"(\d{4})[.\-_](\d{2})[.\-_](\d{2})")


def _chirps3_year(candidates, year):
    for c in candidates:
        url = CHIRPS3 + c.format(y=year)
        names = list_dir(url, r"\.(tif|cog|tiff)$")
        files = {}
        for n in names:
            m = _DATE_IN_NAME.search(n)
            if m:
                files[date(*map(int, m.groups()))] = url + n
        if files:
            return files
    return {}


def chirps3_files(since, until):
    """{date: (url, 'final'|'prelim')} for days in range, final preferred."""
    out = {}
    for year in range(since.year, until.year + 1):
        for d, u in _chirps3_year(CHIRPS3_PRELIM, year).items():
            out[d] = (u, "prelim")
        for d, u in _chirps3_year(CHIRPS3_FINAL, year).items():
            out[d] = (u, "final")
    return {d: v for d, v in out.items() if since <= d <= until}
