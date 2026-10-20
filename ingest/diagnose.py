"""Print what the data servers actually serve. Runs on the GitHub runner, which can reach them."""

import json
import os
import re
import sys
from datetime import date

import requests

Y = date.today().year
UA = {"User-Agent": "slewcis-diagnose/1.0"}


def show(label, url, session=None, headers=None, head=False, body_chars=300):
    s = session or requests
    try:
        r = (s.head if head else s.get)(url, timeout=60, allow_redirects=True, headers={**UA, **(headers or {})})
        ctype = r.headers.get("content-type", "")
        body = r.text if (not head and ("text" in ctype or "json" in ctype)) else ""
        links = re.findall(r'href="([^"?#][^"]*)"', body)
        files = sorted(set(l for l in links if not l.startswith(("/", "http", "../"))))
        print(f"\n### {label}\n    {url}\n    HTTP {r.status_code}  type={ctype}  len={r.headers.get('content-length')}")
        if r.url != url:
            print(f"    final={r.url}")
        if r.status_code >= 400 and body:
            print("    body:", body[:body_chars].replace("\n", " "))
        elif files:
            print(f"    {len(files)} entries; first: {files[:4]}; last: {files[-4:]}")
        elif body:
            print("    text:", body[:body_chars].replace("\n", " "))
        return r
    except Exception as e:
        print(f"\n### {label}\n    {url}\n    ERROR {type(e).__name__}: {e}")


print("=" * 60, "\nCMR variants")
r = show("CMR collections", "https://cmr.earthdata.nasa.gov/search/collections.json?short_name=GPM_3IMERGDL&version=07")
cid = None
try:
    cid = r.json()["feed"]["entry"][0]["id"]
    print("    concept id:", cid)
except Exception:
    pass
show("CMR granules.json short_name", "https://cmr.earthdata.nasa.gov/search/granules.json?short_name=GPM_3IMERGDL&page_size=1")
show("CMR granules.umm_json short_name", "https://cmr.earthdata.nasa.gov/search/granules.umm_json?short_name=GPM_3IMERGDL&page_size=1")
show("CMR granules xml", "https://cmr.earthdata.nasa.gov/search/granules?short_name=GPM_3IMERGDL&page_size=1")
if cid:
    show("CMR granules by collection_concept_id", f"https://cmr.earthdata.nasa.gov/search/granules.json?collection_concept_id={cid}&page_size=1")
show("CMR-STAC GES_DISC root", "https://cmr.earthdata.nasa.gov/stac/GES_DISC")
show("CMR-STAC GPM items", "https://cmr.earthdata.nasa.gov/stac/GES_DISC/collections/GPM_3IMERGDL_7/items?limit=1", body_chars=600)
show("CMR-STAC LPCLOUD MOD13C1 items", "https://cmr.earthdata.nasa.gov/stac/LPCLOUD/collections/MOD13C1_061/items?limit=1", body_chars=600)

print("\n" + "=" * 60, "\nCHIRPS")
show("v2 readme", "https://data.chc.ucsb.edu/products/CHIRPS-2.0/README-CHIRPS.txt", body_chars=400)
for d in ["2026.03.31", "2026.04.01", "2026.04.15", "2026.06.30"]:
    show(f"v2 cog {d} HEAD", f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/cogs/p05/{Y}/chirps-v2.0.{d}.cog", head=True)
show("v2 prelim root", "https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/")
show("v2 prelim global_daily", "https://data.chc.ucsb.edu/products/CHIRPS-2.0/prelim/global_daily/")
show("v3 readme", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/readme.txt", body_chars=2500)


def descend(label, url, depth=4):
    """Follow the last subdirectory at each level to show the tree shape."""
    for _ in range(depth):
        r = show(label, url)
        if r is None or r.status_code != 200:
            return
        dirs = sorted(set(l for l in re.findall(r'href="([^"?#/][^"?#]*/)"', r.text) if not l.startswith("..")))
        if not dirs:
            return
        url += dirs[-1]


descend("v3 final/sat", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/sat/")
descend("v3 final/rnl", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/rnl/")
descend("v3 prelim/sat", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/sat/")

try:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rasterio==1.4.3"], check=True)
    import rasterio
    for d in ["2026.03.31", "2026.04.15"]:
        u = f"/vsicurl/https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/cogs/p05/{Y}/chirps-v2.0.{d}.cog"
        try:
            with rasterio.open(u) as src:
                print(f"\n### rasterio open v2 {d}: OK {src.width}x{src.height} {src.dtypes[0]} nodata={src.nodata} crs={src.crs}")
        except Exception as e:
            print(f"\n### rasterio open v2 {d}: FAILED {type(e).__name__}: {e}")
except Exception as e:
    print("rasterio check skipped:", e)

print("\n" + "=" * 60, "\nLAADS (MODIS without CMR)")
show("LAADS MOD13C1 years", "https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1.json", body_chars=400)
r = show("LAADS MOD13C1 2026 days", f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1/{Y}.json", body_chars=600)
show("LAADS MOD16A2 2026 days", f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD16A2/{Y}.json", body_chars=600)
show("LAADS MOD13C1 2026/257 files", f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1/{Y}/257.json", body_chars=800)
show("LAADS MOD16A2 2026/257 files (h20v07?)", f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD16A2/{Y}/257.json", body_chars=1200)

print("\n" + "=" * 60, "\nEARTHDATA-authenticated")
u, p = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
if not (u and p):
    print("No credentials; skipping")
    sys.exit(0)
auth = requests.Session()
auth.auth = (u, p)
show("GLDAS 2026/08 listing", "https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_CLSM025_DA1_D.2.2/2026/08/", auth)
show("GPM 2026/10 one file HEAD", "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/2026/10/3B-DAY-L.MS.MRG.3IMERG.20261018-S000000-E235959.V07C.nc4", auth, head=True)

try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "earthaccess==0.14.0"], check=True)
    import earthaccess
    a = earthaccess.login(strategy="environment")
    tok = a.token["access_token"]
    print("\nEDL token obtained:", bool(tok))
    bearer = {"Authorization": f"Bearer {tok}"}
    show("GPM file via bearer HEAD", "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/2026/10/3B-DAY-L.MS.MRG.3IMERG.20261018-S000000-E235959.V07C.nc4", headers=bearer, head=True)
    show("LP DAAC cloud ASTGTM N10E029 via bearer HEAD", "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/ASTGTM.003/ASTGTMV003_N10E029_dem.tif", headers=bearer, head=True)
    show("LP DAAC cloud MOD13C1 dir", "https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/MOD13C1.061/", headers=bearer)
    show("PO.DAAC cumulus GRACE dir", "https://archive.podaac.earthdata.nasa.gov/podaac-ops-cumulus-protected/TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4/", headers=bearer)
    # LAADS download with bearer: find a real MOD13C1 file name first
    try:
        files = requests.get(f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1/{Y}/257.json", timeout=60).json()
        files = files.get("content", files) if isinstance(files, dict) else files
        name = next(e["name"] for e in files if e["name"].endswith(".hdf"))
        show("LAADS MOD13C1 file via bearer HEAD", f"https://ladsweb.modaps.eosdis.nasa.gov/archive/allData/61/MOD13C1/{Y}/257/{name}", headers=bearer, head=True)
    except Exception as e:
        print("LAADS file probe skipped:", e)
except Exception as e:
    print("earthaccess/token step failed:", type(e).__name__, e)
