"""Print what the data servers actually serve. Runs on the GitHub runner, which can reach them."""

import os
import re
import sys
from datetime import date

import requests

Y = date.today().year
M = date.today().month

PUBLIC = [
    ("CMR anon granules.json", f"https://cmr.earthdata.nasa.gov/search/granules.json?short_name=GPM_3IMERGDL&page_size=1"),
    ("CMR anon collections", "https://cmr.earthdata.nasa.gov/search/collections.json?short_name=GPM_3IMERGDL"),
    ("CMR health", "https://cmr.earthdata.nasa.gov/search/health"),
    ("CMR via client-id", f"https://cmr.earthdata.nasa.gov/search/granules.json?short_name=GPM_3IMERGDL&page_size=1&client_id=slewcis"),
    ("CHIRPS v2 cogs 2026", f"https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/cogs/p05/{Y}/"),
    ("CHIRPS v3 daily", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/"),
    ("CHIRPS v3 daily final", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/"),
    ("CHIRPS v3 daily final global p05", f"https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/global/p05/"),
    ("CHIRPS v3 daily final global p05 year", f"https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/final/global/p05/{Y}/"),
    ("CHIRPS v3 daily prelim", "https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/"),
    ("CHIRPS v3 daily prelim global p05 year", f"https://data.chc.ucsb.edu/products/CHIRPS/v3.0/daily/prelim/global/p05/{Y}/"),
    ("LPDAAC MOD13C1 root", "https://e4ftl01.cr.usgs.gov/MOLT/MOD13C1.061/"),
    ("LPDAAC MOD16A2 root", "https://e4ftl01.cr.usgs.gov/MOLT/MOD16A2.061/"),
    ("HWSD2 zip (head)", "https://s3.eu-west-1.amazonaws.com/data.gaezdev.aws.fao.org/HWSD/HWSD2_RASTER.zip"),
]

AUTH = [
    ("GES DISC GPM IMERG DL root", "https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/"),
    ("GES DISC GPM IMERG DL this month", f"https://gpm1.gesdisc.eosdis.nasa.gov/data/GPM_L3/GPM_3IMERGDL.07/{Y}/{M:02d}/"),
    ("GES DISC GLDAS CLSM root", "https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_CLSM025_DA1_D.2.2/"),
    ("GES DISC GLDAS CLSM this year", f"https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_CLSM025_DA1_D.2.2/{Y}/"),
    ("PODAAC GRACE mascon listing", "https://podaac-tools.jpl.nasa.gov/drive/files/allData/tellus/L3/mascon/RL06.3/JPL/CRI/netcdf/"),
    ("LPDAAC ASTGTM root", "https://e4ftl01.cr.usgs.gov/ASTT/ASTGTM.003/"),
]


def show(label, url, session):
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
        body = r.text if "text" in r.headers.get("content-type", "") or "json" in r.headers.get("content-type", "") else ""
        links = re.findall(r'href="([^"?#][^"]*)"', body)
        files = [l for l in links if not l.startswith(("/", "http", "../"))]
        print(f"\n### {label}\n    {url}\n    HTTP {r.status_code}  final={r.url}  type={r.headers.get('content-type')}")
        if r.status_code >= 400 and body:
            print("    body:", body[:300].replace("\n", " "))
        if files:
            print(f"    {len(files)} entries; first: {files[:4]}; last: {files[-5:]}")
        elif body:
            print("    text:", body[:300].replace("\n", " "))
    except Exception as e:
        print(f"\n### {label}\n    {url}\n    ERROR {type(e).__name__}: {e}")


anon = requests.Session()
anon.headers["User-Agent"] = "slewcis-diagnose/1.0"
print("=" * 60, "\nPUBLIC endpoints")
for label, url in PUBLIC:
    show(label, url, anon)

print("\n" + "=" * 60, "\nEARTHDATA-authenticated endpoints")
u, p = os.environ.get("EARTHDATA_USERNAME"), os.environ.get("EARTHDATA_PASSWORD")
if not (u and p):
    print("No EARTHDATA_USERNAME/PASSWORD; skipping")
    sys.exit(0)
auth = requests.Session()
auth.auth = (u, p)
auth.headers["User-Agent"] = "slewcis-diagnose/1.0"
# URS redirect flow: first request bounces to urs.earthdata.nasa.gov, which accepts basic auth.
for label, url in AUTH:
    show(label, url, auth)
