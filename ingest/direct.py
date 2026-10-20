"""Direct access to NASA archives without the CMR search service.

CMR's granule search has been returning 500s. The archives themselves publish
directory listings (GES DISC) or JSON listings (LAADS), and file names carry the
date, so we can find granules without CMR. Downloads authenticate with the
Earthdata login from the environment.
"""

import os
import re
from datetime import date, datetime

import requests

_session = None


def session():
    """requests session that follows the Earthdata (URS) redirect login."""
    global _session
    if _session is None:
        u, p = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
        if not (u and p):
            raise RuntimeError("EARTHDATA_USERNAME / EARTHDATA_PASSWORD not set")
        s = requests.Session()
        s.auth = (u, p)
        s.headers["User-Agent"] = "slewcis-ingest/1.0"
        _session = s
    return _session


def token():
    """Earthdata bearer token, for archives that want a header instead of a redirect."""
    import earthaccess

    auth = earthaccess.login(strategy="environment")
    if not auth or not auth.authenticated:
        raise RuntimeError("Earthdata login failed: check EARTHDATA_USERNAME / EARTHDATA_PASSWORD")
    return auth.token["access_token"]


def list_dir(url, pattern, auth=True):
    """Return sorted unique hrefs in an HTML directory listing that match pattern."""
    s = session() if auth else requests
    r = s.get(url, timeout=120)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    names = set(re.findall(r'href="([^"?#/][^"?#]*)"', r.text))
    return sorted(n for n in names if re.search(pattern, n))


def download(url, dest, bearer=None):
    """Stream url to dest. Fails loudly on an HTML login page instead of saving it."""
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    s = requests if bearer else session()
    with s.get(url, headers=headers, stream=True, timeout=600, allow_redirects=True) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "text/html" in ctype:
            raise RuntimeError(
                f"{url} returned an HTML page, not data. The archive probably needs approval under "
                "Authorized Apps in your Earthdata profile."
            )
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return dest


# ---------------------------------------------------------------------------
# GES DISC: /data/<path>/<YYYY>/<MM>/<file>  with YYYYMMDD in the file name
# ---------------------------------------------------------------------------

GESDISC = {
    "GPM_3IMERGDL": "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/",
    "GLDAS_CLSM025_DA1_D": "https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_CLSM025_DA1_D.2.2/",
}


def _months(since, until):
    y, m = since.year, since.month
    while (y, m) <= (until.year, until.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def gesdisc_files(product, since, until):
    """Yield (date, url) for daily files between since and until, newest last."""
    root = GESDISC[product]
    for y, m in _months(since, until):
        month_url = f"{root}{y}/{m:02d}/"
        for name in list_dir(month_url, r"\.nc4$"):
            md = re.search(r"(?<!\d)(20\d{6})(?!\d)", name)
            if not md:
                continue
            d = datetime.strptime(md.group(1), "%Y%m%d").date()
            if since <= d <= until:
                yield d, month_url + name


# ---------------------------------------------------------------------------
# LAADS: /archive/allData/<collection>/<product>/<YYYY>/<DDD>.json
# ---------------------------------------------------------------------------

LAADS = "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/"


def laads_days(product, year):
    """Day-of-year folders that exist for product in year."""
    r = requests.get(f"{LAADS}{product}/{year}.json", timeout=120)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return sorted(int(e["name"]) for e in _laads_entries(r.json()) if e["name"].isdigit())


def laads_files(product, year, doy, tile=None):
    r = requests.get(f"{LAADS}{product}/{year}/{doy:03d}.json", timeout=120)
    r.raise_for_status()
    names = [e["name"] for e in _laads_entries(r.json()) if e["name"].endswith(".hdf")]
    if tile:
        names = [n for n in names if f".{tile}." in n]
    return [f"{LAADS}{product}/{year}/{doy:03d}/{n}" for n in sorted(names)]


def _laads_entries(payload):
    # LAADS has returned both a bare list and {"content": [...]} over time.
    if isinstance(payload, dict):
        payload = payload.get("content") or payload.get("entries") or []
    return payload


def doy_to_date(year, doy):
    return date.fromordinal(date(year, 1, 1).toordinal() + doy - 1)
