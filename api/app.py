"""
Nearest-location recommender over a road network on a 1x1 grid.

Route:  /search/   (GET or POST)
Fields: lat, long, cat, rad, link
  - lat, long : current position
  - cat       : category to search for (bank, cafe, ...)
  - rad       : search radius (straight-line / circular distance from lat,long)
  - link      : road linkage .txt ("a b" per line = road between IDs a and b).
                Accepted as an uploaded file (multipart), raw text, a URL,
                or a filename that exists on the server.

Ranking: shortest-path (road/grid) distance computed with Dijkstra over the
link graph, restricted to locations of category `cat` that lie inside the
circle of radius `rad` around (lat, long). Returns the 10 closest IDs.
"""

import csv
import heapq
import math
import os
import urllib.request
from functools import lru_cache

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.environ.get("LOCATIONS_CSV", os.path.join(BASE, "locations.csv"))
# Folder of link files that can be referred to by name (a Docker volume in the container)
LINK_DIR = os.environ.get("LINK_DIR", os.path.join(BASE, "data"))
K = 10
EPS = 1e-9

# ---------------------------------------------------------------- data load
ids, lats, lons, cats = [], [], [], []
with open(CSV_PATH, newline="") as f:
    for row in csv.DictReader(f):
        ids.append(int(row["ID"]))
        lats.append(float(row["Latitude"]))
        lons.append(float(row["Longitude"]))
        cats.append(row["Category"].strip().lower())

N = len(ids)
IDS = np.array(ids)
LAT = np.array(lats)
LON = np.array(lons)
CAT = np.array(cats)
ID_TO_IDX = {v: i for i, v in enumerate(ids)}
MAX_ID = max(ids)

# Integer grid coordinates (row, col). The CSV rounds coords to 6 decimals,
# so road lengths are measured in exact grid units to keep true ties exact.
SIDE = int(round(math.sqrt(N)))
STEP = 1.0 / (SIDE - 1)
ROW = np.rint(LAT / STEP).astype(int)
COL = np.rint(LON / STEP).astype(int)


# ------------------------------------------------------------- graph build
def default_grid_links():
    """Fallback when no link file is given: full 4-neighbour grid."""
    lines = []
    for r in range(SIDE):
        for c in range(SIDE):
            a = r * SIDE + c + 1
            if c + 1 < SIDE:
                lines.append(f"{a} {a + 1}")
            if r + 1 < SIDE:
                lines.append(f"{a} {a + SIDE}")
    return "\n".join(lines)


@lru_cache(maxsize=32)
def build_graph(text: str):
    """Adjacency list [(neighbour_idx, edge_length), ...] per node.
    Edge length = Euclidean length of the road segment in grid units
    (1 for neighbouring points)."""
    pairs = []
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            pairs.append((int(float(parts[0])), int(float(parts[1]))))
        except ValueError:
            continue  # header / junk line

    # Detect 0-based IDs (0 present, max ID never used)
    flat = [x for p in pairs for x in p]
    offset = 1 if flat and min(flat) == 0 and max(flat) < MAX_ID else 0

    adj = [[] for _ in range(N)]
    for a, b in pairs:
        ia, ib = ID_TO_IDX.get(a + offset), ID_TO_IDX.get(b + offset)
        if ia is None or ib is None or ia == ib:
            continue
        w = math.hypot(int(ROW[ia] - ROW[ib]), int(COL[ia] - COL[ib]))
        adj[ia].append((ib, w))
        adj[ib].append((ia, w))
    return adj


# ----------------------------------------------------------------- search
def search(lat, lon, cat, rad, adj):
    eu = np.hypot(LAT - lat, LON - lon)
    targets = set(np.nonzero((CAT == cat) & (eu <= rad + EPS))[0].tolist())
    if not targets:
        return []

    # start from the grid node(s) nearest to the current position; if the
    # point sits exactly between several nodes, all of them are sources
    srcs = np.nonzero(eu <= eu.min() + 1e-6)[0].tolist()
    start = 0.0

    dist = {s: start for s in srcs}
    heap = [(start, s) for s in srcs]
    found = []
    done = set()
    while heap and len(found) < K:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u in targets:
            found.append((d, u))
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, math.inf) - 1e-12:
                dist[v] = nd
                heapq.heappush(heap, (nd, v))

    # Drain ties at the boundary so tie-breaking is deterministic
    if len(found) == K:
        last = found[-1][0]
        while heap and heap[0][0] <= last + 1e-12:
            d, u = heapq.heappop(heap)
            if u in done:
                continue
            done.add(u)
            if u in targets:
                found.append((d, u))
            for v, w in adj[u]:
                nd = d + w
                if nd < dist.get(v, math.inf) - 1e-12:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))

    # tie-break: road distance, then straight-line distance, then ID
    found.sort(key=lambda t: (round(t[0], 9), round(float(eu[t[1]]), 5), IDS[t[1]]))
    result = [(d, u, True) for d, u in found[:K]]

    # Fallback: if the network can't reach K targets, fill by straight line
    if len(result) < K:
        got = {u for _, u, _ in result}
        rest = sorted((t for t in targets if t not in got),
                      key=lambda t: (eu[t], IDS[t]))
        result += [(math.inf, u, False) for u in rest[: K - len(result)]]

    return [
        {
            "id": int(IDS[u]),
            "lat": float(LAT[u]),
            "long": float(LON[u]),
            "category": str(CAT[u]),
            "grid_distance": None if math.isinf(d) else round(d * STEP, 6),
            "hops": None if math.isinf(d) else round(d, 6),
            "radial_distance": round(float(eu[u]), 6),
            "reachable": ok,
        }
        for d, u, ok in result
    ]


# -------------------------------------------------------------------- API
app = FastAPI(title="Nearest Location Recommender")


async def read_link(value) -> str:
    if value is None or value == "":
        return default_grid_links()
    if hasattr(value, "read"):  # UploadFile
        data = await value.read()
        return data.decode("utf-8", errors="ignore")
    s = str(value).strip()
    if s.startswith(("http://", "https://")):
        with urllib.request.urlopen(s, timeout=20) as r:
            return r.read().decode("utf-8", errors="ignore")
    for p in (s, os.path.join(BASE, s), os.path.join(LINK_DIR, s)):
        if "\n" not in s and len(s) < 512 and os.path.isfile(p):
            with open(p) as f:
                return f.read()
    return s.replace("\\n", "\n").replace(";", "\n")  # raw text


def pick(params, *names):
    for n in names:
        if n in params and params[n] not in (None, ""):
            return params[n]
    return None


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"status": "ok", "locations": N, "usage": "/search/?lat=&long=&cat=&rad=&link=", "ui": "/ui"}


@app.get("/ui", include_in_schema=False)
def ui():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.api_route("/search", methods=["GET", "POST"], include_in_schema=False)
@app.api_route("/search/", methods=["GET", "POST"])
async def search_endpoint(request: Request):
    params = dict(request.query_params)
    if request.method == "POST":
        ctype = request.headers.get("content-type", "")
        if "json" in ctype:
            params.update(await request.json())
        elif "form" in ctype:
            form = await request.form()
            for k, v in form.items():
                params[k] = v

    try:
        lat = float(pick(params, "lat", "latitude"))
        lon = float(pick(params, "long", "lon", "lng", "longitude"))
        cat = str(pick(params, "cat", "category")).strip().lower()
        rad_v = pick(params, "rad", "radius")
        rad = float(rad_v) if rad_v is not None else math.inf
    except (TypeError, ValueError):
        raise HTTPException(400, "lat, long, cat (and rad) are required")

    try:
        text = await read_link(pick(params, "link", "links"))
    except Exception as e:
        raise HTTPException(400, f"could not read link: {e}")

    adj = build_graph(text)
    res = search(lat, lon, cat, rad, adj)
    return JSONResponse({"ids": [r["id"] for r in res], "results": res})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
