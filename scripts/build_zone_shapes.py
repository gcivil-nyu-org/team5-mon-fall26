"""Build zones/data/taxi_zones.geojson from the TLC taxi zone shapefile.

Only needed to regenerate the committed file. Needs pyshp and pyproj (pinned
in the README and docs/decisions.md, not in requirements.txt).

Usage, from the repo root:
    python scripts/build_zone_shapes.py path/to/taxi_zones.shp
    python scripts/build_zone_shapes.py path/to/taxi_zones.shp -o out.geojson

The coordinate system is read from the .prj next to the .shp and converted
to WGS84 [longitude, latitude]. Coordinates are rounded to 6 decimals; shapes
are not simplified. The script stops without writing anything if the
LocationIDs are not unique and exactly 1..263.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import shapefile
from pyproj import CRS, Transformer

EXPECTED_IDS = set(range(1, 264))
DECIMALS = 6
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "zones" / "data" / "taxi_zones.geojson"


def read_source_crs(shp_path):
    prj_path = shp_path.with_suffix(".prj")
    if not prj_path.exists():
        sys.exit(f"No .prj file next to {shp_path}; cannot tell the coordinate system.")
    return CRS.from_wkt(prj_path.read_text())


def read_encoding(shp_path):
    cpg_path = shp_path.with_suffix(".cpg")
    if cpg_path.exists():
        return cpg_path.read_text().strip() or "utf-8"
    return "utf-8"


def transform_rings(rings, transformer):
    out = []
    for ring in rings:
        xs, ys = zip(*((pt[0], pt[1]) for pt in ring))
        lons, lats = transformer.transform(xs, ys)
        out.append([[round(lon, DECIMALS), round(lat, DECIMALS)] for lon, lat in zip(lons, lats)])
    return out


def transform_geometry(geo, transformer):
    if geo["type"] == "Polygon":
        coords = transform_rings(geo["coordinates"], transformer)
    elif geo["type"] == "MultiPolygon":
        coords = [transform_rings(polygon, transformer) for polygon in geo["coordinates"]]
    else:
        raise ValueError(f"Unexpected geometry type {geo['type']}")
    return {"type": geo["type"], "coordinates": coords}


def check_ids(features):
    """Return a list of problems with the LocationIDs (empty if they are fine)."""
    counts = Counter(f["properties"]["LocationID"] for f in features)
    problems = []
    for location_id, count in sorted(counts.items()):
        if count > 1:
            names = [f["properties"]["zone"] for f in features
                     if f["properties"]["LocationID"] == location_id]
            problems.append(f"LocationID {location_id} appears {count} times: {names}")
    for location_id in sorted(EXPECTED_IDS - counts.keys()):
        problems.append(f"LocationID {location_id} is missing")
    for location_id in sorted(counts.keys() - EXPECTED_IDS):
        problems.append(f"LocationID {location_id} is outside 1..263")
    return problems


def build_features(shp_path, transformer):
    features = []
    with shapefile.Reader(str(shp_path), encoding=read_encoding(shp_path)) as reader:
        for shape_record in reader.shapeRecords():
            record = shape_record.record.as_dict()
            features.append({
                "type": "Feature",
                "properties": {
                    "LocationID": int(record["LocationID"]),
                    "zone": record["zone"],
                    "borough": record["borough"],
                },
                "geometry": transform_geometry(shape_record.shape.__geo_interface__, transformer),
            })
    return features


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("shapefile", type=Path, help="path to taxi_zones.shp")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_crs = read_source_crs(args.shapefile)
    epsg = source_crs.to_epsg()
    print(f"Source CRS (from .prj): {source_crs.name}" + (f" (EPSG:{epsg})" if epsg else ""))
    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)

    features = build_features(args.shapefile, transformer)
    print(f"Read {len(features)} records")

    problems = check_ids(features)
    if problems:
        print("LocationID check failed, nothing written:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        sys.exit(1)

    features.sort(key=lambda f: f["properties"]["LocationID"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        json.dump({"type": "FeatureCollection", "features": features}, out,
                  ensure_ascii=False, separators=(",", ":"))
    size = args.output.stat().st_size
    print(f"Wrote {len(features)} features to {args.output} ({size:,} bytes, {size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
