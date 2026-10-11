"""
Generates assets/hero_dotmap.svg - a decorative dot-matrix world map for the
landing page hero. Every dot is the same colour on purpose: it is an
illustration, NOT data, so it can never be misread as a score.

Run once (or whenever you want a different density):
    pip install shapely
    python dev/make_hero_dotmap.py
"""
import json, pathlib
from shapely.geometry import shape, Point
from shapely.ops import unary_union
from shapely.prepared import prep

ROOT = pathlib.Path(__file__).resolve().parent.parent
geo = json.load(open(ROOT / "assets" / "world_countries.geojson"))
land = prep(unary_union([shape(f["geometry"]).buffer(0) for f in geo["features"]]))

LON0, LON1, LAT0, LAT1 = -168, 180, -56, 80
STEP = 2.2          # degrees between dots
PX = 4              # svg px per degree
W, H = (LON1 - LON0) * PX, (LAT1 - LAT0) * PX

dots = []
lat = LAT1
row = 0
while lat >= LAT0:
    lon = LON0 + (STEP / 2 if row % 2 else 0)      # offset alternate rows
    while lon <= LON1:
        if land.contains(Point(lon, lat)):
            dots.append(((lon - LON0) * PX, (LAT1 - lat) * PX))
        lon += STEP
    lat -= STEP * 0.9
    row += 1

d = "".join(f"M{x:.0f} {y:.0f}h0" for x, y in dots)
svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
    f'preserveAspectRatio="xMidYMid slice" role="img" aria-label="Decorative dot map of the world">'
    f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="5.2" stroke-linecap="round"/></svg>'
)
(ROOT / "assets" / "hero_dotmap.svg").write_text(svg)
print(len(dots), "dots,", len(svg) // 1024, "KB")
