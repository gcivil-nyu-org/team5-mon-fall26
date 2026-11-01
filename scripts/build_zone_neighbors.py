"""Build zones/data/zone_neighbors.json from zones/data/taxi_zones.geojson.

US18 #47. Two zones are neighbours when their borders run alongside each
other for at least MIN_SHARED_M metres. Zones that only touch at a corner, or
face each other across a river, are not neighbours.

Only needed to regenerate the committed file. Needs shapely (pinned in
docs/decisions.md and the README, not in requirements.txt).

Usage, from the repo root:
    python scripts/build_zone_neighbors.py
    python scripts/build_zone_neighbors.py -o out.json
"""

import argparse
import json
import math
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.ops import transform, unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid

DATA_DIR = Path(__file__).resolve().parent.parent / "zones" / "data"
SHAPES_PATH = DATA_DIR / "taxi_zones.geojson"
DEFAULT_OUTPUT = DATA_DIR / "zone_neighbors.json"

# Lon/lat degrees -> metres with a flat (equirectangular) projection centred on
# NYC. The error over the city is well under 1%, which is plenty for comparing
# border lengths, and avoids needing pyproj.
LAT0 = 40.7
METRES_PER_DEG_LON = 111_320 * math.cos(math.radians(LAT0))
METRES_PER_DEG_LAT = 110_574

# Coordinates are rounded to 6 decimals (~0.1 m), so two zones that share a
# border may not line up exactly. Borders closer than this count as touching.
# The narrowest real gap between zones (a creek) is about 15 m.
TOUCH_TOLERANCE_M = 2.0
# A corner contact measures about 2 x TOUCH_TOLERANCE_M; the shortest real
# shared border is over 10 m.
MIN_SHARED_M = 10.0


def to_metres(geometry):
    return transform(
        lambda x, y, z=None: (x * METRES_PER_DEG_LON, y * METRES_PER_DEG_LAT),
        geometry,
    )


def polygonal(geometry):
    """Repair an invalid shape and keep only its area (a repair can leave
    stray lines or points behind)."""
    geometry = make_valid(geometry)
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    return unary_union(
        [g for g in geometry.geoms if isinstance(g, (Polygon, MultiPolygon))]
    )


def load_zones(path):
    with path.open(encoding="utf-8") as f:
        features = json.load(f)["features"]
    return {
        int(f["properties"]["LocationID"]): polygonal(to_metres(shape(f["geometry"])))
        for f in features
    }


def shared_border_m(a, b):
    """Length of a's border that lies within TOUCH_TOLERANCE_M of b."""
    return a.boundary.intersection(b.buffer(TOUCH_TOLERANCE_M)).length


def find_neighbors(zones):
    ids = sorted(zones)
    tree = STRtree([zones[i] for i in ids])
    neighbors = {i: set() for i in ids}
    for i in ids:
        for k in tree.query(zones[i].buffer(TOUCH_TOLERANCE_M)):
            j = ids[k]
            if j <= i:
                continue
            # Measure from both sides and keep the longer, so the answer
            # does not depend on which zone is a or b.
            shared = max(
                shared_border_m(zones[i], zones[j]),
                shared_border_m(zones[j], zones[i]),
            )
            if shared >= MIN_SHARED_M:
                neighbors[i].add(j)
                neighbors[j].add(i)
    return {str(i): sorted(neighbors[i]) for i in ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-i", "--input", type=Path, default=SHAPES_PATH)
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    zones = load_zones(args.input)
    neighbors = find_neighbors(zones)
    pairs = sum(len(v) for v in neighbors.values()) // 2
    alone = [z for z, v in neighbors.items() if not v]
    print(f"{len(zones)} zones, {pairs} adjacent pairs")
    print(f"zones with no neighbour: {', '.join(alone) or 'none'}")

    with args.output.open("w", encoding="utf-8") as out:
        json.dump(neighbors, out, indent=1)
        out.write("\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
