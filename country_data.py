"""
country_data.py
---------------
Data layer for the country-wise page (?page=country-wise-cbd-analysis).
No Dash components and no Plotly figures in here - just "what do we show for
this country?". country_figures.py draws it, country_page.py wires it up.

Nothing in queries.py or datasets.py had to change. For every benchmark we call
the SAME resolver the one-page Dashboard uses (datasets.DATASETS[key]["resolve"]),
so a number on this page is always the number on the Dashboard.

How a country is looked up in each benchmark
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  world   efficiency frontier: one global table, every country is on it.
  region  climate institutions, GovTech, infrastructure gap, PEFA: the benchmark
          is filtered by World Bank region, so we use the country's own region
          (read from the country_group table) and everything is that region.
  local   climate assessment (CCIA) and PIM tracker (PIIAG): only a few country
          groups were assessed (Western Balkans 6, Central Asia). A country in
          none of them is simply "not covered" and the page says so.

View models are cached for the life of the process, exactly like queries.load_csv()
caches the tables. Call clear_cache() next to queries.refresh_all_tables() if you
ever wire that up.
"""

import json
import logging
import math
import os
import threading
from urllib.parse import parse_qs

import numpy as np
from plotly.utils import PlotlyJSONEncoder   # same JSON clean-up app.py applies to every view model

import datasets as ds
import queries as q
import utils as u

log = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# What the page contains
# ══════════════════════════════════════════════════════════════════════════

# At most this many peers next to the selected country. Four colours (the selected
# country's red + three peers) is the most that stay clearly apart for colour-blind
# readers, so raise this only together with PEER_COLORS in country_figures.py.
MAX_PEERS = 3

# (section heading, benchmark keys). Two benchmarks per row, in reading order.
SECTIONS = [
    ("Infrastructure", ["ef", "infra"]),
    ("Public investment management", ["pefa", "gtmi"]),
    ("Climate readiness", ["gccii", "ccia"]),
    ("Regional deep-dive", ["piiag"]),
]
KEYS = [k for _, keys in SECTIONS for k in keys]

SCOPE = {
    "ef": "world",
    "infra": "region", "pefa": "region", "gtmi": "region", "gccii": "region",
    "ccia": "local", "piiag": "local",
}

# datasets.FILTERS[key] starts with a Region / Country-group filter for every
# benchmark except the efficiency frontier. Here that one is chosen by the country
# itself, so it is skipped and only the remaining filters (Topic, Indicator,
# Pillar ...) are shown on the page.
_AUTO_FILTERS = {"ef": 0, "infra": 1, "pefa": 1, "gtmi": 1, "gccii": 1, "ccia": 1, "piiag": 1}


def user_filters(key):
    """The filters a person can change on this page for one benchmark."""
    return ds.FILTERS[key][_AUTO_FILTERS[key]:]


def default_vals(key):
    return tuple(f["default"]() for f in user_filters(key))


# ══════════════════════════════════════════════════════════════════════════
# Countries, regions, URL hash
# ══════════════════════════════════════════════════════════════════════════

def country_names():
    return q.get_country_name_map()


def _is_iso(code):
    return isinstance(code, str) and len(code) == 3 and code.isalpha() and code.isupper()


def country_options():
    """[{label, value}] for the dropdowns, A-Z by name."""
    names = country_names()
    items = [(str(n), c) for c, n in names.items() if _is_iso(c) and isinstance(n, str) and n.strip()]
    items.sort(key=lambda t: t[0].casefold())
    return [{"label": n, "value": c} for n, c in items]


_GROUPS = {}


def _group_index():
    """iso -> set of group names (a country can sit in several: region + EU27 ...)."""
    if _GROUPS:
        return _GROUPS
    df = q.get_country_groups_df()           # returns an empty frame instead of raising
    idx = {}
    for iso, grp in zip(df["cntrCode"], df["grpName"]):
        idx.setdefault(iso, set()).add(grp)
    if idx:                                   # never cache a failed (empty) load
        _GROUPS.update(idx)
    return idx


def region_of(iso):
    """The World Bank region used by the Dashboard's Region filter, or None."""
    groups = _group_index().get(iso, set())
    return next((r for r in u.GLOBAL_REGIONS if r in groups), None)


def clean_selection(country, peers):
    """Valid country + peers only: known codes, no duplicates, selected country never its own peer."""
    names = country_names()
    ok = (lambda c: _is_iso(c) and c in names) if names else _is_iso
    country = country if ok(country) else None
    out = []
    for p in peers or []:
        if ok(p) and p != country and p not in out:
            out.append(p)
    return country, (out[:MAX_PEERS] if country else [])


def parse_hash(hash_):
    """'#country=KHM&peers=VNM,THA' -> ('KHM', ['VNM', 'THA']). Bad input is dropped."""
    qs = parse_qs((hash_ or "").lstrip("#"))
    country = (qs.get("country", [""])[0] or "").strip().upper()
    peers = [p.strip().upper() for p in (qs.get("peers", [""])[0] or "").split(",") if p.strip()]
    return clean_selection(country, peers)


# ══════════════════════════════════════════════════════════════════════════
# View models (one per benchmark, from the Dashboard's own resolvers)
# ══════════════════════════════════════════════════════════════════════════

_VM_CACHE = {}
_LOCK = threading.RLock()     # first calls hit Databricks; one at a time avoids duplicate table loads


def panel_vm(key, scope, vals=()):
    """The Dashboard's view model for `key` in `scope` (region / country group / 'World')."""
    ck = (key, scope, tuple(vals))
    vm = _VM_CACHE.get(ck)
    if vm is None:
        with _LOCK:
            vm = _VM_CACHE.get(ck)
            if vm is None:
                args = list(vals) if key == "ef" else [scope, *vals]
                vm = json.loads(json.dumps(ds.DATASETS[key]["resolve"](args), cls=PlotlyJSONEncoder))
                if len(_VM_CACHE) > 400:
                    _VM_CACHE.clear()
                _VM_CACHE[ck] = vm
    return vm


def row_of(vm, iso):
    return next((r for r in vm["rows"] if r["iso"] == iso), None) if vm else None


_LOCAL = {}


def local_coverage(key):
    """CCIA / PIIAG: {iso: country group} for every country that was assessed."""
    if key in _LOCAL:
        return _LOCAL[key]
    out = {}
    vals = default_vals(key)
    for group in u.LOCAL_REGIONS:
        try:
            vm = panel_vm(key, group, vals)
        except Exception:
            log.exception("Could not read %s for group %s", key, group)
            continue
        for r in vm["rows"]:
            out.setdefault(r["iso"], group)
    if out:
        _LOCAL[key] = out
    return out


def scope_for(key, iso):
    """Where `iso` lives in this benchmark: 'World', a region, a country group, or None."""
    kind = SCOPE[key]
    if kind == "world":
        return "World"
    if kind == "region":
        return region_of(iso)
    return local_coverage(key).get(iso)


def locate(key, iso, vals):
    """(scope, view model, the country's row) - row is None when there is no data for it."""
    scope = scope_for(key, iso)
    if not scope:
        return None, None, None
    vm = panel_vm(key, scope, vals)
    return scope, vm, row_of(vm, iso)


def has_data(vm_row):
    if not vm_row:
        return False
    if "theta" in vm_row:                    # efficiency frontier rows
        return vm_row.get("theta") is not None
    return vm_row.get("band") is not None


def coverage(iso):
    """{key: bool} - does this country have a score in each benchmark? (default filters)"""
    out = {}
    for key in KEYS:
        try:
            out[key] = has_data(locate(key, iso, default_vals(key))[2])
        except Exception:
            log.exception("Coverage check failed for %s / %s", key, iso)
            out[key] = False
    return out


def covered_countries(key):
    """[(iso, name)] assessed in a local benchmark, A-Z. Used by the 'not covered' message."""
    names = country_names()
    return sorted(((iso, names.get(iso, iso)) for iso in local_coverage(key)), key=lambda t: t[1].casefold())


def measure_label(key, vals):
    """What the headline row of the comparison table is called for the chosen filters."""
    vals = list(vals or [])
    if key == "infra":
        return "Gap index"
    if key == "pefa":
        return f"{vals[0]} grade" if vals else "Grade"
    if key == "gtmi":
        pillar = vals[0] if vals else "PIMS"
        return "PIMS status" if pillar == "PIMS" else ds.GTMI_PILLAR_LABELS.get(pillar, pillar)
    return "Average score"


# ── Efficiency frontier ──────────────────────────────────────────────────

def ef_filters():
    return q.ef_get_filters()


def ef_vm():
    return panel_vm("ef", "World", ())


def ef_scores(method, sample, isos):
    return q.ef_get_scores(method=method, sample=sample, isos=list(isos))


def clear_cache():
    _VM_CACHE.clear()
    _LOCAL.clear()
    _GROUPS.clear()
    _GEOM_CACHE.clear()
    _BBOX_CACHE.clear()


# ══════════════════════════════════════════════════════════════════════════
# Light boundaries
# ══════════════════════════════════════════════════════════════════════════
# One country page draws up to six maps, and every map carries its own copy of the
# country shapes. The World Bank boundaries are full resolution (~160 MB for the
# world), which is fine for one map but far too heavy for six. So the shapes are
# thinned once per country (Douglas-Peucker, tolerance in degrees; 0.01 deg is about
# 1 km, well under a pixel at these zoom levels) and cached.
#
#   CONTEXT_TOL  every country that is only shown for comparison (light colours)
#   FOCUS_TOL    the selected country and peers (full colour, outlined), finer
#
# Set CBD_GEOM_TOL_CONTEXT / CBD_GEOM_TOL_FOCUS to 0 to switch thinning off.

CONTEXT_TOL = float(os.environ.get("CBD_GEOM_TOL_CONTEXT", "0.03"))
FOCUS_TOL = float(os.environ.get("CBD_GEOM_TOL_FOCUS", "0.008"))

_GEOM_CACHE = {}
_BBOX_CACHE = {}


def _rdp_keep(pts, tol):
    """Ramer-Douglas-Peucker on an open polyline: boolean mask of the points to keep."""
    n = len(pts)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        a, b = pts[s], pts[e]
        seg = pts[s + 1:e] - a
        d = b - a
        length = math.hypot(d[0], d[1])
        if length == 0:
            dist = np.hypot(seg[:, 0], seg[:, 1])
        else:
            dist = np.abs(seg[:, 0] * d[1] - seg[:, 1] * d[0]) / length
        i = int(np.argmax(dist))
        if dist[i] > tol:
            m = s + 1 + i
            keep[m] = True
            stack.append((s, m))
            stack.append((m, e))
    return keep


def _round_dedupe(arr, decimals):
    arr = np.round(arr, decimals)
    if len(arr) > 1:
        same = np.all(arr[1:] == arr[:-1], axis=1)
        arr = arr[np.concatenate(([True], ~same))]
    return arr


def _simplify_ring(ring, tol, decimals):
    arr = np.asarray(ring, dtype=float)[:, :2]
    if len(arr) < 4:
        return None
    closed = bool(np.allclose(arr[0], arr[-1]))
    pts = arr[:-1] if closed else arr
    thin = pts
    if len(pts) > 8:
        if closed:
            # a ring has no natural ends: split it at the point farthest from the first one
            k = int(np.argmax(np.hypot(*(pts - pts[0]).T)))
            a = pts[:k + 1]
            b = np.vstack([pts[k:], pts[:1]])
            thin = np.vstack([a[_rdp_keep(a, tol)], b[_rdp_keep(b, tol)][1:-1]])
        else:
            thin = pts[_rdp_keep(pts, tol)]
    thin = _round_dedupe(thin, decimals)
    if len(thin) < 3:                                       # collapsed: keep the (tiny) original
        thin = _round_dedupe(pts, decimals)
    if len(thin) < 3:
        return None
    thin = np.vstack([thin, thin[:1]])                      # close the ring
    return thin.tolist()


def _simplify_geometry(geom, tol):
    decimals = 3 if tol <= 0.01 else 2
    kind = geom.get("type")
    if kind == "Polygon":
        polys = [geom["coordinates"]]
    elif kind == "MultiPolygon":
        polys = geom["coordinates"]
    else:
        return geom
    out = []
    for poly in polys:
        rings = [_simplify_ring(r, tol, decimals) for r in poly]
        if rings and rings[0] is not None:
            out.append([r for r in rings if r is not None])
    if not out:
        return geom
    return {"type": "MultiPolygon", "coordinates": out} if kind == "MultiPolygon" or len(out) > 1 \
        else {"type": "Polygon", "coordinates": out[0]}


def _light_feature(feature, tol):
    if not tol or tol <= 0:
        return feature
    try:
        return {"type": "Feature", "properties": feature.get("properties", {}),
                "geometry": _simplify_geometry(feature["geometry"], tol)}
    except Exception:
        log.exception("Could not thin boundary for %s; using it as is", feature.get("properties"))
        return feature


def light_geojson(isos, tol):
    """FeatureCollection with thinned shapes for just these countries (cached per country)."""
    isos = sorted({i for i in isos if i})
    missing = [i for i in isos if (i, tol) not in _GEOM_CACHE]
    if missing:
        raw = q.get_world_boundaries_geojson(missing)
        found = {f.get("properties", {}).get("ISO_A3"): f for f in raw.get("features", [])}
        for iso in missing:
            f = found.get(iso)
            _GEOM_CACHE[(iso, tol)] = _light_feature(f, tol) if f else None
    feats = [_GEOM_CACHE[(i, tol)] for i in isos if _GEOM_CACHE.get((i, tol))]
    return {"type": "FeatureCollection", "features": feats}


def mainland_bbox(iso):
    """(west, south, east, north) of the country's main land, ignoring far-away islands/territories."""
    if iso in _BBOX_CACHE:
        return _BBOX_CACHE[iso]
    box = None
    feats = light_geojson([iso], FOCUS_TOL)["features"]
    if feats:
        geom = feats[0]["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        boxes = []
        for poly in polys:
            outer = np.asarray(poly[0], dtype=float)
            w, s = outer.min(axis=0)[:2]
            e, n = outer.max(axis=0)[:2]
            boxes.append((w, s, e, n, max((e - w) * (n - s), 1e-9)))
        if boxes:
            biggest = max(b[4] for b in boxes)
            kept = [b for b in boxes if b[4] >= 0.15 * biggest]    # main islands, not stray dots
            box = tuple(float(v) for v in (min(b[0] for b in kept), min(b[1] for b in kept),
                                           max(b[2] for b in kept), max(b[3] for b in kept)))
    _BBOX_CACHE[iso] = box
    return box


def _merc(lat):
    lat = max(-85.0, min(85.0, lat))
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def map_frame(iso, region_key, width=560, height=380):
    """
    (lat, lon, zoom) that shows the selected country with its neighbours around it.

    u.MAP_VIEWS holds one frame per region, tuned for a ~1000 px wide map. These maps
    are about half as wide, so the zoom is lowered to match. The result is never
    zoomed out further than the whole region (the region frame) and never closer than
    zoom 5.5 (a window of about 7 degrees, so even a tiny country has neighbours).
    """
    base_lat, base_lon, base_zoom = u.MAP_VIEWS.get(region_key, u.MAP_VIEWS["World"])
    lo = float(max(base_zoom + math.log2(width / 1000.0), 0.8))
    box = mainland_bbox(iso)
    if not box:
        return base_lat, base_lon, lo
    w, s, e, n = box
    if e - w > 110:                                          # spans half the globe: use the region frame
        return base_lat, base_lon, lo
    span_x = max((e - w) * 2.4, 7.0) / 360.0
    span_y = max((_merc(n) - _merc(s)) * 2.4, math.radians(7.0)) / (2 * math.pi)
    zoom = math.log2(min(width / (512 * span_x), height / (512 * span_y)))
    if zoom <= lo:
        return base_lat, base_lon, lo
    zoom = min(zoom, 5.5)
    mid = (_merc(n) + _merc(s)) / 2
    lat = math.degrees(2 * math.atan(math.exp(mid)) - math.pi / 2)
    return lat, (w + e) / 2, float(zoom)
