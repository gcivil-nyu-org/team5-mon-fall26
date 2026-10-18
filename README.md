# team5-mon-fall26

TaxiScope NYC. See `CLAUDE.md` and `docs/` for the project docs.

## Run it locally

Requires Python 3.12 and a running PostgreSQL (e.g. the `taxiscope-db` Docker container).

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in DATABASE_URL etc.
python manage.py migrate
python manage.py runserver
```

Run tests with:

```bash
python manage.py test
```

## Regenerate the zone shapes

`zones/data/taxi_zones.geojson` is committed, so you only need this if TLC publishes new zone boundaries. It is built from the official TLC taxi zone shapefile by `scripts/build_zone_shapes.py`.

The script needs two packages that the app does not use, so they are not in `requirements.txt`. Install these exact versions:

```bash
pip install pyshp==3.1.6 pyproj==3.8.0
```

Download and unzip the shapefile outside the repo (this link is the "Taxi Zone Shapefile" link on the [TLC Trip Record Data page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page)), then run the script from the repo root:

```bash
mkdir -p ~/Downloads/taxi_zones && cd ~/Downloads/taxi_zones
curl -fLO https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip && unzip taxi_zones.zip
cd -   # back to the repo root
python scripts/build_zone_shapes.py ~/Downloads/taxi_zones/taxi_zones/taxi_zones.shp
python manage.py test zones.tests.test_zone_shapes
```

The script reads the coordinate system from the `.prj` file, converts to WGS84 longitude/latitude, rounds to 6 decimals, and writes one feature per zone (`LocationID`, `zone`, `borough`). It stops without writing anything if the LocationIDs are not unique and exactly 1..263. See `docs/decisions.md` (zone shapes).
