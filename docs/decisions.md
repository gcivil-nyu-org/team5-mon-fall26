# Decisions

Add new decisions at the bottom with the date. Do not contradict one silently: change it here and say why.

## Required by the course (not ours to change)
- Python, web application, Django framework, AWS hosting, git/GitHub, Scrum with ZenHub.
- Two environments: **Integration** (deployed from `develop`) and **Production** (deployed from `main`, tagged to match the ZenHub sprint milestone). The sprint demo runs only on Production.
- Estimates use planning poker with 0, 0.5, 1, 2, 3. Anything bigger is split. The team estimates, not the PO or SM.

## Our choices (agreed in the High Level Design)
- **Frontend:** Django templates + Leaflet. No separate React app.
- **Database:** PostgreSQL. No PostGIS.
- **Zone shapes:** one static GeoJSON file in the repo, joined to the statistics by zone id in Django.
- **Data import:** a Django management command using pandas and pyarrow. It reads one monthly TLC Parquet file at a time. No PySpark.
- **Precompute:** the import writes aggregate tables (`zone`, `zone_hour_stats`, `route_hour_stats`). The API never queries raw trips.
- **Fare range:** minimum, average, and maximum, computed after outlier cleaning.
- **Duration only:** the data has no wait time, so we report trip duration, not waiting.
- **Too few trips:** the API returns an empty result and the UI shows "Not enough data".
- **API contract:** the four endpoints in the High Level Design, all public and read-only. Changing them needs a note here and an updated HLD.

## Our choices (project scaffold, 2026-10-16)
- **Project and app layout:** one Django project `taxiscope`, one app `zones`. The data model, views, and (for now) the API all live in `zones`; split into more apps later only if it earns its keep.
- **Python version:** 3.12. Documented in the README. Do not rely on 3.13-only features.
- **Django version:** 5.2 (LTS).
- **Test runner:** Django's built-in `manage.py test`. No pytest, to avoid an extra dependency the course has not asked for.
- **Env vars:** `django-environ`, one `DATABASE_URL` for the database connection. All other settings (`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`) are also read from the environment via `.env`.
- **Postgres driver:** `psycopg[binary]` (v3).
- **Settings layout:** a single env-driven `taxiscope/settings.py`, no `settings/base.py` + `dev.py`/`prod.py` split.
- **Zone shapes file location:** `zones/data/`. `.gitignore` only ignores the top-level `/data/` directory and `*.parquet` files, not `zones/data/`, so the committed GeoJSON file is not accidentally excluded.
- **Leaflet delivery:** vendored into `zones/static/`, not loaded from a CDN, so the demo does not depend on outside network access.
- **`day_of_week` convention:** Monday=0 .. Sunday=6, the same as Python's `weekday()` and pandas' `dayofweek`. Used consistently in the database columns and in the API's `day=` parameter.

## Our choices (zone shapes, US0b, 2026-10-18)
- **Source:** the official TLC taxi zone shapefile, https://d37ci6vzurychx.cloudfront.net/misc/taxi_zones.zip (linked from the TLC Trip Record Data page).
- **Build tool:** `scripts/build_zone_shapes.py` using pyshp==3.1.6 and pyproj==3.8.0. Needed only to rebuild the file, so they are not in `requirements.txt`.
- **Coordinate system:** read from the shapefile's `.prj`, never assumed; converted to WGS84 [longitude, latitude] (EPSG:4326).
- **Output:** `zones/data/taxi_zones.geojson`, one feature per zone with `LocationID` (int), `zone`, `borough`. Coordinates rounded to 6 decimals (~10 cm), no simplification. Size: 2.17 MB.
- **IDs:** LocationIDs must be unique and exactly 1..263; the script stops otherwise. Zones 264 and 265 (Unknown / Outside of NYC) have no shape.

## Open (decide before the story that needs it)
- Which AWS services host the Django app and the database. Needed before the first deploy.
- Minimum trip count for a window to be shown (suggested starting point: decide with the PO).
- Exact rule for "best" and "worst" travel windows (volume only, or a mix with duration).
- Which months of TLC data to load first.
- CI tooling. Waiting on the remaining course slides. (Testing tool is decided above: Django's built-in test runner.)
- Map tile provider for the demo. OpenStreetMap's public tile servers have a usage policy and are not meant for heavy production use (they already 403'd once locally over a missing Referer header). Check this before the sprint demo and be ready to switch to another tile provider (for example a paid provider, or self-hosted tiles) if it becomes a problem.
